"""SDK-independent dispatch with policy enforced even for hidden operations."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
from pydantic import ValidationError

from .client import SyncthingClient
from .config import Instance, Settings
from .errors import PublicError
from .reads import read_operation
from .registry import REGISTRY, ToolDefinition, permitted, validate_filters
from .safety import redact


def validate_depth(value: Any, depth: int = 0) -> None:
    if depth > 20:
        raise PublicError("invalid_argument", "Arguments exceed the nesting limit.")
    if isinstance(value, dict):
        for item in value.values():
            validate_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            validate_depth(item, depth + 1)


class Engine:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        validate_filters(settings)
        self.settings = settings
        self.instances = {instance.name: instance for instance in settings.instances}
        self.clients = {
            instance.name: SyncthingClient(instance, settings, transport)
            for instance in settings.instances
        }
        self.locks = {name: asyncio.Lock() for name in self.instances}
        self.semaphore = asyncio.Semaphore(settings.concurrency)
        self.secrets = tuple(x.api_key for x in settings.instances) + (settings.auth_token or "",)

    def tools(self) -> list[ToolDefinition]:
        return [op.definition() for op in REGISTRY.values() if permitted(op, self.settings)]

    def instance_for(self, name: str | None, *, mutation: bool) -> Instance:
        if name is None:
            if mutation and len(self.instances) != 1:
                raise PublicError("instance_required", "Writes require an explicit instance.")
            # Deterministic first configured instance for read convenience.
            return next(iter(self.instances.values()))
        if name not in self.instances:
            raise PublicError("unknown_instance", "Unknown configured instance.")
        return self.instances[name]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        op = REGISTRY.get(name)
        if op is None:
            raise PublicError("unknown_tool", "Unknown tool.")
        if not permitted(op, self.settings):
            raise PublicError("permission_denied", "Operation is disabled by server policy.")
        validate_depth(arguments)
        try:
            encoded = json.dumps(arguments, allow_nan=False).encode()
        except (ValueError, TypeError, RecursionError):
            raise PublicError("invalid_argument", "Arguments must be finite JSON values.") from None
        if len(encoded) > self.settings.max_request_bytes:
            raise PublicError("request_too_large", "Arguments exceed the request byte limit.")
        try:
            args = op.model.model_validate(arguments).model_dump()
        except ValidationError:
            raise PublicError(
                "invalid_argument", "Arguments do not match the tool schema."
            ) from None
        instance = self.instance_for(args.get("instance"), mutation=not op.read_only)
        client = self.clients[instance.name]
        async with self.semaphore:
            if op.read_only:
                result = await read_operation(op, args, instance, client, self.settings)
            else:
                from .writes import write_operation

                async with self.locks[instance.name]:
                    result = await write_operation(op, args, instance, client, self.settings)
        result = redact(result, self.secrets)
        try:
            output = json.dumps(
                result, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            ).encode()
        except (ValueError, TypeError, RecursionError):
            raise PublicError(
                "upstream_shape", "Upstream output cannot be safely serialized."
            ) from None
        if len(output) > self.settings.max_output_bytes:
            raise PublicError(
                "output_too_large",
                "Result exceeds output limit; narrow fields or limit.",
                outcome="not_attempted" if op.read_only else "outcome_unknown",
            )
        return cast(dict[str, Any], result)

    async def aclose(self) -> None:
        for client in self.clients.values():
            await client.aclose()

"""One bounded, TLS-verifying HTTP client per configured instance."""

from __future__ import annotations

import asyncio
import json
import ssl
from typing import Any

import httpx

from .config import Instance, Settings
from .errors import PublicError


class SyncthingClient:
    def __init__(
        self,
        instance: Instance,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        context = ssl.create_default_context(cafile=settings.ca_file)
        self.http = httpx.AsyncClient(
            base_url=instance.url + "/",
            headers={"X-API-Key": instance.api_key},
            timeout=httpx.Timeout(settings.request_timeout),
            follow_redirects=False,
            trust_env=False,
            verify=context,
            transport=transport,
            limits=httpx.Limits(
                max_connections=settings.concurrency, max_keepalive_connections=settings.concurrency
            ),
        )

    async def request(
        self,
        method: str,
        route: str,
        *,
        params: dict[str, Any] | None = None,
        body: Any = None,
        timeout: float | None = None,
        text: bool = False,
        raw_text: str | None = None,
    ) -> Any:
        mutation = method != "GET"
        unknown = "outcome_unknown" if mutation else "not_attempted"
        if not route.startswith("/rest/") or "://" in route or "?" in route or "#" in route:
            raise PublicError("invalid_route", "Only fixed REST routes are supported.")
        deadline = timeout or self.settings.request_timeout
        try:
            # The total deadline also bounds trickle responses: HTTPX timeouts
            # alone limit inactivity, not total wall-clock time.
            async with asyncio.timeout(deadline):
                async with self.http.stream(
                    method,
                    route.lstrip("/"),
                    params=params,
                    json=body,
                    content=raw_text,
                    headers={"Content-Type": "text/plain"} if raw_text else None,
                    timeout=deadline,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise PublicError(
                            "upstream_redirect", "Upstream redirects are refused.", outcome=unknown
                        )
                    if not 200 <= response.status_code < 300:
                        status = response.status_code
                        code = "not_found" if status == 404 else "upstream_error"
                        raise PublicError(
                            code,
                            f"Upstream returned HTTP {status}.",
                            retryable=not mutation and status >= 500,
                            outcome=unknown,
                        )
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(content) + len(chunk) > self.settings.max_upstream_bytes:
                            raise PublicError(
                                "upstream_too_large",
                                "Upstream response exceeds the configured byte limit.",
                                outcome=unknown,
                            )
                        content.extend(chunk)
                    if not content:
                        return None
                    if text:
                        return content.decode("utf-8", errors="replace")
                    try:
                        return json.loads(content)
                    except (ValueError, UnicodeError, RecursionError):
                        raise PublicError(
                            "upstream_invalid_json",
                            "Upstream returned invalid JSON.",
                            outcome=unknown,
                        ) from None
        except (httpx.TimeoutException, TimeoutError):
            raise PublicError(
                "upstream_timeout",
                "Upstream request timed out.",
                retryable=not mutation,
                outcome=unknown,
            ) from None
        except httpx.HTTPError:
            raise PublicError(
                "upstream_unavailable",
                "Upstream request failed.",
                retryable=not mutation,
                outcome=unknown,
            ) from None

    async def aclose(self) -> None:
        await self.http.aclose()

"""Immutable, fail-closed environment configuration."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .errors import PublicError


def invalid(name: str) -> PublicError:
    return PublicError("configuration", f"Invalid configuration for {name}.")


def secret(value: str | None, filename: str | None, name: str) -> str | None:
    if value is not None and filename is not None:
        raise invalid(name)
    if filename is not None:
        try:
            if Path(filename).stat().st_size > 8192:
                raise invalid(name)
            value = Path(filename).read_text().rstrip("\r\n")
        except (OSError, UnicodeError):
            raise invalid(name) from None
    if value is not None and (not value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise invalid(name)
    return value


def base_url(value: str) -> str:
    try:
        url = urlsplit(value)
        _ = url.port
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or "%" in url.netloc
            or "\\" in value
        ):
            raise invalid("instance URL")
    except ValueError:
        raise invalid("instance URL") from None
    return value.rstrip("/")


@dataclass(frozen=True)
class Instance:
    name: str
    url: str
    api_key: str = field(repr=False)
    allowed_paths: tuple[str, ...] = ()
    path_style: str = "posix"


@dataclass(frozen=True)
class Settings:
    instances: tuple[Instance, ...]
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8080
    auth_token: str | None = field(default=None, repr=False)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]")
    allowed_origins: tuple[str, ...] = ()
    max_request_bytes: int = 262144
    max_output_bytes: int = 262144
    http_rate_limit: int = 120
    concurrency: int = 8
    profile: str = "full"
    groups: tuple[str, ...] | None = None
    enabled_tools: tuple[str, ...] | None = None
    disabled_tools: tuple[str, ...] = ()
    allow_writes: bool = False
    allow_destructive: bool = False
    allow_admin: bool = False
    request_timeout: float = 30.0
    scan_timeout: float = 300.0
    max_upstream_bytes: int = 4194304
    max_page_size: int = 100
    ca_file: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        prefix = "SYNCTHING_MCP_"

        def get(name: str, default: str | None = None) -> str | None:
            return env.get(prefix + name, default)

        def number(name: str, default: int, low: int, high: int) -> int:
            try:
                result = int(get(name, str(default)) or "")
            except ValueError:
                raise invalid(name) from None
            if not low <= result <= high:
                raise invalid(name)
            return result

        def seconds(name: str, default: float, high: float) -> float:
            try:
                result = float(get(name, str(default)) or "")
            except ValueError:
                raise invalid(name) from None
            if not math.isfinite(result) or not 0.1 <= result <= high:
                raise invalid(name)
            return result

        def boolean(name: str) -> bool:
            result = get(name, "false")
            if result not in {"true", "false"}:
                raise invalid(name)
            return result == "true"

        def names(name: str, default: tuple[str, ...] | None = None) -> tuple[str, ...] | None:
            result = get(name)
            if result is None:
                return default
            if result.lstrip().startswith("["):
                try:
                    parsed = json.loads(result)
                except ValueError:
                    raise invalid(name) from None
                if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
                    raise invalid(name)
                values = tuple(parsed)
                if any(not x or x != x.strip() for x in values):
                    raise invalid(name)
            else:
                values = tuple(x.strip() for x in result.split(",") if x.strip())
            if len(set(values)) != len(values):
                raise invalid(name)
            return values

        transport = get("TRANSPORT", "stdio")
        profile = get("PROFILE", "full")
        if transport not in {"stdio", "http"}:
            raise invalid("TRANSPORT")
        if profile not in {"core", "full"}:
            raise invalid("PROFILE")
        raw = get("INSTANCES")
        instances: list[Instance] = []
        if raw is not None:
            if env.get("SYNCTHING_URL") is not None or env.get("SYNCTHING_API_KEY") is not None:
                raise invalid("INSTANCES and single-instance variables")
            try:
                entries = json.loads(raw)
            except (ValueError, TypeError):
                raise invalid("INSTANCES") from None
            if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
                raise invalid("INSTANCES")
        else:
            entries = [
                {
                    "name": "default",
                    "url": env.get("SYNCTHING_URL"),
                    "api_key": env.get("SYNCTHING_API_KEY"),
                    "api_key_file": get("API_KEY_FILE"),
                    "allowed_paths": list(names("ALLOWED_PATHS", ()) or ()),
                    "path_style": get("PATH_STYLE", "posix"),
                }
            ]
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) - {
                "name",
                "url",
                "api_key",
                "api_key_file",
                "allowed_paths",
                "path_style",
            }:
                raise invalid("INSTANCES")
            name, url = entry.get("name"), entry.get("url")
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                raise invalid("instance name")
            if not isinstance(url, str):
                raise invalid("instance URL")
            key, filename = entry.get("api_key"), entry.get("api_key_file")
            if (key is not None and not isinstance(key, str)) or (
                filename is not None and not isinstance(filename, str)
            ):
                raise invalid("instance key")
            key = secret(key, filename, "instance key")
            if key is None:
                raise invalid("instance key")
            paths, style = entry.get("allowed_paths", []), entry.get("path_style", "posix")
            if (
                not isinstance(paths, list)
                or not all(isinstance(x, str) for x in paths)
                or style not in {"posix", "windows"}
            ):
                raise invalid("instance path policy")
            instances.append(Instance(name, base_url(url), key, tuple(paths), style))
        if len({x.name for x in instances}) != len(instances):
            raise invalid("duplicate instance names")
        token = secret(get("AUTH_TOKEN"), get("AUTH_TOKEN_FILE"), "AUTH_TOKEN")
        if token is not None and (len(token) < 32 or any(token == x.api_key for x in instances)):
            raise invalid("AUTH_TOKEN")
        if transport == "http" and token is None:
            raise invalid("AUTH_TOKEN required for HTTP")
        writes, destructive, admin = (
            boolean("ALLOW_WRITES"),
            boolean("ALLOW_DESTRUCTIVE"),
            boolean("ALLOW_ADMIN"),
        )
        if (destructive or admin) and not writes:
            raise invalid("ALLOW_WRITES required for elevated permissions")
        hosts = names("ALLOWED_HOSTS", ("localhost", "127.0.0.1", "[::1]")) or ()
        if not hosts or any("*" in x or "/" in x or not x for x in hosts):
            raise invalid("ALLOWED_HOSTS")
        origins = names("ALLOWED_ORIGINS", ()) or ()
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or "*" in origin
            ):
                raise invalid("ALLOWED_ORIGINS")
        host = get("HOST", "127.0.0.1") or ""
        if not host or any(ord(x) <= 32 for x in host):
            raise invalid("HOST")
        ca_file = get("CA_FILE")
        if ca_file is not None and not Path(ca_file).is_file():
            raise invalid("CA_FILE")
        settings = cls(
            instances=tuple(instances),
            transport=transport,
            host=host,
            port=number("PORT", 8080, 1, 65535),
            auth_token=token,
            allowed_hosts=hosts,
            allowed_origins=origins,
            max_request_bytes=number("MAX_REQUEST_BYTES", 262144, 1024, 16777216),
            max_output_bytes=number("MAX_OUTPUT_BYTES", 262144, 1024, 16777216),
            http_rate_limit=number("HTTP_RATE_LIMIT", 120, 1, 100000),
            concurrency=number("CONCURRENCY", 8, 1, 128),
            profile=profile,
            groups=names("GROUPS"),
            enabled_tools=names("ENABLED_TOOLS"),
            disabled_tools=names("DISABLED_TOOLS", ()) or (),
            allow_writes=writes,
            allow_destructive=destructive,
            allow_admin=admin,
            request_timeout=seconds("REQUEST_TIMEOUT", 30.0, 300.0),
            scan_timeout=seconds("SCAN_TIMEOUT", 300.0, 3600.0),
            max_upstream_bytes=number("MAX_UPSTREAM_BYTES", 4194304, 1024, 67108864),
            max_page_size=number("MAX_PAGE_SIZE", 100, 1, 1000),
            ca_file=ca_file,
        )
        from .registry import validate_filters

        validate_filters(settings)
        from .safety import destination

        for instance in settings.instances:
            for path in instance.allowed_paths:
                destination(path, instance)
        return settings

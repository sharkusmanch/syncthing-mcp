"""Remote lexical path confinement and mandatory result redaction."""

from __future__ import annotations

import hashlib
import json
import ntpath
import posixpath
import re
from typing import Any
from urllib.parse import quote

from .config import Instance
from .errors import PublicError


def bad(message: str) -> PublicError:
    return PublicError("invalid_argument", message)


def clean(value: str) -> None:
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or "%" in value:
        raise bad("Control characters and percent-encoded paths are not allowed.")


def opaque_id(value: str) -> str:
    clean(value)
    if not value or len(value) > 256 or value in {".", ".."} or "/" in value or "\\" in value:
        raise bad("Invalid resource identifier.")
    return quote(value, safe="")


def relative_path(value: str) -> str:
    clean(value)
    if (
        not value
        or len(value) > 4096
        or value.startswith(("/", "\\", "~"))
        or "\\" in value
        or re.match(r"^[A-Za-z]:", value)
        or any(part in {".", "..", ""} for part in value.split("/"))
    ):
        raise bad("Expected a folder-relative path without traversal.")
    return value


def _absolute(value: str, style: str) -> str:
    clean(value)
    if len(value) > 4096 or value.startswith("~"):
        raise bad("Invalid destination path.")
    if style == "windows":
        value = value.replace("/", "\\")
        if (
            not re.match(r"^[A-Za-z]:\\", value)
            or value.startswith("\\")
            or ".." in value.split("\\")
            or "." in value.split("\\")
        ):
            raise bad("Windows destinations require an absolute drive-root path.")
        for part in value[3:].split("\\"):
            if not part:
                continue
            basename = part.split(".")[0].upper()
            if (
                part.endswith((" ", "."))
                or any(c in part for c in '<>:"|?*')
                or basename in {"CON", "PRN", "AUX", "NUL"}
                or re.fullmatch(r"(COM|LPT)[1-9]", basename)
            ):
                raise bad("Ambiguous Windows path components are excluded.")
        return ntpath.normcase(ntpath.normpath(value))
    if not value.startswith("/") or "\\" in value or ".." in value.split("/"):
        raise bad("POSIX destinations require an absolute path without traversal.")
    return posixpath.normpath(value)


def destination(value: str, instance: Instance) -> str:
    candidate = _absolute(value, instance.path_style)
    sep = "\\" if instance.path_style == "windows" else "/"
    for root in instance.allowed_paths:
        allowed = _absolute(root, instance.path_style).rstrip(sep)
        if candidate == allowed or candidate.startswith(allowed + sep):
            return value
    raise PublicError("path_denied", "Destination is outside the configured allowed paths.")


def revision(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


SENSITIVE = {
    "apikey",
    "password",
    "token",
    "secret",
    "encryptionpassword",
    "apikeyfile",
    "auth",
    "authorization",
    "cert",
    "key",
    "privatekey",
}


def redact(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            redact(str(key), secrets): (
                "[REDACTED]"
                if str(key).lower().replace("_", "") in SENSITIVE
                else redact(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


def merge(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Objects merge recursively; arrays are intentionally replaced in order."""
    result = dict(current)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        if expected and all(isinstance(item, dict) and "deviceID" in item for item in expected):
            if not all(isinstance(item, dict) and "deviceID" in item for item in actual):
                return False
            indexed = {item["deviceID"]: item for item in actual}
            return len(indexed) == len(actual) and all(
                item["deviceID"] in indexed and matches(indexed[item["deviceID"]], item)
                for item in expected
            )
        return all(matches(item, target) for item, target in zip(actual, expected, strict=True))
    return bool(actual == expected)

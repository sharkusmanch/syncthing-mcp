"""Serialized mutations, independently checked readbacks and honest outcomes."""

from __future__ import annotations

from typing import Any

import bcrypt

from .client import SyncthingClient
from .config import Instance, Settings
from .errors import PublicError
from .policy import ignore_lines, validate_patch
from .reads import params_for, raw_ignores, route_for
from .registry import Operation, permitted
from .safety import destination, matches, merge, opaque_id, relative_path, revision


def kind_for(route: str) -> str:
    if "/folders" in route or route.endswith("/folder"):
        return "folder"
    if "/devices" in route or route.endswith("/device"):
        return "device"
    return route.rsplit("/", 1)[-1]


def check_revision(current: Any, args: dict[str, Any]) -> None:
    if args.get("expected_revision") is not None and revision(current) != args["expected_revision"]:
        raise PublicError("revision_conflict", "Resource changed since the supplied revision.")


async def restart_required(client: SyncthingClient) -> bool | None:
    try:
        result = await client.request("GET", "/rest/config/restart-required")
        if isinstance(result, dict) and type(result.get("requiresRestart")) is bool:
            return bool(result["requiresRestart"])
    except PublicError:
        pass
    return None


async def mutate(
    client: SyncthingClient,
    method: str,
    route: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
    timeout: float | None = None,
    raw_text: str | None = None,
) -> tuple[bool, Any, dict[str, Any] | None]:
    try:
        value = await client.request(
            method, route, params=params, body=body, timeout=timeout, raw_text=raw_text
        )
        return True, value, None
    except PublicError as error:
        return False, None, error.payload()


def result_for(
    instance: Instance,
    succeeded: bool,
    verified: bool | None,
    *,
    accepted: bool = False,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "instance": instance.name,
        "outcome": (
            "verified"
            if succeeded and verified is True
            else "accepted"
            if succeeded and accepted
            else "outcome_unknown"
        ),
        "request_outcome": "succeeded" if succeeded else "unknown",
        "readback_verified": verified,
        "persistence": "unknown",
        "restart_required": None,
    }
    if error:
        result["error"] = error
    return result


async def config_mutation(
    client: SyncthingClient,
    instance: Instance,
    method: str,
    route: str,
    body: Any,
    *,
    read_route: str | None = None,
    deleted: bool = False,
) -> dict[str, Any]:
    succeeded, _, error = await mutate(client, method, route, body=body)
    verified: bool | None = None
    current: Any = None
    try:
        current = await client.request("GET", read_route or route)
        if not deleted and route == "/rest/config/gui" and isinstance(body, dict):
            verified = gui_matches(current, body)
        else:
            verified = False if deleted else matches(current, body)
    except PublicError as read_error:
        if deleted and read_error.code == "not_found":
            verified = True
    result = result_for(instance, succeeded, verified, error=error)
    result["restart_required"] = await restart_required(client)
    if current is not None:
        result["revision"] = revision(current)
    return result


def gui_matches(current: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(current, dict):
        return False
    password = expected.get("password")
    hashed = current.get("password")
    if isinstance(password, str) and isinstance(hashed, str) and password != hashed:
        try:
            if not bcrypt.checkpw(password.encode(), hashed.encode()):
                return False
        except ValueError:
            return False
        current = dict(current, password=password)
    return matches(current, expected)


async def validate_peers(client: SyncthingClient, peers: list[dict[str, Any]]) -> None:
    for peer in peers:
        device = peer["deviceID"]
        current = await client.request("GET", "/rest/config/devices/" + opaque_id(device))
        if not isinstance(current, dict) or current.get("deviceID") != device:
            raise PublicError(
                "preflight_failed", "Every shared peer must be a configured canonical device."
            )


async def update(
    client: SyncthingClient,
    instance: Instance,
    settings: Settings,
    route: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    current = await client.request("GET", route)
    if not isinstance(current, dict):
        raise PublicError("upstream_shape", "Expected a configuration object.")
    check_revision(current, args)
    patch = args["patch"]
    effective = merge(current, patch)
    kind = kind_for(route)
    validate_patch(kind, patch, settings, instance, effective=effective)
    if kind == "gui":
        status = await client.request("GET", "/rest/system/status")
        if not isinstance(status, dict) or type(status.get("guiAddressOverridden")) is not bool:
            raise PublicError("upstream_shape", "Cannot verify the GUI runtime override state.")
        if status["guiAddressOverridden"]:
            raise PublicError(
                "unsupported_override",
                "GUI runtime address overrides require manual administration.",
            )
        address = effective.get("address")
        if isinstance(address, str) and address.startswith("/"):
            if not settings.allow_destructive:
                raise PublicError(
                    "permission_denied", "UNIX socket GUI rebinding requires destructive authority."
                )
            if args.get("confirm") is not True:
                raise PublicError(
                    "confirmation_required", "UNIX socket GUI rebinding requires confirm=true."
                )
    if kind == "folder" and "devices" in patch:
        await validate_peers(client, patch["devices"])
    if (
        kind == "folder"
        and "type" in patch
        and current.get("type") != patch["type"]
        and "receiveencrypted" in {current.get("type"), patch["type"]}
    ):
        raise PublicError("invalid_patch", "Transitions to or from receiveencrypted are excluded.")
    # PUT the complete controlled merge: PATCH replaces child objects upstream.
    return await config_mutation(client, instance, "PUT", route, effective)


async def absent(client: SyncthingClient, route: str) -> None:
    try:
        await client.request("GET", route)
    except PublicError as error:
        if error.code == "not_found":
            return
        raise
    raise PublicError("already_exists", "Resource already exists; create will not replace it.")


async def replace_ignores(
    client: SyncthingClient,
    instance: Instance,
    folder: str,
    lines: list[str],
    expected: str | None = None,
) -> dict[str, Any]:
    ignore_lines(lines)
    params = {"folder": folder}
    current = await client.request("GET", "/rest/db/ignores", params=params)
    check_revision({"ignore": raw_ignores(current)}, {"expected_revision": expected})
    succeeded, _, error = await mutate(
        client, "POST", "/rest/db/ignores", params=params, body={"ignore": lines}
    )
    verified: bool | None = None
    try:
        readback = await client.request("GET", "/rest/db/ignores", params=params)
        verified = raw_ignores(readback) == lines
    except PublicError:
        pass
    result = result_for(instance, succeeded, verified, error=error)
    result["scope"] = {"folder": folder}
    return result


async def create_folder(
    op: Operation,
    args: dict[str, Any],
    instance: Instance,
    client: SyncthingClient,
    settings: Settings,
) -> dict[str, Any]:
    folder = args["folder"]
    path = destination(args["path"], instance)
    resource = "/rest/config/folders/" + opaque_id(folder)
    device = args.get("device")
    if device is not None:
        offers = await client.request("GET", "/rest/cluster/pending/folders")
        offer = offers.get(folder, {}) if isinstance(offers, dict) else {}
        offered_by = offer.get("offeredBy", {}) if isinstance(offer, dict) else {}
        if device not in offered_by:
            raise PublicError("pending_offer_missing", "No matching pending folder offer exists.")
        offered = offered_by[device]
        if offered.get("receiveEncrypted") or offered.get("remoteEncrypted"):
            raise PublicError("unsupported_offer", "Encrypted pending offers require manual setup.")
        try:
            current = await client.request("GET", resource)
        except PublicError as error:
            if error.code != "not_found":
                raise
        else:
            if not isinstance(current, dict) or current.get("path") != path:
                raise PublicError("already_exists", "Existing shared folder must retain its path.")
            peers = list(current.get("devices") or [])
            if device not in {peer.get("deviceID") for peer in peers}:
                peers.append({"deviceID": device})
            # Accepting an existing folder is a deliberate merge; caller must
            # use update for other changes rather than unintentionally replace it.
            if args.get("patch") or args.get("ignores") is not None or args.get("devices"):
                raise PublicError(
                    "invalid_argument", "Existing-folder acceptance only adds the offered peer."
                )
            return await update(
                client,
                instance,
                settings,
                resource,
                {"patch": {"devices": peers}, "expected_revision": revision(current)},
            )
    else:
        await absent(client, resource)
    defaults = await client.request("GET", "/rest/config/defaults/folder")
    if not isinstance(defaults, dict):
        raise PublicError("upstream_shape", "Expected folder defaults.")
    if any(key in args["patch"] for key in {"id", "path", "devices", "paused", "label"}):
        raise PublicError(
            "invalid_patch", "Use the explicit creation arguments for identity and sharing."
        )
    peers = list(args["devices"])
    if device is not None and device not in peers:
        peers.append(device)
    if len(set(peers)) != len(peers):
        raise PublicError("invalid_argument", "Duplicate peer IDs.")
    status = await client.request("GET", "/rest/system/status")
    local = status.get("myID") if isinstance(status, dict) else None
    if not isinstance(local, str) or not local:
        raise PublicError("upstream_shape", "Cannot determine the local device ID.")
    if local not in peers:
        peers.append(local)
    for peer in peers:
        opaque_id(peer)
    await validate_peers(client, [{"deviceID": peer} for peer in peers])
    effective = merge(defaults, args["patch"])
    effective.update(
        id=folder,
        path=path,
        label=args["label"],
        paused=True,
        devices=[{"deviceID": peer} for peer in peers],
    )
    # Do not inherit sharing lists. Every other inherited setting is reviewed
    # exactly like an explicit field before any mutation.
    validate_patch(
        "folder",
        {key: value for key, value in effective.items() if key != "id"},
        settings,
        instance,
        effective=effective,
        creating=True,
    )
    lines = args.get("ignores")
    if lines is not None:
        if not settings.allow_destructive:
            raise PublicError(
                "permission_denied", "Initial ignore replacement requires destructive permission."
            )
        ignore_lines(lines)
    else:
        ignore_defaults = await client.request("GET", "/rest/config/defaults/ignores")
        if not isinstance(ignore_defaults, dict) or not isinstance(
            ignore_defaults.get("lines"), list
        ):
            raise PublicError("upstream_shape", "Expected default ignore lines.")
        ignore_lines(ignore_defaults["lines"])
        lines = ignore_defaults["lines"]
        if lines and not settings.allow_destructive:
            raise PublicError(
                "permission_denied", "Inherited ignore setup requires destructive permission."
            )
    result = await config_mutation(
        client, instance, "POST", "/rest/config/folders", effective, read_route=resource
    )
    result["scope"] = {"folder": folder}
    if result["outcome"] != "verified":
        return result
    try:
        actual_ignores = await client.request("GET", "/rest/db/ignores", params={"folder": folder})
        existing_lines = raw_ignores(actual_ignores)
        ignore_lines(existing_lines)
        if args.get("ignores") is None and existing_lines:
            if lines and lines != existing_lines:
                raise PublicError(
                    "ignore_conflict",
                    "Existing ignore file differs from defaults; folder remains paused.",
                )
            # Preserve the existing physical ignore file when no replacement was
            # explicitly requested, including its original raw line ordering.
        else:
            ignore_result = await replace_ignores(
                client, instance, folder, lines or [], revision({"ignore": existing_lines})
            )
            if ignore_result["outcome"] != "verified":
                ignore_result.update(
                    scope={"folder": folder}, setup_stage="ignores", kept_paused=True
                )
                return ignore_result
    except PublicError as setup_error:
        result.update(
            outcome="outcome_unknown",
            setup_stage="ignores",
            kept_paused=True,
            error=setup_error.payload(),
        )
        return result
    if not args["paused"]:
        result = await update(client, instance, settings, resource, {"patch": {"paused": False}})
        result["scope"] = {"folder": folder}
    return result


async def create_device(
    op: Operation,
    args: dict[str, Any],
    instance: Instance,
    client: SyncthingClient,
    settings: Settings,
) -> dict[str, Any]:
    device = args["device"]
    resource = "/rest/config/devices/" + opaque_id(device)
    if op.handler == "accept_device":
        pending = await client.request("GET", "/rest/cluster/pending/devices")
        if not isinstance(pending, dict) or device not in pending:
            raise PublicError("pending_offer_missing", "No matching pending device exists.")
    await absent(client, resource)
    validated = await client.request("GET", "/rest/svc/deviceid", params={"id": device})
    if not isinstance(validated, dict) or validated.get("id") != device:
        raise PublicError("invalid_argument", "Use a valid canonical device ID.")
    defaults = await client.request("GET", "/rest/config/defaults/device")
    if not isinstance(defaults, dict):
        raise PublicError("upstream_shape", "Expected device defaults.")
    if set(args["patch"]) & {"deviceID", "name"}:
        raise PublicError("invalid_patch", "Use explicit device identity and name arguments.")
    effective = merge(defaults, args["patch"])
    effective.update(deviceID=device, name=args["name"])
    validate_patch(
        "device",
        {key: value for key, value in effective.items() if key != "deviceID"},
        settings,
        instance,
        effective=effective,
        creating=True,
    )
    return await config_mutation(
        client, instance, "POST", "/rest/config/devices", effective, read_route=resource
    )


async def write_operation(
    op: Operation,
    args: dict[str, Any],
    instance: Instance,
    client: SyncthingClient,
    settings: Settings,
) -> dict[str, Any]:
    # Defense in depth when called independently from Engine.
    if not permitted(op, settings):
        raise PublicError("permission_denied", "Operation is disabled by server policy.")
    if op.destructive and args.get("confirm") is not True:
        raise PublicError("confirmation_required", "Destructive operations require confirm=true.")
    route, params = route_for(op, args), params_for(op, args)
    if op.handler == "update":
        return await update(client, instance, settings, route, args)
    if op.handler in {"create_folder", "accept_folder"}:
        return await create_folder(op, args, instance, client, settings)
    if op.handler in {"create_device", "accept_device"}:
        return await create_device(op, args, instance, client, settings)
    if op.handler == "delete":
        current = await client.request("GET", route)
        check_revision(current, args)
        result = await config_mutation(client, instance, "DELETE", route, None, deleted=True)
        result["scope"] = {key: args[key] for key in ("folder", "device") if key in args}
        result["semantics"] = "Removes configuration only; local folder data is retained."
        return result
    if op.handler == "pause_folder":
        return await update(
            client, instance, settings, route, {"patch": {"paused": op.name.startswith("pause")}}
        )
    if op.handler == "pause_device":
        current_route = "/rest/config/devices/" + opaque_id(args["device"])
        await client.request("GET", current_route)
        succeeded, _, error = await mutate(client, "POST", route, params={"device": args["device"]})
        verified = None
        try:
            actual = await client.request("GET", current_route)
            verified = actual.get("paused") is op.name.startswith("pause")
        except PublicError:
            pass
        result = result_for(instance, succeeded, verified, error=error)
        result["restart_required"] = await restart_required(client)
        return result
    if op.handler == "ignores":
        await client.request("GET", "/rest/config/folders/" + opaque_id(args["folder"]))
        return await replace_ignores(
            client, instance, args["folder"], args["lines"], args.get("expected_revision")
        )
    if op.handler == "default_ignores":
        ignore_lines(args["lines"])
        current = await client.request("GET", route)
        check_revision(current, args)
        return await config_mutation(client, instance, "PUT", route, {"lines": args["lines"]})
    if op.handler == "restore":
        for path in args["versions"]:
            relative_path(path)
        current = await client.request("GET", "/rest/config/folders/" + opaque_id(args["folder"]))
        if not isinstance(current, dict):
            raise PublicError("upstream_shape", "Expected a folder configuration object.")
        check_revision(current, args)
        available = await client.request("GET", "/rest/folder/versions", params=params)
        if not isinstance(available, dict):
            raise PublicError("upstream_shape", "Expected available file versions.")
        for path, timestamp in args["versions"].items():
            versions = available.get(path, [])
            if not any(
                isinstance(version, dict) and version.get("versionTime") == timestamp
                for version in versions
            ):
                raise PublicError("version_missing", "Requested version is not available.")
        succeeded, errors, error = await mutate(
            client, "POST", route, params=params, body=args["versions"]
        )
        restored, failed, unknown = [], [], []
        readback: dict[str, Any] = {}
        for path in args["versions"]:
            try:
                readback[path] = await client.request(
                    "GET", "/rest/db/file", params={"folder": args["folder"], "file": path}
                )
            except PublicError:
                readback[path] = None
            if not succeeded or not isinstance(errors, dict):
                unknown.append(path)
            elif errors.get(path):
                failed.append(path)
            else:
                restored.append(path)
        result = result_for(instance, succeeded, None, accepted=succeeded, error=error)
        # Metadata readback cannot establish identical restored content; HTTP 200
        # per-file results establish completion reported by the versioner only.
        result.update(
            restored=restored,
            failed=failed,
            unknown=unknown,
            readback_observed=[path for path, value in readback.items() if value is not None],
        )
        if failed or unknown:
            result["outcome"] = "outcome_unknown"
        return result
    if op.handler == "reset":
        if len(set(args["folders"])) != len(args["folders"]):
            raise PublicError("invalid_argument", "Duplicate reset targets.")
        for folder in args["folders"]:
            current = await client.request("GET", "/rest/config/folders/" + opaque_id(folder))
            if not isinstance(current, dict) or current.get("paused") is not True:
                raise PublicError("preflight_failed", "Every database reset target must be paused.")
        affected: list[str] = []
        error = None
        succeeded = True
        for folder in args["folders"]:
            ok, _, error = await mutate(client, "POST", route, params={"folder": folder})
            affected.append(folder)
            if not ok:
                succeeded = False
                break
        observations = []
        for folder in affected:
            try:
                observations.append(
                    {
                        "folder": folder,
                        "status": await client.request(
                            "GET", "/rest/db/status", params={"folder": folder}
                        ),
                    }
                )
            except PublicError:
                observations.append({"folder": folder, "status": None})
        result = result_for(instance, succeeded, None, accepted=succeeded, error=error)
        result.update(
            affected=affected,
            not_attempted=[x for x in args["folders"] if x not in affected],
            partial_possible=not succeeded,
            status=observations,
        )
        return result
    if op.handler in {"override", "revert", "scan", "action"}:
        current = await client.request("GET", "/rest/config/folders/" + opaque_id(args["folder"]))
        check_revision(current, args)
        if op.handler in {"override", "revert"}:
            required = "sendonly" if op.handler == "override" else "receiveonly"
            if not isinstance(current, dict) or current.get("type") != required:
                raise PublicError("preflight_failed", f"Operation requires a {required} folder.")
        if op.handler == "scan":
            if args.get("sub") is not None:
                params["sub"] = relative_path(args["sub"])
            if args.get("next") is not None:
                params["next"] = args["next"]
        succeeded, _, error = await mutate(
            client,
            "POST",
            route,
            params=params,
            timeout=settings.scan_timeout if op.handler == "scan" else None,
        )
        status = None
        try:
            status = await client.request(
                "GET", "/rest/db/status", params={"folder": args["folder"]}
            )
        except PublicError:
            pass
        result = result_for(instance, succeeded, None, accepted=succeeded, error=error)
        result.update(scope={"folder": args["folder"]}, status=status)
        if op.handler == "scan":
            result["completed_synchronously"] = succeeded
        return result
    if op.handler.startswith("dismiss_"):
        collection = "/rest/cluster/pending/" + (
            "devices" if op.handler == "dismiss_device" else "folders"
        )
        before = await client.request("GET", collection)
        key = args["device"] if op.handler == "dismiss_device" else args["folder"]
        if not isinstance(before, dict) or key not in before:
            raise PublicError("pending_offer_missing", "No matching pending offer exists.")
        if op.handler == "dismiss_folder":
            offered_by = before[key].get("offeredBy", {})
            if args["device"] not in offered_by:
                raise PublicError("pending_offer_missing", "No matching offering device exists.")
        query = {key: args[key] for key in ("device", "folder") if key in args}
        succeeded, _, error = await mutate(client, "DELETE", collection, params=query)
        verified = None
        try:
            after = await client.request("GET", collection)
            verified = (
                key not in after
                if op.handler == "dismiss_device"
                else (args["device"] not in after.get(key, {}).get("offeredBy", {}))
            )
        except PublicError:
            pass
        result = result_for(instance, succeeded, verified, error=error)
        result["semantics"] = "Temporary offer dismissal; does not persistently block the peer."
        return result
    if op.handler in {"clear_errors", "report_error"}:
        await client.request("GET", "/rest/system/error")
        body = args.get("message")
        succeeded, _, error = await mutate(
            client, "POST", route, raw_text=body if op.handler == "report_error" else None
        )
        verified = None
        messages: list[Any] = []
        readback_observed: bool | None = None
        try:
            actual = await client.request("GET", "/rest/system/error")
            if not isinstance(actual, dict) or not isinstance(actual.get("errors") or [], list):
                raise PublicError("upstream_shape", "Expected upstream errors.")
            messages = actual.get("errors") or []
            if op.handler == "clear_errors":
                verified = len(messages) == 0
            else:
                # Backend wraps arbitrary external text in a structured log
                # message. Seeing it is an observation, not exact verification.
                verified = None
                readback_observed = any(
                    isinstance(item, dict) and str(body) in str(item.get("message", ""))
                    for item in messages
                )
        except PublicError:
            pass
        result = result_for(
            instance,
            succeeded,
            verified,
            accepted=succeeded and op.handler == "report_error",
            error=error,
        )
        if op.handler == "report_error":
            result["readback_observed"] = readback_observed
        return result
    if op.handler == "loglevels":
        current = await client.request("GET", route)
        levels = current.get("levels", {}) if isinstance(current, dict) else {}
        if set(args["levels"]) - levels.keys():
            raise PublicError("invalid_argument", "Unknown logger name.")
        requested_levels = {key: value.upper() for key, value in args["levels"].items()}
        succeeded, _, error = await mutate(client, "POST", route, body=requested_levels)
        verified = None
        try:
            actual = await client.request("GET", route)
            normalized = {
                key: str(value).upper() for key, value in actual.get("levels", {}).items()
            }
            verified = matches(normalized, requested_levels)
        except PublicError:
            pass
        return result_for(instance, succeeded, verified, error=error)
    if op.handler == "admin_action":
        await client.request("GET", "/rest/system/status")
        if op.name == "upgrade":
            available = await client.request("GET", "/rest/system/upgrade")
            if not isinstance(available, dict) or available.get("newer") is not True:
                raise PublicError("preflight_failed", "No newer upgrade is available.")
        succeeded, _, error = await mutate(client, "POST", route)
        observed = False
        try:
            await client.request("GET", "/rest/system/status")
            observed = True
        except PublicError:
            pass
        result = result_for(instance, succeeded, None, accepted=succeeded, error=error)
        result["backend_reachable_after_request"] = observed
        return result
    raise PublicError("unknown_tool", "Unsupported mutation handler.")

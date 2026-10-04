"""Bounded reads and allowlisted configuration projections."""

from __future__ import annotations

import asyncio
from typing import Any

from .client import SyncthingClient
from .config import Instance, Settings
from .errors import PublicError
from .registry import Operation
from .safety import destination, opaque_id, relative_path, revision

FOLDER_FIELDS = frozenset(
    """id label path type filesystemType paused rescanIntervalS
fsWatcherEnabled fsWatcherDelayS fsWatcherTimeoutS devices group ignorePerms autoNormalize
minDiskFree versioning copiers pullerMaxPendingKiB hashers order ignoreDelete
scanProgressIntervalS pullerPauseS pullerDelayS maxConflicts disableSparseFiles markerName
copyOwnershipFromParent modTimeWindowS maxConcurrentWrites disableFsync blockPullOrder
copyRangeMethod caseSensitiveFS junctionsAsDirs syncOwnership sendOwnership syncXattrs
sendXattrs blockIndexing xattrFilter""".split()
)
DEVICE_FIELDS = frozenset(
    """deviceID name compression introducer skipIntroductionRemovals
introducedBy paused autoAcceptFolders maxSendKbps maxRecvKbps maxRequestKiB untrusted
remoteGUIPort numConnections group""".split()
)
OPTIONS_FIELDS = frozenset(
    """globalAnnounceEnabled localAnnounceEnabled localAnnouncePort
maxSendKbps maxRecvKbps reconnectionIntervalS relaysEnabled relayReconnectIntervalM
startBrowser natEnabled natLeaseMinutes natRenewalMinutes natTimeoutSeconds urAccepted
urSeen urInitialDelayS autoUpgradeIntervalH upgradeToPreReleases keepTemporariesH
progressUpdateIntervalS limitBandwidthInLan minHomeDiskFree overwriteRemoteDeviceNamesOnConnect
tempIndexMinBlocks trafficClass setLowPriority maxFolderConcurrency crashReportingEnabled
stunKeepaliveStartS stunKeepaliveMinS maxConcurrentIncomingRequestKiB announceLANAddresses
sendFullIndexOnUpgrade auditEnabled connectionLimitEnough connectionLimitMax
connectionPriorityTcpLan connectionPriorityQuicLan connectionPriorityTcpWan
connectionPriorityQuicWan connectionPriorityRelay connectionPriorityUpgradeThreshold""".split()
)
GUI_FIELDS = frozenset(
    """enabled address authMode metricsWithoutAuth useTLS theme
insecureAdminAccess insecureSkipHostcheck insecureAllowFrameLoading sendBasicAuthPrompt
sessionCookieDurationS sessionCookiePath""".split()
)
LDAP_FIELDS = frozenset("address transport insecureSkipVerify".split())


def configuration_projection(value: Any, route: str) -> Any:
    if not isinstance(value, dict):
        raise PublicError("upstream_shape", "Upstream configuration has an unexpected shape.")
    if route == "/rest/config":
        result: dict[str, Any] = {}
        for key in ("folders", "devices"):
            if isinstance(value.get(key), list):
                result[key] = [
                    configuration_projection(item, "/rest/config/" + key) for item in value[key]
                ]
        for key in ("options", "gui", "ldap"):
            if isinstance(value.get(key), dict):
                result[key] = configuration_projection(value[key], "/rest/config/" + key)
        if isinstance(value.get("defaults"), dict):
            result["defaults"] = {
                key: configuration_projection(item, "/rest/config/defaults/" + key)
                for key, item in value["defaults"].items()
                if key in {"folder", "device", "ignores"} and isinstance(item, dict)
            }
        if isinstance(value.get("version"), int):
            result["version"] = value["version"]
        return result
    if "/folders" in route or route.endswith("/folder"):
        fields = FOLDER_FIELDS
    elif "/devices" in route or route.endswith("/device"):
        fields = DEVICE_FIELDS
    elif route.endswith("/options"):
        fields = OPTIONS_FIELDS
    elif route.endswith("/gui"):
        fields = GUI_FIELDS
    elif route.endswith("/ldap"):
        fields = LDAP_FIELDS
    elif route.endswith("/ignores"):
        fields = frozenset({"lines"})
    else:
        fields = frozenset()
    result = {key: item for key, item in value.items() if key in fields}
    if isinstance(result.get("devices"), list):
        result["devices"] = [
            {key: item for key, item in device.items() if key in {"deviceID", "introducedBy"}}
            for device in result["devices"]
            if isinstance(device, dict)
        ]
    if isinstance(result.get("versioning"), dict):
        versioning = result["versioning"]
        allowed_params = {"keep", "maxAge", "cleanInterval", "cleanoutDays", "versionsPath"}
        result["versioning"] = {
            key: (
                {k: v for k, v in item.items() if k in allowed_params}
                if key == "params" and isinstance(item, dict)
                else item
            )
            for key, item in versioning.items()
            if key in {"type", "params", "cleanupIntervalS", "fsPath", "fsType"}
        }
    if isinstance(result.get("minDiskFree"), dict):
        result["minDiskFree"] = {
            key: item for key, item in result["minDiskFree"].items() if key in {"value", "unit"}
        }
    if isinstance(result.get("xattrFilter"), dict):
        # Nested unknown fields are also excluded.
        attr = result["xattrFilter"]
        result["xattrFilter"] = {
            key: item for key, item in attr.items() if key in {"maxSingleEntrySize", "maxTotalSize"}
        }
        if isinstance(attr.get("entries"), list):
            result["xattrFilter"]["entries"] = [
                {key: item for key, item in entry.items() if key in {"match", "permit"}}
                for entry in attr["entries"]
                if isinstance(entry, dict)
            ]
    return result


def selected(value: Any, fields: list[str] | None) -> Any:
    if fields is None:
        return value
    if isinstance(value, list):
        return [selected(item, fields) for item in value]
    if not isinstance(value, dict) or any(key not in value for key in fields):
        raise PublicError(
            "invalid_fields", "Requested fields are unavailable in the safe projection."
        )
    return {key: value[key] for key in fields}


EVENT_DATA_FIELDS = {
    "StateChanged": {"folder", "from", "to", "duration"},
    "DeviceDiscovered": {"device"},
    "DeviceConnected": {"id", "deviceName", "clientName", "clientVersion", "type"},
    "DeviceDisconnected": {"id"},
    "DevicePaused": {"device"},
    "DeviceResumed": {"device"},
    "FolderPaused": {"id"},
    "FolderResumed": {"id"},
    "FolderCompletion": {"folder", "device", "completion", "needBytes", "needItems", "needDeletes"},
    "FolderSummary": {"folder"},
    "FolderErrors": {"folder"},
    "FolderScanProgress": {"folder", "current", "total", "rate"},
    "FolderWatchStateChanged": {"folder", "from", "to"},
    "LocalChangeDetected": {"folder", "folderID", "path", "action", "type"},
    "RemoteChangeDetected": {"folder", "folderID", "path", "action", "type"},
    "ItemStarted": {"folder", "item", "type", "action"},
    "ItemFinished": {"folder", "item", "type", "action"},
    "LocalIndexUpdated": {"folder", "items", "sequence"},
    "RemoteIndexUpdated": {"folder", "device", "items", "sequence"},
    "FolderRejected": {"folder", "device"},
    "DeviceRejected": {"device"},
    "PendingDevicesChanged": set(),
    "PendingFoldersChanged": set(),
    "StartupComplete": set(),
    "Starting": set(),
    "Ping": set(),
}


def event_projection(event: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: value
        for key, value in event.items()
        if key in {"id", "globalID", "time", "type"} and type(value) in {str, int}
    }
    kind = event.get("type")
    if kind == "ConfigSaved":
        result["data"] = {"configuration_changed": True}
        return result
    data = event.get("data")
    if not isinstance(data, dict):
        data = {}
    allowed = EVENT_DATA_FIELDS.get(kind, set()) if isinstance(kind, str) else set()
    result["data"] = {
        key: value
        for key, value in data.items()
        if key in allowed and type(value) in {str, int, float, bool}
    }
    if kind not in EVENT_DATA_FIELDS:
        result["data_omitted"] = True
    return result


def route_for(op: Operation, args: dict[str, Any]) -> str:
    route = op.route
    for key in ("folder", "device"):
        if args.get(key) is not None:
            encoded = opaque_id(args[key])
            route = route.replace("{" + key + "}", encoded)
    return route


def params_for(op: Operation, args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if op.route.startswith(("/rest/db/", "/rest/folder/", "/rest/debug/")):
        for key in ("folder", "device", "file"):
            if args.get(key) is not None:
                if key == "file":
                    relative_path(args[key])
                else:
                    opaque_id(args[key])
                params[key] = args[key]
    if op.name == "validate_device_id":
        opaque_id(args["device"])
        params["id"] = args["device"]
    if args.get("prefix") is not None:
        params["prefix"] = relative_path(args["prefix"])
    if op.name == "folder_browse":
        params["levels"] = args["levels"]
    if args.get("length") is not None:
        params["length"] = args["length"]
    if args.get("since") is not None and op.handler == "logs":
        params["since"] = args["since"]
    return params


def local_page(items: list[Any], args: dict[str, Any], settings: Settings) -> dict[str, Any]:
    limit = min(args.get("limit", 50), settings.max_page_size)
    start = int(args.get("cursor") or 0)
    page = selected(items[start : start + limit], args.get("fields"))
    more = start + len(page) < len(items)
    return {
        "items": page,
        "returned": len(page),
        "next_cursor": str(start + len(page)) if more else None,
        "truncated": more,
        "pagination": "local_slice",
        "consistency": "Upstream state can change between calls.",
    }


def raw_ignores(value: Any) -> list[str]:
    if (
        not isinstance(value, dict)
        or "ignore" not in value
        or value["ignore"] is not None
        and (
            not isinstance(value["ignore"], list)
            or not all(isinstance(line, str) for line in value["ignore"])
        )
    ):
        raise PublicError("upstream_shape", "Expected raw ignore lines.")
    return value["ignore"] or []


async def read_operation(
    op: Operation,
    args: dict[str, Any],
    instance: Instance,
    client: SyncthingClient,
    settings: Settings,
) -> dict[str, Any]:
    if op.handler == "instances":
        return {
            "items": [
                {"name": item.name, "default_for_reads": index == 0}
                for index, item in enumerate(settings.instances)
            ],
            "permissions": {
                "writes": settings.allow_writes,
                "destructive": settings.allow_destructive,
                "admin": settings.allow_admin,
            },
            "profile": settings.profile,
        }
    if op.handler == "overview":
        summary = None
        partial = False
        deadline_exceeded = False
        try:
            # A dashboard shares one deadline across all upstream requests;
            # slow folders must not multiply it by the page size.
            async with asyncio.timeout(settings.request_timeout):
                status = await client.request("GET", "/rest/system/status")
                folders = await client.request("GET", "/rest/config/folders")
                if not isinstance(folders, list):
                    raise PublicError("upstream_shape", "Expected upstream folders.")
                summary = local_page(
                    [
                        configuration_projection(folder, "/rest/config/folders")
                        for folder in folders
                    ],
                    args,
                    settings,
                )
                for folder in summary["items"]:
                    if "id" in folder:
                        folder["status"] = None
                for folder in summary["items"]:
                    if "id" not in folder:
                        continue
                    try:
                        folder["status"] = await client.request(
                            "GET", "/rest/db/status", params={"folder": folder["id"]}
                        )
                    except PublicError:
                        partial = True
        except TimeoutError:
            if summary is None:
                raise PublicError("upstream_timeout", "Overview exceeded its deadline.") from None
            partial = deadline_exceeded = True
        return {
            "instance": instance.name,
            "system": status,
            **summary,
            "partial": partial,
            "deadline_exceeded": deadline_exceeded,
        }
    route = route_for(op, args)
    params = params_for(op, args)
    limit = min(args.get("limit", 50), settings.max_page_size)
    if op.handler in {"upstream", "errors", "errors_safe"}:
        params.update(page=max(1, int(args.get("cursor") or 1)), perpage=limit)
    if op.handler == "host":
        destination(args["current"], instance)
        # Upstream globs can cross configured roots and cannot be confined lexically.
        if any(c in args["current"] for c in "*?[]{}"):
            raise PublicError("path_denied", "Host glob browsing is not supported.")
        params["current"] = args["current"]
    if op.handler == "events":
        params.update(since=args["since"], timeout=args["timeout"])
        # Upstream limit returns the newest N, losing earlier events. Fetch the
        # bounded retention buffer instead, then slice the oldest processed events.
        if args.get("events"):
            if any(not x.isascii() or not x.isalnum() for x in args["events"]):
                raise PublicError("invalid_argument", "Invalid event type name.")
            if op.name == "disk_events":
                raise PublicError("invalid_argument", "Disk events do not support event filters.")
            params["events"] = ",".join(args["events"])
    value = await client.request(
        "GET",
        route,
        params=params,
        timeout=max(settings.request_timeout, args.get("timeout", 0) + 5),
    )
    base: dict[str, Any] = {"instance": instance.name}
    if op.handler == "config":
        base.update(
            data=selected(configuration_projection(value, route), args.get("fields")),
            revision=revision(value),
        )
    elif op.handler == "config_list":
        if not isinstance(value, list):
            raise PublicError("upstream_shape", "Expected an upstream configuration list.")
        base.update(
            local_page([configuration_projection(item, route) for item in value], args, settings)
        )
    elif op.handler in {"list", "host"}:
        if value is None and op.handler == "list":
            value = []
        if not isinstance(value, list):
            raise PublicError("upstream_shape", "Expected an upstream list.")
        if op.handler == "host":
            value = [item for item in value if isinstance(item, str) and _allowed(item, instance)]
        base.update(local_page(value, args, settings))
    elif op.handler == "map":
        if not isinstance(value, dict):
            raise PublicError("upstream_shape", "Expected an upstream map.")
        base.update(
            local_page(
                [{"id": key, "value": item} for key, item in sorted(value.items())], args, settings
            )
        )
    elif op.handler in {"upstream", "errors", "errors_safe"}:
        if not isinstance(value, dict):
            raise PublicError("upstream_shape", "Expected an upstream paged object.")
        keys = (
            ("progress", "queued", "rest")
            if op.name == "needed_files"
            else (("errors",) if op.handler in {"errors", "errors_safe"} else ("files",))
        )
        if op.handler == "errors_safe":
            value = {
                key: item for key, item in value.items() if key in {"folder", "page", "perpage"}
            } | {
                "errors": [
                    {"path": item.get("path"), "error_present": bool(item.get("error"))}
                    for item in value.get("errors") or []
                    if isinstance(item, dict)
                ]
            }
        count = sum(len(value.get(key) or []) for key in keys)
        page = int(value.get("page", params["page"]))
        base.update(
            data=selected(value, args.get("fields")),
            returned=count,
            next_cursor=str(page + 1) if count >= limit else None,
            truncated=count >= limit,
            pagination="upstream_pages",
            consistency="A full page may have a successor; state can change between calls.",
        )
    elif op.handler == "events":
        if not isinstance(value, list) or any(
            not isinstance(item, dict) or not isinstance(item.get("id"), int) for item in value
        ):
            raise PublicError(
                "upstream_shape", "Expected an upstream event array with integer IDs."
            )
        items = [item for item in value if item["id"] > args["since"]]
        event_page = items[:limit]
        # Filtered subscriptions naturally have ID gaps; report uncertainty rather
        # than promise absence of losses in that case.
        filtered = bool(args.get("events")) or op.name == "disk_events"
        gap = bool(items and args["since"] > 0 and items[0]["id"] > args["since"] + 1)
        base.update(
            items=selected([event_projection(item) for item in event_page], args.get("fields")),
            returned=len(event_page),
            next_cursor=event_page[-1]["id"] if event_page else args["since"],
            upstream_gap=gap if not filtered else None,
            gap_detection="unavailable_for_filtered_stream" if filtered else "id_discontinuity",
            retention_complete=False,
            local_truncated=len(event_page) < len(items),
            truncated=len(event_page) < len(items),
            skipped=0,
            pagination="event_ids",
        )
    elif op.handler == "logs":
        if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
            raise PublicError("upstream_shape", "Expected upstream log messages.")
        base.update(local_page(value["messages"], args, settings))
    elif op.handler == "ignores":
        lines = raw_ignores(value)
        base.update(
            data=selected({"ignore": lines}, args.get("fields")),
            revision=revision({"ignore": lines}),
        )
    elif op.handler == "error_count":
        if not isinstance(value, dict) or not isinstance(value.get("errors") or [], list):
            raise PublicError("upstream_shape", "Expected upstream errors.")
        base["data"] = selected({"count": len(value.get("errors") or [])}, args.get("fields"))
    else:
        base["data"] = selected(value, args.get("fields"))
    return base


def _allowed(path: str, instance: Instance) -> bool:
    try:
        destination(path, instance)
        return True
    except PublicError:
        return False

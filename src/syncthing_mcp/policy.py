"""Reviewed configuration mutation fields for Syncthing 2.1.5."""

from __future__ import annotations

import math
import ntpath
import posixpath
from typing import Any

from .config import Instance, Settings
from .errors import PublicError
from .reads import FOLDER_FIELDS, GUI_FIELDS, LDAP_FIELDS, OPTIONS_FIELDS
from .safety import destination, opaque_id, relative_path

FOLDER_RUNTIME = frozenset("label paused rescanIntervalS fsWatcherEnabled fsWatcherDelayS".split())
DEVICE_RUNTIME = frozenset("name paused compression maxSendKbps maxRecvKbps".split())
DEVICE_ADMIN = frozenset(
    """addresses certName introducer skipIntroductionRemovals introducedBy
allowedNetworks autoAcceptFolders ignoredFolders maxRequestKiB untrusted remoteGUIPort
numConnections group""".split()
)
FOLDER_BOOL = frozenset(
    """paused fsWatcherEnabled ignorePerms autoNormalize ignoreDelete
 disableSparseFiles copyOwnershipFromParent disableFsync caseSensitiveFS junctionsAsDirs
syncOwnership sendOwnership syncXattrs sendXattrs blockIndexing""".split()
)
FOLDER_INT = frozenset(
    """rescanIntervalS copiers pullerMaxPendingKiB hashers scanProgressIntervalS
pullerPauseS maxConflicts modTimeWindowS maxConcurrentWrites""".split()
)
FOLDER_FLOAT = frozenset("fsWatcherDelayS fsWatcherTimeoutS pullerDelayS".split())
DEVICE_BOOL = frozenset(
    """paused introducer skipIntroductionRemovals
    autoAcceptFolders untrusted""".split()
)
DEVICE_INT = frozenset("maxSendKbps maxRecvKbps maxRequestKiB remoteGUIPort numConnections".split())
OPTIONS_BOOL = frozenset(
    """globalAnnounceEnabled localAnnounceEnabled relaysEnabled startBrowser
natEnabled upgradeToPreReleases limitBandwidthInLan overwriteRemoteDeviceNamesOnConnect
setLowPriority crashReportingEnabled announceLANAddresses sendFullIndexOnUpgrade
auditEnabled""".split()
)
OPTIONS_ADMIN = OPTIONS_FIELDS | frozenset(
    """listenAddresses globalAnnounceServers localAnnounceMCAddr
urUniqueId urURL releasesURL alwaysLocalNets unackedNotificationIDs crURL stunServers
featureFlags auditFile""".split()
)
GUI_ADMIN = GUI_FIELDS | frozenset({"user", "password", "unixSocketPermissions"})
LDAP_ADMIN = LDAP_FIELDS | frozenset({"bindDN", "searchBaseDN", "searchFilter"})


def deny(message: str = "Unsupported or unsafe configuration field.") -> PublicError:
    return PublicError("invalid_patch", message)


def scalar(value: Any, kind: type, *, minimum: float | None = None) -> None:
    if kind is float:
        valid = type(value) in {int, float} and math.isfinite(value)
    else:
        valid = type(value) is kind
    if not valid:
        raise deny("Configuration field has an invalid type.")
    if kind in {int, float} and (abs(value) > 2**31 or minimum is not None and value < minimum):
        raise deny("Configuration number is out of range.")
    if kind is str and (len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise deny("Configuration text is too long or contains control characters.")


def string_list(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 100:
        raise deny()
    for item in value:
        scalar(item, str)


def ignore_lines(lines: list[str]) -> None:
    for line in lines:
        if (
            len(line) > 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in line)
            or line.lstrip().lower().startswith("#include")
        ):
            raise deny("Ignore lines must be single lines without #include directives.")


def versioning(value: Any, instance: Instance, folder_path: str | None) -> None:
    if not isinstance(value, dict) or set(value) - {
        "type",
        "params",
        "cleanupIntervalS",
        "fsPath",
        "fsType",
    }:
        raise deny("Unsupported versioning field.")
    if value.get("type", "") not in {"", "simple", "staggered", "trashcan"}:
        raise deny("External and unknown versioning types are excluded.")
    if "cleanupIntervalS" in value:
        scalar(value["cleanupIntervalS"], int, minimum=0)
    if value.get("fsType", "basic") != "basic":
        raise deny("Only basic versioning filesystems are supported.")
    params = value.get("params", {})
    if not isinstance(params, dict) or set(params) - {
        "keep",
        "maxAge",
        "cleanInterval",
        "cleanoutDays",
        "versionsPath",
    }:
        raise deny("Unsupported versioning parameters; commands are excluded.")
    for key, param in params.items():
        scalar(param, str)
        if key != "versionsPath":
            try:
                if not param or not 0 <= int(param) <= 2**31:
                    raise deny("Versioning numeric parameter is out of range.")
            except ValueError:
                raise deny("Versioning numeric parameter is invalid.") from None
    for path in (value.get("fsPath", ""), params.get("versionsPath", "")):
        scalar(path, str)
        if not path:
            continue
        pathmod = ntpath if instance.path_style == "windows" else posixpath
        if pathmod.isabs(path):
            destination(path, instance)
        else:
            relative_path(path)
            if not folder_path:
                raise deny("A version archive requires an explicit allowed destination.")
            destination(pathmod.join(folder_path, path), instance)


def validate_patch(
    kind: str,
    patch: dict[str, Any],
    settings: Settings,
    instance: Instance,
    *,
    effective: dict[str, Any] | None = None,
    creating: bool = False,
) -> None:
    if kind == "folder":
        allowed = FOLDER_FIELDS - {"id"} if settings.allow_admin else FOLDER_RUNTIME
    elif kind == "device":
        allowed = DEVICE_RUNTIME | DEVICE_ADMIN if settings.allow_admin else DEVICE_RUNTIME
    elif kind == "options":
        allowed = OPTIONS_ADMIN
    elif kind == "gui":
        allowed = GUI_ADMIN
    elif kind == "ldap":
        allowed = LDAP_ADMIN
    else:
        raise deny()
    if set(patch) - allowed:
        raise deny("Unknown, identity-changing or unauthorized configuration field.")
    for key, value in patch.items():
        if kind == "folder":
            if key in FOLDER_BOOL:
                scalar(value, bool)
            elif key in FOLDER_INT:
                scalar(value, int, minimum=-1 if key in {"maxConflicts", "modTimeWindowS"} else 0)
            elif key in FOLDER_FLOAT:
                scalar(value, float, minimum=0)
            elif key == "path":
                scalar(value, str)
                destination(value, instance)
            elif key == "devices":
                if not isinstance(value, list) or len(value) > 100:
                    raise deny()
                seen = set()
                for peer in value:
                    if (
                        not isinstance(peer, dict)
                        or set(peer) - {"deviceID", "introducedBy", "encryptionPassword"}
                        or "deviceID" not in peer
                    ):
                        raise deny("Folder peers require explicit valid device IDs.")
                    for peerkey, item in peer.items():
                        scalar(item, str)
                        if peerkey != "encryptionPassword" and item:
                            opaque_id(item)
                    if peer["deviceID"] in seen:
                        raise deny("Duplicate folder peer.")
                    seen.add(peer["deviceID"])
            elif key == "versioning":
                versioning(value, instance, (effective or {}).get("path"))
            elif key == "minDiskFree":
                if not isinstance(value, dict) or set(value) - {"value", "unit"}:
                    raise deny()
                if "value" in value:
                    scalar(value["value"], float, minimum=0)
                if value.get("unit", "%") not in {"%", "k", "M", "G", "T"}:
                    raise deny()
            elif key == "xattrFilter":
                if not isinstance(value, dict) or set(value) - {
                    "entries",
                    "maxSingleEntrySize",
                    "maxTotalSize",
                }:
                    raise deny()
                for size in ("maxSingleEntrySize", "maxTotalSize"):
                    if size in value:
                        scalar(value[size], int, minimum=0)
                entries = value.get("entries", [])
                if not isinstance(entries, list) or len(entries) > 100:
                    raise deny()
                for entry in entries:
                    if not isinstance(entry, dict) or set(entry) - {"match", "permit"}:
                        raise deny()
                    scalar(entry.get("match"), str)
                    scalar(entry.get("permit"), bool)
            else:
                scalar(value, str)
                if key == "type" and value not in {
                    "sendreceive",
                    "sendonly",
                    "receiveonly",
                    "receiveencrypted",
                }:
                    raise deny("Invalid folder type.")
                if key == "filesystemType" and value != "basic":
                    raise deny("Only basic folder filesystems are supported.")
                if key == "markerName" and value:
                    relative_path(value)
        elif kind == "device":
            if key in DEVICE_BOOL:
                scalar(value, bool)
            elif key in DEVICE_INT:
                scalar(value, int, minimum=0)
            elif key in {"addresses", "allowedNetworks"}:
                string_list(value)
            elif key == "ignoredFolders":
                # Persistent ignored-folder edits are deliberately excluded; they
                # would need additional independent offer and trust semantics.
                if value != []:
                    raise deny("Persistent ignored folder edits are excluded.")
            else:
                scalar(value, str)
                if key == "compression" and value not in {"always", "metadata", "never"}:
                    raise deny("Invalid compression mode.")
        elif kind == "options":
            if key in OPTIONS_BOOL:
                scalar(value, bool)
            elif key in {
                "listenAddresses",
                "globalAnnounceServers",
                "alwaysLocalNets",
                "unackedNotificationIDs",
                "stunServers",
                "featureFlags",
            }:
                string_list(value)
            elif key == "minHomeDiskFree":
                if not isinstance(value, dict) or set(value) - {"value", "unit"}:
                    raise deny()
                scalar(value.get("value"), float, minimum=0)
                if value.get("unit") not in {"%", "k", "M", "G", "T"}:
                    raise deny()
            elif key in {
                "localAnnounceMCAddr",
                "urUniqueId",
                "urURL",
                "releasesURL",
                "crURL",
                "auditFile",
            }:
                scalar(value, str)
                if key == "auditFile" and value:
                    destination(value, instance)
            else:
                scalar(value, int, minimum=-1 if key == "urAccepted" else 0)
        elif kind in {"gui", "ldap"}:
            booleans = {
                "enabled",
                "metricsWithoutAuth",
                "useTLS",
                "insecureAdminAccess",
                "insecureSkipHostcheck",
                "insecureAllowFrameLoading",
                "sendBasicAuthPrompt",
                "insecureSkipVerify",
            }
            if key in booleans:
                scalar(value, bool)
                if (key.startswith("insecure") or key == "metricsWithoutAuth") and value:
                    raise deny(
                        "Disabling authentication, host checks or TLS validation is excluded."
                    )
            elif key == "sessionCookieDurationS":
                scalar(value, int, minimum=1)
            else:
                scalar(value, str)
                if key in {"user", "password"} and not value:
                    raise deny("Removing GUI authentication is excluded.")
                if key == "password" and len(value.encode()) > 72:
                    raise deny("GUI passwords must be at most 72 UTF-8 bytes.")
                if key == "authMode" and value not in {"static", "ldap"}:
                    raise deny("Unsupported authentication mode.")
                if key == "transport" and value not in {"plain", "tls", "starttls"}:
                    raise deny("Unsupported LDAP transport.")
    if kind == "folder" and effective is not None:
        if "versioning" in patch or creating:
            versioning(effective.get("versioning", {}), instance, effective.get("path"))
    if kind == "gui" and "authMode" in patch and patch["authMode"] == "static":
        if effective is None or not effective.get("user") or not effective.get("password"):
            raise deny(
                "Static GUI authentication requires effective user and password credentials."
            )
    if kind == "gui" and effective is not None:
        address = effective.get("address")
        # Syncthing classifies leading-slash raw GUI addresses as UNIX sockets.
        # Every changed GUI object restarts that listener, even a theme change.
        if isinstance(address, str) and address.startswith("/"):
            destination(address, instance)

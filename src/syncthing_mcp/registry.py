"""Reviewed, fixed endpoint registry. No arbitrary upstream proxy exists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import PublicError

if TYPE_CHECKING:
    from .config import Settings

ID = Annotated[str, Field(min_length=1, max_length=256)]
PATH = Annotated[str, Field(min_length=1, max_length=4096)]


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instance: Annotated[str | None, Field(max_length=64)] = None
    fields: Annotated[list[str] | None, Field(max_length=30)] = None


class PageArguments(Arguments):
    limit: Annotated[int, Field(ge=1, le=1000)] = 50
    cursor: Annotated[str | None, Field(pattern=r"^[0-9]{1,12}$")] = None


class FolderArguments(Arguments):
    folder: ID


class DeviceArguments(Arguments):
    device: ID


class FolderPageArguments(PageArguments):
    folder: ID


class FileArguments(FolderArguments):
    file: PATH


class BrowseArguments(FolderArguments):
    prefix: PATH | None = None
    levels: Annotated[int, Field(ge=0, le=10)] = 1
    limit: Annotated[int, Field(ge=1, le=1000)] = 50
    cursor: Annotated[str | None, Field(pattern=r"^[0-9]{1,12}$")] = None


class RemotePageArguments(FolderPageArguments):
    device: ID


class CompletionArguments(FolderArguments):
    device: ID | None = None


class EventArguments(Arguments):
    since: Annotated[int, Field(ge=0, le=2**53)] = 0
    limit: Annotated[int, Field(ge=1, le=1000)] = 50
    timeout: Annotated[int, Field(ge=0, le=60)] = 0
    events: Annotated[list[str] | None, Field(max_length=30)] = None


class HostBrowseArguments(PageArguments):
    current: PATH


class LogArguments(PageArguments):
    since: Annotated[str | None, Field(max_length=64)] = None


class RandomArguments(Arguments):
    length: Annotated[int, Field(ge=1, le=128)] = 32


class MutationArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instance: Annotated[str | None, Field(max_length=64)] = None


class ConfirmArguments(MutationArguments):
    confirm: bool


class FolderMutationArguments(MutationArguments):
    folder: ID


class DeviceMutationArguments(MutationArguments):
    device: ID


class FolderConfirmArguments(FolderMutationArguments):
    confirm: bool
    expected_revision: Annotated[str | None, Field(pattern=r"^[a-f0-9]{64}$")] = None


class DeviceConfirmArguments(DeviceMutationArguments):
    confirm: bool
    expected_revision: Annotated[str | None, Field(pattern=r"^[a-f0-9]{64}$")] = None


class PatchArguments(MutationArguments):
    patch: Annotated[dict[str, Any], Field(min_length=1, max_length=64)]
    expected_revision: Annotated[str | None, Field(pattern=r"^[a-f0-9]{64}$")] = None


class GuiPatchArguments(PatchArguments):
    confirm: Annotated[
        bool,
        Field(
            description="Required for UNIX socket GUI rebinding, which may unlink its destination."
        ),
    ] = False


class FolderPatchArguments(PatchArguments):
    folder: ID


class DevicePatchArguments(PatchArguments):
    device: ID


class CreateFolderArguments(FolderMutationArguments):
    path: PATH
    label: Annotated[str, Field(max_length=256)] = ""
    devices: Annotated[list[ID], Field(max_length=100)] = Field(default_factory=list)
    paused: bool = True
    patch: Annotated[dict[str, Any], Field(max_length=64)] = Field(default_factory=dict)
    ignores: Annotated[list[str] | None, Field(max_length=1000)] = None


class CreateDeviceArguments(DeviceMutationArguments):
    name: Annotated[str, Field(max_length=256)] = ""
    patch: Annotated[dict[str, Any], Field(max_length=64)] = Field(default_factory=dict)


class AcceptFolderArguments(CreateFolderArguments):
    device: ID


class ScanArguments(FolderMutationArguments):
    sub: PATH | None = None
    next: Annotated[int | None, Field(ge=0, le=86400)] = None


class PriorityArguments(FolderMutationArguments):
    file: PATH


class IgnoreArguments(FolderConfirmArguments):
    lines: Annotated[list[str], Field(max_length=1000)]


class DefaultIgnoreArguments(ConfirmArguments):
    lines: Annotated[list[str], Field(max_length=1000)]
    expected_revision: Annotated[str | None, Field(pattern=r"^[a-f0-9]{64}$")] = None


class RestoreArguments(FolderConfirmArguments):
    versions: Annotated[dict[str, str], Field(min_length=1, max_length=100)]


class ResetArguments(ConfirmArguments):
    folders: Annotated[list[ID], Field(min_length=1, max_length=1)]


class DismissFolderArguments(FolderMutationArguments):
    device: ID


class LogLevelArguments(MutationArguments):
    levels: Annotated[
        dict[str, Literal["debug", "info", "warn", "error"]], Field(min_length=1, max_length=50)
    ]


class ReportErrorArguments(MutationArguments):
    message: Annotated[str, Field(min_length=1, max_length=4096)]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    destructive: bool
    group: str


@dataclass(frozen=True)
class Operation:
    name: str
    description: str
    model: type[BaseModel]
    route: str
    handler: str = "object"
    group: str = "system"
    read_only: bool = True
    destructive: bool = False
    admin: bool = False
    core: bool = False

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "syncthing_" + self.name,
            self.description,
            self.model.model_json_schema(),
            self.read_only,
            self.destructive or self.name == "update_gui",
            self.group,
        )


def read(
    name: str,
    route: str,
    model: type[BaseModel] = Arguments,
    *,
    handler: str = "object",
    group: str = "system",
    core: bool = False,
    description: str | None = None,
) -> Operation:
    return Operation(
        name,
        description or name.replace("_", " ").capitalize() + ".",
        model,
        "/rest/" + route,
        handler,
        group,
        core=core,
    )


def write(
    name: str,
    route: str,
    model: type[BaseModel],
    *,
    handler: str,
    group: str = "config",
    destructive: bool = False,
    admin: bool = False,
    core: bool = False,
    description: str | None = None,
) -> Operation:
    return Operation(
        name,
        description or name.replace("_", " ").capitalize() + ".",
        model,
        "/rest/" + route,
        handler,
        group,
        False,
        destructive,
        admin,
        core,
    )


OPERATIONS = [
    read(
        "instances",
        "system/status",
        handler="instances",
        core=True,
        description="Discover configured instance aliases and active permissions.",
    ),
    read(
        "overview",
        "system/status",
        PageArguments,
        handler="overview",
        core=True,
        description="Bounded overview of this instance and folder synchronization state.",
    ),
    read("system_status", "system/status", core=True),
    read("system_version", "system/version", core=True),
    read("system_ping", "system/ping", core=True),
    read("system_health", "noauth/health", core=True),
    read("system_connections", "system/connections", core=True),
    read("system_errors", "system/error", handler="error_count"),
    read("system_error_messages", "system/error", group="diagnostics"),
    read("system_discovery", "system/discovery", group="diagnostics"),
    read("system_paths", "system/paths", group="diagnostics"),
    read("system_logs", "system/log", LogArguments, group="diagnostics", handler="logs"),
    read("log_levels", "system/loglevels", group="diagnostics"),
    read("host_browse", "system/browse", HostBrowseArguments, group="diagnostics", handler="host"),
    read("upgrade_available", "system/upgrade"),
    read("config", "config", handler="config", group="config"),
    read("restart_required", "config/restart-required", group="config", core=True),
    read(
        "folders", "config/folders", PageArguments, handler="config_list", group="config", core=True
    ),
    read(
        "devices", "config/devices", PageArguments, handler="config_list", group="config", core=True
    ),
    read(
        "folder_config",
        "config/folders/{folder}",
        FolderArguments,
        handler="config",
        group="config",
    ),
    read(
        "device_config",
        "config/devices/{device}",
        DeviceArguments,
        handler="config",
        group="config",
    ),
    read("folder_defaults", "config/defaults/folder", handler="config", group="config"),
    read("device_defaults", "config/defaults/device", handler="config", group="config"),
    read("ignore_defaults", "config/defaults/ignores", handler="config", group="config"),
    read("options", "config/options", handler="config", group="config"),
    read("gui_config", "config/gui", handler="config", group="config"),
    read("ldap_config", "config/ldap", handler="config", group="config"),
    read(
        "pending_devices", "cluster/pending/devices", PageArguments, handler="map", group="cluster"
    ),
    read(
        "pending_folders", "cluster/pending/folders", PageArguments, handler="map", group="cluster"
    ),
    read("folder_status", "db/status", FolderArguments, group="folder", core=True),
    read("folder_completion", "db/completion", CompletionArguments, group="folder", core=True),
    read(
        "folder_errors", "folder/errors", FolderPageArguments, group="folder", handler="errors_safe"
    ),
    read(
        "folder_error_messages",
        "folder/errors",
        FolderPageArguments,
        group="diagnostics",
        handler="errors",
    ),
    read("file_metadata", "db/file", FileArguments, group="folder"),
    read("folder_browse", "db/browse", BrowseArguments, group="folder", handler="list"),
    read(
        "needed_files",
        "db/need",
        FolderPageArguments,
        group="folder",
        handler="upstream",
        core=True,
    ),
    read(
        "remote_needed_files",
        "db/remoteneed",
        RemotePageArguments,
        group="folder",
        handler="upstream",
    ),
    read(
        "local_changes", "db/localchanged", FolderPageArguments, group="folder", handler="upstream"
    ),
    read("ignores", "db/ignores", FolderArguments, group="folder", handler="ignores"),
    read("file_versions", "folder/versions", FolderPageArguments, group="folder", handler="map"),
    read("events", "events", EventArguments, group="events", handler="events", core=True),
    read("disk_events", "events/disk", EventArguments, group="events", handler="events"),
    read(
        "device_statistics", "stats/device", PageArguments, group="stats", handler="map", core=True
    ),
    read(
        "folder_statistics", "stats/folder", PageArguments, group="stats", handler="map", core=True
    ),
    read("validate_device_id", "svc/deviceid", DeviceArguments, group="utilities"),
    read("languages", "svc/lang", group="utilities"),
    read("random_string", "svc/random/string", RandomArguments, group="utilities"),
    read("usage_report", "svc/report", group="diagnostics"),
    read("debug_file", "debug/file", FileArguments, group="diagnostics"),
    write(
        "update_folder",
        "config/folders/{folder}",
        FolderPatchArguments,
        handler="update",
        core=True,
    ),
    write(
        "update_device",
        "config/devices/{device}",
        DevicePatchArguments,
        handler="update",
        core=True,
    ),
    write(
        "create_folder",
        "config/folders",
        CreateFolderArguments,
        handler="create_folder",
        admin=True,
    ),
    write(
        "create_device",
        "config/devices",
        CreateDeviceArguments,
        handler="create_device",
        admin=True,
    ),
    write(
        "accept_folder",
        "config/folders",
        AcceptFolderArguments,
        handler="accept_folder",
        admin=True,
    ),
    write(
        "accept_device",
        "config/devices",
        CreateDeviceArguments,
        handler="accept_device",
        admin=True,
    ),
    write(
        "delete_folder",
        "config/folders/{folder}",
        FolderConfirmArguments,
        handler="delete",
        destructive=True,
        admin=True,
        description="Remove folder configuration; leaves local data.",
    ),
    write(
        "delete_device",
        "config/devices/{device}",
        DeviceConfirmArguments,
        handler="delete",
        destructive=True,
        admin=True,
    ),
    write(
        "update_folder_defaults",
        "config/defaults/folder",
        PatchArguments,
        handler="update",
        admin=True,
    ),
    write(
        "update_device_defaults",
        "config/defaults/device",
        PatchArguments,
        handler="update",
        admin=True,
    ),
    write(
        "update_ignore_defaults",
        "config/defaults/ignores",
        DefaultIgnoreArguments,
        handler="default_ignores",
        destructive=True,
        admin=True,
    ),
    write("update_options", "config/options", PatchArguments, handler="update", admin=True),
    write(
        "update_gui",
        "config/gui",
        GuiPatchArguments,
        handler="update",
        admin=True,
        description="Update GUI; UNIX sockets require destructive authority and confirm=true.",
    ),
    write("update_ldap", "config/ldap", PatchArguments, handler="update", admin=True),
    write(
        "pause_folder",
        "config/folders/{folder}",
        FolderMutationArguments,
        handler="pause_folder",
        core=True,
    ),
    write(
        "resume_folder",
        "config/folders/{folder}",
        FolderMutationArguments,
        handler="pause_folder",
        core=True,
    ),
    write(
        "pause_device", "system/pause", DeviceMutationArguments, handler="pause_device", core=True
    ),
    write(
        "resume_device", "system/resume", DeviceMutationArguments, handler="pause_device", core=True
    ),
    write("scan_folder", "db/scan", ScanArguments, group="folder", handler="scan", core=True),
    write("prioritize_file", "db/prio", PriorityArguments, group="folder", handler="action"),
    write(
        "clear_errors",
        "system/error/clear",
        MutationArguments,
        group="system",
        handler="clear_errors",
    ),
    write(
        "report_error",
        "system/error",
        ReportErrorArguments,
        group="diagnostics",
        handler="report_error",
        admin=True,
    ),
    write(
        "update_log_levels",
        "system/loglevels",
        LogLevelArguments,
        group="diagnostics",
        handler="loglevels",
        admin=True,
    ),
    write(
        "dismiss_pending_device",
        "cluster/pending/devices",
        DeviceMutationArguments,
        group="cluster",
        handler="dismiss_device",
    ),
    write(
        "dismiss_pending_folder",
        "cluster/pending/folders",
        DismissFolderArguments,
        group="cluster",
        handler="dismiss_folder",
    ),
    write(
        "replace_ignores",
        "db/ignores",
        IgnoreArguments,
        group="folder",
        handler="ignores",
        destructive=True,
    ),
    write(
        "restore_versions",
        "folder/versions",
        RestoreArguments,
        group="folder",
        handler="restore",
        destructive=True,
    ),
    write(
        "override_folder",
        "db/override",
        FolderConfirmArguments,
        group="admin",
        handler="override",
        destructive=True,
        admin=True,
    ),
    write(
        "revert_folder",
        "db/revert",
        FolderConfirmArguments,
        group="admin",
        handler="revert",
        destructive=True,
        admin=True,
    ),
    write(
        "reset_database",
        "system/reset",
        ResetArguments,
        group="admin",
        handler="reset",
        destructive=True,
        admin=True,
    ),
    write(
        "restart",
        "system/restart",
        ConfirmArguments,
        group="admin",
        handler="admin_action",
        destructive=True,
        admin=True,
    ),
    write(
        "shutdown",
        "system/shutdown",
        ConfirmArguments,
        group="admin",
        handler="admin_action",
        destructive=True,
        admin=True,
    ),
    write(
        "upgrade",
        "system/upgrade",
        ConfirmArguments,
        group="admin",
        handler="admin_action",
        destructive=True,
        admin=True,
    ),
]
REGISTRY = {"syncthing_" + op.name: op for op in OPERATIONS}
GROUPS = frozenset(op.group for op in OPERATIONS)


def validate_filters(settings: Settings) -> None:
    for names in (settings.enabled_tools or (), settings.disabled_tools):
        if set(names) - REGISTRY.keys():
            raise PublicError("configuration", "Unknown tool name in startup filter.")
    if settings.groups is not None and set(settings.groups) - GROUPS:
        raise PublicError("configuration", "Unknown group name in startup filter.")


def permitted(op: Operation, settings: Settings) -> bool:
    name = "syncthing_" + op.name
    if (
        not op.read_only
        and not settings.allow_writes
        or op.destructive
        and not settings.allow_destructive
        or op.admin
        and not settings.allow_admin
        or name in settings.disabled_tools
    ):
        return False
    if settings.enabled_tools is not None:
        if name not in settings.enabled_tools:
            return False
    elif settings.profile == "core" and not op.core:
        return False
    if settings.groups is not None:
        return op.group in settings.groups
    return op.group != "diagnostics" or (
        settings.enabled_tools is not None and name in settings.enabled_tools
    )

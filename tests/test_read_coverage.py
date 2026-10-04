"""Protocol fixtures for every reviewed read operation, including opt-in diagnostics."""

import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError
from syncthing_mcp.reads import configuration_projection, event_projection

ENV = {
    "SYNCTHING_URL": "http://syncthing.test:8384",
    "SYNCTHING_API_KEY": "secret-key",
    "SYNCTHING_MCP_ALLOWED_PATHS": '["/data"]',
    "SYNCTHING_MCP_GROUPS": (
        '["system","config","folder","cluster","events","stats","utilities","diagnostics"]'
    ),
}
CASES = [
    ("system_status", "system/status", {}, {"myID": "local"}),
    ("system_version", "system/version", {}, {"version": "v2.1.5"}),
    ("system_ping", "system/ping", {}, {"ping": "pong"}),
    ("system_health", "noauth/health", {}, {"status": "OK"}),
    ("system_connections", "system/connections", {}, {"connections": {}}),
    ("system_errors", "system/error", {}, {"errors": None}),
    ("system_error_messages", "system/error", {}, {"errors": [{"message": "error"}]}),
    ("system_discovery", "system/discovery", {}, {"local": ["tcp://host:22000"]}),
    ("system_paths", "system/paths", {}, {"config": "/config"}),
    ("system_logs", "system/log", {"since": "2026-01-01T00:00:00Z"}, {"messages": []}),
    (
        "log_levels",
        "system/loglevels",
        {},
        {"packages": {"model": "Model"}, "levels": {"model": "INFO"}},
    ),
    ("host_browse", "system/browse", {"current": "/data"}, ["/data/one", "/outside"]),
    ("upgrade_available", "system/upgrade", {}, {"newer": False}),
    (
        "config",
        "config",
        {},
        {
            "version": 37,
            "folders": [{"id": "f"}],
            "devices": [{"deviceID": "d"}],
            "gui": {"enabled": True, "apiKey": "never-show"},
            "ldap": {"address": "ldap.test", "bindDN": "secret"},
            "options": {"maxSendKbps": 0},
            "defaults": {
                "folder": {"id": ""},
                "device": {"deviceID": ""},
                "ignores": {"lines": []},
            },
        },
    ),
    ("restart_required", "config/restart-required", {}, {"requiresRestart": False}),
    ("folders", "config/folders", {}, [{"id": "f", "label": "Folder"}]),
    ("devices", "config/devices", {}, [{"deviceID": "d", "name": "Device"}]),
    (
        "folder_config",
        "config/folders/folder%20name",
        {"folder": "folder name"},
        {"id": "folder name"},
    ),
    ("device_config", "config/devices/d", {"device": "d"}, {"deviceID": "d"}),
    (
        "folder_defaults",
        "config/defaults/folder",
        {},
        {
            "path": "",
            "devices": [],
            "minDiskFree": {"value": 1, "unit": "%", "futureSecret": "hide"},
            "xattrFilter": {
                "entries": [{"match": "*", "permit": True, "secret": "hide"}],
                "maxTotalSize": 10,
            },
            "versioning": {"type": "simple", "params": {"keep": "5", "futureCommand": "hide"}},
        },
    ),
    ("device_defaults", "config/defaults/device", {}, {"name": ""}),
    ("ignore_defaults", "config/defaults/ignores", {}, {"lines": []}),
    ("options", "config/options", {}, {"maxSendKbps": 0, "unknownSecret": "hide"}),
    ("gui_config", "config/gui", {}, {"enabled": True, "apiKey": "hide"}),
    ("ldap_config", "config/ldap", {}, {"transport": "tls", "unknownSecret": "hide"}),
    ("pending_devices", "cluster/pending/devices", {}, {"peer": {"name": "Peer"}}),
    (
        "pending_folders",
        "cluster/pending/folders",
        {},
        {"f": {"offeredBy": {"peer": {"label": "F"}}}},
    ),
    ("folder_status", "db/status", {"folder": "f"}, {"state": "idle"}),
    ("folder_completion", "db/completion", {"folder": "f", "device": "d"}, {"completion": 100}),
    ("folder_errors", "folder/errors", {"folder": "f"}, {"errors": None, "folder": "f"}),
    ("folder_error_messages", "folder/errors", {"folder": "f"}, {"errors": [], "folder": "f"}),
    (
        "file_metadata",
        "db/file",
        {"folder": "f", "file": "nested/a.txt"},
        {"global": {"name": "nested/a.txt"}},
    ),
    ("folder_browse", "db/browse", {"folder": "f", "prefix": "nested"}, [{"name": "nested/a.txt"}]),
    ("needed_files", "db/need", {"folder": "f"}, {"progress": [], "queued": [], "rest": []}),
    ("remote_needed_files", "db/remoteneed", {"folder": "f", "device": "d"}, {"files": []}),
    ("local_changes", "db/localchanged", {"folder": "f"}, {"files": []}),
    ("ignores", "db/ignores", {"folder": "f"}, {"ignore": [], "expanded": ["not raw"]}),
    ("file_versions", "folder/versions", {"folder": "f"}, {"a.txt": [{"versionTime": "now"}]}),
    (
        "events",
        "events",
        {"events": ["StateChanged"]},
        [
            {
                "id": 1,
                "type": "StateChanged",
                "data": {"folder": "f", "from": "idle", "to": "syncing", "unknown": "hide"},
            }
        ],
    ),
    ("disk_events", "events/disk", {}, [{"id": 1, "type": "LocalChangeDetected", "data": None}]),
    ("device_statistics", "stats/device", {}, {"peer": {"lastSeen": "now"}}),
    ("folder_statistics", "stats/folder", {}, {"f": {"lastScan": "now"}}),
    ("validate_device_id", "svc/deviceid", {"device": "peer"}, {"id": "peer"}),
    ("languages", "svc/lang", {}, ["en", "de"]),
    ("random_string", "svc/random/string", {"length": 16}, {"random": "abcdefghijklmnop"}),
    ("usage_report", "svc/report", {}, {"version": "v2.1.5"}),
    ("debug_file", "debug/file", {"folder": "f", "file": "a.txt"}, {"globalVersions": []}),
]


@pytest.mark.parametrize("name,route,args,body", CASES)
async def test_documented_read_routes(name, route, args, body):
    def handle(request):
        assert request.method == "GET"
        assert request.url.raw_path.split(b"?")[0] == ("/rest/" + route).encode()
        return httpx.Response(200, json=body)

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(handle))
    result = await engine.call("syncthing_" + name, args)
    assert result["instance"] == "default"
    assert "hide" not in str(result)
    assert "secret-key" not in str(result)
    if name == "host_browse":
        assert result["items"] == ["/data/one"]
    await engine.aclose()


@pytest.mark.parametrize(
    "name,args",
    [
        ("host_browse", {"current": "/data/*"}),
        ("host_browse", {"current": "/outside"}),
        ("events", {"events": ["X,Y"]}),
        ("disk_events", {"events": ["X"]}),
        ("file_metadata", {"folder": "f", "file": "../secret"}),
    ],
)
async def test_unsafe_reads_fail_before_http(name, args):
    def forbidden(request):
        pytest.fail("Unsafe arguments reached upstream")

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(forbidden))
    with pytest.raises(PublicError):
        await engine.call("syncthing_" + name, args)
    await engine.aclose()


@pytest.mark.parametrize(
    "name,args",
    [
        ("folder_config", {"folder": "f"}),
        ("folders", {}),
        ("pending_folders", {}),
        ("needed_files", {"folder": "f"}),
        ("folder_browse", {"folder": "f"}),
        ("events", {}),
        ("system_logs", {}),
        ("ignores", {"folder": "f"}),
        ("system_errors", {}),
    ],
)
async def test_malformed_upstream_shapes_return_public_errors(name, args):
    engine = Engine(
        Settings.from_env(ENV), httpx.MockTransport(lambda r: httpx.Response(200, json=3))
    )
    with pytest.raises(PublicError) as error:
        await engine.call("syncthing_" + name, args)
    assert error.value.code == "upstream_shape"
    await engine.aclose()


def test_unknown_event_payload_omitted_and_configuration_unknown_fields_dropped():
    assert event_projection({"id": 1, "type": "Future", "data": {"password": "hide"}})["data"] == {}
    assert configuration_projection({"something": "hide"}, "/rest/config/unknown") == {}

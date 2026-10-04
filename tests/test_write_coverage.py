"""Behavioral REST contract fixtures for remaining mutations and failed readbacks."""

import json

import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError

ENV = {
    "SYNCTHING_URL": "http://example.test",
    "SYNCTHING_API_KEY": "key",
    "SYNCTHING_MCP_ALLOW_WRITES": "true",
    "SYNCTHING_MCP_ALLOW_ADMIN": "true",
    "SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "true",
    "SYNCTHING_MCP_ALLOWED_PATHS": '["/data"]',
    "SYNCTHING_MCP_GROUPS": '["system","config","folder","cluster","admin","diagnostics"]',
}


class ContractBackend:
    def __init__(self):
        self.calls = []
        self.fail_readback = False
        self.write_seen = False
        self.state = {
            "/rest/config/folders/f": {
                "id": "f",
                "path": "/data/f",
                "paused": True,
                "type": "sendonly",
                "devices": [{"deviceID": "peer"}],
            },
            "/rest/config/devices/peer": {"deviceID": "peer", "name": "Peer", "paused": False},
            "/rest/config/defaults/folder": {
                "label": "",
                "path": "",
                "type": "sendreceive",
                "devices": [],
                "versioning": {"type": "", "params": {}},
            },
            "/rest/config/defaults/device": {
                "name": "",
                "addresses": ["dynamic"],
                "paused": True,
                "compression": "metadata",
                "ignoredFolders": [],
            },
            "/rest/config/defaults/ignores": {"lines": []},
            "/rest/config/options": {"maxSendKbps": 0, "unknownOld": "preserve"},
            "/rest/config/gui": {"theme": "default", "user": "user", "password": "hash"},
            "/rest/config/ldap": {"address": "", "transport": "tls"},
        }
        self.pending_devices = {"new-peer": {"name": "New"}}
        self.pending_folders = {"f": {"offeredBy": {"peer": {"label": "F"}}}}
        self.errors = [{"message": "error"}]

    def __call__(self, request):
        self.calls.append(request)
        route, method = request.url.path, request.method
        if method != "GET":
            self.write_seen = True
        if method == "GET" and self.fail_readback and self.write_seen:
            return httpx.Response(503)
        if route in self.state:
            if method == "GET":
                return httpx.Response(200, json=self.state[route])
            if method == "PUT":
                self.state[route] = json.loads(request.content)
                return httpx.Response(200)
            if method == "DELETE":
                del self.state[route]
                return httpx.Response(200)
        if route == "/rest/config/restart-required":
            return httpx.Response(200, json={"requiresRestart": False})
        if route == "/rest/svc/deviceid":
            return httpx.Response(200, json={"id": request.url.params["id"]})
        if route == "/rest/config/devices" and method == "POST":
            body = json.loads(request.content)
            self.state["/rest/config/devices/" + body["deviceID"]] = body
            return httpx.Response(200)
        if route.startswith("/rest/config/devices/") or route.startswith("/rest/config/folders/"):
            return httpx.Response(404)
        if route in ("/rest/system/pause", "/rest/system/resume"):
            self.state["/rest/config/devices/" + request.url.params["device"]]["paused"] = (
                route.endswith("pause")
            )
            return httpx.Response(200)
        if route == "/rest/system/status":
            return httpx.Response(200, json={"myID": "peer", "guiAddressOverridden": False})
        if route == "/rest/system/upgrade" and method == "GET":
            return httpx.Response(200, json={"newer": True, "latest": "v2.1.6"})
        if route.startswith("/rest/cluster/pending/"):
            pending = self.pending_devices if route.endswith("devices") else self.pending_folders
            if method == "DELETE":
                if route.endswith("devices"):
                    pending.pop(request.url.params["device"], None)
                else:
                    pending[request.url.params["folder"]]["offeredBy"].pop(
                        request.url.params["device"], None
                    )
                return httpx.Response(200)
            return httpx.Response(200, json=pending)
        if route == "/rest/system/error":
            return httpx.Response(200, json={"errors": self.errors})
        if route == "/rest/system/error/clear":
            self.errors = []
            return httpx.Response(200)
        if route == "/rest/db/status":
            return httpx.Response(200, json={"state": "idle"})
        if route == "/rest/folder/versions":
            if method == "GET":
                return httpx.Response(
                    200, json={"a.txt": [{"versionTime": "2026-01-01T00:00:00Z"}]}
                )
            return httpx.Response(200, json={})
        if route == "/rest/db/file":
            return httpx.Response(200, json={"local": {"name": "a.txt"}})
        return httpx.Response(200)


CASES = [
    ("update_device", {"device": "peer", "patch": {"name": "New"}}),
    ("create_device", {"device": "new-peer", "name": "New"}),
    ("accept_device", {"device": "new-peer", "name": "New"}),
    ("accept_folder", {"folder": "f", "device": "peer", "path": "/data/f"}),
    ("delete_device", {"device": "peer", "confirm": True}),
    ("update_folder_defaults", {"patch": {"label": "Default"}}),
    ("update_device_defaults", {"patch": {"compression": "never"}}),
    ("update_ignore_defaults", {"lines": ["*.tmp"], "confirm": True}),
    ("update_options", {"patch": {"maxSendKbps": 10}}),
    ("update_gui", {"patch": {"theme": "dark"}}),
    ("update_ldap", {"patch": {"address": "ldap.test:636"}}),
    ("pause_folder", {"folder": "f"}),
    ("resume_folder", {"folder": "f"}),
    ("pause_device", {"device": "peer"}),
    ("resume_device", {"device": "peer"}),
    ("scan_folder", {"folder": "f", "sub": "nested", "next": 30}),
    ("prioritize_file", {"folder": "f", "file": "nested/a.txt"}),
    ("clear_errors", {}),
    ("dismiss_pending_device", {"device": "new-peer"}),
    ("dismiss_pending_folder", {"folder": "f", "device": "peer"}),
    (
        "restore_versions",
        {"folder": "f", "confirm": True, "versions": {"a.txt": "2026-01-01T00:00:00Z"}},
    ),
    ("override_folder", {"folder": "f", "confirm": True}),
    ("revert_folder", {"folder": "f", "confirm": True}),
    ("reset_database", {"folders": ["f"], "confirm": True}),
    ("restart", {"confirm": True}),
    ("shutdown", {"confirm": True}),
    ("upgrade", {"confirm": True}),
]


@pytest.mark.parametrize("name,args", CASES)
async def test_supported_mutation_contract(name, args):
    backend = ContractBackend()
    if name == "revert_folder":
        backend.state["/rest/config/folders/f"]["type"] = "receiveonly"
    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(backend))
    result = await engine.call("syncthing_" + name, args)
    assert result["outcome"] in {"verified", "accepted"}, result
    assert result["request_outcome"] == "succeeded"
    assert result["persistence"] == "unknown"
    assert any(r.method != "GET" for r in backend.calls)
    assert backend.calls[-1].method == "GET"
    if name == "update_options":
        assert backend.state["/rest/config/options"]["unknownOld"] == "preserve"
    if name == "scan_folder":
        scan = next(r for r in backend.calls if r.url.path == "/rest/db/scan")
        assert scan.url.params["sub"] == "nested" and scan.url.params["next"] == "30"
    await engine.aclose()


@pytest.mark.parametrize("name,args", CASES)
async def test_mutations_handle_failed_independent_readback(name, args):
    backend = ContractBackend()
    backend.fail_readback = True
    if name == "revert_folder":
        backend.state["/rest/config/folders/f"]["type"] = "receiveonly"
    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(backend))
    result = await engine.call("syncthing_" + name, args)
    assert result["outcome"] in {"accepted", "outcome_unknown"}
    assert result["readback_verified"] is None
    assert result["persistence"] == "unknown"
    await engine.aclose()


@pytest.mark.parametrize(
    "name,args",
    [
        ("accept_device", {"device": "missing"}),
        ("accept_folder", {"folder": "f", "device": "missing", "path": "/data/f"}),
        ("dismiss_pending_device", {"device": "missing"}),
        ("dismiss_pending_folder", {"folder": "missing", "device": "peer"}),
        ("dismiss_pending_folder", {"folder": "f", "device": "missing"}),
        ("override_folder", {"folder": "f", "confirm": True}),
    ],
)
async def test_missing_offers_or_invalid_types_do_not_mutate(name, args):
    backend = ContractBackend()
    backend.state["/rest/config/folders/f"]["type"] = "sendreceive"
    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(backend))
    with pytest.raises(PublicError):
        await engine.call("syncthing_" + name, args)
    assert all(r.method == "GET" for r in backend.calls)
    await engine.aclose()

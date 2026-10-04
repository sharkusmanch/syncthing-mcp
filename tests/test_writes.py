import asyncio
import json

import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError
from syncthing_mcp.safety import revision

ENV = {
    "SYNCTHING_URL": "http://syncthing.test:8384",
    "SYNCTHING_API_KEY": "secret-key",
    "SYNCTHING_MCP_ALLOW_WRITES": "true",
    "SYNCTHING_MCP_ALLOWED_PATHS": '["/data"]',
}
ADMIN = ENV | {"SYNCTHING_MCP_ALLOW_ADMIN": "true", "SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "true"}


class Backend:
    def __init__(self):
        self.folder = {
            "id": "x",
            "label": "Old",
            "path": "/data/x",
            "type": "sendreceive",
            "paused": True,
            "versioning": {"type": "", "params": {}},
            "devices": [],
            "unknownExisting": {"preserve": True},
        }
        self.calls = []
        self.apply = True
        self.timeout = False
        self.restart_fails = False
        self.deleted = False
        self.defaults = {
            "path": "/data/default",
            "devices": [],
            "type": "sendreceive",
            "versioning": {"type": "", "params": {}},
            "paused": False,
        }
        self.pending = {"new": {"offeredBy": {"peer": {"label": "Share"}}}}
        self.ignores = ["*.tmp", "!important.tmp"]

    def __call__(self, request):
        self.calls.append(request)
        path = request.url.path
        if path == "/rest/config/restart-required":
            return httpx.Response(
                500 if self.restart_fails else 200, json={"requiresRestart": False}
            )
        if path == "/rest/config/defaults/folder":
            return httpx.Response(200, json=self.defaults)
        if path == "/rest/config/defaults/ignores":
            return httpx.Response(200, json={"lines": []})
        if path == "/rest/system/status":
            return httpx.Response(200, json={"myID": "local"})
        if path in ("/rest/config/devices/peer", "/rest/config/devices/local"):
            return httpx.Response(200, json={"deviceID": path.rsplit("/", 1)[-1]})
        if path == "/rest/cluster/pending/folders":
            return httpx.Response(200, json=self.pending)
        if path == "/rest/db/ignores":
            if request.method == "POST" and self.apply:
                self.ignores = json.loads(request.content)["ignore"]
            return httpx.Response(200, json={"ignore": self.ignores, "expanded": ["wrong"]})
        if path == "/rest/folder/versions":
            if request.method == "GET":
                return httpx.Response(
                    200, json={"a.txt": [{"versionTime": "2026-01-01T00:00:00Z"}]}
                )
            return httpx.Response(200, json={"a.txt": "could not restore"})
        if path.startswith("/rest/config/folders/"):
            resource = path.rsplit("/", 1)[-1]
            if request.method == "GET":
                if self.deleted or self.folder["id"] != resource:
                    return httpx.Response(404)
                return httpx.Response(200, json=self.folder)
            if request.method in ("PATCH", "PUT") and self.apply:
                self.folder = json.loads(request.content)
            if request.method == "DELETE" and self.apply:
                self.deleted = True
            if self.timeout:
                raise httpx.ReadTimeout("secret-key", request=request)
            return httpx.Response(200)
        if path == "/rest/config/folders" and request.method == "POST":
            if self.apply:
                self.folder = json.loads(request.content)
                self.deleted = False
            return httpx.Response(200)
        if path in ("/rest/db/status", "/rest/db/file"):
            return httpx.Response(200, json={"state": "idle"})
        if path in ("/rest/system/reset", "/rest/db/scan", "/rest/db/override", "/rest/db/revert"):
            if self.timeout:
                raise httpx.ReadTimeout("secret-key", request=request)
            return httpx.Response(200)
        return httpx.Response(200, json={})


def engine(backend, env=ADMIN):
    return Engine(Settings.from_env(env), httpx.MockTransport(backend))


async def test_update_preserves_unrelated_nested_fields_and_reads_back():
    backend = Backend()
    client = engine(backend)
    result = await client.call(
        "syncthing_update_folder", {"folder": "x", "patch": {"label": "New"}}
    )
    assert backend.folder["unknownExisting"] == {"preserve": True}
    assert backend.folder["versioning"] == {"type": "", "params": {}}
    assert result["outcome"] == "verified" and result["readback_verified"] is True
    assert result["persistence"] == "unknown"
    assert result["restart_required"] is False
    methods = [r.method for r in backend.calls if r.url.path.endswith("/folders/x")]
    assert methods == ["GET", "PUT", "GET"]
    await client.aclose()


async def test_false_success_is_not_reported_verified():
    backend = Backend()
    backend.apply = False
    client = engine(backend)
    result = await client.call(
        "syncthing_update_folder", {"folder": "x", "patch": {"label": "New"}}
    )
    assert result["outcome"] == "outcome_unknown"
    assert result["readback_verified"] is False
    await client.aclose()


async def test_ambiguous_matching_readback_does_not_claim_persistence():
    backend = Backend()
    backend.timeout = True
    client = engine(backend)
    result = await client.call(
        "syncthing_update_folder", {"folder": "x", "patch": {"label": "New"}}
    )
    assert result["outcome"] == "outcome_unknown"
    assert result["readback_verified"] is True
    assert result["request_outcome"] == "unknown"
    assert result["persistence"] == "unknown"
    assert sum(r.method == "PUT" for r in backend.calls) == 1
    await client.aclose()


async def test_restart_lookup_failure_is_unknown():
    backend = Backend()
    backend.restart_fails = True
    client = engine(backend)
    result = await client.call(
        "syncthing_update_folder", {"folder": "x", "patch": {"label": "New"}}
    )
    assert result["restart_required"] is None
    await client.aclose()


async def test_expected_revision_stale_fails_before_write():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError) as error:
        await client.call(
            "syncthing_update_folder",
            {
                "folder": "x",
                "patch": {"label": "New"},
                "expected_revision": revision({"wrong": True}),
            },
        )
    assert error.value.code == "revision_conflict"
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


@pytest.mark.parametrize(
    "patch",
    [
        {"id": "replacement"},
        {"unknown": True},
        {"path": "/data/new"},
        {"versioning": {"type": "external"}},
        {"paused": "false"},
    ],
)
async def test_runtime_patch_cannot_bypass_authority(patch):
    backend = Backend()
    client = engine(backend, ENV)
    with pytest.raises(PublicError):
        await client.call("syncthing_update_folder", {"folder": "x", "patch": patch})
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


async def test_admin_path_containment_and_external_versioner_rejected():
    backend = Backend()
    client = engine(backend)
    for patch in [
        {"path": "/data/../escape"},
        {"versioning": {"type": "external", "params": {"command": "evil"}}},
        {"type": "receiveencrypted"},
    ]:
        with pytest.raises(PublicError):
            await client.call("syncthing_update_folder", {"folder": "x", "patch": patch})
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


async def test_duplicate_create_never_posts():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_create_folder", {"folder": "x", "path": "/data/x"})
    assert error.value.code == "already_exists"
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


async def test_create_selects_peers_ignores_and_unpause_after_verification():
    backend = Backend()
    backend.defaults["devices"] = [{"deviceID": "inherited-wrong-peer"}]
    client = engine(backend)
    result = await client.call(
        "syncthing_create_folder",
        {
            "folder": "new",
            "path": "/data/new",
            "devices": ["peer"],
            "ignores": ["*.tmp"],
            "paused": False,
        },
    )
    assert result["outcome"] == "verified"
    created = next(
        r for r in backend.calls if r.method == "POST" and r.url.path == "/rest/config/folders"
    )
    body = json.loads(created.content)
    assert body["paused"] is True
    assert {x["deviceID"] for x in body["devices"]} == {"peer", "local"}
    assert backend.folder["paused"] is False
    assert backend.ignores == ["*.tmp"]
    await client.aclose()


async def test_unsafe_inherited_defaults_deny_creation():
    backend = Backend()
    backend.defaults["versioning"] = {"type": "external", "params": {"command": "evil"}}
    client = engine(backend)
    with pytest.raises(PublicError):
        await client.call("syncthing_create_folder", {"folder": "new", "path": "/data/new"})
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


async def test_accept_requires_real_matching_offer():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError) as error:
        await client.call(
            "syncthing_accept_folder", {"folder": "bogus", "device": "peer", "path": "/data/new"}
        )
    assert error.value.code == "pending_offer_missing"
    assert all(r.method == "GET" for r in backend.calls)
    await client.aclose()


async def test_delete_fetches_and_independently_checks_absence():
    backend = Backend()
    client = engine(backend)
    result = await client.call("syncthing_delete_folder", {"folder": "x", "confirm": True})
    assert result["outcome"] == "verified"
    assert [r.method for r in backend.calls if r.url.path.endswith("/folders/x")] == [
        "GET",
        "DELETE",
        "GET",
    ]
    await client.aclose()


async def test_destructive_requires_confirm_and_permission():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError):
        await client.call("syncthing_delete_folder", {"folder": "x", "confirm": False})
    assert backend.calls == []
    await client.aclose()
    limited = engine(backend, ENV)
    with pytest.raises(PublicError) as error:
        await limited.call(
            "syncthing_replace_ignores", {"folder": "x", "confirm": True, "lines": []}
        )
    assert error.value.code == "permission_denied"
    await limited.aclose()


async def test_ignore_raw_order_preserved_include_rejected():
    backend = Backend()
    client = engine(backend)
    for lines in [["#include unsafe"], ["#include\tunsafe"], ["line\nother"]]:
        with pytest.raises(PublicError):
            await client.call(
                "syncthing_replace_ignores", {"folder": "x", "confirm": True, "lines": lines}
            )
    result = await client.call(
        "syncthing_replace_ignores",
        {"folder": "x", "confirm": True, "lines": ["!important.tmp", "*.tmp"]},
    )
    assert result["outcome"] == "verified"
    assert backend.ignores == ["!important.tmp", "*.tmp"]
    await client.aclose()


async def test_restore_checks_versions_and_http200_per_file_errors():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError):
        await client.call(
            "syncthing_restore_versions",
            {"folder": "x", "confirm": True, "versions": {"a.txt": "bogus"}},
        )
    result = await client.call(
        "syncthing_restore_versions",
        {"folder": "x", "confirm": True, "versions": {"a.txt": "2026-01-01T00:00:00Z"}},
    )
    assert result["restored"] == [] and result["failed"] == ["a.txt"]
    assert result["outcome"] != "verified"
    await client.aclose()


async def test_bulk_reset_preflights_all_targets_and_requires_paused():
    backend = Backend()
    backend.folder["paused"] = False
    client = engine(backend)
    with pytest.raises(PublicError):
        await client.call("syncthing_reset_database", {"folders": ["x"], "confirm": True})
    assert not any(r.url.path == "/rest/system/reset" for r in backend.calls)
    await client.aclose()


async def test_scan_finite_timeout_and_unknown_outcome():
    backend = Backend()
    backend.timeout = True
    client = engine(backend)
    result = await client.call("syncthing_scan_folder", {"folder": "x"})
    scan = next(r for r in backend.calls if r.url.path == "/rest/db/scan")
    assert scan.extensions["timeout"]["read"] == 300.0
    assert result["outcome"] == "outcome_unknown"
    assert sum(r.url.path == "/rest/db/scan" for r in backend.calls) == 1
    await client.aclose()


async def test_write_serialization_preserves_concurrent_edits():
    backend = Backend()
    client = engine(backend)
    await asyncio.gather(
        client.call("syncthing_update_folder", {"folder": "x", "patch": {"label": "New"}}),
        client.call("syncthing_update_folder", {"folder": "x", "patch": {"rescanIntervalS": 120}}),
    )
    assert backend.folder["label"] == "New" and backend.folder["rescanIntervalS"] == 120
    await client.aclose()


async def test_default_ignores_applied_and_verified_before_unpause():
    backend = Backend()
    backend.ignores = []

    def handle(request):
        if request.url.path == "/rest/config/defaults/ignores":
            return httpx.Response(200, json={"lines": ["default-ignore"]})
        return backend(request)

    client = engine(handle)
    result = await client.call(
        "syncthing_create_folder", {"folder": "new", "path": "/data/new", "paused": False}
    )
    assert result["outcome"] == "verified"
    assert backend.ignores == ["default-ignore"]
    writes = [r for r in backend.calls if r.method != "GET"]
    assert writes[-1].url.path == "/rest/config/folders/new"
    await client.aclose()


async def test_existing_physical_ignore_file_conflict_keeps_created_folder_paused():
    backend = Backend()

    def handle(request):
        if request.url.path == "/rest/config/defaults/ignores":
            return httpx.Response(200, json={"lines": ["default-ignore"]})
        return backend(request)

    client = engine(handle)
    result = await client.call(
        "syncthing_create_folder", {"folder": "new", "path": "/data/new", "paused": False}
    )
    assert result["outcome"] == "outcome_unknown"
    assert result["kept_paused"] is True
    assert backend.folder["paused"] is True
    assert backend.ignores == ["*.tmp", "!important.tmp"]
    await client.aclose()


async def test_multiple_reset_targets_refused_before_any_restart():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError):
        await client.call("syncthing_reset_database", {"folders": ["x", "y"], "confirm": True})
    assert not any(r.method == "POST" for r in backend.calls)
    await client.aclose()


@pytest.mark.parametrize(
    "patch",
    [{"user": ""}, {"password": ""}, {"metricsWithoutAuth": True}, {"insecureAdminAccess": True}],
)
async def test_gui_auth_removing_changes_denied(patch):
    backend = Backend()

    def handle(request):
        if request.url.path == "/rest/config/gui":
            return httpx.Response(
                200,
                json={
                    "user": "existing",
                    "password": "hash",
                    "enabled": True,
                    "metricsWithoutAuth": False,
                },
            )
        return backend(request)

    client = engine(handle)
    with pytest.raises(PublicError):
        await client.call("syncthing_update_gui", {"patch": patch})
    assert not any(r.method == "PUT" for r in backend.calls)
    await client.aclose()


async def test_new_folder_without_ignore_file_can_apply_initial_ignores():
    backend = Backend()
    backend.ignores = None
    client = engine(backend)
    result = await client.call(
        "syncthing_create_folder", {"folder": "new", "path": "/data/new", "ignores": ["*.tmp"]}
    )
    assert result["outcome"] == "verified"
    await client.aclose()


async def test_gui_password_bcrypt_readback_verification():
    import bcrypt

    state = {
        "user": "existing",
        "password": bcrypt.hashpw(b"old", bcrypt.gensalt()).decode(),
        "enabled": True,
    }

    def handle(request):
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={"guiAddressOverridden": False})
        if request.url.path == "/rest/config/gui":
            if request.method == "PUT":
                state.update(json.loads(request.content))
                state["password"] = bcrypt.hashpw(
                    state["password"].encode(), bcrypt.gensalt()
                ).decode()
            return httpx.Response(200, json=state)
        return httpx.Response(200, json={"requiresRestart": False})

    client = engine(handle)
    result = await client.call("syncthing_update_gui", {"patch": {"password": "new-test-password"}})
    assert result["outcome"] == "verified"
    assert "new-test-password" not in str(result) and "$2b$" not in str(result)
    await client.aclose()


async def test_unknown_peers_rejected_before_folder_creation():
    backend = Backend()

    def handle(request):
        if request.url.path == "/rest/config/devices/unknown-peer":
            return httpx.Response(404)
        return backend(request)

    client = engine(handle)
    with pytest.raises(PublicError):
        await client.call(
            "syncthing_create_folder",
            {"folder": "new", "path": "/data/new", "devices": ["unknown-peer"]},
        )
    assert not any(r.method == "POST" for r in backend.calls)
    await client.aclose()


async def test_report_error_uses_plain_body_and_wrapper_readback():
    message = "test-error"
    called = []

    def handle(request):
        called.append(request)
        if request.method == "POST":
            assert request.content == message.encode()
            return httpx.Response(200)
        errors = (
            [] if len(called) == 1 else [{"message": 'External error report (error="test-error")'}]
        )
        return httpx.Response(200, json={"errors": errors})

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_GROUPS": '["diagnostics"]'})
    result = await client.call("syncthing_report_error", {"message": message})
    assert result["outcome"] == "accepted"
    assert result["readback_observed"] is True
    await client.aclose()


async def test_log_level_readback_normalizes_upstream_uppercase():
    def handle(request):
        if request.method == "POST":
            assert json.loads(request.content) == {"model": "DEBUG"}
            return httpx.Response(200)
        return httpx.Response(200, json={"levels": {"model": "DEBUG"}})

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_GROUPS": '["diagnostics"]'})
    result = await client.call("syncthing_update_log_levels", {"levels": {"model": "debug"}})
    assert result["outcome"] == "verified"
    await client.aclose()


async def test_ldap_to_static_requires_effective_static_credentials():
    def handle(request):
        return httpx.Response(200, json={"authMode": "ldap", "user": "", "password": ""})

    client = engine(handle)
    with pytest.raises(PublicError):
        await client.call("syncthing_update_gui", {"patch": {"authMode": "static"}})
    await client.aclose()


async def test_report_error_failed_readback_keeps_honest_accepted_outcome():
    write_seen = False

    def handle(request):
        nonlocal write_seen
        if request.method == "POST":
            write_seen = True
            return httpx.Response(200)
        return httpx.Response(503 if write_seen else 200, json={"errors": []})

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_GROUPS": '["diagnostics"]'})
    result = await client.call("syncthing_report_error", {"message": "test-error"})
    assert result["outcome"] == "accepted"
    assert result["readback_observed"] is None
    await client.aclose()


async def test_restore_rejects_stale_folder_revision_before_version_requests_or_mutation():
    backend = Backend()
    client = engine(backend)
    with pytest.raises(PublicError) as error:
        await client.call(
            "syncthing_restore_versions",
            {
                "folder": "x",
                "confirm": True,
                "expected_revision": revision({"stale": True}),
                "versions": {"a.txt": "2026-01-01T00:00:00Z"},
            },
        )
    assert error.value.code == "revision_conflict"
    assert [(r.method, r.url.path) for r in backend.calls] == [("GET", "/rest/config/folders/x")]
    await client.aclose()


async def test_restore_accepts_current_raw_folder_revision_before_version_side_effects():
    backend = Backend()
    client = engine(backend)
    await client.call(
        "syncthing_restore_versions",
        {
            "folder": "x",
            "confirm": True,
            "expected_revision": revision(backend.folder),
            "versions": {"a.txt": "2026-01-01T00:00:00Z"},
        },
    )
    assert [(r.method, r.url.path) for r in backend.calls[:3]] == [
        ("GET", "/rest/config/folders/x"),
        ("GET", "/rest/folder/versions"),
        ("POST", "/rest/folder/versions"),
    ]
    await client.aclose()


@pytest.mark.parametrize("path", ["/outside/gui.sock", "/data/../outside/gui.sock"])
async def test_gui_unix_socket_address_cannot_bypass_destination_roots(path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"address": "127.0.0.1:8384", "theme": "default"})

    client = engine(handle)
    with pytest.raises(PublicError):
        await client.call("syncthing_update_gui", {"patch": {"address": path}})
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


@pytest.mark.parametrize("patch", [{"theme": "dark"}, {"unixSocketPermissions": "0600"}])
async def test_gui_rebind_checks_existing_unix_socket_destination(patch):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"address": "/outside/gui.sock", "theme": "default"})

    client = engine(handle)
    with pytest.raises(PublicError):
        await client.call("syncthing_update_gui", {"patch": patch})
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


async def test_gui_unix_socket_destination_requires_configured_roots():
    def handle(request):
        return httpx.Response(200, json={"address": "127.0.0.1:8384"})

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_ALLOWED_PATHS": "[]"})
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", {"patch": {"address": "/data/gui.sock"}})
    assert error.value.code == "path_denied"
    await client.aclose()


@pytest.mark.parametrize("address", ["/data/gui.sock", "127.0.0.1:8385", "[::1]:8385"])
async def test_gui_addresses_with_safe_socket_or_tcp_destination_remain_supported(address):
    state = {"address": "127.0.0.1:8384", "theme": "default"}

    def handle(request):
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={"guiAddressOverridden": False})
        if request.url.path == "/rest/config/restart-required":
            return httpx.Response(200, json={"requiresRestart": True})
        if request.method == "PUT":
            state.update(json.loads(request.content))
            return httpx.Response(200)
        return httpx.Response(200, json=state)

    client = engine(handle)
    result = await client.call(
        "syncthing_update_gui", {"patch": {"address": address}, "confirm": True}
    )
    assert result["outcome"] == "verified"
    assert state["address"] == address
    await client.aclose()


async def test_gui_socket_rebind_requires_destructive_authority_even_for_theme_change():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={"guiAddressOverridden": False})
        return httpx.Response(200, json={"address": "/data/gui.sock", "theme": "default"})

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "false"})
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", {"patch": {"theme": "dark"}, "confirm": True})
    assert error.value.code == "permission_denied"
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


@pytest.mark.parametrize("confirm", [None, False])
async def test_gui_socket_rebind_requires_explicit_confirmation(confirm):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={"guiAddressOverridden": False})
        return httpx.Response(200, json={"address": "/data/gui.sock", "theme": "default"})

    client = engine(handle)
    arguments = {"patch": {"theme": "dark"}}
    if confirm is not None:
        arguments["confirm"] = confirm
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", arguments)
    assert error.value.code == "confirmation_required"
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


async def test_gui_runtime_override_cannot_hide_unix_socket_behind_raw_tcp_address():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            return httpx.Response(
                200, json={"guiAddressOverridden": True, "guiAddressUsed": "/outside/runtime.sock"}
            )
        return httpx.Response(200, json={"address": "127.0.0.1:8384", "theme": "default"})

    client = engine(handle)
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", {"patch": {"theme": "dark"}})
    assert error.value.code == "unsupported_override"
    assert all(request.method == "GET" for request in calls)
    assert "/outside/runtime.sock" not in str(error.value)
    await client.aclose()


@pytest.mark.parametrize(
    "status", [None, [], {}, {"guiAddressOverridden": "false"}, {"guiAddressOverridden": 0}]
)
async def test_gui_runtime_override_preflight_requires_typed_status_flag(status):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json=status)
        return httpx.Response(200, json={"address": "127.0.0.1:8384", "theme": "default"})

    client = engine(handle)
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", {"patch": {"theme": "dark"}})
    assert error.value.code == "upstream_shape"
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


@pytest.mark.parametrize("failure", ["http", "timeout"])
async def test_gui_runtime_override_preflight_failure_denies_mutation(failure):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            if failure == "timeout":
                raise httpx.ReadTimeout("fixture", request=request)
            return httpx.Response(503)
        return httpx.Response(200, json={"address": "127.0.0.1:8384", "theme": "default"})

    client = engine(handle)
    with pytest.raises(PublicError) as error:
        await client.call("syncthing_update_gui", {"patch": {"theme": "dark"}})
    assert error.value.code == ("upstream_timeout" if failure == "timeout" else "upstream_error")
    assert all(request.method == "GET" for request in calls)
    await client.aclose()


async def test_gui_without_runtime_override_can_update_tcp_theme():
    calls = []
    state = {"address": "127.0.0.1:8384", "theme": "default"}

    def handle(request):
        calls.append(request)
        if request.url.path == "/rest/system/status":
            return httpx.Response(
                200, json={"guiAddressOverridden": False, "guiAddressUsed": "127.0.0.1:8384"}
            )
        if request.url.path == "/rest/config/restart-required":
            return httpx.Response(200, json={"requiresRestart": False})
        if request.method == "PUT":
            state.update(json.loads(request.content))
            return httpx.Response(200)
        return httpx.Response(200, json=state)

    client = engine(handle, ADMIN | {"SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "false"})
    result = await client.call("syncthing_update_gui", {"patch": {"theme": "dark"}})
    assert result["outcome"] == "verified"
    assert state["theme"] == "dark"
    assert [(request.method, request.url.path) for request in calls[:3]] == [
        ("GET", "/rest/config/gui"),
        ("GET", "/rest/system/status"),
        ("PUT", "/rest/config/gui"),
    ]
    await client.aclose()

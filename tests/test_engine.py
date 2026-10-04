import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError

ENV = {"SYNCTHING_URL": "http://syncthing.test:8384", "SYNCTHING_API_KEY": "secret-key"}


def test_catalog_profiles_permissions_and_diagnostics():
    full = Engine(Settings.from_env(ENV))
    core = Engine(Settings.from_env(ENV | {"SYNCTHING_MCP_PROFILE": "core"}))
    assert len(full.tools()) > len(core.tools()) >= 8
    assert all(tool.read_only and tool.group != "diagnostics" for tool in full.tools())
    assert len({tool.name for tool in full.tools()}) == len(full.tools())
    assert all(tool.input_schema["additionalProperties"] is False for tool in full.tools())


async def test_hidden_tools_cannot_be_called_directly():
    engine = Engine(Settings.from_env(ENV))
    for name in ["syncthing_restart", "syncthing_update_folder", "syncthing_system_logs"]:
        with pytest.raises(PublicError) as error:
            await engine.call(name, {"folder": "x", "patch": {"paused": True}, "confirm": True})
        assert error.value.code == "permission_denied"
    await engine.aclose()


async def test_rejects_unknown_args_no_proxy_escape():
    engine = Engine(Settings.from_env(ENV))
    with pytest.raises(PublicError):
        await engine.call("syncthing_system_status", {"url": "http://attacker.test"})
    await engine.aclose()


async def test_output_redaction_and_bounded_single_object():
    engine = Engine(
        Settings.from_env(ENV | {"SYNCTHING_MCP_MAX_OUTPUT_BYTES": "1024"}),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"text": "x" * 1025})),
    )
    with pytest.raises(PublicError) as error:
        await engine.call("syncthing_system_status", {})
    assert error.value.code == "output_too_large"
    await engine.aclose()


async def test_instances_alias_discovery_never_reveals_addresses_or_keys():
    engine = Engine(Settings.from_env(ENV))
    result = await engine.call("syncthing_instances", {})
    assert result["items"][0]["name"] == "default"
    assert "syncthing.test" not in str(result) and "secret-key" not in str(result)
    assert result["permissions"]["writes"] is False
    await engine.aclose()


async def test_overview_composes_safe_bounded_status_and_folders():
    def handle(request):
        data = {"myID": "local"}
        if request.url.path == "/rest/config/folders":
            data = [{"id": "one", "label": "One", "unknown": "secret"}]
        if request.url.path == "/rest/db/status":
            data = {"state": "idle", "needBytes": 0}
        return httpx.Response(200, json=data)

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(handle))
    result = await engine.call("syncthing_overview", {})
    assert result["items"][0]["id"] == "one"
    assert result["items"][0]["status"]["state"] == "idle"
    assert "secret" not in str(result)
    await engine.aclose()

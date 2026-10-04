import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError

ENV = {"SYNCTHING_URL": "http://syncthing.test:8384", "SYNCTHING_API_KEY": "secret-key"}


async def test_safe_configuration_projection_precedes_field_selection():
    engine = Engine(
        Settings.from_env(ENV),
        httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "enabled": True,
                    "apiKey": "secret-key",
                    "password": "arbitrary",
                    "newSensitiveField": "unknown-secret",
                    "address": "127.0.0.1:8384",
                },
            )
        ),
    )
    result = await engine.call("syncthing_gui_config", {})
    assert "secret" not in str(result)
    assert result["data"] == {"enabled": True, "address": "127.0.0.1:8384"}
    with pytest.raises(PublicError):
        await engine.call("syncthing_gui_config", {"fields": ["apiKey"]})
    await engine.aclose()


async def test_local_pagination_continuation():
    engine = Engine(
        Settings.from_env(ENV),
        httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=[{"id": str(i), "label": "Folder " + str(i)} for i in range(5)]
            )
        ),
    )
    first = await engine.call("syncthing_folders", {"limit": 2})
    assert first["returned"] == 2
    assert first["next_cursor"] == "2"
    assert first["truncated"] is True
    second = await engine.call("syncthing_folders", {"limit": 2, "cursor": first["next_cursor"]})
    assert [x["id"] for x in second["items"]] == ["2", "3"]
    await engine.aclose()


async def test_need_upstream_pagination_across_all_sections():
    def handle(request):
        assert request.url.params["page"] == "2"
        assert request.url.params["perpage"] == "2"
        return httpx.Response(
            200,
            json={
                "progress": [],
                "queued": [{"name": "a"}],
                "rest": [{"name": "b"}],
                "page": 2,
                "perpage": 2,
            },
        )

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(handle))
    result = await engine.call("syncthing_needed_files", {"folder": "x", "limit": 2, "cursor": "2"})
    assert result["returned"] == 2 and result["next_cursor"] == "3"
    assert result["pagination"] == "upstream_pages"
    await engine.aclose()


async def test_events_advances_processed_boundary_and_reports_gaps():
    def handle(request):
        assert request.url.params["timeout"] == "0"
        return httpx.Response(
            200, json=[{"id": 10, "type": "X"}, {"id": 11, "type": "Y"}, {"id": 12, "type": "Z"}]
        )

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(handle))
    result = await engine.call("syncthing_events", {"since": 1, "limit": 2, "timeout": 0})
    assert result["next_cursor"] == 11
    assert result["upstream_gap"] is True
    assert result["local_truncated"] is True
    await engine.aclose()


async def test_config_object_revision_not_secret_projection_revision():
    raw = {"id": "x", "path": "/data/x", "label": "X", "newUnknown": 1}
    engine = Engine(
        Settings.from_env(ENV), httpx.MockTransport(lambda r: httpx.Response(200, json=raw))
    )
    result = await engine.call("syncthing_folder_config", {"folder": "x"})
    assert len(result["revision"]) == 64
    assert "newUnknown" not in result["data"]
    await engine.aclose()


async def test_default_errors_expose_counts_not_arbitrary_operational_text():
    engine = Engine(
        Settings.from_env(ENV),
        httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"errors": [{"message": "unknown secret from raw log"}]}
            )
        ),
    )
    result = await engine.call("syncthing_system_errors", {})
    assert result["data"]["count"] == 1
    assert "unknown secret" not in str(result)
    await engine.aclose()


async def test_config_saved_events_cannot_bypass_safe_projection():
    event = {
        "id": 1,
        "type": "ConfigSaved",
        "time": "now",
        "data": {
            "gui": {"password": "unknown-password", "apiKey": "unknown-key"},
            "options": {"releasesURL": "https://user:credential@example.test"},
            "unknownFutureSecret": "private",
        },
    }
    engine = Engine(
        Settings.from_env(ENV), httpx.MockTransport(lambda r: httpx.Response(200, json=[event]))
    )
    result = await engine.call("syncthing_events", {})
    assert result["items"][0]["data"]["configuration_changed"] is True
    assert all(
        value not in str(result)
        for value in ["unknown-password", "unknown-key", "credential", "private"]
    )
    await engine.aclose()


async def test_no_ignore_file_null_is_empty_raw_lines():
    engine = Engine(
        Settings.from_env(ENV),
        httpx.MockTransport(lambda r: httpx.Response(200, json={"ignore": None, "expanded": None})),
    )
    result = await engine.call("syncthing_ignores", {"folder": "x"})
    assert result["data"]["ignore"] == []
    await engine.aclose()

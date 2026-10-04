import httpx
import pytest

from syncthing_mcp.client import SyncthingClient
from syncthing_mcp.config import Settings
from syncthing_mcp.errors import PublicError

ENV = {"SYNCTHING_URL": "http://syncthing.test:8384", "SYNCTHING_API_KEY": "secret-key"}


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_all_methods_are_finite_authenticated_and_no_redirects(method):
    def handle(request):
        assert request.headers["X-API-Key"] == "secret-key"
        assert all(x is not None for x in request.extensions["timeout"].values())
        return httpx.Response(302, headers={"Location": "http://attacker.test"})

    settings = Settings.from_env(ENV)
    client = SyncthingClient(settings.instances[0], settings, httpx.MockTransport(handle))
    with pytest.raises(PublicError) as error:
        await client.request(method, "/rest/system/ping")
    assert error.value.code == "upstream_redirect"
    await client.aclose()


async def test_caps_streamed_bytes():
    settings = Settings.from_env(ENV | {"SYNCTHING_MCP_MAX_UPSTREAM_BYTES": "1024"})
    client = SyncthingClient(
        settings.instances[0],
        settings,
        httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 1025)),
    )
    with pytest.raises(PublicError) as error:
        await client.request("GET", "/rest/system/status")
    assert error.value.code == "upstream_too_large"
    await client.aclose()


async def test_write_timeout_has_unknown_outcome_no_retry():
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("private secret content", request=request)

    settings = Settings.from_env(ENV)
    client = SyncthingClient(settings.instances[0], settings, httpx.MockTransport(handle))
    with pytest.raises(PublicError) as error:
        await client.request("POST", "/rest/db/scan")
    assert error.value.outcome == "outcome_unknown"
    assert "private" not in str(error.value)
    assert len(calls) == 1
    await client.aclose()


async def test_never_exposes_error_body():
    settings = Settings.from_env(ENV)
    client = SyncthingClient(
        settings.instances[0],
        settings,
        httpx.MockTransport(lambda r: httpx.Response(500, text="secret-key")),
    )
    with pytest.raises(PublicError) as error:
        await client.request("GET", "/rest/system/status")
    assert "secret-key" not in str(error.value)
    await client.aclose()


async def test_stream_has_total_deadline_even_with_continuous_chunks():
    import asyncio

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                await asyncio.sleep(0.03)
                yield b" "

    settings = Settings.from_env(ENV | {"SYNCTHING_MCP_REQUEST_TIMEOUT": "0.1"})
    client = SyncthingClient(
        settings.instances[0],
        settings,
        httpx.MockTransport(lambda r: httpx.Response(200, stream=SlowStream())),
    )
    with pytest.raises(PublicError) as error:
        await client.request("GET", "/rest/system/status")
    assert error.value.code == "upstream_timeout"
    await client.aclose()

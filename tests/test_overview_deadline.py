"""Aggregate reads must not multiply the configured deadline by folder count."""

import asyncio
from dataclasses import replace

import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError

ENV = {"SYNCTHING_URL": "http://syncthing.test:8384", "SYNCTHING_API_KEY": "test-key"}


async def test_overview_deadline_returns_honest_partial_statuses():
    requests = []

    async def handle(request):
        requests.append(request.url.path)
        if request.url.path == "/rest/system/ping":
            return httpx.Response(200, json={"ping": "pong"})
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={"uptime": 100})
        if request.url.path == "/rest/config/folders":
            return httpx.Response(200, json=[{"id": str(i)} for i in range(12)])
        if request.url.params["folder"] == "0":
            return httpx.Response(200, json={"state": "idle"})
        await asyncio.sleep(1)
        return httpx.Response(200, json={"state": "idle"})

    engine = Engine(
        replace(Settings.from_env(ENV), request_timeout=0.1, concurrency=1),
        httpx.MockTransport(handle),
    )
    try:
        async with asyncio.timeout(0.5):
            result = await engine.call("syncthing_overview", {})
        assert result["partial"] is True
        assert result["deadline_exceeded"] is True
        assert result["items"][0]["status"] == {"state": "idle"}
        assert all(item["status"] is None for item in result["items"][1:])
        assert requests.count("/rest/db/status") == 2
        async with asyncio.timeout(0.5):
            assert (await engine.call("syncthing_system_ping", {}))["data"] == {"ping": "pong"}
    finally:
        await engine.aclose()


async def test_overview_initial_timeout_has_no_success_result():
    async def handle(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    engine = Engine(
        replace(Settings.from_env(ENV), request_timeout=0.05), httpx.MockTransport(handle)
    )
    try:
        with pytest.raises(PublicError, match="deadline|timed out"):
            await engine.call("syncthing_overview", {})
    finally:
        await engine.aclose()


async def test_overview_failed_folder_status_is_marked_partial():
    def handle(request):
        if request.url.path == "/rest/system/status":
            return httpx.Response(200, json={})
        if request.url.path == "/rest/config/folders":
            return httpx.Response(200, json=[{"id": "f"}])
        return httpx.Response(503)

    engine = Engine(Settings.from_env(ENV), httpx.MockTransport(handle))
    try:
        result = await engine.call("syncthing_overview", {})
        assert result["partial"] is True
        assert result["deadline_exceeded"] is False
        assert result["items"][0]["status"] is None
    finally:
        await engine.aclose()

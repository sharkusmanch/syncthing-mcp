"""Actual SDK v2 wire clients exercise discovery and policy on both transports."""

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile

import httpx
import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.streamable_http import streamable_http_client


async def verify(client):
    tools = await client.list_tools()
    assert "syncthing_instances" in {t.name for t in tools.tools}
    assert all(t.annotations.read_only_hint for t in tools.tools)
    result = await client.call_tool("syncthing_instances", {})
    assert not result.is_error
    assert result.structured_content["permissions"]["writes"] is False
    denied = await client.call_tool("syncthing_delete_folder", {"folder": "fixture"})
    assert denied.is_error


async def test_modern_stdio_and_http():
    env = {k: v for k, v in os.environ.items() if not k.startswith("SYNCTHING_")}
    env.update(
        SYNCTHING_URL="http://127.0.0.1:9",
        SYNCTHING_API_KEY="modern-fixture-key",
        SYNCTHING_MCP_PROFILE="core",
    )
    async with Client(
        StdioServerParameters(command=sys.executable, args=["-m", "syncthing_mcp"], env=env),
        read_timeout_seconds=10,
    ) as client:
        await verify(client)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = "modern-fixture-" + "x" * 40
    env.update(
        SYNCTHING_MCP_TRANSPORT="http",
        SYNCTHING_MCP_PORT=str(port),
        SYNCTHING_MCP_AUTH_TOKEN=token,
        SYNCTHING_MCP_ALLOWED_HOSTS=json.dumps([f"127.0.0.1:{port}"]),
    )
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "syncthing_mcp"], env=env, stdout=log, stderr=log
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as health:
                for _ in range(100):
                    assert process.poll() is None, "HTTP server exited"
                    try:
                        response = await health.get(f"http://127.0.0.1:{port}/healthz")
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError("HTTP server did not become healthy")
            async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
                async with Client(
                    streamable_http_client(f"http://127.0.0.1:{port}/mcp", http_client=http),
                    read_timeout_seconds=10,
                ) as client:
                    await verify(client)
        finally:
            process.terminate()
            process.wait(timeout=10)

"""Run under a pinned MCP v1 environment against the independently installed server."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client


async def check(streams):
    async with ClientSession(streams[0], streams[1]) as session:
        await session.initialize()
        listing = await session.list_tools()
        names = {tool.name for tool in listing.tools}
        assert "syncthing_instances" in names
        assert "syncthing_delete_folder" not in names
        result = await session.call_tool("syncthing_instances", {})
        assert not result.isError
        assert json.loads(result.content[0].text)
        denied = await session.call_tool("syncthing_delete_folder", {"folder": "test"})
        assert denied.isError


async def main(python):
    token = "legacy-fixture-" + "x" * 40
    env = {
        **os.environ,
        "SYNCTHING_URL": "http://127.0.0.1:9",
        "SYNCTHING_API_KEY": "legacy-fixture-backend-key",
        "SYNCTHING_MCP_TRANSPORT": "stdio",
        "SYNCTHING_MCP_ALLOW_WRITES": "false",
        "SYNCTHING_MCP_ALLOW_ADMIN": "false",
        "SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "false",
    }
    env.pop("SYNCTHING_MCP_INSTANCES", None)
    async with stdio_client(
        StdioServerParameters(command=python, args=["-m", "syncthing_mcp"], env=env)
    ) as streams:
        await check(streams)
    print("MCP v1 stdio: passed")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env.update(
        SYNCTHING_MCP_TRANSPORT="http",
        SYNCTHING_MCP_PORT=str(port),
        SYNCTHING_MCP_AUTH_TOKEN=token,
        SYNCTHING_MCP_ALLOWED_HOSTS=json.dumps([f"127.0.0.1:{port}"]),
    )
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen([python, "-m", "syncthing_mcp"], env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Server startup failed")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                        break
                except (urllib.error.URLError, TimeoutError):
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Server startup timeout")
            async with streamablehttp_client(
                f"http://127.0.0.1:{port}/mcp", headers={"Authorization": "Bearer " + token}
            ) as streams:
                await check(streams)
            print("MCP v1 HTTP: passed")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-python", required=True)
    asyncio.run(main(parser.parse_args().server_python))

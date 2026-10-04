"""Real Syncthing integration in a disposable directory with no peers/network discovery."""

import asyncio
import json
import os
import socket
import subprocess
import xml.etree.ElementTree as ET

import httpx
import pytest

from syncthing_mcp.config import Settings
from syncthing_mcp.engine import Engine
from syncthing_mcp.errors import PublicError


@pytest.fixture
async def backend(tmp_path):
    binary = os.environ.get("SYNCTHING_TEST_BINARY")
    if not binary:
        pytest.skip("Set SYNCTHING_TEST_BINARY to verified Syncthing 2.1.5 binary")
    home = tmp_path / "config"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ST")}
    subprocess.run(
        [binary, "generate", "--home", str(home), "--no-port-probing"],
        env=env,
        check=True,
        capture_output=True,
    )
    tree = ET.parse(home / "config.xml")
    root = tree.getroot()
    for folder in root.findall("folder"):
        root.remove(folder)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    gui = root.find("gui")
    gui.set("tls", "false")
    gui.find("address").text = f"127.0.0.1:{port}"
    gui.find("apikey").text = "disposable-integration-key"
    options = root.find("options")
    for tag, value in {
        "globalAnnounceEnabled": "false",
        "localAnnounceEnabled": "false",
        "relaysEnabled": "false",
        "natEnabled": "false",
        "startBrowser": "false",
        "urAccepted": "-1",
        "autoUpgradeIntervalH": "0",
        "crashReportingEnabled": "false",
    }.items():
        item = options.find(tag)
        if item is None:
            item = ET.SubElement(options, tag)
        item.text = value
    for listener in options.findall("listenAddress"):
        options.remove(listener)
    ET.SubElement(options, "listenAddress").text = "tcp://127.0.0.1:0"
    tree.write(home / "config.xml", encoding="utf-8")
    with (tmp_path / "backend.log").open("w+") as log:
        process = subprocess.Popen(
            [binary, "serve", "--home", str(home), "--no-browser", "--no-restart", "--no-upgrade"],
            env=env,
            cwd=tmp_path,
            stdout=log,
            stderr=log,
        )
        url = f"http://127.0.0.1:{port}"
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Disposable backend exited")
                    try:
                        response = await client.get(url + "/rest/noauth/health", timeout=1)
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Disposable backend startup timed out")
            yield (
                {
                    "SYNCTHING_URL": url,
                    "SYNCTHING_API_KEY": "disposable-integration-key",
                    "SYNCTHING_MCP_ALLOWED_PATHS": json.dumps([str(tmp_path)]),
                },
                tmp_path,
            )
        finally:
            process.terminate()
            process.wait(timeout=15)


async def test_real_reads_and_verified_folder_lifecycle(backend):
    env, root = backend
    readonly = Engine(Settings.from_env(env))
    try:
        for name in (
            "system_ping",
            "system_health",
            "system_status",
            "system_version",
            "system_connections",
            "system_errors",
            "config",
            "folders",
            "devices",
            "folder_defaults",
            "device_defaults",
            "ignore_defaults",
            "options",
            "gui_config",
            "ldap_config",
            "pending_devices",
            "pending_folders",
            "device_statistics",
            "folder_statistics",
            "events",
            "disk_events",
            "restart_required",
            "languages",
            "random_string",
        ):
            result = await readonly.call("syncthing_" + name, {})
            assert result, name
            assert "disposable-integration-key" not in json.dumps(result), name
        with pytest.raises(PublicError) as exc:
            await readonly.call("syncthing_scan_folder", {"folder": "fixture"})
        assert exc.value.code == "permission_denied"
    finally:
        await readonly.aclose()
    settings = Settings.from_env(
        env
        | {
            "SYNCTHING_MCP_ALLOW_WRITES": "true",
            "SYNCTHING_MCP_ALLOW_ADMIN": "true",
            "SYNCTHING_MCP_ALLOW_DESTRUCTIVE": "true",
        }
    )
    engine = Engine(settings)
    folder_path = root / "files"
    folder_path.mkdir()
    try:
        created = await engine.call(
            "syncthing_create_folder",
            {
                "folder": "fixture",
                "path": str(folder_path),
                "label": "Fixture",
                "patch": {
                    "versioning": {"type": "simple", "params": {"keep": "5", "cleanoutDays": "30"}}
                },
                "ignores": ["private.txt"],
                "paused": True,
            },
        )
        assert created["outcome"] == "verified", created
        config = await engine.call("syncthing_folder_config", {"folder": "fixture"})
        assert config["data"]["paused"] is True
        with pytest.raises(PublicError) as exc:
            await engine.call(
                "syncthing_create_folder",
                {"folder": "fixture", "path": str(folder_path), "label": "Replace"},
            )
        assert exc.value.code == "already_exists"
        changed = await engine.call(
            "syncthing_update_folder",
            {
                "folder": "fixture",
                "patch": {"label": "Updated"},
                "expected_revision": config["revision"],
            },
        )
        assert changed["readback_verified"] is True, changed
        ignores = await engine.call("syncthing_ignores", {"folder": "fixture"})
        assert "private.txt" in ignores["data"]["ignore"]
        resumed = await engine.call("syncthing_resume_folder", {"folder": "fixture"})
        assert resumed["readback_verified"] is True
        await asyncio.sleep(0.2)
        scanned = await engine.call("syncthing_scan_folder", {"folder": "fixture"})
        assert scanned["request_outcome"] == "succeeded", scanned
        for name in (
            "folder_status",
            "folder_completion",
            "folder_errors",
            "needed_files",
            "local_changes",
            "folder_browse",
            "file_versions",
        ):
            assert await engine.call("syncthing_" + name, {"folder": "fixture"}), name
        removed = await engine.call(
            "syncthing_delete_folder", {"folder": "fixture", "confirm": True}
        )
        assert removed["outcome"] == "verified", removed
        assert folder_path.exists()
    finally:
        await engine.aclose()

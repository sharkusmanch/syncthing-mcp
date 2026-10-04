from types import SimpleNamespace

import httpx
import pytest

from syncthing_mcp.server import create_app

TOKEN = "testing-only-" + "x" * 40


class FakeEngine:
    def tools(self):
        return [
            SimpleNamespace(
                name="test_read",
                description="Read fixture.",
                input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                read_only=True,
                destructive=False,
                group="status",
            )
        ]

    async def call(self, name, arguments):
        return {"ok": True}

    async def aclose(self):
        pass


def settings(**updates):
    values = dict(
        host="127.0.0.1",
        auth_token=TOKEN,
        allowed_hosts=("testserver",),
        allowed_origins=("https://trusted.example",),
        max_request_bytes=1024,
        max_output_bytes=4096,
        http_rate_limit=120,
        concurrency=4,
    )
    values.update(updates)
    return SimpleNamespace(**values)


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/mcp"),
        ("POST", "/mcp"),
        ("DELETE", "/mcp"),
        ("POST", "/mcp/"),
        ("GET", "/healthz/"),
        ("POST", "/healthz"),
    ],
)
async def test_all_non_health_requests_require_bearer(method, path):
    app = create_app(FakeEngine(), settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        r = await c.request(method, path)
    assert r.status_code == 401


async def test_health_is_minimal_and_unauthenticated():
    app = create_app(FakeEngine(), settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"authorization": "Bearer wrong"}, 401),
        ([("authorization", "Bearer " + TOKEN), ("authorization", "Bearer " + TOKEN)], 401),
        ({"authorization": "Bearer " + TOKEN, "host": "evil.example"}, 421),
        ({"authorization": "Bearer " + TOKEN, "origin": "https://evil.example"}, 403),
    ],
)
async def test_bad_credentials_hosts_origins_rejected(headers, status):
    app = create_app(FakeEngine(), settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        r = await c.post("/mcp", headers=headers, json={})
    assert r.status_code == status


async def test_http_mcp_roundtrip_and_body_limit():
    app = create_app(FakeEngine(), settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={
                "authorization": "Bearer " + TOKEN,
                "accept": "application/json, text/event-stream",
            },
        ) as c:
            init = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                },
            )
            assert init.status_code == 200
            r = await c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            assert r.json()["result"]["tools"][0]["name"] == "test_read"
            call = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "test_read", "arguments": {}},
                },
            )
            assert call.json()["result"]["structuredContent"] == {"ok": True}
            large = await c.post("/mcp", content="x" * 1100)
            assert large.status_code == 413


async def test_rate_limit_applies_to_authenticated_requests():
    app = create_app(FakeEngine(), settings(http_rate_limit=1))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"authorization": "Bearer " + TOKEN},
        ) as c:
            await c.get("/missing")
            r = await c.get("/missing")
            assert r.status_code == 429


async def test_full_http_envelope_limit_includes_reflected_request_id():
    app = create_app(FakeEngine(), settings(max_request_bytes=16384))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={
                "authorization": "Bearer " + TOKEN,
                "accept": "application/json, text/event-stream",
            },
        ) as c:
            r = await c.post(
                "/mcp", json={"jsonrpc": "2.0", "id": "x" * 8000, "method": "tools/list"}
            )
            assert r.status_code == 500
            assert r.json() == {"error": "response_limit"}
            assert len(r.content) < 4096


async def test_authenticated_sse_get_is_explicitly_unsupported():
    app = create_app(FakeEngine(), settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"authorization": "Bearer " + TOKEN},
    ) as c:
        r = await c.get("/mcp")
        assert r.status_code == 405
        assert r.headers["allow"] == "POST"


@pytest.mark.parametrize("cursor", ["x", "1" * 100, "99"])
async def test_malformed_catalog_cursor_is_invalid_parameters(cursor):
    app = create_app(FakeEngine(), settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={
                "authorization": "Bearer " + TOKEN,
                "accept": "application/json, text/event-stream",
            },
        ) as c:
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {"cursor": cursor},
                },
            )
            assert r.json()["error"]["code"] == -32602


@pytest.mark.parametrize(
    "payload",
    [
        {"outcome": "outcome_unknown", "request_outcome": "unknown"},
        {"outcome": "accepted", "error": {"code": "upstream_error"}},
    ],
)
async def test_ambiguous_or_failed_mutations_set_mcp_error(payload):
    from mcp import Client

    from syncthing_mcp.server import create_server

    class AmbiguousEngine(FakeEngine):
        async def call(self, name, arguments):
            return payload

    async with Client(create_server(AmbiguousEngine(), settings())) as client:
        result = await client.call_tool("test_read", {})
        assert result.is_error
        assert result.structured_content == payload

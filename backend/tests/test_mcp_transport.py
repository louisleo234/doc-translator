"""Exercise our MCP boundary with the official client and ASGI transport."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from botocore.exceptions import EndpointConnectionError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from src.mcp_server.config import McpSettings
from src.mcp_server.server import create_mcp_runtime


class Tokens:
    revoked = False
    unavailable = False

    async def authenticate(self, token):
        if self.unavailable:
            raise EndpointConnectionError(endpoint_url="http://database")
        if token == "test-secret" and not self.revoked:
            return SimpleNamespace(token_id="test-token")
        return None


class Terminology:
    async def list_catalogs(self, **kwargs):
        return {
            "items": [{"catalog_id": "it", "name": "IT", "language_pair_id": "zh-vi"}],
            "next_cursor": None,
        }

    async def match_terminology(self, **kwargs):
        return {
            "terms": [
                {
                    "source_term": "服务器",
                    "target_term": "máy chủ",
                    "catalog_id": "it",
                }
            ],
            "total_matches": 1,
            "truncated": False,
        }


@pytest.fixture
async def endpoint():
    tokens = Tokens()
    runtime = create_mcp_runtime(
        lambda: tokens,
        lambda: Terminology(),
        McpSettings(allowed_hosts=["testserver"], allowed_origins=[]),
    )

    @asynccontextmanager
    async def lifespan(app):
        async with runtime.lifespan():
            yield

    app = Starlette(
        routes=[Mount("/api", routes=[Route("/mcp", runtime.app)])],
        lifespan=lifespan,
    )
    # pytest-asyncio enters/exits generator fixtures in distinct tasks. AnyIO
    # cancel scopes require one task, just like the real ASGI lifespan runner.
    ready = asyncio.Event()
    stop = asyncio.Event()

    async def run_lifespan():
        async with app.router.lifespan_context(app):
            ready.set()
            await stop.wait()

    task = asyncio.create_task(run_lifespan())
    await ready.wait()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={
                "Authorization": "Bearer test-secret",
                "Accept": "application/json, text/event-stream",
            },
        ) as client:
            yield client, tokens
    finally:
        stop.set()
        await task


async def test_official_client_discovers_and_calls_tools(endpoint):
    client, _ = endpoint
    async with streamable_http_client(
        "http://testserver/api/mcp", http_client=client
    ) as (read, write, get_session):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            assert result.serverInfo.name == "Doc Translation Terminology"
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "list_terminology_catalogs",
                "match_terminology",
            }
            assert all(tool.inputSchema for tool in tools.tools)
            assert all(tool.outputSchema for tool in tools.tools)
            assert all(tool.annotations.readOnlyHint for tool in tools.tools)
            catalogs = await session.call_tool("list_terminology_catalogs", {})
            assert catalogs.structuredContent["items"][0]["catalog_id"] == "it"
            result = await session.call_tool(
                "match_terminology",
                {"text": "服务器", "language_pair_id": "zh-vi"},
            )
            assert not result.isError
            assert result.structuredContent["terms"][0]["target_term"] == "máy chủ"
            assert get_session() is None


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_every_method_requires_service_token(endpoint, method):
    client, _ = endpoint
    response = await client.request(
        method, "/api/mcp", headers={"Authorization": "Bearer web.jwt.token"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert "test-secret" not in response.text


async def test_get_does_not_open_sse_and_revoke_is_immediate(endpoint):
    client, tokens = endpoint
    assert (await client.get("/api/mcp")).status_code == 405
    tokens.revoked = True
    assert (await client.get("/api/mcp")).status_code == 401


async def test_invalid_origin_rejected_even_on_get(endpoint):
    client, _ = endpoint
    result = await client.get(
        "/api/mcp", headers={"Origin": "https://untrusted.example"}
    )
    assert result.status_code == 403


async def test_invalid_host_rejected(endpoint):
    client, _ = endpoint
    result = await client.get("/api/mcp", headers={"Host": "untrusted.example"})
    assert result.status_code == 421


async def test_dependency_failure_is_not_invalid_token(endpoint):
    client, tokens = endpoint
    tokens.unavailable = True
    response = await client.get("/api/mcp")
    assert response.status_code == 503
    assert "database" not in response.text


async def test_notification_is_accepted_without_body(endpoint):
    client, _ = endpoint
    response = await client.post(
        "/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response.status_code == 202
    assert not response.content


async def test_invalid_tool_arguments_return_error(endpoint):
    client, _ = endpoint
    async with streamable_http_client(
        "http://testserver/api/mcp", http_client=client
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "match_terminology",
                {"text": " ", "language_pair_id": "zh-vi", "max_results": 0},
            )
            assert result.isError


async def test_oversized_post_rejected(endpoint):
    client, _ = endpoint
    response = await client.post(
        "/api/mcp",
        content=b"x" * (1024 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


async def test_missing_credentials_rejected(endpoint):
    client, _ = endpoint
    response = await client.post(
        "/api/mcp",
        headers={"Authorization": ""},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 401


async def test_unsupported_protocol_version_rejected(endpoint):
    client, _ = endpoint
    response = await client.post(
        "/api/mcp",
        headers={"MCP-Protocol-Version": "2099-01-01"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    assert response.status_code == 400


async def test_invalid_json_and_batch_rejected(endpoint):
    client, _ = endpoint
    invalid = await client.post(
        "/api/mcp", content="{", headers={"Content-Type": "application/json"}
    )
    assert invalid.status_code == 400
    batch = await client.post(
        "/api/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    )
    assert batch.status_code == 400


async def test_concurrency_capacity_and_timeout_are_tool_errors():
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowTerminology(Terminology):
        async def match_terminology(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().match_terminology(**kwargs)

    runtime = create_mcp_runtime(
        lambda: Tokens(),
        lambda: SlowTerminology(),
        McpSettings(max_concurrent_calls=1, timeout_seconds=0.2),
    )
    # Exercise registered tools, including our capacity and timeout wrappers.
    arguments = {"text": "服务器", "language_pair_id": "zh-vi"}
    first = asyncio.create_task(
        runtime.server.call_tool("match_terminology", arguments)
    )
    await entered.wait()
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="RESOURCE_LIMIT"):
        await runtime.server.call_tool("match_terminology", arguments)
    with pytest.raises(ToolError, match="TIMEOUT"):
        await first
    release.set()
    result = await runtime.server.call_tool("match_terminology", arguments)
    assert result[1]["total_matches"] == 1


def test_network_settings_use_explicit_origins_and_hosts(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://docs.example.com")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    settings = McpSettings.from_env()
    assert "docs.example.com" in settings.allowed_hosts
    assert settings.allowed_origins == ["https://docs.example.com"]
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "internal.example.com,127.0.0.1:*")
    assert McpSettings.from_env().allowed_hosts == [
        "internal.example.com",
        "127.0.0.1:*",
    ]
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "*")
    with pytest.raises(ValueError):
        McpSettings.from_env()

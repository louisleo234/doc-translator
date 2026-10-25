"""Full HTTP management-to-MCP lifecycle without contacting AWS."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main
from tests.test_mcp_tokens import MemoryRepository
from tests.test_mcp_transport import Terminology
from src.models.user import User, UserRole, UserStatus
from src.services.mcp_token_service import McpTokenService


async def test_admin_creates_uses_and_revokes_token_through_actual_app(monkeypatch):
    repository = MemoryRepository()
    token_service = McpTokenService(repository)
    initialized = []

    class Users:
        async def get_user(self, username, *, consistent_read=False):
            assert consistent_read
            return User(username, "", UserRole.ADMIN, UserStatus.ACTIVE, False)

    resolver = SimpleNamespace(
        auth_service=SimpleNamespace(
            verify_token=lambda token: {"sub": "admin"} if token == "web-jwt" else None
        ),
        user_service=Users(),
    )

    class Context:
        mcp_token_service = token_service
        terminology_service = Terminology()

        async def initialize_async_services(self):
            initialized.append(True)

        def get_resolver_context(self):
            return resolver

    monkeypatch.setattr(main, "AppContext", Context)
    monkeypatch.setattr(main, "app_context", None)
    async with main.app.router.lifespan_context(main.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app),
            base_url="http://localhost:8000",
            follow_redirects=True,
        ) as client:
            expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
            created = await client.post(
                "/api/graphql",
                headers={"Authorization": "Bearer web-jwt"},
                json={
                    "query": """mutation($expiry: DateTime!) {
                        createMcpToken(input: {name: "integration", expiresAt: $expiry}) {
                            token { id } secret
                        }
                    }""",
                    "variables": {"expiry": expires},
                },
            )
            assert "errors" not in created.json(), created.text
            assert created.headers["cache-control"] == "no-store"
            credential = created.json()["data"]["createMcpToken"]
            client.headers.update(
                {
                    "Authorization": f"Bearer {credential['secret']}",
                    "Accept": "application/json, text/event-stream",
                }
            )
            async with streamable_http_client(
                "http://localhost:8000/api/mcp", http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    match = await session.call_tool(
                        "match_terminology",
                        {"text": "服务器", "language_pair_id": "zh-vi"},
                    )
                    assert match.structuredContent["total_matches"] == 1
            denied = await client.post(
                "/api/graphql",
                json={"query": "{ mcpTokens { items { id } } }"},
            )
            assert denied.json().get("errors")
            revoked = await client.post(
                "/api/graphql",
                headers={"Authorization": "Bearer web-jwt"},
                json={
                    "query": "mutation($id: String!) { revokeMcpToken(id: $id) }",
                    "variables": {"id": credential["token"]["id"]},
                },
            )
            assert revoked.json()["data"]["revokeMcpToken"] is True
            assert (await client.get("/api/mcp")).status_code == 401
            assert (await client.get("/api/health")).status_code == 200
    assert initialized == [True]

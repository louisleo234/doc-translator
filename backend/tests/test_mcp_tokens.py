"""Independent service credentials and real GraphQL management contract."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.responses import Response

from src.services.mcp_token_service import McpTokenService
from src.storage.mcp_token_repository import McpTokenRepository
from src.graphql.schema import schema
from src.models.user import User, UserRole, UserStatus


class MemoryRepository:
    def __init__(self):
        self.items = {}
        self.reads = 0

    async def create(self, record):
        self.items[record.token_id] = record

    async def get(self, token_id):
        self.reads += 1
        return self.items.get(token_id)

    async def list(self, first, after):
        return list(self.items.values())[:first], None

    async def revoke(self, token_id, revoked_by, revoked_at):
        record = self.items.get(token_id)
        if not record:
            return False
        if record.revoked_at is None:
            record.revoked_at = revoked_at
            record.revoked_by = revoked_by
        return True


async def test_independent_tokens_hash_only_uncached_and_idempotent_revoke():
    repository = MemoryRepository()
    service = McpTokenService(repository)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    record, secret = await service.create_token(" CI ", future, "admin")
    other, other_secret = await service.create_token("other", future, "admin")
    assert secret not in str(repository.items)
    assert record.name == "CI"
    assert len(record.token_sha256) == 64
    assert (await service.authenticate(secret)).token_id == record.token_id
    assert (await service.authenticate(secret)).token_id == record.token_id
    assert repository.reads == 2
    assert await service.revoke_token(record.token_id, "admin")
    first_revoke = record.revoked_at
    assert await service.revoke_token(record.token_id, "other")
    assert record.revoked_at == first_revoke and record.revoked_by == "admin"
    assert await service.authenticate(secret) is None
    assert (await service.authenticate(other_secret)).token_id == other.token_id
    assert not await service.revoke_token("missing", "admin")


async def test_invalid_expired_and_web_credentials():
    service = McpTokenService(MemoryRepository())
    now = datetime.now(timezone.utc)
    for name, expiry in [
        ("", now + timedelta(days=1)),
        ("x" * 101, now),
        ("a", now),
        ("a", now.replace(tzinfo=None)),
    ]:
        with pytest.raises(ValueError):
            await service.create_token(name, expiry, "admin")
    record, secret = await service.create_token("CI", now + timedelta(days=1), "admin")
    for invalid in [
        "",
        "eyJhbGciOiJIUzI1NiJ9.payload.signature",
        secret[:-1],
        secret + "x",
    ]:
        assert await service.authenticate(invalid) is None
    record.expires_at = now - timedelta(seconds=1)
    assert await service.authenticate(secret) is None


async def test_repository_get_is_consistent_and_failures_propagate():
    table = MagicMock()
    table.get_item.return_value = {}
    base = SimpleNamespace(
        _get_resource=lambda: SimpleNamespace(Table=lambda name: table)
    )
    repository = McpTokenRepository(base)
    assert await repository.get("abc") is None
    table.get_item.assert_called_once_with(Key={"token_id": "abc"}, ConsistentRead=True)
    table.get_item.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError):
        await repository.get("abc")


def context(role=UserRole.ADMIN, status=UserStatus.ACTIVE):
    user = User("admin", "", role, status, False)
    return {
        "token": "web-jwt",
        "auth_service": SimpleNamespace(
            verify_token=lambda token: {"sub": "admin", "role": "admin"}
        ),
        "user_service": SimpleNamespace(get_user=AsyncMock(return_value=user)),
        "mcp_token_service": McpTokenService(MemoryRepository()),
        "response": Response(),
    }


async def test_graphql_create_list_revoke_and_no_store():
    ctx = context()
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    result = await schema.execute(
        'mutation($expiry: DateTime!) { createMcpToken(input: {name: "CI", expiresAt: $expiry}) { token { id name createdBy createdAt expiresAt revokedAt } secret } }',
        variable_values={"expiry": expiry},
        context_value=ctx,
    )
    assert not result.errors
    created = result.data["createMcpToken"]
    assert ctx["response"].headers["cache-control"] == "no-store"
    result = await schema.execute(
        "{ mcpTokens(first: 20) { items { id name } nextCursor } }", context_value=ctx
    )
    assert not result.errors
    assert created["secret"] not in str(result.data)
    result = await schema.execute(
        "mutation($id: String!) { revokeMcpToken(id: $id) }",
        variable_values={"id": created["token"]["id"]},
        context_value=ctx,
    )
    assert not result.errors and result.data["revokeMcpToken"]


@pytest.mark.parametrize(
    "role,status",
    [
        (UserRole.USER, UserStatus.ACTIVE),
        (UserRole.ADMIN, UserStatus.LOCKED),
        (UserRole.ADMIN, UserStatus.DELETED),
    ],
)
async def test_management_rechecks_current_user(role, status):
    ctx = context(role, status)
    ctx["current_user"] = User("admin", "", UserRole.ADMIN, UserStatus.ACTIVE, False)
    result = await schema.execute("{ mcpTokens { items { id } } }", context_value=ctx)
    assert result.errors


async def test_anonymous_and_dependency_errors_are_safe():
    assert (
        await schema.execute("{ mcpTokens { items { id } } }", context_value={})
    ).errors
    ctx = context()
    ctx["mcp_token_service"].repository.list = AsyncMock(
        side_effect=RuntimeError("secret-should-never-leak")
    )
    result = await schema.execute("{ mcpTokens { items { id } } }", context_value=ctx)
    assert result.errors and "secret-should-never-leak" not in str(result.errors)


async def test_repository_real_cursor_and_conditional_revoke():
    from botocore.exceptions import ClientError

    repository = MemoryRepository()
    record, _ = await McpTokenService(repository).create_token(
        "CI", datetime.now(timezone.utc) + timedelta(days=1), "admin"
    )
    table = MagicMock()
    table.scan.side_effect = [
        {
            "Items": [record.to_dict()],
            "LastEvaluatedKey": {"token_id": record.token_id},
        },
        {"Items": []},
    ]
    base = SimpleNamespace(
        _get_resource=lambda: SimpleNamespace(Table=lambda name: table)
    )
    dynamo = McpTokenRepository(base)
    records, cursor = await dynamo.list(1, None)
    assert records[0].token_id == record.token_id and cursor
    assert await dynamo.list(1, cursor) == ([], None)
    assert table.scan.call_args.kwargs == {
        "Limit": 1,
        "ExclusiveStartKey": {"token_id": record.token_id},
    }
    with pytest.raises(ValueError):
        await dynamo.list(1, "not-a-cursor")
    table.update_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
    )
    record.revoked_at = datetime.now(timezone.utc)
    record.revoked_by = "first-admin"
    table.get_item.return_value = {"Item": record.to_dict()}
    assert await dynamo.revoke(
        record.token_id, "second-admin", datetime.now(timezone.utc)
    )
    assert (
        "attribute_not_exists(revoked_at)"
        in table.update_item.call_args.kwargs["ConditionExpression"]
    )
    assert table.get_item.call_args.kwargs["ConsistentRead"] is True
    table.get_item.return_value = {}
    assert not await dynamo.revoke("missing", "admin", datetime.now(timezone.utc))


async def test_create_error_does_not_disclose_plaintext():
    ctx = context()
    ctx["mcp_token_service"].repository.create = AsyncMock(
        side_effect=RuntimeError("sensitive-credential-error")
    )
    result = await schema.execute(
        'mutation($expiry: DateTime!) { createMcpToken(input: {name: "CI", expiresAt: $expiry}) { secret } }',
        variable_values={
            "expiry": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        },
        context_value=ctx,
    )
    assert result.errors and result.data is None
    assert "sensitive-credential-error" not in str(result.errors)
    assert ctx["response"].headers["cache-control"] == "no-store"


async def test_management_reads_current_admin_strongly_consistently():
    from src.services.user_service import UserService
    from src.storage.dynamodb_repository import DynamoDBRepository

    ctx = context()
    table = MagicMock()
    table.get_item.return_value = {
        "Item": User("admin", "", UserRole.ADMIN, UserStatus.ACTIVE, False).to_dict()
    }
    repository = DynamoDBRepository()
    repository._resource = SimpleNamespace(Table=lambda name: table)
    ctx["user_service"] = UserService(repository)
    result = await schema.execute("{ mcpTokens { items { id } } }", context_value=ctx)
    assert not result.errors
    table.get_item.assert_called_once_with(
        Key={"username": "admin"}, ConsistentRead=True
    )
    table.get_item.return_value["Item"]["role"] = "user"
    result = await schema.execute("{ mcpTokens { items { id } } }", context_value=ctx)
    assert result.errors

"""Administrator-only independent token management."""

from datetime import datetime
from typing import Callable, Any

import strawberry
from strawberry.types import Info
from graphql import GraphQLError

from ..models.mcp_token import McpToken
from ..models.user import UserRole, UserStatus
from .decorators import get_token_from_context


@strawberry.type
class McpTokenInfo:
    id: str
    name: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@strawberry.type
class McpTokenPage:
    items: list[McpTokenInfo]
    next_cursor: str | None


@strawberry.type
class McpTokenCreated:
    token: McpTokenInfo
    secret: str


@strawberry.input
class CreateMcpTokenInput:
    name: str
    expires_at: datetime


def metadata(record: McpToken) -> McpTokenInfo:
    return McpTokenInfo(
        id=record.token_id,
        name=record.name,
        created_by=record.created_by,
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
    )


async def management_context(info: Info) -> tuple[Any, str]:
    """Reverify web JWT and current database role/status for every operation."""
    ctx = info.context
    auth = ctx.get("auth_service")
    users = ctx.get("user_service")
    token = get_token_from_context(info)
    if not auth or not users or not token:
        raise GraphQLError("Administrator authentication required")
    payload = auth.verify_token(token)
    if not payload or not payload.get("sub"):
        raise GraphQLError("Administrator authentication required")
    user = await users.get_user(payload["sub"], consistent_read=True)
    if not user or user.role != UserRole.ADMIN or user.status != UserStatus.ACTIVE:
        raise GraphQLError("Active administrator access required")
    service = ctx.get("mcp_token_service")
    if service is None:
        raise GraphQLError("Token management unavailable")
    return service, user.username


async def safe_operation(operation: Callable[[], Any]) -> Any:
    """Never pass storage exception messages (possibly containing credentials)."""
    try:
        return await operation()
    except GraphQLError:
        raise
    except ValueError:
        raise GraphQLError("Invalid token management input") from None
    except Exception:
        raise GraphQLError("Token management unavailable") from None


async def resolve_mcp_tokens(info: Info, first: int, after: str | None) -> McpTokenPage:
    async def operation() -> McpTokenPage:
        service, _ = await management_context(info)
        records, cursor = await service.list_tokens(first, after)
        return McpTokenPage(
            items=[metadata(record) for record in records], next_cursor=cursor
        )

    return await safe_operation(operation)


async def resolve_create_mcp_token(
    info: Info, input: CreateMcpTokenInput
) -> McpTokenCreated:
    # Set even on errors and partial responses; credentials must never be cached.
    response = info.context.get("response")
    if response is not None:
        response.headers["Cache-Control"] = "no-store"

    async def operation() -> McpTokenCreated:
        service, username = await management_context(info)
        record, secret = await service.create_token(
            input.name, input.expires_at, username
        )
        return McpTokenCreated(token=metadata(record), secret=secret)

    return await safe_operation(operation)


async def resolve_revoke_mcp_token(info: Info, id: str) -> bool:
    async def operation() -> bool:
        service, username = await management_context(info)
        return await service.revoke_token(id, username)

    return await safe_operation(operation)

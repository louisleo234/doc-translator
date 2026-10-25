"""Independent high-entropy MCP credential lifecycle."""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from ..models.mcp_token import McpToken
from ..storage.mcp_token_repository import McpTokenRepository

TOKEN_PATTERN = re.compile(r"^dtmcp_([0-9a-f]{32})\.([A-Za-z0-9_-]{43})$")


class McpTokenService:
    def __init__(self, repository: McpTokenRepository) -> None:
        self.repository = repository

    async def create_token(
        self, name: str, expires_at: datetime, created_by: str
    ) -> tuple[McpToken, str]:
        name = name.strip()
        now = datetime.now(timezone.utc)
        if not 1 <= len(name) <= 100:
            raise ValueError("Token name must contain 1–100 characters")
        if (
            expires_at.tzinfo is None
            or expires_at.utcoffset() is None
            or expires_at <= now
        ):
            raise ValueError("Expiry must be a future UTC timestamp")
        token_id = uuid4().hex
        plaintext = f"dtmcp_{token_id}.{secrets.token_urlsafe(32)}"
        record = McpToken(
            token_id,
            name,
            hashlib.sha256(plaintext.encode()).hexdigest(),
            created_by,
            now,
            expires_at.astimezone(timezone.utc),
        )
        await self.repository.create(record)
        return record, plaintext

    async def authenticate(self, token: str) -> McpToken | None:
        match = TOKEN_PATTERN.fullmatch(token) if isinstance(token, str) else None
        if not match:
            return None
        record = await self.repository.get(match.group(1))
        if record is None:
            return None
        digest_matches = hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(),
            record.token_sha256,
        )
        if (
            not digest_matches
            or record.revoked_at is not None
            or record.expires_at <= datetime.now(timezone.utc)
        ):
            return None
        return record

    async def list_tokens(
        self, first: int = 20, after: str | None = None
    ) -> tuple[list[McpToken], str | None]:
        if not 1 <= first <= 100:
            raise ValueError("Page size must be between 1 and 100")
        if after is not None and (not after or len(after) > 2048):
            raise ValueError("Invalid cursor")
        return await self.repository.list(first, after)

    async def revoke_token(self, token_id: str, revoked_by: str) -> bool:
        return await self.repository.revoke(
            token_id, revoked_by, datetime.now(timezone.utc)
        )

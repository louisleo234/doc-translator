"""Persistent independent MCP credential metadata (never plaintext)."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class McpToken:
    token_id: str
    name: str
    token_sha256: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revoked_by: str | None = None

    def to_dict(self) -> dict:
        return {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in vars(self).items()
            if value is not None
        }

    @classmethod
    def from_dict(cls, item: dict) -> "McpToken":
        data = dict(item)
        for key in ("created_at", "expires_at", "revoked_at"):
            if data.get(key):
                data[key] = datetime.fromisoformat(data[key])
        return cls(**data)

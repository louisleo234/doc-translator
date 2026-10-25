"""Explicit network and resource limits for the remote MCP endpoint."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class McpSettings:
    allowed_hosts: list[str] = field(
        default_factory=lambda: ["localhost:*", "127.0.0.1:*", "[::1]:*"]
    )
    allowed_origins: list[str] = field(default_factory=list)
    max_body_bytes: int = 1024 * 1024
    max_concurrent_calls: int = 8
    timeout_seconds: float = 15

    @classmethod
    def from_env(cls) -> "McpSettings":
        defaults = cls()
        frontend = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
        hosts = list(defaults.allowed_hosts)
        origins: list[str] = []
        if frontend:
            parsed = urlsplit(frontend)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                hosts.append(parsed.netloc)
                origins.append(f"{parsed.scheme}://{parsed.netloc}")
        if "MCP_ALLOWED_HOSTS" in os.environ:
            hosts = cls._csv("MCP_ALLOWED_HOSTS")
        if "MCP_ALLOWED_ORIGINS" in os.environ:
            origins = cls._csv("MCP_ALLOWED_ORIGINS")
        if not hosts or "*" in hosts or "*" in origins:
            raise ValueError("MCP requires explicit allowed hosts and origins")
        return cls(allowed_hosts=hosts, allowed_origins=origins)

    @staticmethod
    def _csv(name: str) -> list[str]:
        return [value.strip() for value in os.environ[name].split(",") if value.strip()]

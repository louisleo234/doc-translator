"""Authenticate every HTTP exchange without reusing web JWT authentication."""

import asyncio
import logging
from collections.abc import Callable
from contextvars import ContextVar
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from mcp.server.transport_security import (
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from src.services.mcp_token_service import McpTokenService

from .config import McpSettings

logger = logging.getLogger(__name__)
credential_id: ContextVar[str] = ContextVar("mcp_credential_id", default="")
request_id: ContextVar[str] = ContextVar("mcp_request_id", default="")


class McpAuthentication:
    def __init__(
        self,
        app: ASGIApp,
        token_service: Callable[[], McpTokenService],
        settings: McpSettings,
    ) -> None:
        self.app = app
        self.token_service = token_service
        self.security = TransportSecurityMiddleware(
            TransportSecuritySettings(
                allowed_hosts=settings.allowed_hosts,
                allowed_origins=settings.allowed_origins,
            )
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        # Validate network headers on GET as well as POST, before any DB access.
        failure = await self.security.validate_request(request)
        if failure is not None:
            await failure(scope, receive, send)
            return
        auth_headers = request.headers.getlist("authorization")
        parts = auth_headers[0].split() if len(auth_headers) == 1 else []
        token = parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else ""
        try:
            async with asyncio.timeout(5):
                record = await self.token_service().authenticate(token)
        except (BotoCoreError, ClientError, TimeoutError):
            logger.warning("MCP authentication storage unavailable")
            response = JSONResponse(
                {"error": "temporarily_unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store", "Retry-After": "5"},
            )
            await response(scope, receive, send)
            return
        if record is None:
            response = JSONResponse(
                {"error": "invalid_token"},
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Bearer realm="terminology-mcp"',
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return
        if request.method in {"GET", "DELETE", "HEAD"}:
            await Response(status_code=405, headers={"Allow": "POST"})(
                scope, receive, send
            )
            return
        credential_context = credential_id.set(record.token_id)
        request_context = request_id.set(uuid4().hex)
        try:
            await self.app(scope, receive, send)
        finally:
            credential_id.reset(credential_context)
            request_id.reset(request_context)

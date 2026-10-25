"""Official SDK transport with application-owned authentication and lifespan."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.types import ASGIApp

from src.services.mcp_token_service import McpTokenService
from src.services.terminology_service import TerminologyError, TerminologyService

from .auth import McpAuthentication, credential_id, request_id
from .config import McpSettings

logger = logging.getLogger(__name__)


class MatchedTerm(BaseModel):
    source_term: str
    target_term: str
    catalog_id: str


class MatchResult(BaseModel):
    terms: list[MatchedTerm]
    total_matches: int
    truncated: bool


class CatalogResult(BaseModel):
    catalog_id: str
    name: str
    language_pair_id: str
    source_language: str | None = None
    target_language: str | None = None


class CatalogPage(BaseModel):
    items: list[CatalogResult]
    next_cursor: str | None


@dataclass
class McpRuntime:
    server: FastMCP
    app: ASGIApp

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        async with self.server.session_manager.run():
            yield


def create_mcp_runtime(
    token_service: Callable[[], McpTokenService],
    terminology_service: Callable[[], TerminologyService],
    settings: McpSettings | None = None,
) -> McpRuntime:
    settings = settings or McpSettings.from_env()
    server = FastMCP(
        "Doc Translation Terminology",
        instructions=(
            "Read existing glossary translations. List catalogs to discover "
            "language_pair_id values, then match terminology against source text. "
            "All catalogs are readable. This server never translates new terms."
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.max_body_bytes,
        transport_security=TransportSecuritySettings(
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        ),
    )
    # SDK DEBUG logs include raw protocol messages. Keep them out of application
    # DEBUG logs; application telemetry below contains only counts and identifiers.
    logging.getLogger("mcp").setLevel(logging.WARNING)
    semaphore = asyncio.Semaphore(settings.max_concurrent_calls)
    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    async def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if semaphore.locked():
            raise ToolError("RESOURCE_LIMIT: Too many active terminology requests")
        started = monotonic()
        error_code = ""
        result: dict[str, Any] = {}
        try:
            async with semaphore:
                async with asyncio.timeout(settings.timeout_seconds):
                    service = terminology_service()
                    method = (
                        service.list_catalogs
                        if name == "list_terminology_catalogs"
                        else service.match_terminology
                    )
                    result = await method(**arguments)
                    return result
        except TimeoutError:
            error_code = "TIMEOUT"
            raise ToolError("TIMEOUT: Terminology request timed out") from None
        except TerminologyError as exc:
            error_code = exc.code
            raise ToolError(str(exc)) from None
        finally:
            logger.info(
                "MCP tool=%s request_id=%s token_id=%s text_length=%d "
                "matches=%s duration_ms=%d error_code=%s",
                name,
                request_id.get(),
                credential_id.get(),
                len(arguments.get("text", "")),
                result.get("total_matches", 0),
                int((monotonic() - started) * 1000),
                error_code,
            )

    @server.tool(annotations=annotations)
    async def list_terminology_catalogs(
        language_pair_id: str | None = None,
        page_size: Annotated[int, Field(ge=1, le=200)] = 100,
        cursor: str | None = None,
    ) -> CatalogPage:
        """List all available glossary catalogs and their actual language pair IDs.

        Follow next_cursor until null. Omit language_pair_id to discover all pairs.
        """
        result = await execute(
            "list_terminology_catalogs",
            {
                "language_pair_id": language_pair_id,
                "page_size": page_size,
                "cursor": cursor,
            },
        )
        return CatalogPage.model_validate(result)

    @server.tool(annotations=annotations)
    async def match_terminology(
        text: Annotated[str, Field(min_length=1, max_length=50_000)],
        language_pair_id: Annotated[str, Field(min_length=1)],
        catalog_ids: list[str] | None = None,
        max_results: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> MatchResult:
        """Return existing source/target glossary terms appearing in source text.

        language_pair_id comes from list_terminology_catalogs. Omit catalog_ids to
        search every catalog in that pair; provide ordered IDs to choose priority.
        Matching is case-sensitive and NFC-normalized. No new text is translated.
        """
        result = await execute(
            "match_terminology",
            {
                "text": text,
                "language_pair_id": language_pair_id,
                "catalog_ids": catalog_ids,
                "max_results": max_results,
            },
        )
        return MatchResult.model_validate(result)

    app = McpAuthentication(server.streamable_http_app(), token_service, settings)
    return McpRuntime(server=server, app=app)

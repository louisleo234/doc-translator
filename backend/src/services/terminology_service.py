"""Read-only terminology service independent of GraphQL, MCP and Bedrock."""

import asyncio
import base64
import binascii
import json
import time
from threading import Event
from typing import Any

from src.services.terminology_matcher import TerminologyMatcher
from src.storage.terminology_repository import (
    DependencyUnavailableError,
    ResourceLimitError,
    TerminologyError,
    TerminologyRepository,
)


def _invalid(message: str) -> TerminologyError:
    return TerminologyError("INVALID_CATALOG_SELECTION", message)


class TerminologyService:
    def __init__(
        self,
        repository: TerminologyRepository,
        max_records: int = 100_000,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.repository = repository
        self.max_records = max_records
        self.timeout_seconds = timeout_seconds

    async def list_catalogs(
        self,
        language_pair_id: str | None = None,
        page_size: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._list_catalogs(language_pair_id, page_size, cursor)
        except TimeoutError as exc:
            raise TerminologyError(
                "TIMEOUT", "Terminology request exceeded its time budget"
            ) from exc

    async def _list_catalogs(
        self,
        language_pair_id: str | None,
        page_size: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        if type(page_size) is not int or not 1 <= page_size <= 200:
            raise _invalid("page_size must be between 1 and 200")
        if language_pair_id is not None and not language_pair_id.strip():
            raise _invalid("language_pair_id must not be blank")
        key = None
        if cursor is not None:
            try:
                if len(cursor) > 4096:
                    raise ValueError("oversized cursor")
                data = json.loads(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
                key = data["key"]
                if (
                    data["language_pair_id"] != language_pair_id
                    or not isinstance(key, dict)
                    or set(key) != {"pk", "sk"}
                    or not all(isinstance(v, str) for v in key.values())
                ):
                    raise ValueError("invalid cursor scope or key")
            except (ValueError, KeyError, TypeError, binascii.Error) as exc:
                raise _invalid("Invalid catalog cursor") from exc
        items, next_key, _ = await self.repository.catalogs_page(
            language_pair_id, page_size, key
        )
        next_cursor = None
        if next_key:
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    dict(language_pair_id=language_pair_id, key=next_key)
                ).encode()
            ).decode()
        # At most page_size distinct reads, within the same total timeout.
        # Missing legacy records remain explicitly unknown rather than inferred.
        directions: dict[str, dict[str, Any]] = {}
        for catalog in items:
            pair_id = catalog["language_pair_id"]
            if pair_id not in directions:
                directions[pair_id] = (
                    await self.repository.get_language_pair(pair_id) or {}
                )
        return dict(
            items=[
                dict(
                    catalog_id=c["id"],
                    name=c["name"],
                    language_pair_id=c["language_pair_id"],
                    source_language=directions[c["language_pair_id"]].get(
                        "source_language"
                    ),
                    target_language=directions[c["language_pair_id"]].get(
                        "target_language"
                    ),
                )
                for c in items
            ],
            next_cursor=next_cursor,
        )

    async def match_terminology(
        self,
        text: str,
        language_pair_id: str,
        catalog_ids: list[str] | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        stop = Event()
        deadline = time.monotonic() + self.timeout_seconds
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._match_terminology(
                    text, language_pair_id, catalog_ids, max_results, stop, deadline
                )
        except TimeoutError as exc:
            raise TerminologyError(
                "TIMEOUT", "Terminology request exceeded its time budget"
            ) from exc
        finally:
            # asyncio cancellation alone cannot stop an already-running thread.
            stop.set()

    async def _match_terminology(
        self,
        text: str,
        language_pair_id: str,
        catalog_ids: list[str] | None,
        max_results: int,
        stop: Event,
        deadline: float,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip() or len(text) > 50_000:
            raise _invalid("text must contain 1 to 50000 nonblank Unicode characters")
        if not isinstance(language_pair_id, str) or not language_pair_id.strip():
            raise _invalid("language_pair_id is required")
        if type(max_results) is not int or not 1 <= max_results <= 1000:
            raise _invalid("max_results must be between 1 and 1000")
        scanned = 0

        def account(count: int) -> None:
            nonlocal scanned
            scanned += count
            if scanned > self.max_records:
                raise ResourceLimitError()

        def page_limit() -> int:
            # Read at most one record beyond the budget to distinguish exhaustion.
            return min(1000, max(1, self.max_records - scanned + 1))

        if catalog_ids is not None:
            if (
                not isinstance(catalog_ids, list)
                or not 1 <= len(catalog_ids) <= 20
                or any(not isinstance(c, str) or not c.strip() for c in catalog_ids)
            ):
                raise _invalid("catalog_ids must contain 1 to 20 nonblank IDs")
            selected = list(dict.fromkeys(catalog_ids))
            for catalog_id in selected:
                catalog = await self.repository.get_catalog(
                    language_pair_id, catalog_id
                )
                account(1)
                if not catalog or catalog["language_pair_id"] != language_pair_id:
                    raise _invalid(
                        "Catalog does not exist in the requested language pair"
                    )
        else:
            selected = []
            key = None
            while True:
                items, key, count = await self.repository.catalogs_page(
                    language_pair_id, page_limit(), key
                )
                account(count)
                selected.extend(c["id"] for c in items)
                if not key:
                    break
            selected = sorted(set(selected))
        matcher = TerminologyMatcher(text, stop, deadline)
        for priority, catalog_id in enumerate(selected):
            key = None
            while True:
                items, key, count = await self.repository.terms_page(
                    catalog_id, page_limit(), key
                )
                account(count)
                # Catalog IDs are not language-scoped in the GSI partition.
                # Count every examined row, but match only this language pair.
                selected_items = [
                    item
                    for item in items
                    if item.get("language_pair_id") == language_pair_id
                ]
                await asyncio.to_thread(
                    matcher.consume, selected_items, catalog_id, priority
                )
                if not key:
                    break
        return await asyncio.to_thread(matcher.result, max_results)

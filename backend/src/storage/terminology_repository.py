"""Uncapped, page-oriented read access using the existing AWS resource."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from src.storage.dynamodb_repository import (
    CATALOGS_TABLE,
    TERM_PAIRS_TABLE,
    DynamoDBRepository,
)


class TerminologyError(ValueError):
    """Safe, public terminology failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ResourceLimitError(TerminologyError):
    def __init__(self) -> None:
        super().__init__("RESOURCE_LIMIT", "Terminology record budget exceeded")


class DependencyUnavailableError(TerminologyError):
    def __init__(self) -> None:
        super().__init__("DEPENDENCY_UNAVAILABLE", "Terminology storage unavailable")


class TerminologyRepository:
    def __init__(self, repository: DynamoDBRepository) -> None:
        self.repository = repository

    async def _read(
        self, table_name: str, operation: str, **kwargs: Any
    ) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            table = self.repository._get_resource().Table(table_name)
            return getattr(table, operation)(**kwargs)

        try:
            return await self.repository._run_sync(execute)
        except (BotoCoreError, ClientError) as exc:
            raise DependencyUnavailableError() from exc

    async def catalogs_page(
        self,
        language_pair_id: str | None,
        limit: int,
        last_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
        kwargs: dict[str, Any] = {"Limit": limit}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        if language_pair_id is not None:
            kwargs.update(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": f"LP#{language_pair_id}"},
            )
        response = await self._read(
            CATALOGS_TABLE,
            "query" if language_pair_id is not None else "scan",
            **kwargs,
        )
        items = response.get("Items", [])
        return (
            items,
            response.get("LastEvaluatedKey"),
            response.get("ScannedCount", len(items)),
        )

    async def get_catalog(
        self, language_pair_id: str, catalog_id: str
    ) -> dict[str, Any] | None:
        response = await self._read(
            CATALOGS_TABLE,
            "get_item",
            Key={"pk": f"LP#{language_pair_id}", "sk": f"CAT#{catalog_id}"},
        )
        return response.get("Item")

    async def get_language_pair(
        self,
        language_pair_id: str,
    ) -> dict[str, Any] | None:
        """Read the shared language direction without creating defaults."""
        response = await self._read(
            DynamoDBRepository.LANGUAGE_PAIRS_TABLE,
            "get_item",
            Key={"pk": "USER#__global__", "sk": f"LP#{language_pair_id}"},
        )
        return response.get("Item")

    async def terms_page(
        self,
        catalog_id: str,
        limit: int,
        last_key: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int]:
        kwargs: dict[str, Any] = dict(
            IndexName="GSI1-catalog-updated",
            KeyConditionExpression="catalog_id = :cat_id",
            ExpressionAttributeValues={":cat_id": catalog_id},
            Limit=limit,
        )
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        response = await self._read(TERM_PAIRS_TABLE, "query", **kwargs)
        items = response.get("Items", [])
        return (
            items,
            response.get("LastEvaluatedKey"),
            response.get("ScannedCount", len(items)),
        )

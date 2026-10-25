"""Bounded token persistence with uncached strongly consistent authentication."""

import asyncio
import base64
import json
from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError

from ..models.mcp_token import McpToken
from .dynamodb_repository import DynamoDBRepository

MCP_TOKENS_TABLE = "doc_translation_mcp_tokens"


class McpTokenRepository:
    def __init__(self, repository: DynamoDBRepository | None = None) -> None:
        self.repository = repository or DynamoDBRepository()

    def _table(self) -> Any:
        return self.repository._get_resource().Table(MCP_TOKENS_TABLE)

    async def initialize_table(self) -> None:
        def initialize() -> None:
            client = self.repository._get_client()
            try:
                client.describe_table(TableName=MCP_TOKENS_TABLE)
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
                try:
                    client.create_table(
                        TableName=MCP_TOKENS_TABLE,
                        KeySchema=[{"AttributeName": "token_id", "KeyType": "HASH"}],
                        AttributeDefinitions=[
                            {"AttributeName": "token_id", "AttributeType": "S"}
                        ],
                        BillingMode="PAY_PER_REQUEST",
                    )
                except ClientError as create_exc:
                    if create_exc.response["Error"]["Code"] != "ResourceInUseException":
                        raise
            client.get_waiter("table_exists").wait(TableName=MCP_TOKENS_TABLE)

        await asyncio.to_thread(initialize)

    async def create(self, record: McpToken) -> None:
        await asyncio.to_thread(
            self._table().put_item,
            Item=record.to_dict(),
            ConditionExpression="attribute_not_exists(token_id)",
        )

    async def get(self, token_id: str) -> McpToken | None:
        result = await asyncio.to_thread(
            self._table().get_item,
            Key={"token_id": token_id},
            ConsistentRead=True,
        )
        return McpToken.from_dict(result["Item"]) if result.get("Item") else None

    async def list(
        self, first: int, after: str | None
    ) -> tuple[list[McpToken], str | None]:
        options: dict[str, Any] = {"Limit": first}
        if after:
            try:
                key = json.loads(base64.urlsafe_b64decode(after.encode()).decode())
                if (
                    not isinstance(key, dict)
                    or set(key) != {"token_id"}
                    or not isinstance(key["token_id"], str)
                ):
                    raise ValueError("Invalid cursor")
            except (ValueError, UnicodeError, TypeError):
                raise ValueError("Invalid cursor") from None
            options["ExclusiveStartKey"] = key
        result = await asyncio.to_thread(self._table().scan, **options)
        key = result.get("LastEvaluatedKey")
        cursor = (
            base64.urlsafe_b64encode(json.dumps(key).encode()).decode() if key else None
        )
        return [McpToken.from_dict(item) for item in result.get("Items", [])], cursor

    async def revoke(
        self, token_id: str, revoked_by: str, revoked_at: datetime
    ) -> bool:
        try:
            await asyncio.to_thread(
                self._table().update_item,
                Key={"token_id": token_id},
                UpdateExpression="SET revoked_at = :at, revoked_by = :by",
                ConditionExpression="attribute_exists(token_id) AND attribute_not_exists(revoked_at)",
                ExpressionAttributeValues={
                    ":at": revoked_at.isoformat(),
                    ":by": revoked_by,
                },
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            record = await self.get(token_id)
            return record is not None and record.revoked_at is not None

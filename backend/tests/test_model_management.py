"""
Tests for admin model list management (service + GraphQL resolvers).
"""
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.graphql.config_resolvers import (
    resolve_create_config_model,
    resolve_delete_config_model,
    resolve_update_config_model,
)
from src.graphql.decorators import PermissionError as AuthPermissionError
from src.graphql.resolvers import ValidationError
from src.models.config import ConfigKey, ModelConfig, UserSettings
from src.models.user import User as UserModel, UserRole, UserStatus
from src.services.global_config_service import (
    DEFAULT_MODELS,
    GlobalConfigService,
    ModelListConflictError,
    infer_provider,
)
from src.services.user_settings_service import UserSettingsService
from src.storage.dynamodb_repository import VersionConflictError

NOVA = "global.amazon.nova-2-lite-v1:0"
GROK = "global.xai.grok-4.7"


class FakeConfigRepository:
    """In-memory stand-in for the global config part of DynamoDBRepository."""

    def __init__(self, items: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.items: Dict[str, Dict[str, Any]] = items or {}

    async def get_global_config(self, key: str) -> Optional[Dict[str, Any]]:
        item = self.items.get(key)
        return dict(item) if item else None

    async def create_global_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        item = {"description": "", **data}
        self.items[data["config_key"]] = item
        return dict(item)

    async def update_global_config(self, key: str, **updates: Any) -> Dict[str, Any]:
        self.items[key].update(updates)
        return dict(self.items[key])

    async def put_global_config_versioned(
        self,
        key: str,
        value: Dict[str, Any],
        expected_version: Optional[int],
        description: str = "",
    ) -> Dict[str, Any]:
        """Mimics the DynamoDB condition on the version attribute."""
        self.versioned_writes += 1
        current = self.items.get(key, {}).get("version")
        if current != expected_version:
            raise VersionConflictError(key)
        item = {"config_key": key, "description": description,
                **self.items.get(key, {})}
        item.update(config_value=value, version=(expected_version or 0) + 1)
        self.items[key] = item
        return dict(item)

    versioned_writes = 0


def _models_item(models: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "config_key": ConfigKey.AVAILABLE_MODELS.value,
        "config_value": {"models": models},
        "description": "",
    }


@pytest.fixture
def repo() -> FakeConfigRepository:
    return FakeConfigRepository(
        {
            ConfigKey.AVAILABLE_MODELS.value: _models_item(
                [
                    {"model_id": NOVA, "display_name": "Nova 2 Lite",
                     "provider": "amazon", "is_default": True},
                    {"model_id": GROK, "display_name": "Grok 4.7",
                     "provider": "xai", "is_default": False},
                ]
            ),
            ConfigKey.DEFAULT_SETTINGS.value: {
                "config_key": ConfigKey.DEFAULT_SETTINGS.value,
                "config_value": {
                    "default_model_id": NOVA,
                    "ui_language": "vi",
                    "translation_batch_size": 10,
                    "max_concurrent_tasks": 5,
                },
            },
        }
    )


@pytest.fixture
def service(repo: FakeConfigRepository) -> GlobalConfigService:
    return GlobalConfigService(repository=repo)


def _stored_models(repo: FakeConfigRepository) -> List[Dict[str, Any]]:
    return repo.items[ConfigKey.AVAILABLE_MODELS.value]["config_value"]["models"]


def _defaults(repo: FakeConfigRepository) -> List[str]:
    return [m["model_id"] for m in _stored_models(repo) if m["is_default"]]


class TestInferProvider:
    @pytest.mark.parametrize(
        "model_id, expected",
        [
            ("global.xai.grok-4.7", "xai"),
            ("us.anthropic.foo-v1:0", "anthropic"),
            ("amazon.nova-pro-v1:0", "amazon"),
            ("plainname", "unknown"),
            (
                "arn:aws:bedrock:us-east-1:123456789012:"
                "inference-profile/us.xai.grok-4.7",
                "xai",
            ),
            (
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
                "amazon",
            ),
            (
                "arn:aws:bedrock:us-east-1:123456789012:"
                "application-inference-profile/abc123",
                "unknown",
            ),
        ],
    )
    def test_infer_provider(self, model_id: str, expected: str) -> None:
        assert infer_provider(model_id) == expected


class TestDefaultModels:
    def test_default_models_contain_new_models_and_no_anthropic(self) -> None:
        ids = [m["model_id"] for m in DEFAULT_MODELS]
        assert ids == [
            NOVA,
            "global.xai.grok-4.7",
            "global.zai.glm-5.3",
            "global.moonshotai.kimi-k3.1",
        ]
        assert sum(m["is_default"] for m in DEFAULT_MODELS) == 1


class TestAddModel:
    async def test_add_model_infers_provider(self, service, repo) -> None:
        model = await service.add_model(" global.zai.glm-5.3 ", " GLM 5.3 ")
        assert model == ModelConfig("global.zai.glm-5.3", "GLM 5.3", "zai", False)
        assert _stored_models(repo)[-1]["model_id"] == "global.zai.glm-5.3"

    async def test_add_duplicate_rejected(self, service) -> None:
        with pytest.raises(ValueError, match="already exists"):
            await service.add_model(GROK, "Dup")

    @pytest.mark.parametrize("bad_id", ["", "   ", "has space", "x;rm", "a" * 257])
    async def test_add_invalid_id_rejected(self, service, bad_id: str) -> None:
        with pytest.raises(ValueError):
            await service.add_model(bad_id, "Name")

    async def test_add_empty_display_name_rejected(self, service) -> None:
        with pytest.raises(ValueError, match="Display name"):
            await service.add_model("global.zai.glm-5.3", "  ")

    async def test_add_as_default_moves_default(self, service, repo) -> None:
        await service.add_model("global.zai.glm-5.3", "GLM 5.3", is_default=True)
        assert _defaults(repo) == ["global.zai.glm-5.3"]
        settings = await service.get_default_settings()
        assert settings["default_model_id"] == "global.zai.glm-5.3"


class TestUpdateModel:
    async def test_update_display_name(self, service, repo) -> None:
        model = await service.update_model(GROK, display_name="Grok")
        assert model is not None and model.display_name == "Grok"
        assert _stored_models(repo)[1]["display_name"] == "Grok"

    async def test_update_missing_returns_none(self, service) -> None:
        assert await service.update_model("nope", display_name="x") is None

    async def test_set_default(self, service, repo) -> None:
        await service.update_model(GROK, is_default=True)
        assert _defaults(repo) == [GROK]
        # Only the model list is written; DEFAULT_SETTINGS derives from it.
        assert repo.versioned_writes == 1
        settings = await service.get_default_settings()
        assert settings["default_model_id"] == GROK

    async def test_empty_provider_is_reinferred(self, service, repo) -> None:
        repo.items[ConfigKey.AVAILABLE_MODELS.value]["config_value"]["models"][1][
            "provider"
        ] = "custom"
        model = await service.update_model(GROK, provider="")
        assert model is not None and model.provider == "xai"

    async def test_none_provider_keeps_current(self, service, repo) -> None:
        model = await service.update_model(GROK, display_name="G")
        assert model is not None and model.provider == "xai"

    async def test_unset_current_default_rejected(self, service) -> None:
        with pytest.raises(ValueError, match="Cannot unset the default"):
            await service.update_model(NOVA, is_default=False)

    async def test_unset_non_default_is_noop(self, service, repo) -> None:
        await service.update_model(GROK, is_default=False)
        assert _defaults(repo) == [NOVA]


class TestDeleteModel:
    async def test_delete_model(self, service, repo) -> None:
        assert await service.delete_model(GROK) is True
        assert [m["model_id"] for m in _stored_models(repo)] == [NOVA]

    async def test_delete_missing_returns_false(self, service) -> None:
        assert await service.delete_model("nope") is False

    async def test_delete_default_rejected(self, service) -> None:
        with pytest.raises(ValueError, match="default model"):
            await service.delete_model(NOVA)

    async def test_delete_last_model_rejected(self) -> None:
        repo = FakeConfigRepository(
            {
                ConfigKey.AVAILABLE_MODELS.value: _models_item(
                    [{"model_id": GROK, "display_name": "Grok",
                      "provider": "xai", "is_default": False}]
                )
            }
        )
        with pytest.raises(ValueError, match="last model"):
            await GlobalConfigService(repository=repo).delete_model(GROK)


class TestConcurrency:
    async def test_writes_bump_version(self, service, repo) -> None:
        await service.add_model("global.zai.glm-5.3", "GLM 5.3")
        await service.delete_model(GROK)
        assert repo.items[ConfigKey.AVAILABLE_MODELS.value]["version"] == 2

    async def test_lost_race_is_retried_on_fresh_list(self, service, repo) -> None:
        """A delete racing an add must not resurrect the deleted model."""
        real_put = repo.put_global_config_versioned
        raced = False

        async def put_after_concurrent_delete(*args: Any, **kwargs: Any) -> Any:
            nonlocal raced
            if not raced:
                raced = True
                # Another admin deletes GROK between our read and our write.
                other = GlobalConfigService(repository=repo)
                repo.put_global_config_versioned = real_put
                await other.delete_model(GROK)
                repo.put_global_config_versioned = put_after_concurrent_delete
            return await real_put(*args, **kwargs)

        repo.put_global_config_versioned = put_after_concurrent_delete
        await service.add_model("global.zai.glm-5.3", "GLM 5.3")

        ids = [m["model_id"] for m in _stored_models(repo)]
        assert ids == [NOVA, "global.zai.glm-5.3"]

    async def test_retry_revalidates(self, service, repo) -> None:
        """If a concurrent writer adds the same ID, the retry reports it."""
        real_put = repo.put_global_config_versioned

        async def put_after_concurrent_add(*args: Any, **kwargs: Any) -> Any:
            repo.put_global_config_versioned = real_put
            await GlobalConfigService(repository=repo).add_model(
                "global.zai.glm-5.3", "Other"
            )
            return await real_put(*args, **kwargs)

        repo.put_global_config_versioned = put_after_concurrent_add
        with pytest.raises(ValueError, match="already exists"):
            await service.add_model("global.zai.glm-5.3", "GLM 5.3")

    async def test_gives_up_after_repeated_conflicts(self, service, repo) -> None:
        repo.put_global_config_versioned = AsyncMock(
            side_effect=VersionConflictError("AVAILABLE_MODELS")
        )
        with pytest.raises(ModelListConflictError):
            await service.add_model("global.zai.glm-5.3", "GLM 5.3")
        assert repo.put_global_config_versioned.await_count == 3

    async def test_generic_update_config_is_versioned(self, service, repo) -> None:
        await service.update_config(
            ConfigKey.AVAILABLE_MODELS.value,
            {"models": [{"model_id": GROK, "display_name": "Grok",
                         "provider": "xai", "is_default": True}]},
        )
        assert repo.items[ConfigKey.AVAILABLE_MODELS.value]["version"] == 1
        assert _defaults(repo) == [GROK]


class FakeUserSettingsRepository:
    def __init__(self, items: Dict[str, Dict[str, Any]]) -> None:
        self.items = items

    async def get_user_settings(self, user_id: str) -> Optional[Dict[str, Any]]:
        item = self.items.get(user_id)
        return dict(item) if item else None

    async def create_user_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        self.items[data["user_id"]] = dict(data)
        return dict(data)

    async def update_user_settings(self, user_id: str, **updates: Any) -> Any:
        self.items[user_id].update(updates)
        return dict(self.items[user_id])


def _user_row(model_id: str, **extra: Any) -> Dict[str, Any]:
    return {"user_id": "u", "default_model_id": model_id, **extra}


class TestUsersFollowSystemDefault:
    @pytest.fixture
    def make(self, service):
        def _make(rows: Dict[str, Dict[str, Any]]):
            repo = FakeUserSettingsRepository(rows)
            return repo, UserSettingsService(repo, service)
        return _make

    async def test_new_user_follows_default_change(self, service, make) -> None:
        repo, users = make({})
        assert (await users.get_user_settings("u")).default_model_id == NOVA
        assert repo.items["u"]["model_explicit"] is False

        await service.update_model(GROK, is_default=True)
        assert (await users.get_user_settings("u")).default_model_id == GROK

    async def test_explicit_choice_is_kept(self, service, make) -> None:
        repo, users = make({})
        await users.update_user_settings("u", default_model_id=NOVA)
        assert repo.items["u"]["model_explicit"] is True

        await service.update_model(GROK, is_default=True)
        assert (await users.get_user_settings("u")).default_model_id == NOVA

    async def test_legacy_row_with_seeded_default_follows(
        self, service, make
    ) -> None:
        _, users = make({"u": _user_row(NOVA)})
        await service.update_model(GROK, is_default=True)
        assert (await users.get_user_settings("u")).default_model_id == GROK

    async def test_legacy_row_with_other_model_is_explicit(
        self, service, make
    ) -> None:
        _, users = make({"u": _user_row(GROK)})
        await service.add_model("global.zai.glm-5.3", "GLM", is_default=True)
        assert (await users.get_user_settings("u")).default_model_id == GROK

    def test_directly_built_settings_are_explicit(self) -> None:
        assert UserSettings(user_id="u", default_model_id=GROK).model_explicit


# =============================================================================
# Resolver tests
# =============================================================================

def _info(service: Any) -> MagicMock:
    context = MagicMock()
    context.global_config_service = service
    info = MagicMock()
    info.context = {"resolver_context": context}
    return info


def _as(role: UserRole):
    """Patch token verification to return a user with the given role."""
    user = UserModel(username="u", password_hash="h", role=role, status=UserStatus.ACTIVE)
    return patch(
        "src.graphql.config_resolvers.verify_and_get_user",
        AsyncMock(return_value=user),
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    return AsyncMock()


class TestModelResolvers:
    async def test_create_as_admin(self, mock_service) -> None:
        mock_service.add_model.return_value = ModelConfig(GROK, "Grok 4.7", "xai")
        with _as(UserRole.ADMIN):
            result = await resolve_create_config_model(
                _info(mock_service), GROK, "Grok 4.7"
            )
        assert result.model_id == GROK and result.provider == "xai"
        mock_service.add_model.assert_awaited_once_with(GROK, "Grok 4.7", None, False)

    async def test_value_error_becomes_validation_error(self, mock_service) -> None:
        mock_service.delete_model.side_effect = ValueError("Cannot delete")
        with _as(UserRole.ADMIN):
            with pytest.raises(ValidationError, match="Cannot delete"):
                await resolve_delete_config_model(
                    _info(mock_service), NOVA
                )

    async def test_update_missing_returns_none(self, mock_service) -> None:
        mock_service.update_model.return_value = None
        with _as(UserRole.ADMIN):
            assert await resolve_update_config_model(
                _info(mock_service), "nope", display_name="x"
            ) is None

    @pytest.mark.parametrize(
        "call",
        [
            lambda i: resolve_create_config_model(i, GROK, "Grok"),
            lambda i: resolve_update_config_model(i, GROK, display_name="x"),
            lambda i: resolve_delete_config_model(i, GROK),
        ],
    )
    async def test_regular_user_rejected(self, mock_service, call) -> None:
        with _as(UserRole.USER):
            with pytest.raises(AuthPermissionError, match="Admin access required"):
                await call(_info(mock_service))
        assert not mock_service.method_calls

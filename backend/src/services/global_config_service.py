"""
Global configuration service for managing system-wide settings.

This service provides:
- Access to global configuration values
- Available models management
- Default settings retrieval
- Model validation
"""
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from src.models.config import (
    ConfigErrorCode,
    ConfigKey,
    GlobalConfig,
    ModelConfig,
    READONLY_CONFIG_KEYS,
)
from src.storage.dynamodb_repository import (
    DynamoDBRepository,
    VersionConflictError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Model seeded as the first default; also the last-resort fallback.
FALLBACK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
# How often a model list edit is retried after losing a concurrent write.
_MAX_SAVE_ATTEMPTS = 3


class ModelListConflictError(ValueError):
    """Raised when the model list keeps changing under a concurrent edit."""

# Built-in model list used to seed AVAILABLE_MODELS and as a fallback.
DEFAULT_MODELS: List[Dict[str, Any]] = [
    {
        "model_id": "global.amazon.nova-2-lite-v1:0",
        "display_name": "Nova 2 Lite",
        "provider": "amazon",
        "is_default": True,
    },
    {
        "model_id": "global.xai.grok-4.7",
        "display_name": "Grok 4.7",
        "provider": "xai",
        "is_default": False,
    },
    {
        "model_id": "global.zai.glm-5.3",
        "display_name": "GLM 5.3",
        "provider": "zai",
        "is_default": False,
    },
    {
        "model_id": "global.moonshotai.kimi-k3.1",
        "display_name": "Kimi K3.1",
        "provider": "moonshotai",
        "is_default": False,
    },
]

# Bedrock model IDs, inference profile IDs and ARNs use only these characters.
_MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:/-]+$")
_MAX_MODEL_ID_LENGTH = 256
_MAX_DISPLAY_NAME_LENGTH = 100
_MAX_PROVIDER_LENGTH = 50
# Cross-region inference profile prefixes (e.g. "global.xai.grok-4.7").
_REGION_PREFIXES = {"global", "us", "eu", "apac", "jp", "au", "ca", "us-gov"}


def infer_provider(model_id: str) -> str:
    """Derive the provider from a Bedrock model ID (e.g. "global.xai.x" -> "xai").

    For ARNs the resource ID after the last "/" is used, so
    "arn:...:inference-profile/us.xai.grok-4.7" -> "xai".
    """
    if model_id.startswith("arn:"):
        model_id = model_id.rsplit("/", 1)[-1]
    parts = model_id.split(".")
    if len(parts) > 2 and parts[0] in _REGION_PREFIXES:
        return parts[1]
    if len(parts) > 1:
        return parts[0]
    return "unknown"


def pick_default_model_id(models: List[ModelConfig]) -> str:
    """Return the flagged default model, else the first model, else the fallback."""
    for model in models:
        if model.is_default:
            return model.model_id
    if models:
        return models[0].model_id
    return FALLBACK_MODEL_ID


class GlobalConfigService:
    """
    Service for managing global system configuration.
    
    This service handles:
    - Retrieving global configuration values
    - Managing available translation models
    - Providing default user settings
    - Validating model IDs
    """
    
    def __init__(
        self,
        repository: DynamoDBRepository,
        logger_instance: Optional[logging.Logger] = None
    ):
        """
        Initialize the global config service.
        
        Args:
            repository: DynamoDB repository instance.
            logger_instance: Optional logger instance.
        """
        self.repository = repository
        self._logger = logger_instance or logger
    
    async def get_config(self, config_key: str) -> Optional[GlobalConfig]:
        """
        Get a global configuration by key.
        
        Args:
            config_key: Configuration key.
            
        Returns:
            GlobalConfig if found, None otherwise.
        """
        data = await self.repository.get_global_config(config_key)
        if data:
            return GlobalConfig.from_dict(data)
        return None
    
    async def get_available_models(self) -> List[ModelConfig]:
        """
        Get the list of available translation models.
        
        Returns:
            List of ModelConfig objects.
        """
        models, _ = await self._read_models()
        return models
    
    async def get_default_settings(self) -> Dict[str, Any]:
        """
        Get the default user settings.

        ``default_model_id`` always comes from the model list (the model
        flagged ``is_default``), which is the single source of truth.

        Returns:
            Dictionary of default settings.
        """
        config = await self.get_config(ConfigKey.DEFAULT_SETTINGS.value)

        if not config or not config.config_value:
            self._logger.warning("No default settings configured, returning defaults")
            settings = self._get_default_settings_fallback()
        else:
            settings = dict(config.config_value)

        settings["default_model_id"] = await self.get_default_model_id()
        return settings
    
    async def is_model_valid(self, model_id: str) -> bool:
        """
        Check if a model ID is valid (exists in available models).
        
        Args:
            model_id: Model ID to validate.
            
        Returns:
            True if valid, False otherwise.
        """
        models = await self.get_available_models()
        return any(m.model_id == model_id for m in models)
    
    async def get_default_model_id(self) -> str:
        """
        Get the default model ID.
        
        Returns:
            Default model ID.
        """
        return pick_default_model_id(await self.get_available_models())
    
    async def update_config(
        self,
        config_key: str,
        config_value: Dict[str, Any],
        description: Optional[str] = None
    ) -> GlobalConfig:
        """
        Update a global configuration.
        
        Args:
            config_key: Configuration key.
            config_value: New configuration value.
            description: Optional description.
            
        Returns:
            Updated GlobalConfig.
            
        Raises:
            ValueError: If config key is read-only.
        """
        if config_key in READONLY_CONFIG_KEYS:
            raise ValueError(
                f"Configuration '{config_key}' is read-only and cannot be modified via API"
            )
        
        # Validate specific config types
        if config_key == ConfigKey.AVAILABLE_MODELS.value:
            self._validate_models_config(config_value)
            # Go through the versioned write so concurrent model edits
            # are not silently overwritten.
            new_models = [ModelConfig.from_dict(m) for m in config_value["models"]]
            await self._mutate_models(lambda _models: (new_models, None))
            if description is not None:
                await self.repository.update_global_config(
                    config_key, description=description
                )
            return await self.get_config(config_key)
        elif config_key == ConfigKey.DEFAULT_SETTINGS.value:
            self._validate_default_settings(config_value)
        
        updates = {"config_value": config_value}
        if description is not None:
            updates["description"] = description
        
        # Check if config exists
        existing = await self.get_config(config_key)
        
        if existing:
            data = await self.repository.update_global_config(config_key, **updates)
        else:
            data = await self.repository.create_global_config({
                "config_key": config_key,
                "config_value": config_value,
                "description": description or "",
            })
        
        return GlobalConfig.from_dict(data)
    
    async def create_config(
        self,
        config_key: str,
        config_value: Dict[str, Any],
        description: str = "",
    ) -> GlobalConfig:
        """
        Create a new global configuration.

        Args:
            config_key: Configuration key.
            config_value: Configuration value.
            description: Configuration description.

        Returns:
            Created GlobalConfig.
        """
        data = await self.repository.create_global_config({
            "config_key": config_key,
            "config_value": config_value,
            "description": description,
        })

        return GlobalConfig.from_dict(data)
    
    async def delete_config(self, config_key: str) -> bool:
        """
        Delete a global configuration.
        
        Args:
            config_key: Configuration key.
            
        Returns:
            True if deleted, False if not found.
            
        Raises:
            ValueError: If config key is read-only.
        """
        if config_key in READONLY_CONFIG_KEYS:
            raise ValueError(
                f"Configuration '{config_key}' is read-only and cannot be deleted"
            )
        
        return await self.repository.delete_global_config(config_key)
    
    # =========================================================================
    # Model list management (admin)
    # =========================================================================

    async def add_model(
        self,
        model_id: str,
        display_name: str,
        provider: Optional[str] = None,
        is_default: bool = False,
    ) -> ModelConfig:
        """
        Add a model to AVAILABLE_MODELS.

        Args:
            model_id: Bedrock model ID or inference profile ID.
            display_name: Name shown in the UI.
            provider: Provider name; inferred from model_id when empty.
            is_default: Make this the system default model.

        Returns:
            The created ModelConfig.

        Raises:
            ValueError: If input is invalid or the model ID already exists.
            ModelListConflictError: If concurrent edits keep conflicting.
        """
        model_id = self._clean_model_id(model_id)
        display_name = self._clean_display_name(display_name)
        provider = self._clean_provider(provider, model_id)
        new_model = ModelConfig(
            model_id=model_id,
            display_name=display_name,
            provider=provider,
            is_default=is_default,
        )

        def mutate(
            models: List[ModelConfig],
        ) -> Tuple[List[ModelConfig], ModelConfig]:
            if any(m.model_id == model_id for m in models):
                raise ValueError(f"Model '{model_id}' already exists")
            models = [*models, new_model]
            if is_default:
                models = self._with_single_default(models, model_id)
            return models, new_model

        result = await self._mutate_models(mutate)
        self._logger.info(f"Added model {model_id}")
        return result

    async def update_model(
        self,
        model_id: str,
        display_name: Optional[str] = None,
        provider: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> Optional[ModelConfig]:
        """
        Update a model in AVAILABLE_MODELS. The model ID itself is immutable.

        Args:
            model_id: ID of the model to update.
            display_name: New display name (optional).
            provider: New provider (optional). An empty string re-infers it
                from the model ID; None keeps the current value.
            is_default: True to make it the default model (optional). Passing
                False for the current default is rejected; set another model
                as default instead.

        Returns:
            The updated ModelConfig, or None if the model does not exist.

        Raises:
            ValueError: If input is invalid.
            ModelListConflictError: If concurrent edits keep conflicting.
        """
        if display_name is not None:
            display_name = self._clean_display_name(display_name)

        def mutate(
            models: List[ModelConfig],
        ) -> Tuple[Optional[List[ModelConfig]], Optional[ModelConfig]]:
            current = next((m for m in models if m.model_id == model_id), None)
            if current is None:
                return None, None
            if is_default is False and current.is_default:
                raise ValueError(
                    "Cannot unset the default model; "
                    "set another model as default instead"
                )
            updated = ModelConfig(
                model_id=current.model_id,
                display_name=display_name or current.display_name,
                provider=(
                    self._clean_provider(provider, current.model_id)
                    if provider is not None
                    else current.provider
                ),
                is_default=current.is_default or bool(is_default),
            )
            models = [updated if m.model_id == model_id else m for m in models]
            if updated.is_default and not current.is_default:
                models = self._with_single_default(models, model_id)
            return models, updated

        result = await self._mutate_models(mutate)
        if result is not None:
            self._logger.info(f"Updated model {model_id}")
        return result

    async def delete_model(self, model_id: str) -> bool:
        """
        Delete a model from AVAILABLE_MODELS.

        Args:
            model_id: ID of the model to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            ValueError: If the model is the default or the last model.
            ModelListConflictError: If concurrent edits keep conflicting.
        """

        def mutate(
            models: List[ModelConfig],
        ) -> Tuple[Optional[List[ModelConfig]], bool]:
            target = next((m for m in models if m.model_id == model_id), None)
            if target is None:
                return None, False
            if len(models) == 1:
                raise ValueError("Cannot delete the last model")
            if target.is_default:
                raise ValueError(
                    "Cannot delete the default model; "
                    "set another model as default first"
                )
            return [m for m in models if m.model_id != model_id], True

        deleted = await self._mutate_models(mutate)
        if deleted:
            self._logger.info(f"Deleted model {model_id}")
        return deleted

    async def _read_models(self) -> Tuple[List[ModelConfig], Optional[int]]:
        """Read the model list and its optimistic-locking version."""
        item = await self.repository.get_global_config(
            ConfigKey.AVAILABLE_MODELS.value
        )
        version = item.get("version") if item else None
        version = int(version) if version is not None else None
        models_data = ((item or {}).get("config_value") or {}).get("models")
        if not models_data:
            self._logger.warning("No available models configured, returning defaults")
            return self._get_default_models(), version
        return [ModelConfig.from_dict(m) for m in models_data], version

    async def _mutate_models(
        self,
        mutate: Callable[[List[ModelConfig]], Tuple[Optional[List[ModelConfig]], T]],
    ) -> T:
        """
        Apply a read-modify-write to AVAILABLE_MODELS with optimistic locking.

        ``mutate`` receives the current list and returns ``(new_list, result)``;
        a ``new_list`` of None means nothing to write. It is re-run on the
        fresh list if another writer got in first, so its checks (duplicates,
        default model, ...) always see the latest state.

        Raises:
            ModelListConflictError: If every attempt lost a concurrent write.
        """
        for attempt in range(1, _MAX_SAVE_ATTEMPTS + 1):
            models, version = await self._read_models()
            new_models, result = mutate(models)
            if new_models is None:
                return result
            try:
                await self.repository.put_global_config_versioned(
                    ConfigKey.AVAILABLE_MODELS.value,
                    {"models": [m.to_dict() for m in new_models]},
                    expected_version=version,
                    description="Available translation models",
                )
                return result
            except VersionConflictError:
                self._logger.info(
                    f"Model list changed concurrently (attempt {attempt}), retrying"
                )
        raise ModelListConflictError(
            "The model list was modified by someone else; please retry"
        )

    @staticmethod
    def _with_single_default(
        models: List[ModelConfig], default_id: str
    ) -> List[ModelConfig]:
        """Return models with only default_id flagged as default."""
        return [
            ModelConfig(
                model_id=m.model_id,
                display_name=m.display_name,
                provider=m.provider,
                is_default=m.model_id == default_id,
            )
            for m in models
        ]

    @staticmethod
    def _clean_model_id(model_id: str) -> str:
        model_id = (model_id or "").strip()
        if not model_id:
            raise ValueError("Model ID is required")
        if len(model_id) > _MAX_MODEL_ID_LENGTH:
            raise ValueError(
                f"Model ID must be at most {_MAX_MODEL_ID_LENGTH} characters"
            )
        if not _MODEL_ID_PATTERN.match(model_id):
            raise ValueError(
                "Model ID may only contain letters, digits and . _ : / -"
            )
        return model_id

    @staticmethod
    def _clean_display_name(display_name: str) -> str:
        display_name = (display_name or "").strip()
        if not display_name:
            raise ValueError("Display name is required")
        if len(display_name) > _MAX_DISPLAY_NAME_LENGTH:
            raise ValueError(
                f"Display name must be at most {_MAX_DISPLAY_NAME_LENGTH} characters"
            )
        return display_name

    @staticmethod
    def _clean_provider(provider: Optional[str], model_id: str) -> str:
        provider = (provider or "").strip() or infer_provider(model_id)
        if len(provider) > _MAX_PROVIDER_LENGTH:
            raise ValueError(
                f"Provider must be at most {_MAX_PROVIDER_LENGTH} characters"
            )
        return provider

    def _validate_models_config(self, config_value: Dict[str, Any]) -> None:
        """Validate AVAILABLE_MODELS configuration."""
        models = config_value.get("models", [])
        
        if not models:
            raise ValueError("AVAILABLE_MODELS must contain at least one model")
        
        for model in models:
            if not model.get("model_id"):
                raise ValueError("Each model must have a model_id")
            if not model.get("display_name"):
                raise ValueError("Each model must have a display_name")
    
    def _validate_default_settings(self, config_value: Dict[str, Any]) -> None:
        """Validate DEFAULT_SETTINGS configuration."""
        required_fields = [
            "default_model_id",
            "ui_language",
            "translation_batch_size",
            "max_concurrent_tasks"
        ]
        
        for field in required_fields:
            if field not in config_value:
                raise ValueError(f"DEFAULT_SETTINGS must contain '{field}'")
    
    def _get_default_models(self) -> List[ModelConfig]:
        """Get default models when none are configured."""
        return [ModelConfig.from_dict(m) for m in DEFAULT_MODELS]
    
    def _get_default_settings_fallback(self) -> Dict[str, Any]:
        """Get default settings when none are configured."""
        return {
            "default_model_id": FALLBACK_MODEL_ID,
            "ui_language": "zh",
            "translation_batch_size": 10,
            "max_concurrent_tasks": 3,
        }

    async def ensure_defaults_exist(self) -> None:
        """
        Seed default configuration entries if they don't exist.

        This method is idempotent - safe to call multiple times.
        Creates defaults for:
        - AVAILABLE_MODELS
        - DEFAULT_LANGUAGE_PAIRS
        - DEFAULT_SETTINGS
        """
        from datetime import datetime, timezone

        defaults = {
            ConfigKey.AVAILABLE_MODELS.value: {
                "models": [dict(m) for m in DEFAULT_MODELS]
            },
            ConfigKey.DEFAULT_LANGUAGE_PAIRS.value: {
                "language_pairs": [
                    {"source_language": "zh", "target_language": "vi", "display_name": "Chinese → Vietnamese"}
                ]
            },
            # default_model_id here is informational only; the effective
            # default is the model flagged is_default in AVAILABLE_MODELS.
            ConfigKey.DEFAULT_SETTINGS.value: {
                "default_model_id": FALLBACK_MODEL_ID,
                "ui_language": "vi",
                "translation_batch_size": 10,
                "max_concurrent_tasks": 5
            }
        }

        now = datetime.now(timezone.utc).isoformat()

        for config_key, config_value in defaults.items():
            existing = await self.repository.get_global_config(config_key)
            if not existing:
                await self.repository.create_global_config({
                    "config_key": config_key,
                    "config_value": config_value,
                    "description": f"Default {config_key}",
                    "created_at": now,
                    "updated_at": now,
                })
                self._logger.info(f"Created default config: {config_key}")

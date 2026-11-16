"""
Tests for user settings integration with job execution.

Verifies that user-configured translation_batch_size and max_concurrent_tasks
are applied when creating translation jobs.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch

from src.graphql.resolvers import (
    ResolverContext,
    resolve_create_translation_job,
)
from src.models.job import TranslationJob, JobStatus, LanguagePair
from src.models.config import UserSettings
from src.services.user_settings_service import UserSettingsService


@pytest.fixture
def mock_auth_service():
    service = Mock()
    service.get_username_from_token = Mock(return_value="testuser")
    return service


@pytest.fixture
def mock_job_manager():
    manager = Mock()
    mock_job = TranslationJob(
        status=JobStatus.PENDING,
        files_total=1,
        language_pair=LanguagePair(
            id="zh-vi",
            source_language="Chinese",
            target_language="Vietnamese",
            source_language_code="zh",
            target_language_code="vi",
        ),
        file_ids=["file-1"],
    )
    manager.create_job = AsyncMock(return_value=mock_job)
    manager.job_store = Mock()
    manager.job_store.set_user_context = Mock()
    return manager


@pytest.fixture
def mock_s3_file_storage():
    storage = Mock()
    storage.get_upload = AsyncMock(
        return_value=(b"file content", {"original_filename": "test.xlsx"})
    )
    return storage


@pytest.fixture
def mock_language_pair_service():
    from src.models.config import LanguagePair as ConfigLanguagePair

    service = AsyncMock()
    mock_lp = ConfigLanguagePair(
        id="lp-uuid-123",
        user_id="__global__",
        source_language="zh",
        target_language="vi",
        display_name="Chinese->Vietnamese",
    )
    service.get_language_pair = AsyncMock(return_value=mock_lp)
    return service


@pytest.fixture
def mock_global_config_service():
    service = AsyncMock()
    service.is_model_valid = AsyncMock(return_value=True)
    service.get_default_model_id = AsyncMock(
        return_value="global.amazon.nova-2-lite-v1:0"
    )
    return service


@pytest.fixture
def mock_translation_orchestrator():
    orchestrator = Mock()
    orchestrator.process_job = AsyncMock()
    orchestrator.excel_processor = Mock()
    orchestrator.executor = Mock()
    orchestrator.executor.max_file_concurrency = 5
    orchestrator.thesaurus_service = Mock()
    orchestrator.s3_file_storage = Mock()
    orchestrator.translation_service = Mock()
    orchestrator.translation_service.batch_size = 10
    orchestrator.translation_service.max_batch_concurrency = 3
    return orchestrator


def _make_info(resolver_context):
    """Create a mock Strawberry Info object."""
    from strawberry.types import Info

    info = Mock(spec=Info)
    mock_request = Mock()
    mock_request.headers = {"Authorization": "Bearer mock-jwt-token"}
    info.context = {
        "request": mock_request,
        "resolver_context": resolver_context,
    }
    return info


PATCH_ORCHESTRATOR = "src.services.translation_orchestrator.TranslationOrchestrator"
PATCH_TRANSLATION_SERVICE = "src.services.translation_service.TranslationService"
PATCH_CONCURRENT_EXECUTOR = "src.services.concurrent_executor.ConcurrentExecutor"


@pytest.mark.asyncio
async def test_job_uses_user_batch_size(
    mock_auth_service,
    mock_job_manager,
    mock_s3_file_storage,
    mock_language_pair_service,
    mock_global_config_service,
    mock_translation_orchestrator,
):
    """Per-job TranslationService uses the user's translation_batch_size."""
    user_batch_size = 30
    mock_user_settings_service = AsyncMock()
    mock_user_settings_service.get_user_settings = AsyncMock(
        return_value=UserSettings(
            user_id="testuser",
            default_model_id="global.amazon.nova-2-lite-v1:0",
            translation_batch_size=user_batch_size,
            max_concurrent_tasks=5,
        )
    )

    context = ResolverContext(
        auth_service=mock_auth_service,
        job_manager=mock_job_manager,
        s3_file_storage=mock_s3_file_storage,
        translation_orchestrator=mock_translation_orchestrator,
        language_pair_service=mock_language_pair_service,
        global_config_service=mock_global_config_service,
        user_settings_service=mock_user_settings_service,
    )
    info = _make_info(context)

    mock_ts_instance = Mock()
    mock_ts_instance.model_id = "global.amazon.nova-2-lite-v1:0"

    with patch(PATCH_ORCHESTRATOR) as MockOrchestrator, \
         patch(PATCH_TRANSLATION_SERVICE, return_value=mock_ts_instance) as MockTS, \
         patch(PATCH_CONCURRENT_EXECUTOR) as MockExecutor, \
         patch("asyncio.create_task"):
        MockOrchestrator.return_value = Mock(process_job=AsyncMock())
        mock_executor_instance = Mock()
        MockExecutor.return_value = mock_executor_instance

        await resolve_create_translation_job(
            info=info,
            file_ids=["file-1"],
            language_pair_id="lp-uuid-123",
            output_mode="append",
        )

        # Verify TranslationService was created with user's batch_size
        MockTS.assert_called_once_with(
            model_id="global.amazon.nova-2-lite-v1:0",
            batch_size=user_batch_size,
            max_batch_concurrency=3,
        )


@pytest.mark.asyncio
async def test_job_uses_user_max_concurrent_tasks(
    mock_auth_service,
    mock_job_manager,
    mock_s3_file_storage,
    mock_language_pair_service,
    mock_global_config_service,
    mock_translation_orchestrator,
):
    """Per-job ConcurrentExecutor uses the user's max_concurrent_tasks."""
    user_max_concurrent = 7
    mock_user_settings_service = AsyncMock()
    mock_user_settings_service.get_user_settings = AsyncMock(
        return_value=UserSettings(
            user_id="testuser",
            default_model_id="global.amazon.nova-2-lite-v1:0",
            translation_batch_size=20,
            max_concurrent_tasks=user_max_concurrent,
        )
    )

    context = ResolverContext(
        auth_service=mock_auth_service,
        job_manager=mock_job_manager,
        s3_file_storage=mock_s3_file_storage,
        translation_orchestrator=mock_translation_orchestrator,
        language_pair_service=mock_language_pair_service,
        global_config_service=mock_global_config_service,
        user_settings_service=mock_user_settings_service,
    )
    info = _make_info(context)

    mock_ts_instance = Mock()

    with patch(PATCH_ORCHESTRATOR) as MockOrchestrator, \
         patch(PATCH_TRANSLATION_SERVICE, return_value=mock_ts_instance), \
         patch(PATCH_CONCURRENT_EXECUTOR) as MockExecutor, \
         patch("asyncio.create_task"):
        MockOrchestrator.return_value = Mock(process_job=AsyncMock())
        mock_executor_instance = Mock()
        MockExecutor.return_value = mock_executor_instance

        await resolve_create_translation_job(
            info=info,
            file_ids=["file-1"],
            language_pair_id="lp-uuid-123",
            output_mode="append",
        )

        # Verify ConcurrentExecutor was created with user's max_concurrent_tasks
        MockExecutor.assert_called_once_with(
            max_file_concurrency=user_max_concurrent
        )

        # Verify the per-job executor was passed to the orchestrator
        call_kwargs = MockOrchestrator.call_args[1]
        assert call_kwargs["concurrent_executor"] is mock_executor_instance


@pytest.mark.asyncio
async def test_job_falls_back_to_shared_executor_when_no_settings(
    mock_auth_service,
    mock_job_manager,
    mock_s3_file_storage,
    mock_language_pair_service,
    mock_translation_orchestrator,
):
    """When user_settings_service is None, uses the shared executor."""
    context = ResolverContext(
        auth_service=mock_auth_service,
        job_manager=mock_job_manager,
        s3_file_storage=mock_s3_file_storage,
        translation_orchestrator=mock_translation_orchestrator,
        language_pair_service=mock_language_pair_service,
        user_settings_service=None,
        global_config_service=None,
    )
    info = _make_info(context)

    with patch(PATCH_ORCHESTRATOR) as MockOrchestrator, \
         patch(PATCH_TRANSLATION_SERVICE) as MockTS, \
         patch(PATCH_CONCURRENT_EXECUTOR) as MockExecutor, \
         patch("asyncio.create_task"):
        MockOrchestrator.return_value = Mock(process_job=AsyncMock())

        await resolve_create_translation_job(
            info=info,
            file_ids=["file-1"],
            language_pair_id="lp-uuid-123",
            output_mode="append",
        )

        # ConcurrentExecutor should NOT have been constructed
        MockExecutor.assert_not_called()

        # The shared executor should be used
        call_kwargs = MockOrchestrator.call_args[1]
        assert (
            call_kwargs["concurrent_executor"]
            is mock_translation_orchestrator.executor
        )


@pytest.mark.asyncio
async def test_batch_size_validation_rejects_above_200():
    """User settings validation rejects batch_size > 200."""
    service = UserSettingsService(
        repository=AsyncMock(),
        global_config_service=AsyncMock(),
    )
    # Mock get_user_settings to return existing settings
    service.get_user_settings = AsyncMock(
        return_value=UserSettings(
            user_id="testuser",
            default_model_id="global.amazon.nova-2-lite-v1:0",
        )
    )

    with pytest.raises(ValueError, match="between 1 and 200"):
        await service.update_user_settings(
            user_id="testuser",
            translation_batch_size=201,
        )


@pytest.mark.asyncio
async def test_batch_size_validation_accepts_up_to_200():
    """User settings validation accepts batch_size up to 200."""
    mock_repo = AsyncMock()
    mock_repo.update_user_settings = AsyncMock(
        return_value={
            "user_id": "testuser",
            "default_model_id": "global.amazon.nova-2-lite-v1:0",
            "ui_language": "zh",
            "translation_batch_size": 200,
            "max_concurrent_tasks": 3,
        }
    )

    service = UserSettingsService(
        repository=mock_repo,
        global_config_service=AsyncMock(),
    )
    # Mock get_user_settings to return existing settings
    service.get_user_settings = AsyncMock(
        return_value=UserSettings(
            user_id="testuser",
            default_model_id="global.amazon.nova-2-lite-v1:0",
        )
    )

    result = await service.update_user_settings(
        user_id="testuser",
        translation_batch_size=200,
    )

    assert result.translation_batch_size == 200
    mock_repo.update_user_settings.assert_called_once_with(
        "testuser", translation_batch_size=200
    )


@pytest.mark.asyncio
async def test_batch_size_validation_accepts_150():
    """User settings validation accepts batch_size = 150."""
    mock_repo = AsyncMock()
    mock_repo.update_user_settings = AsyncMock(
        return_value={
            "user_id": "testuser",
            "default_model_id": "global.amazon.nova-2-lite-v1:0",
            "ui_language": "zh",
            "translation_batch_size": 150,
            "max_concurrent_tasks": 3,
        }
    )

    service = UserSettingsService(
        repository=mock_repo,
        global_config_service=AsyncMock(),
    )
    service.get_user_settings = AsyncMock(
        return_value=UserSettings(
            user_id="testuser",
            default_model_id="global.amazon.nova-2-lite-v1:0",
        )
    )

    result = await service.update_user_settings(
        user_id="testuser",
        translation_batch_size=150,
    )

    assert result.translation_batch_size == 150

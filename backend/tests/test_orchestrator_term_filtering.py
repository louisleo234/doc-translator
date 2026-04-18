import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock

from src.services.translation_orchestrator import TranslationOrchestrator, FileProcessingResult
from src.services.translation_service import TranslationService, TranslationResult
from src.services.excel_processor import ExcelProcessor
from src.services.concurrent_executor import ConcurrentExecutor
from src.services.document_processor import (
    DocumentProcessorFactory,
    DocumentProcessor,
    TextSegment,
)
from src.models.job import TranslationJob, JobStatus, LanguagePair, DocumentType
from src.models.thesaurus import TermPair


def _tp(source: str, target: str) -> TermPair:
    return TermPair(
        id="x", language_pair_id="zh-vi", catalog_id="c1",
        source_term=source, target_term=target,
    )


@pytest.fixture
def language_pair():
    return LanguagePair(
        id="zh-vi", source_language="Chinese", target_language="Vietnamese",
        source_language_code="zh", target_language_code="vi",
    )


@pytest.fixture
def orchestrator(tmp_path):
    mock_excel = Mock(spec=ExcelProcessor)
    mock_ts = Mock(spec=TranslationService)
    mock_ts.batch_size = 50
    mock_ts.batch_translate_async = AsyncMock(return_value=[])
    mock_ts.filter_relevant_terms = Mock(return_value=[])
    mock_executor = Mock(spec=ConcurrentExecutor)

    mock_processor = Mock(spec=DocumentProcessor)
    mock_processor.supported_extensions = [".txt"]
    mock_processor.document_type = DocumentType.TEXT
    mock_processor.validate_file = AsyncMock(return_value=(True, None))
    mock_processor.extract_text = AsyncMock(return_value=[
        TextSegment(id="seg1", text="升级服务器配置", location="line1", metadata={}),
        TextSegment(id="seg2", text="检查网络连接", location="line2", metadata={}),
    ])
    mock_processor.write_translated = AsyncMock(return_value=True)
    mock_processor.generate_output_filename = Mock(return_value="out_vi.txt")

    mock_factory = Mock(spec=DocumentProcessorFactory)
    mock_factory.get_processor = Mock(return_value=mock_processor)

    orch = TranslationOrchestrator(
        excel_processor=mock_excel,
        translation_service=mock_ts,
        concurrent_executor=mock_executor,
        output_dir=tmp_path,
        processor_factory=mock_factory,
    )
    return orch


class TestOrchestratorTermFiltering:
    async def test_stage1_filters_terms_before_translation(
        self, orchestrator, language_pair, tmp_path
    ):
        """process_file should call filter_relevant_terms with all extracted texts."""
        all_terms = [_tp("服务器", "máy chủ"), _tp("数据库", "cơ sở dữ liệu")]
        filtered = [_tp("服务器", "máy chủ")]
        orchestrator.translation_service.filter_relevant_terms.return_value = filtered
        orchestrator.translation_service.batch_translate_async.return_value = [
            TranslationResult(text="Nâng cấp cấu hình máy chủ"),
            TranslationResult(text="Kiểm tra kết nối mạng"),
        ]

        job = TranslationJob(id="job-1", status=JobStatus.PROCESSING)
        test_file = tmp_path / "test.txt"
        test_file.write_text("dummy")

        await orchestrator.process_file(
            file_path=test_file,
            original_filename="test.txt",
            language_pair=language_pair,
            job=job,
            term_pairs=all_terms,
        )

        # Verify filter was called with all text values
        orchestrator.translation_service.filter_relevant_terms.assert_called_once()
        call_args = orchestrator.translation_service.filter_relevant_terms.call_args
        texts_arg = call_args[0][0]
        assert "升级服务器配置" in texts_arg
        assert "检查网络连接" in texts_arg
        terms_arg = call_args[0][1]
        assert len(terms_arg) == 2  # All terms passed for filtering

        # Verify batch_translate received only filtered terms
        bt_call = orchestrator.translation_service.batch_translate_async.call_args
        assert bt_call[0][2] == filtered  # third positional arg = term_pairs

    async def test_no_filtering_when_no_term_pairs(
        self, orchestrator, language_pair, tmp_path
    ):
        """When term_pairs is None, filter_relevant_terms should not be called."""
        orchestrator.translation_service.batch_translate_async.return_value = [
            TranslationResult(text="t1"),
            TranslationResult(text="t2"),
        ]

        job = TranslationJob(id="job-2", status=JobStatus.PROCESSING)
        test_file = tmp_path / "test.txt"
        test_file.write_text("dummy")

        await orchestrator.process_file(
            file_path=test_file,
            original_filename="test.txt",
            language_pair=language_pair,
            job=job,
            term_pairs=None,
        )

        orchestrator.translation_service.filter_relevant_terms.assert_not_called()

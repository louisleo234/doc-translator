# Two-Stage Term Relevance Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current "load all terms up to 200, inject all into every prompt" approach with a two-stage filtering system that only injects terms whose source text actually appears in the document/batch being translated, reducing token waste and improving translation quality.

**Architecture:** Stage 1 (document-level, once per file) scans all extracted text segments against the full term list to produce a "document-relevant" subset. Stage 2 (batch-level, per API call) further narrows to terms matching the current batch's text. Both stages use Python's `str.__contains__` for substring matching — simple, zero-dependency, and multilingual-safe. The existing `MAX_TERMS_FOR_TRANSLATION = 200` hard cap on DB retrieval is raised to allow loading all terms; the 200-per-prompt cap moves to the batch-level filter output.

**Tech Stack:** Python 3.12, pytest, existing project patterns (dataclass models, async services)

---

### Task 1: Raise `MAX_TERMS_FOR_TRANSLATION` and remove truncation warning

The current hard cap of 200 truncates terms at the DB retrieval stage, potentially discarding terms that are actually used in the document. We raise the cap so all terms are loaded, and move the prompt-size limit to the filtering stage.

**Files:**
- Modify: `backend/src/services/thesaurus_service.py:28-29` (constant) and lines `753-758` (truncation)

- [ ] **Step 1: Write the failing test**

Add a test to `backend/tests/test_translation_service.py` that verifies `get_terms_for_translation` returns more than 200 terms when available.

```python
# In backend/tests/test_thesaurus_get_terms.py (new file)
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.thesaurus_service import ThesaurusService


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.query_term_pairs_by_catalog = AsyncMock()
    return repo


@pytest.fixture
def thesaurus_service(mock_repository):
    return ThesaurusService(repository=mock_repository)


class TestGetTermsForTranslation:
    async def test_returns_all_terms_beyond_old_200_limit(
        self, thesaurus_service, mock_repository
    ):
        """All terms should be returned when catalog has >200 entries."""
        items = [
            {
                "id": f"term-{i}",
                "language_pair_id": "zh-vi",
                "catalog_id": "cat-1",
                "source_term": f"term{i}",
                "target_term": f"translated{i}",
                "updated_at": f"2026-01-01T00:00:{i:02d}+00:00",
            }
            for i in range(300)
        ]
        mock_repository.query_term_pairs_by_catalog.return_value = items

        result = await thesaurus_service.get_terms_for_translation(
            language_pair_id="zh-vi",
            catalog_ids=["cat-1"],
        )

        assert len(result) == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_thesaurus_get_terms.py::TestGetTermsForTranslation::test_returns_all_terms_beyond_old_200_limit -v`
Expected: FAIL — `assert len(result) == 300` fails because current code truncates to 200.

- [ ] **Step 3: Implement the change**

In `backend/src/services/thesaurus_service.py`:

Change line 29:
```python
# Old
MAX_TERMS_FOR_TRANSLATION = 200

# New
MAX_TERMS_FOR_TRANSLATION = 5000
```

Remove the truncation block at lines 753-758. Replace with a soft warning:
```python
        # Soft warning for very large term sets (filtering happens downstream)
        if len(all_terms) > max_terms:
            self._logger.info(
                f"Loaded {len(all_terms)} term pairs (cap: {max_terms})"
            )
            all_terms = all_terms[:max_terms]

        # Convert to TermPair objects
        return [TermPair.from_dict(item) for item in all_terms]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_thesaurus_get_terms.py -v`
Expected: PASS

- [ ] **Step 5: Also add test for deduplication and catalog priority (existing behavior preserved)**

```python
    async def test_deduplication_respects_catalog_priority(
        self, thesaurus_service, mock_repository
    ):
        """First catalog wins when the same source_term appears in multiple catalogs."""
        cat1_items = [
            {
                "id": "t1",
                "language_pair_id": "zh-vi",
                "catalog_id": "cat-1",
                "source_term": "server",
                "target_term": "from-cat-1",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        ]
        cat2_items = [
            {
                "id": "t2",
                "language_pair_id": "zh-vi",
                "catalog_id": "cat-2",
                "source_term": "server",
                "target_term": "from-cat-2",
                "updated_at": "2026-01-02T00:00:00+00:00",
            }
        ]
        mock_repository.query_term_pairs_by_catalog.side_effect = [
            cat1_items, cat2_items
        ]

        result = await thesaurus_service.get_terms_for_translation(
            language_pair_id="zh-vi",
            catalog_ids=["cat-1", "cat-2"],
        )

        assert len(result) == 1
        assert result[0].target_term == "from-cat-1"
```

- [ ] **Step 6: Run all thesaurus tests**

Run: `cd backend && uv run pytest tests/test_thesaurus_get_terms.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/services/thesaurus_service.py backend/tests/test_thesaurus_get_terms.py
git commit -m "feat: raise MAX_TERMS_FOR_TRANSLATION to 5000 for downstream filtering"
```

---

### Task 2: Add `filter_relevant_terms()` to `TranslationService`

This is the core filtering function. It takes a list of text strings and a list of `TermPair` objects, returns only those whose `source_term` appears as a substring in any of the texts. A `max_terms` cap prevents prompt overflow; when exceeded, longer source terms are prioritized (more specific = more important).

**Files:**
- Modify: `backend/src/services/translation_service.py` (add method around line 68, before `_build_system_prompt`)
- Create: `backend/tests/test_term_filtering.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_term_filtering.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from src.services.translation_service import TranslationService
from src.models.thesaurus import TermPair


def _tp(source: str, target: str) -> TermPair:
    """Helper to create a TermPair with minimal fields."""
    return TermPair(
        id="x",
        language_pair_id="zh-vi",
        catalog_id="c1",
        source_term=source,
        target_term=target,
    )


@pytest.fixture
def mock_bedrock_client():
    with patch("boto3.client") as mock_client:
        mock_client.return_value = MagicMock()
        yield


class TestFilterRelevantTerms:
    def test_filters_to_matching_terms_only(self, mock_bedrock_client):
        service = TranslationService()
        terms = [_tp("服务器", "máy chủ"), _tp("数据库", "cơ sở dữ liệu"), _tp("网络", "mạng")]
        texts = ["升级服务器配置", "检查网络连接"]

        result = service.filter_relevant_terms(texts, terms)

        source_terms = {tp.source_term for tp in result}
        assert source_terms == {"服务器", "网络"}

    def test_returns_empty_when_no_match(self, mock_bedrock_client):
        service = TranslationService()
        terms = [_tp("服务器", "máy chủ")]
        texts = ["今天天气不错"]

        result = service.filter_relevant_terms(texts, terms)

        assert result == []

    def test_returns_empty_when_no_terms(self, mock_bedrock_client):
        service = TranslationService()
        result = service.filter_relevant_terms(["some text"], [])
        assert result == []

    def test_returns_empty_when_no_texts(self, mock_bedrock_client):
        service = TranslationService()
        terms = [_tp("服务器", "máy chủ")]
        result = service.filter_relevant_terms([], terms)
        assert result == []

    def test_handles_substring_match_in_chinese(self, mock_bedrock_client):
        """'服务' matches inside '服务器管理', which is desired behavior."""
        service = TranslationService()
        terms = [_tp("服务", "dịch vụ")]
        texts = ["服务器管理"]

        result = service.filter_relevant_terms(texts, terms)

        assert len(result) == 1
        assert result[0].source_term == "服务"

    def test_handles_vietnamese_terms(self, mock_bedrock_client):
        service = TranslationService()
        terms = [_tp("máy chủ", "server"), _tp("mạng", "network")]
        texts = ["cấu hình máy chủ"]

        result = service.filter_relevant_terms(texts, terms)

        assert len(result) == 1
        assert result[0].source_term == "máy chủ"

    def test_respects_max_terms_with_longer_terms_prioritized(self, mock_bedrock_client):
        service = TranslationService()
        terms = [
            _tp("AB", "t1"),
            _tp("ABCD", "t2"),
            _tp("ABCDEF", "t3"),
        ]
        texts = ["xABCDEFx"]  # All three match

        result = service.filter_relevant_terms(texts, terms, max_terms=2)

        assert len(result) == 2
        source_terms = [tp.source_term for tp in result]
        assert source_terms == ["ABCDEF", "ABCD"]

    def test_handles_mixed_language_texts(self, mock_bedrock_client):
        service = TranslationService()
        terms = [_tp("API网关", "API gateway"), _tp("服务器", "server")]
        texts = ["配置API网关参数"]

        result = service.filter_relevant_terms(texts, terms)

        assert len(result) == 1
        assert result[0].source_term == "API网关"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_term_filtering.py -v`
Expected: FAIL — `AttributeError: 'TranslationService' object has no attribute 'filter_relevant_terms'`

- [ ] **Step 3: Implement `filter_relevant_terms`**

In `backend/src/services/translation_service.py`, add this method to `TranslationService` class after line 67 (after `__init__`):

```python
    def filter_relevant_terms(
        self,
        texts: List[str],
        term_pairs: List["TermPair"],
        max_terms: int = 200,
    ) -> List["TermPair"]:
        """Filter term pairs to only those whose source_term appears in the texts."""
        if not texts or not term_pairs:
            return []

        combined_text = "\n".join(texts)
        relevant = [tp for tp in term_pairs if tp.source_term in combined_text]

        if len(relevant) > max_terms:
            relevant.sort(key=lambda tp: len(tp.source_term), reverse=True)
            relevant = relevant[:max_terms]
            self.logger.info(
                f"Filtered terms capped from {len(relevant)} to {max_terms} "
                f"(longest source terms prioritized)"
            )

        return relevant
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_term_filtering.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/translation_service.py backend/tests/test_term_filtering.py
git commit -m "feat: add filter_relevant_terms to TranslationService"
```

---

### Task 3: Integrate Stage 1 filtering in `TranslationOrchestrator.process_file()`

After text segments are extracted from the document, filter the full term list down to document-relevant terms. This replaces passing the full `term_pairs` list to `batch_translate_async`.

**Files:**
- Modify: `backend/src/services/translation_orchestrator.py:457-474`
- Create: `backend/tests/test_orchestrator_term_filtering.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_orchestrator_term_filtering.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call

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
        TextSegment(text="升级服务器配置", metadata={}),
        TextSegment(text="检查网络连接", metadata={}),
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
        assert bt_call[0][2] == filtered  # term_pairs positional arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_orchestrator_term_filtering.py -v`
Expected: FAIL — `filter_relevant_terms` is never called because `process_file` currently passes `term_pairs` directly.

- [ ] **Step 3: Implement Stage 1 integration**

In `backend/src/services/translation_orchestrator.py`, modify `process_file()`. After line 458 (`text_values = [segment.text for segment in segments]`), add the Stage 1 filter:

```python
            # Extract text values for translation
            text_values = [segment.text for segment in segments]

            # Stage 1: filter terms to document-relevant subset
            doc_relevant_terms = term_pairs
            if term_pairs:
                doc_relevant_terms = self.translation_service.filter_relevant_terms(
                    text_values, term_pairs
                )
                self.logger.info(
                    f"Term filtering: {len(term_pairs)} total -> {len(doc_relevant_terms)} relevant to document"
                )
```

Then change every reference to `term_pairs` in the batch loop below (lines 470-474) to `doc_relevant_terms`:

```python
                batch_translations = await self.translation_service.batch_translate_async(
                    batch,
                    language_pair,
                    doc_relevant_terms
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_orchestrator_term_filtering.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/translation_orchestrator.py backend/tests/test_orchestrator_term_filtering.py
git commit -m "feat: integrate Stage 1 document-level term filtering in orchestrator"
```

---

### Task 4: Integrate Stage 2 batch-level filtering in `batch_translate_async()`

For each batch of 50 texts, further narrow the document-relevant terms to only those appearing in the current batch. This minimizes the prompt for each API call.

**Files:**
- Modify: `backend/src/services/translation_service.py:472-493`
- Add tests to: `backend/tests/test_term_filtering.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_term_filtering.py`:

```python
class TestBatchLevelTermFiltering:
    async def test_each_batch_gets_its_own_filtered_terms(self, mock_bedrock_client):
        """When batch_translate_async processes two batches, each should get only relevant terms."""
        service = TranslationService(batch_size=2)

        terms = [_tp("服务器", "máy chủ"), _tp("数据库", "cơ sở dữ liệu")]

        from src.models.job import LanguagePair
        lp = LanguagePair(
            id="zh-vi", source_language="Chinese", target_language="Vietnamese",
            source_language_code="zh", target_language_code="vi",
        )

        # Mock: capture system prompts from each batch call
        captured_prompts = []
        original_build = service._build_system_prompt

        def capturing_build(*args, **kwargs):
            prompt = original_build(*args, **kwargs)
            captured_prompts.append(prompt)
            return prompt

        service._build_system_prompt = capturing_build

        # Mock Bedrock to return valid responses
        service.bedrock_client.converse.side_effect = [
            {
                "output": {"message": {"content": [
                    {"text": '[{"index": 0, "translation": "t1"}, {"index": 1, "translation": "t2"}]'}
                ]}}
            },
            {
                "output": {"message": {"content": [
                    {"text": '[{"index": 0, "translation": "t3"}]'}
                ]}}
            },
        ]

        texts = ["升级服务器", "检查服务器", "备份数据库"]
        await service.batch_translate_async(texts, lp, terms)

        assert len(captured_prompts) == 2
        # Batch 1: "服务器" texts -> only 服务器 term
        assert "服务器" in captured_prompts[0]
        assert "数据库" not in captured_prompts[0]
        # Batch 2: "数据库" text -> only 数据库 term
        assert "数据库" in captured_prompts[1]
        assert "服务器" not in captured_prompts[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_term_filtering.py::TestBatchLevelTermFiltering -v`
Expected: FAIL — both prompts contain both terms because no per-batch filtering exists.

- [ ] **Step 3: Implement Stage 2 in `batch_translate_async`**

In `backend/src/services/translation_service.py`, modify `batch_translate_async()`. Change lines 492-493 from:

```python
            # Build system prompt with batch mode enabled and term pairs
            system_prompt = self._build_system_prompt(language_pair, is_batch=True, term_pairs=term_pairs)
```

to:

```python
            # Stage 2: filter terms to batch-relevant subset
            batch_relevant_terms = self.filter_relevant_terms(
                batch_texts, term_pairs
            ) if term_pairs else None

            # Build system prompt with batch mode enabled and filtered term pairs
            system_prompt = self._build_system_prompt(
                language_pair, is_batch=True, term_pairs=batch_relevant_terms
            )
```

Also apply the same filtering in the fallback path for individual translations (line 524):

Change:
```python
                        batch_results[original_idx] = await self.translate_text_async(text, language_pair, term_pairs)
```

to:
```python
                        fallback_terms = self.filter_relevant_terms(
                            [text], term_pairs
                        ) if term_pairs else None
                        batch_results[original_idx] = await self.translate_text_async(
                            text, language_pair, fallback_terms
                        )
```

And the same in the exception fallback (line 547):

Change:
```python
                    batch_results[original_idx] = await self.translate_text_async(text, language_pair, term_pairs)
```

to:
```python
                    fallback_terms = self.filter_relevant_terms(
                        [text], term_pairs
                    ) if term_pairs else None
                    batch_results[original_idx] = await self.translate_text_async(
                        text, language_pair, fallback_terms
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_term_filtering.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/translation_service.py backend/tests/test_term_filtering.py
git commit -m "feat: integrate Stage 2 batch-level term filtering in batch_translate_async"
```

---

### Task 5: Add logging and run full test suite

Add structured log messages that show the filtering funnel at each stage, and verify no regressions.

**Files:**
- Modify: `backend/src/services/translation_service.py` (logging in `batch_translate_async`)

- [ ] **Step 1: Add batch-level logging**

In `batch_translate_async`, after the Stage 2 filter, add:

```python
            if term_pairs:
                self.logger.debug(
                    f"Batch {i // self.batch_size + 1}: "
                    f"{len(term_pairs)} doc-relevant terms -> "
                    f"{len(batch_relevant_terms) if batch_relevant_terms else 0} batch-relevant"
                )
```

- [ ] **Step 2: Run full test suite**

Run: `cd backend && uv run pytest tests/ -v --tb=short`
Expected: All existing tests PASS. No regressions.

- [ ] **Step 3: Fix any failures**

If any existing tests fail due to the new filtering (e.g., tests that mock `_build_system_prompt` and expect all terms), update them to account for the new behavior.

- [ ] **Step 4: Commit**

```bash
git add backend/src/services/translation_service.py
git commit -m "feat: add debug logging for term filtering funnel"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `backend/src/services/thesaurus_service.py` | Raise `MAX_TERMS_FOR_TRANSLATION` from 200 to 5000 |
| `backend/src/services/translation_service.py` | Add `filter_relevant_terms()` method; apply Stage 2 filtering in `batch_translate_async()` and fallback paths |
| `backend/src/services/translation_orchestrator.py` | Apply Stage 1 filtering in `process_file()` after text extraction |
| `backend/tests/test_thesaurus_get_terms.py` | New: tests for raised limit and deduplication |
| `backend/tests/test_term_filtering.py` | New: tests for `filter_relevant_terms()` and batch-level filtering |
| `backend/tests/test_orchestrator_term_filtering.py` | New: tests for Stage 1 integration in orchestrator |

## Data Flow After Changes

```
User selects catalogs
    ↓
get_terms_for_translation() — loads ALL terms (up to 5000), dedup by catalog priority
    ↓ all_terms (~2000)
process_file() — Stage 1: filter_relevant_terms(all_doc_texts, all_terms)
    ↓ doc_relevant_terms (~50-100)
batch_translate_async() — Stage 2 per batch: filter_relevant_terms(batch_texts, doc_relevant_terms)
    ↓ batch_relevant_terms (~10-30)
_build_system_prompt() — inject only batch-relevant terms into prompt
```

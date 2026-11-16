"""Tests for concurrent batch translation within a single file.

Tests cover:
- Concurrent batch processing with semaphore-limited parallelism
- Result ordering correctness with many texts
- Progress callback invocation after each batch
- Failure isolation between batches
- Sequential behavior when max_batch_concurrency=1
- Initialization with max_batch_concurrency parameter
"""

import asyncio
import json
import time
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from src.services.translation_service import TranslationService, TranslationResult
from src.models.job import LanguagePair


@pytest.fixture
def chinese_vietnamese_pair():
    """Create a Chinese-Vietnamese language pair for testing."""
    return LanguagePair(
        id="zh-vi",
        source_language="Chinese",
        target_language="Vietnamese",
        source_language_code="zh",
        target_language_code="vi"
    )


@pytest.fixture
def mock_bedrock_client():
    """Create a mock Bedrock client."""
    with patch('boto3.client') as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        yield mock_instance


class TestBatchConcurrencyInitialization:
    """Tests for max_batch_concurrency parameter initialization."""

    def test_default_max_batch_concurrency(self, mock_bedrock_client):
        """Test that default max_batch_concurrency is 3."""
        service = TranslationService()
        assert service.max_batch_concurrency == 3

    def test_custom_max_batch_concurrency(self, mock_bedrock_client):
        """Test initialization with custom max_batch_concurrency."""
        service = TranslationService(max_batch_concurrency=5)
        assert service.max_batch_concurrency == 5

    def test_max_batch_concurrency_one(self, mock_bedrock_client):
        """Test initialization with max_batch_concurrency=1."""
        service = TranslationService(max_batch_concurrency=1)
        assert service.max_batch_concurrency == 1


class TestConcurrentBatchProcessing:
    """Tests for concurrent batch processing behavior."""

    @pytest.mark.asyncio
    async def test_batches_processed_concurrently(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that multiple batches run concurrently up to semaphore limit."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=3
        )

        call_times = []

        def mock_converse(**kwargs):
            """Simulate API call with delay to verify concurrency."""
            call_times.append(time.time())
            # Parse the request to determine batch size
            msg_text = kwargs['messages'][0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"translated_{item['text']}"}
                for item in items
            ]
            return {
                'output': {
                    'message': {
                        'content': [
                            {'text': json.dumps(response_items)}
                        ]
                    }
                }
            }

        mock_bedrock_client.converse.side_effect = mock_converse

        # 6 texts with batch_size=2 = 3 batches
        texts = [f"text_{i}" for i in range(6)]
        results = await service.batch_translate_async(
            texts, chinese_vietnamese_pair
        )

        assert len(results) == 6
        # All batches should have been called
        assert mock_bedrock_client.converse.call_count == 3

    @pytest.mark.asyncio
    async def test_semaphore_limits_parallelism(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that semaphore limits concurrent execution."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=2
        )

        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        original_converse = mock_bedrock_client.converse

        async def mock_call_with_tracking(
            messages, system_config, inference_config
        ):
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)

            # Simulate some async work
            await asyncio.sleep(0.05)

            async with lock:
                concurrent_count -= 1

            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.05

        # Patch _call_bedrock_with_retry to track concurrency
        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call_with_tracking
        ):
            # 8 texts with batch_size=2 = 4 batches, concurrency=2
            texts = [f"text_{i}" for i in range(8)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair
            )

        assert len(results) == 8
        # Semaphore should limit to max 2 concurrent
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_sequential_with_concurrency_one(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that max_batch_concurrency=1 processes sequentially."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=1
        )

        execution_order = []

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            batch_idx = items[0]['text']
            execution_order.append(batch_idx)
            await asyncio.sleep(0.01)  # Small delay
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            texts = [f"text_{i}" for i in range(6)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair
            )

        assert len(results) == 6
        # With concurrency=1, batches should complete in order
        assert execution_order == ["text_0", "text_2", "text_4"]


class TestResultOrdering:
    """Tests for result ordering correctness."""

    @pytest.mark.asyncio
    async def test_results_maintain_order_with_many_texts(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that results are correctly ordered with 100+ texts."""
        service = TranslationService(
            batch_size=10, max_batch_concurrency=5
        )

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            # Add varying delay to cause out-of-order completion
            await asyncio.sleep(0.01 * (len(items) % 3))
            response_items = [
                {"index": item["index"],
                 "translation": f"translated_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            texts = [f"segment_{i}" for i in range(105)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair
            )

        assert len(results) == 105
        for i, result in enumerate(results):
            assert result.text == f"translated_segment_{i}", (
                f"Result at index {i} is wrong: {result.text}"
            )

    @pytest.mark.asyncio
    async def test_results_order_with_varying_completion_times(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test ordering when batches complete in reverse order."""
        service = TranslationService(
            batch_size=3, max_batch_concurrency=5
        )

        call_count = 0

        async def mock_call(messages, system_config, inference_config):
            nonlocal call_count
            batch_num = call_count
            call_count += 1
            # Later batches complete faster (reverse order)
            await asyncio.sleep(0.05 - (batch_num * 0.01))
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"],
                 "translation": f"r_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            texts = [f"t{i}" for i in range(15)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair
            )

        assert len(results) == 15
        for i, result in enumerate(results):
            assert result.text == f"r_t{i}"


class TestProgressCallback:
    """Tests for progress callback behavior."""

    @pytest.mark.asyncio
    async def test_progress_callback_fires_after_each_batch(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that progress_callback is called after each batch."""
        service = TranslationService(
            batch_size=3, max_batch_concurrency=2
        )

        callback_calls = []

        async def on_progress(batch_idx, batch_len, total):
            callback_calls.append((batch_idx, batch_len, total))

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            # 9 texts with batch_size=3 = 3 batches
            texts = [f"text_{i}" for i in range(9)]
            await service.batch_translate_async(
                texts, chinese_vietnamese_pair,
                progress_callback=on_progress
            )

        # Should have 3 callback calls (one per batch)
        assert len(callback_calls) == 3
        # All callbacks should report total=9
        for _, _, total in callback_calls:
            assert total == 9
        # batch_len should be 3 for each batch
        for _, batch_len, _ in callback_calls:
            assert batch_len == 3

    @pytest.mark.asyncio
    async def test_progress_callback_reports_correct_batch_indices(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test callback reports correct batch index values."""
        service = TranslationService(
            batch_size=5, max_batch_concurrency=1
        )

        callback_calls = []

        async def on_progress(batch_idx, batch_len, total):
            callback_calls.append((batch_idx, batch_len, total))

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            # 12 texts with batch_size=5 = 3 batches (5, 5, 2)
            texts = [f"text_{i}" for i in range(12)]
            await service.batch_translate_async(
                texts, chinese_vietnamese_pair,
                progress_callback=on_progress
            )

        assert len(callback_calls) == 3
        # With concurrency=1, callbacks fire in order
        assert callback_calls[0] == (0, 5, 12)
        assert callback_calls[1] == (1, 5, 12)
        assert callback_calls[2] == (2, 2, 12)

    @pytest.mark.asyncio
    async def test_no_callback_when_none(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that no error occurs when progress_callback is None."""
        service = TranslationService(
            batch_size=3, max_batch_concurrency=2
        )

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            texts = [f"text_{i}" for i in range(6)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair
            )

        assert len(results) == 6

    @pytest.mark.asyncio
    async def test_callback_error_does_not_prevent_processing(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that errors in the callback do not block translation."""
        service = TranslationService(
            batch_size=3, max_batch_concurrency=2
        )

        async def bad_callback(batch_idx, batch_len, total):
            raise RuntimeError("callback error")

        async def mock_call(messages, system_config, inference_config):
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)
            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            texts = [f"text_{i}" for i in range(6)]
            results = await service.batch_translate_async(
                texts, chinese_vietnamese_pair,
                progress_callback=bad_callback
            )

        # Results should still be correct despite callback errors
        assert len(results) == 6
        for i, r in enumerate(results):
            assert r.text == f"t_text_{i}"


class TestFailureIsolation:
    """Tests for failure isolation between batches."""

    @pytest.mark.asyncio
    async def test_failure_in_one_batch_does_not_block_others(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that API failure in one batch doesn't prevent others."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=3
        )

        call_count = 0

        async def mock_call(messages, system_config, inference_config):
            nonlocal call_count
            current = call_count
            call_count += 1
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)

            # Fail only for the second batch (index 1)
            if current == 1:
                raise Exception("Simulated API failure")

            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        # Mock translate_text_async for fallback
        async def mock_single_translate(text, lp, tp=None):
            return TranslationResult(
                text=f"fallback_{text}", failed=True, error_code="TestError"
            )

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            with patch.object(
                service, 'translate_text_async',
                side_effect=mock_single_translate
            ):
                # 6 texts with batch_size=2 = 3 batches
                texts = [f"text_{i}" for i in range(6)]
                results = await service.batch_translate_async(
                    texts, chinese_vietnamese_pair
                )

        assert len(results) == 6
        # First batch (indices 0,1) should succeed
        assert results[0].text == "t_text_0"
        assert results[1].text == "t_text_1"
        # Second batch (indices 2,3) should fall back
        assert results[2].text == "fallback_text_2"
        assert results[3].text == "fallback_text_3"
        # Third batch (indices 4,5) should succeed
        assert results[4].text == "t_text_4"
        assert results[5].text == "t_text_5"

    @pytest.mark.asyncio
    async def test_json_parse_failure_triggers_individual_fallback(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that JSON parse failure in a batch falls back gracefully."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=2
        )

        call_count = 0

        async def mock_call(messages, system_config, inference_config):
            nonlocal call_count
            current = call_count
            call_count += 1
            msg_text = messages[0]['content'][0]['text']
            items = json.loads(msg_text)

            # Return invalid JSON for first batch
            if current == 0:
                return "not valid json at all", 0.01

            response_items = [
                {"index": item["index"], "translation": f"t_{item['text']}"}
                for item in items
            ]
            return json.dumps(response_items), 0.01

        async def mock_single_translate(text, lp, tp=None):
            return TranslationResult(text=f"single_{text}")

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            with patch.object(
                service, 'translate_text_async',
                side_effect=mock_single_translate
            ):
                texts = [f"text_{i}" for i in range(4)]
                results = await service.batch_translate_async(
                    texts, chinese_vietnamese_pair
                )

        assert len(results) == 4
        # First batch fell back to individual translation
        assert results[0].text == "single_text_0"
        assert results[1].text == "single_text_1"
        # Second batch succeeded normally
        assert results[2].text == "t_text_2"
        assert results[3].text == "t_text_3"

    @pytest.mark.asyncio
    async def test_all_batches_fail_gracefully(
        self, mock_bedrock_client, chinese_vietnamese_pair
    ):
        """Test that if all batches fail, results are still returned."""
        service = TranslationService(
            batch_size=2, max_batch_concurrency=2
        )

        async def mock_call(messages, system_config, inference_config):
            raise Exception("Total API failure")

        async def mock_single_translate(text, lp, tp=None):
            return TranslationResult(
                text=text, failed=True, error_code="APIError"
            )

        with patch.object(
            service, '_call_bedrock_with_retry',
            side_effect=mock_call
        ):
            with patch.object(
                service, 'translate_text_async',
                side_effect=mock_single_translate
            ):
                texts = ["a", "b", "c", "d"]
                results = await service.batch_translate_async(
                    texts, chinese_vietnamese_pair
                )

        assert len(results) == 4
        # All should be original text with failed=True
        for i, r in enumerate(results):
            assert r.text == texts[i]
            assert r.failed is True

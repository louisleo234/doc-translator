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

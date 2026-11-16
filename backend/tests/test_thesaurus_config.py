import pytest
from unittest.mock import AsyncMock, MagicMock
from src.services.thesaurus_service import ThesaurusService, ValidationError


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.query_term_pairs_by_catalog = AsyncMock()
    return repo


class TestThesaurusConfigLimits:
    def test_default_limits(self, mock_repository):
        """Test ThesaurusService initializes with default limits."""
        service = ThesaurusService(repository=mock_repository)
        assert service.max_term_length == 500
        assert service.max_terms_for_translation == 5000

    def test_custom_limits(self, mock_repository):
        """Test ThesaurusService initializes with custom limits."""
        service = ThesaurusService(
            repository=mock_repository,
            max_term_length=100,
            max_terms_for_translation=10
        )
        assert service.max_term_length == 100
        assert service.max_terms_for_translation == 10

    def test_validate_term_custom_limit(self, mock_repository):
        """Test that validate_term respects the dynamic max_term_length limit."""
        service = ThesaurusService(
            repository=mock_repository,
            max_term_length=10
        )
        
        # Sane term length (10 chars) should pass
        service.validate_term("1234567890")
        
        # Term exceeding dynamic limit should raise ValidationError
        with pytest.raises(ValidationError, match="exceeds maximum length of 10"):
            service.validate_term("12345678901")

    async def test_get_terms_for_translation_custom_limit(self, mock_repository):
        """Test that get_terms_for_translation truncates to max_terms_for_translation."""
        service = ThesaurusService(
            repository=mock_repository,
            max_terms_for_translation=3
        )
        
        items = [
            {
                "id": f"term-{i}",
                "language_pair_id": "zh-vi",
                "catalog_id": "cat-1",
                "source_term": f"term{i}",
                "target_term": f"translated{i}",
                "updated_at": f"2026-01-01T00:00:{i:02d}+00:00",
            }
            for i in range(5)
        ]
        mock_repository.query_term_pairs_by_catalog.return_value = items

        result = await service.get_terms_for_translation(
            language_pair_id="zh-vi",
            catalog_ids=["cat-1"]
        )

        # Should be truncated to max_terms_for_translation (3)
        assert len(result) == 3

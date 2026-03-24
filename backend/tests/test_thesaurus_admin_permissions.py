"""
Tests for Thesaurus Admin Permissions

Tests the admin access control for thesaurus mutations:
- Property 1: Admin users can perform all thesaurus mutations
- Property 2: Regular users are rejected with PERMISSION_DENIED
- Property 3: Language pairs are stored with global ownership
"""

import pytest
from unittest.mock import Mock, AsyncMock
from hypothesis import given, strategies as st, settings

from src.graphql.thesaurus_resolvers import require_admin_access
from src.graphql.decorators import PermissionError as AuthPermissionError
from src.models.user import User, UserRole, UserStatus
from src.models.config import LanguagePair as ConfigLanguagePair


# =========================================================================
# Strategies
# =========================================================================

username_strategy = st.from_regex(r"[a-zA-Z0-9_]{3,50}", fullmatch=True)

thesaurus_mutation_types = st.sampled_from([
    "add_term_pair",
    "edit_term_pair",
    "delete_term_pair",
    "bulk_delete_term_pairs",
    "import_terms_csv",
    "create_catalog",
    "update_catalog",
    "delete_catalog",
    "add_language_pair",
    "remove_language_pair",
])

language_code_strategy = st.from_regex(r"[a-z]{2,3}", fullmatch=True)
language_name_strategy = st.from_regex(r"[A-Za-z]{1,30}", fullmatch=True)


# =========================================================================
# Helpers
# =========================================================================

def make_mock_info(username: str, role: UserRole) -> Mock:
    """Create a mock Info with an authenticated user in context."""
    user = User(
        username=username,
        password_hash="hashed",
        role=role,
        status=UserStatus.ACTIVE,
        must_change_password=False,
    )

    info = Mock()
    info.context = {"current_user": user}
    return info


def make_mock_info_with_language_pair_service(
    username: str, role: UserRole
) -> tuple:
    """Create a mock Info with language_pair_service. Returns (info, mock_service)."""
    user = User(
        username=username,
        password_hash="hashed",
        role=role,
        status=UserStatus.ACTIVE,
        must_change_password=False,
    )

    mock_language_pair_service = Mock()
    mock_language_pair_service.create_language_pair = AsyncMock()

    resolver_context = Mock()
    resolver_context.language_pair_service = mock_language_pair_service

    info = Mock()
    info.context = {
        "current_user": user,
        "resolver_context": resolver_context,
    }

    return info, mock_language_pair_service


# =========================================================================
# Property 1: Admin users can perform all thesaurus mutations
# =========================================================================


class TestAdminUserCanPerformAllMutations:
    """Admin users can call require_admin_access for any mutation type."""

    @settings(max_examples=100)
    @given(username=username_strategy, mutation_type=thesaurus_mutation_types)
    async def test_admin_user_can_access_all_mutations(
        self, username: str, mutation_type: str
    ):
        """Admin users pass require_admin_access and get their username returned."""
        info = make_mock_info(username=username, role=UserRole.ADMIN)

        result = await require_admin_access(info)

        assert result == username, (
            f"Expected username '{username}' for admin attempting '{mutation_type}', "
            f"but got '{result}'"
        )


# =========================================================================
# Property 2: Regular users are rejected from all thesaurus mutations
# =========================================================================


class TestRegularUserRejectedFromMutations:
    """Regular users are rejected with PERMISSION_DENIED from all mutations."""

    @settings(max_examples=100)
    @given(username=username_strategy, mutation_type=thesaurus_mutation_types)
    async def test_regular_user_rejected_with_permission_denied(
        self, username: str, mutation_type: str
    ):
        """Regular users get AuthPermissionError with PERMISSION_DENIED."""
        info = make_mock_info(username=username, role=UserRole.USER)

        with pytest.raises(AuthPermissionError) as exc_info:
            await require_admin_access(info)

        assert str(exc_info.value) == "Admin access required", (
            f"Expected 'Admin access required' for user '{username}' "
            f"attempting '{mutation_type}', but got: '{exc_info.value}'"
        )
        assert exc_info.value.error_code.value == "PERMISSION_DENIED", (
            f"Expected PERMISSION_DENIED for user '{username}' "
            f"attempting '{mutation_type}', but got: '{exc_info.value.error_code}'"
        )


# =========================================================================
# Property 3: Language pairs are stored with global ownership
# =========================================================================


class TestLanguagePairsStoredWithGlobalOwnership:
    """Language pairs are created with user_id='__global__', not the admin's username."""

    @settings(max_examples=100)
    @given(
        admin_username=username_strategy,
        source_code=language_code_strategy,
        target_code=language_code_strategy,
        source_name=language_name_strategy,
        target_name=language_name_strategy,
    )
    async def test_add_language_pair_uses_global_user_id(
        self,
        admin_username: str,
        source_code: str,
        target_code: str,
        source_name: str,
        target_name: str,
    ):
        """resolve_add_language_pair passes user_id='__global__' to the service."""
        from src.graphql.resolvers import resolve_add_language_pair

        info, mock_lp_service = make_mock_info_with_language_pair_service(
            username=admin_username, role=UserRole.ADMIN
        )

        mock_lp_service.create_language_pair.return_value = ConfigLanguagePair(
            id="test-uuid",
            user_id="__global__",
            source_language=source_code,
            target_language=target_code,
            display_name=f"{source_name}→{target_name}",
        )

        await resolve_add_language_pair(
            info=info,
            source_language=source_name,
            target_language=target_name,
            source_language_code=source_code,
            target_language_code=target_code,
        )

        mock_lp_service.create_language_pair.assert_called_once()

        call_kwargs = mock_lp_service.create_language_pair.call_args
        actual_user_id = call_kwargs.kwargs.get(
            "user_id", call_kwargs.args[0] if call_kwargs.args else None
        )

        assert actual_user_id == "__global__", (
            f"Expected user_id='__global__' but got '{actual_user_id}'. "
            f"Admin '{admin_username}' should not own language pairs."
        )

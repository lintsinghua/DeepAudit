"""
Tests for app/api/v1/endpoints/auth.py

Covers RegisterRequest validation, login, and register endpoints.
Uses direct function calls with mocked db sessions and security helpers.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm

from app.api.v1.endpoints.auth import RegisterRequest, login, register


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(
    email="user@example.com",
    hashed_password="hashed",
    is_active=True,
    is_superuser=False,
    role="member",
    user_id="test-uuid-1234",
):
    """Create a mock User ORM object."""
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.hashed_password = hashed_password
    user.full_name = "Test User"
    user.is_active = is_active
    user.is_superuser = is_superuser
    user.role = role
    user.phone = None
    user.avatar_url = None
    user.github_username = None
    user.gitlab_username = None
    user.created_at = None
    user.updated_at = None
    return user


def _mock_db(user_query_result=None):
    """
    Build an AsyncMock db session that returns the expected scalars.

    - user_query_result: the single user returned by the first select query
    """
    db = AsyncMock()

    # First execute call: select(User).where(User.email == ...)
    first_result = MagicMock()
    first_scalars = MagicMock()
    first_scalars.first.return_value = user_query_result
    first_result.scalars.return_value = first_scalars

    db.execute.return_value = first_result

    # SQLAlchemy AsyncSession.add() is synchronous, override the AsyncMock
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    return db


# ===================================================================
# 1. RegisterRequest validation
# ===================================================================

class TestRegisterRequestValidation:
    """Pydantic validation tests for the RegisterRequest model."""

    def test_valid_request(self):
        req = RegisterRequest(
            email="alice@example.com",
            password="secret123",
            full_name="Alice",
        )
        assert req.email == "alice@example.com"
        assert req.password == "secret123"
        assert req.full_name == "Alice"

    def test_invalid_email_fails(self):
        with pytest.raises(Exception):
            # "not-an-email" is not a valid EmailStr
            RegisterRequest(
                email="not-an-email",
                password="secret123",
                full_name="Alice",
            )

    def test_missing_password_fails(self):
        with pytest.raises(Exception):
            RegisterRequest(
                email="alice@example.com",
                full_name="Alice",
                # password omitted
            )

    def test_missing_full_name_fails(self):
        with pytest.raises(Exception):
            RegisterRequest(
                email="alice@example.com",
                password="secret123",
                # full_name omitted
            )


# ===================================================================
# 2. login endpoint
# ===================================================================

class TestLoginEndpoint:
    """Tests for the login async endpoint function."""

    @pytest.mark.asyncio
    async def test_successful_login_returns_access_token(self):
        user = _make_user()
        db = _mock_db(user_query_result=user)
        form = MagicMock()
        form.username = "user@example.com"
        form.password = "correct-password"

        with patch(
            "app.api.v1.endpoints.auth.security.verify_password", return_value=True
        ), patch(
            "app.api.v1.endpoints.auth.security.create_access_token",
            return_value="jwt-token-123",
        ):
            result = await login(db=db, form_data=form)

        assert result["access_token"] == "jwt-token-123"
        assert result["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_wrong_password_raises_400(self):
        user = _make_user()
        db = _mock_db(user_query_result=user)
        form = MagicMock()
        form.username = "user@example.com"
        form.password = "wrong-password"

        with patch(
            "app.api.v1.endpoints.auth.security.verify_password", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await login(db=db, form_data=form)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_user_not_found_raises_400(self):
        db = _mock_db(user_query_result=None)
        form = MagicMock()
        form.username = "nobody@example.com"
        form.password = "does-not-matter"

        with patch(
            "app.api.v1.endpoints.auth.security.verify_password", return_value=False
        ):
            with pytest.raises(HTTPException) as exc_info:
                await login(db=db, form_data=form)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_inactive_user_raises_400(self):
        user = _make_user(is_active=False)
        db = _mock_db(user_query_result=user)
        form = MagicMock()
        form.username = "user@example.com"
        form.password = "correct-password"

        with patch(
            "app.api.v1.endpoints.auth.security.verify_password", return_value=True
        ):
            with pytest.raises(HTTPException) as exc_info:
                await login(db=db, form_data=form)
            assert exc_info.value.status_code == 400


# ===================================================================
# 3. register endpoint
# ===================================================================

class TestRegisterEndpoint:
    """Tests for the register async endpoint function."""

    @pytest.mark.asyncio
    async def test_successful_registration_returns_user(self):
        db = _mock_db(user_query_result=None)

        db.refresh = AsyncMock()

        user_in = RegisterRequest(
            email="new@example.com",
            password="password123",
            full_name="New User",
        )

        with patch(
            "app.api.v1.endpoints.auth.security.get_password_hash",
            return_value="hashed_new",
        ):
            result = await register(db=db, user_in=user_in)

        assert result.email == "new@example.com"
        assert result.full_name == "New User"
        assert result.is_active is True
        db.add.assert_called_once()
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_400(self):
        existing = _make_user()
        db = _mock_db(user_query_result=existing)

        user_in = RegisterRequest(
            email="user@example.com",
            password="password123",
            full_name="Dup User",
        )

        with pytest.raises(HTTPException) as exc_info:
            await register(db=db, user_in=user_in)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_public_registration_cannot_claim_admin(self):
        db = _mock_db()
        user_in = RegisterRequest(
            email="first@example.com",
            full_name="First User",
            password="member-password",
            role="admin",
            is_superuser=True,
        )
        user = await register(db=db, user_in=user_in)
        assert user.is_superuser is False
        assert user.role == "member"

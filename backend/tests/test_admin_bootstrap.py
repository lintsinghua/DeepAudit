from unittest.mock import AsyncMock, create_autospec, patch

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.db import init_db as bootstrap
from app.main import app
from app.models.user import User


@pytest.fixture
def db():
    return create_autospec(AsyncSession, instance=True)


@pytest.fixture
def configure(monkeypatch):
    def set_credentials(email=None, password=None):
        monkeypatch.setattr(bootstrap.settings, "BOOTSTRAP_ADMIN_EMAIL", email)
        secret = SecretStr(password) if password is not None else None
        monkeypatch.setattr(bootstrap.settings, "BOOTSTRAP_ADMIN_PASSWORD", secret)

    return set_credentials


async def test_bootstrap_then_restart_preserves_the_admin(db, configure):
    password = "operator-chosen-test-password"
    configure("owner@example.com", password)
    db.scalar.side_effect = [None, None]
    await bootstrap.ensure_admin(db)
    user = db.add.call_args.args[0]
    assert user.email == "owner@example.com"
    assert user.is_superuser and user.is_active and user.role == "admin"
    assert verify_password(password, user.hashed_password)

    db.scalar.side_effect = [user.email]
    configure()
    await bootstrap.ensure_admin(db)
    db.add.assert_called_once()


@pytest.mark.parametrize(("email", "password"), [
    (None, None),
    ("owner@example.com", None),
    (None, "long-enough-for-this-test"),
    ("owner@example.com", "short"),
    ("owner@example.com", "密" * 25),
])
async def test_invalid_bootstrap_stops_without_creating_user(db, configure, email, password):
    configure(email, password)
    db.scalar.return_value = None
    with pytest.raises(RuntimeError):
        await bootstrap.ensure_admin(db)
    db.add.assert_not_called()


async def test_existing_email_cannot_be_promoted(db, configure):
    configure("member@example.com", "operator-chosen-test-password")
    db.scalar.side_effect = [None, "existing-member-id"]
    with pytest.raises(RuntimeError, match="邮箱已被占用"):
        await bootstrap.ensure_admin(db)
    db.add.assert_not_called()


async def test_upgrade_retires_weak_credential_even_if_bootstrap_is_missing(db, configure):
    configure()
    weak_hash = get_password_hash(bootstrap.LEGACY_DEMO_PASSWORD)
    user = User(id="original-owner", email=bootstrap.LEGACY_DEMO_EMAIL,
                hashed_password=weak_hash, is_active=True, is_superuser=True)
    db.scalars.return_value = [user]
    db.scalar.return_value = None
    with pytest.raises(RuntimeError, match="BOOTSTRAP_ADMIN_EMAIL"):
        await bootstrap.init_db(db)
    assert user.id == "original-owner"
    assert not user.is_active
    assert not verify_password(bootstrap.LEGACY_DEMO_PASSWORD, user.hashed_password)
    db.commit.assert_awaited_once()
    db.delete.assert_not_called()


async def test_upgrade_keeps_rotated_credentials_and_seeds_system_templates(db, configure):
    configure()
    rotated_hash = get_password_hash("a-rotated-private-password")
    user = User(id="owner", email=bootstrap.LEGACY_DEMO_EMAIL, hashed_password=rotated_hash,
                is_active=True, is_superuser=True)
    db.scalars.return_value = [user]
    db.scalar.return_value = user.id
    with patch("app.services.init_templates.init_templates_and_rules", new_callable=AsyncMock) as seed:
        await bootstrap.init_db(db)
    seed.assert_awaited_once_with(db)
    assert user.is_active and user.hashed_password == rotated_hash
    db.add.assert_not_called()


async def test_public_index_and_startup_logs_contain_no_credentials(db, configure, caplog):
    email, password = "private-owner@example.com", "private-bootstrap-password"
    configure(email, password)
    db.scalars.return_value = []
    db.scalar.side_effect = [None, None]
    caplog.set_level("INFO")
    with (
        patch("app.main.AsyncSessionLocal") as sessions,
        patch("app.main.check_agent_services", new_callable=AsyncMock, return_value=[]),
        patch("app.services.init_templates.init_templates_and_rules", new_callable=AsyncMock),
    ):
        sessions.return_value.__aenter__.return_value = db
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to DeepAudit API", "docs": "/docs"}
    for value in (email, password, bootstrap.LEGACY_DEMO_EMAIL, bootstrap.LEGACY_DEMO_PASSWORD):
        assert value not in caplog.text

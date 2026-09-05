"""Regression coverage for deployment credentials, demo bootstrap, and CORS."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db import init_db as bootstrap


def test_secret_is_required(monkeypatch):
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None)


@pytest.mark.parametrize("secret", [
    "short", " " * 32,
    "changethis_in_production_to_a_long_random_string",
    "your-super-secret-key-change-this-in-production",
])
def test_unsafe_secrets_are_rejected(secret):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, SECRET_KEY=secret)


def test_production_rejects_demo_mode():
    with pytest.raises(ValidationError, match="DEMO_ENABLED"):
        Settings(_env_file=None, ENVIRONMENT="production", DEMO_ENABLED=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("default_password", [True, False])
async def test_existing_demo_is_disabled_only_with_default_password(default_password):
    user = SimpleNamespace(is_active=True, hashed_password="stored-hash")
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = user
    db.execute.return_value = result
    with (
        patch.object(bootstrap, "settings", Settings(_env_file=None, DEMO_ENABLED=False)),
        patch.object(bootstrap, "verify_password", return_value=default_password),
        patch.object(bootstrap, "create_demo_user", new_callable=AsyncMock) as create,
        patch("app.services.init_templates.init_templates_and_rules", new_callable=AsyncMock),
    ):
        await bootstrap.init_db(db)
    assert user.is_active is (not default_password)
    create.assert_not_awaited()
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_fresh_install_does_not_create_demo():
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db.execute.return_value = result
    with (
        patch.object(bootstrap, "settings", Settings(_env_file=None, DEMO_ENABLED=False)),
        patch.object(bootstrap, "create_demo_user", new_callable=AsyncMock) as create,
        patch("app.services.init_templates.init_templates_and_rules", new_callable=AsyncMock),
    ):
        await bootstrap.init_db(db)
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_demo_can_be_explicitly_enabled_in_development():
    db = AsyncMock()
    with (
        patch.object(bootstrap, "settings", Settings(
            _env_file=None, ENVIRONMENT="development", DEMO_ENABLED=True,
        )),
        patch.object(bootstrap, "create_demo_user", new_callable=AsyncMock) as create,
        patch.object(bootstrap, "create_demo_data", new_callable=AsyncMock) as data,
        patch("app.services.init_templates.init_templates_and_rules", new_callable=AsyncMock),
    ):
        await bootstrap.init_db(db)
    create.assert_awaited_once_with(db)
    data.assert_awaited_once_with(db, create.return_value)


@pytest.mark.asyncio
async def test_root_does_not_publish_credentials_and_cors_rejects_unknown_origin():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test",
    ) as client:
        response = await client.get("/")
        assert "demo_account" not in response.json()
        assert "demo123" not in response.text
        preflight = await client.options("/api/v1/tasks/", headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        })
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


@pytest.mark.asyncio
async def test_production_does_not_start_when_security_bootstrap_fails():
    from app import main

    with (
        patch.object(main, "settings", Settings(_env_file=None, ENVIRONMENT="production")),
        patch.object(main, "AsyncSessionLocal", return_value=AsyncMock()),
        patch.object(main, "init_db", side_effect=RuntimeError("bootstrap failed")),
        patch.object(main, "check_agent_services", new_callable=AsyncMock) as check,
    ):
        with pytest.raises(RuntimeError, match="bootstrap failed"):
            async with main.lifespan(main.app):
                pytest.fail("Production startup must fail closed")
    check.assert_not_awaited()

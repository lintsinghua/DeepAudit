"""
Shared test fixtures for all backend tests.
"""

import pytest
import tempfile
import shutil
import os
from unittest.mock import patch, MagicMock

# Configure imports before the application constructs its settings singleton.
os.environ["SECRET_KEY"] = "test_secret_key_for_testing_1234567890"
os.environ["ENVIRONMENT"] = "test"
os.environ["DEMO_ENABLED"] = "false"

from app.core.config import Settings


@pytest.fixture(autouse=True)
def mock_settings():
    """Patch settings with deterministic test values to avoid env dependency."""
    test_settings = Settings(
        SECRET_KEY="test_secret_key_for_testing_1234567890",
        ALGORITHM="HS256",
        ACCESS_TOKEN_EXPIRE_MINUTES=30,
    )
    with patch("app.core.config.settings", test_settings):
        with patch("app.core.security.settings", test_settings):
            with patch("app.core.encryption.settings", test_settings):
                yield test_settings


@pytest.fixture(autouse=True)
def reset_agent_config():
    """Clear @lru_cache on get_agent_config between tests to prevent state leakage."""
    from app.services.agent.config import get_agent_config

    get_agent_config.cache_clear()
    yield
    get_agent_config.cache_clear()


@pytest.fixture
def temp_dir():
    """Provide a clean temporary directory (cleaned up after test)."""
    d = tempfile.mkdtemp(prefix="deepaudit_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)

"""
Tests for pure utility functions in app.services.scanner.

Covers:
- get_analysis_config: with/without/partial user_config
- is_text_file: known extensions, unknown extensions, case-insensitive
- should_exclude: default patterns, custom patterns, substring matching
- get_language_from_path: known extensions, unknown extensions, no extension
- TaskControlManager: cancel_task, is_cancelled, cleanup_task
- github_api, gitlab_api, gitea_api: token injection, error handling (401/403/non-200)
- fetch_file_content: success, failure, timeout
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scanner import (
    get_analysis_config,
    is_text_file,
    should_exclude,
    get_language_from_path,
    TaskControlManager,
    github_api,
    gitlab_api,
    gitea_api,
    fetch_file_content,
)


# ---------------------------------------------------------------------------
# get_analysis_config
# ---------------------------------------------------------------------------

class TestGetAnalysisConfig:

    def test_default_config_no_user_config(self):
        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.MAX_ANALYZE_FILES = 50
            mock_settings.LLM_CONCURRENCY = 3
            mock_settings.LLM_GAP_MS = 2000
            result = get_analysis_config()
        assert result["max_analyze_files"] == 50
        assert result["llm_concurrency"] == 3
        assert result["llm_gap_ms"] == 2000

    def test_user_config_overrides(self):
        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.MAX_ANALYZE_FILES = 50
            mock_settings.LLM_CONCURRENCY = 3
            mock_settings.LLM_GAP_MS = 2000
            user_config = {
                "otherConfig": {
                    "maxAnalyzeFiles": 100,
                    "llmConcurrency": 5,
                    "llmGapMs": 3000,
                }
            }
            result = get_analysis_config(user_config)
        assert result["max_analyze_files"] == 100
        assert result["llm_concurrency"] == 5
        assert result["llm_gap_ms"] == 3000

    def test_partial_user_config_falls_back_to_settings(self):
        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.MAX_ANALYZE_FILES = 50
            mock_settings.LLM_CONCURRENCY = 3
            mock_settings.LLM_GAP_MS = 2000
            user_config = {
                "otherConfig": {
                    "maxAnalyzeFiles": 100,
                    # llmConcurrency and llmGapMs not provided
                }
            }
            result = get_analysis_config(user_config)
        assert result["max_analyze_files"] == 100
        assert result["llm_concurrency"] == 3   # falls back to settings
        assert result["llm_gap_ms"] == 2000     # falls back to settings

    def test_empty_other_config(self):
        with patch("app.services.scanner.settings") as mock_settings:
            mock_settings.MAX_ANALYZE_FILES = 0
            mock_settings.LLM_CONCURRENCY = 3
            mock_settings.LLM_GAP_MS = 2000
            result = get_analysis_config({"otherConfig": {}})
        assert result["max_analyze_files"] == 0
        assert result["llm_concurrency"] == 3
        assert result["llm_gap_ms"] == 2000


# ---------------------------------------------------------------------------
# is_text_file
# ---------------------------------------------------------------------------

class TestIsTextFile:

    def test_python_extension(self):
        assert is_text_file("main.py") is True

    def test_javascript_extension(self):
        assert is_text_file("app.js") is True

    def test_typescript_extension(self):
        assert is_text_file("component.tsx") is True

    def test_json_extension(self):
        assert is_text_file("package.json") is True

    def test_yaml_extension(self):
        assert is_text_file("config.yaml") is True

    def test_binary_png(self):
        assert is_text_file("image.png") is False

    def test_binary_exe(self):
        assert is_text_file("setup.exe") is False

    def test_no_extension(self):
        assert is_text_file("Makefile") is False

    def test_case_insensitive(self):
        assert is_text_file("README.MD") is False  # .md not in TEXT_EXTENSIONS
        assert is_text_file("script.PY") is True   # .py is in extensions, and lower() matches


# ---------------------------------------------------------------------------
# should_exclude
# ---------------------------------------------------------------------------

class TestShouldExclude:

    def test_node_modules(self):
        assert should_exclude("src/node_modules/react/index.js") is True

    def test_git_directory(self):
        assert should_exclude(".git/config") is True

    def test_dist_directory(self):
        assert should_exclude("dist/bundle.js") is True

    def test_normal_file_not_excluded(self):
        assert should_exclude("src/main.py") is False

    def test_custom_exclude_patterns(self):
        assert should_exclude("logs/app.log", exclude_patterns=["logs/"]) is True

    def test_no_custom_patterns(self):
        # Without custom patterns, only default patterns are checked
        assert should_exclude("my_custom_dir/file.txt") is False

    def test_minified_js(self):
        assert should_exclude("vendor/jquery.min.js") is True

    def test_source_map(self):
        assert should_exclude("bundle.js.map") is True


# ---------------------------------------------------------------------------
# get_language_from_path
# ---------------------------------------------------------------------------

class TestGetLanguageFromPath:

    def test_python(self):
        assert get_language_from_path("main.py") == "python"

    def test_javascript(self):
        assert get_language_from_path("app.js") == "javascript"

    def test_typescript(self):
        assert get_language_from_path("component.ts") == "typescript"

    def test_tsx_is_typescript(self):
        assert get_language_from_path("widget.tsx") == "typescript"

    def test_go(self):
        assert get_language_from_path("main.go") == "go"

    def test_rust(self):
        assert get_language_from_path("lib.rs") == "rust"

    def test_java(self):
        assert get_language_from_path("App.java") == "java"

    def test_unknown_extension_returns_text(self):
        assert get_language_from_path("data.csv") == "text"

    def test_no_extension_returns_text(self):
        assert get_language_from_path("Makefile") == "text"

    def test_c_returns_cpp(self):
        assert get_language_from_path("utils.c") == "cpp"

    def test_csharp(self):
        assert get_language_from_path("Program.cs") == "csharp"


# ---------------------------------------------------------------------------
# TaskControlManager
# ---------------------------------------------------------------------------

class TestTaskControlManager:

    def test_initial_state(self):
        mgr = TaskControlManager()
        assert mgr.is_cancelled("task-1") is False

    def test_cancel_task(self):
        mgr = TaskControlManager()
        mgr.cancel_task("task-1")
        assert mgr.is_cancelled("task-1") is True

    def test_cancel_does_not_affect_other_tasks(self):
        mgr = TaskControlManager()
        mgr.cancel_task("task-1")
        assert mgr.is_cancelled("task-2") is False

    def test_cleanup_task(self):
        mgr = TaskControlManager()
        mgr.cancel_task("task-1")
        mgr.cleanup_task("task-1")
        assert mgr.is_cancelled("task-1") is False

    def test_cleanup_nonexistent_task_no_error(self):
        mgr = TaskControlManager()
        mgr.cleanup_task("nonexistent")  # should not raise

    def test_multiple_cancellations(self):
        mgr = TaskControlManager()
        mgr.cancel_task("a")
        mgr.cancel_task("b")
        mgr.cancel_task("c")
        assert mgr.is_cancelled("a") is True
        assert mgr.is_cancelled("b") is True
        assert mgr.is_cancelled("c") is True


# ---------------------------------------------------------------------------
# github_api
# ---------------------------------------------------------------------------

class TestGithubApi:

    async def test_success_with_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "ok"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await github_api("https://api.github.com/test", token="ghp_test123")

        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer ghp_test123"
        assert result == {"data": "ok"}

    async def test_403_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="403"):
                await github_api("https://api.github.com/test")

    async def test_non_200_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="404"):
                await github_api("https://api.github.com/test")


# ---------------------------------------------------------------------------
# gitlab_api
# ---------------------------------------------------------------------------

class TestGitlabApi:

    async def test_success_with_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "main"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await gitlab_api("https://gitlab.com/api/v4/test", token="glpat_test")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["PRIVATE-TOKEN"] == "glpat_test"
        assert result == {"name": "main"}

    async def test_401_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="401"):
                await gitlab_api("https://gitlab.com/api/v4/test")

    async def test_403_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="403"):
                await gitlab_api("https://gitlab.com/api/v4/test")

    async def test_non_200_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="500"):
                await gitlab_api("https://gitlab.com/api/v4/test")


# ---------------------------------------------------------------------------
# gitea_api
# ---------------------------------------------------------------------------

class TestGiteaApi:

    @pytest.fixture(autouse=True)
    def trusted_gitea(self, monkeypatch):
        from app.utils.repo_utils import settings
        monkeypatch.setattr(settings, "GITEA_ORIGIN", "https://gitea.example.com")

    async def test_success_with_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"name": "main"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await gitea_api("https://gitea.example.com/api/v1/test", token="gitea_token")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "token gitea_token"
        assert result == {"name": "main"}

    async def test_401_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="401"):
                await gitea_api("https://gitea.example.com/api/v1/test")

    async def test_403_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="403"):
                await gitea_api("https://gitea.example.com/api/v1/test")

    async def test_non_200_raises_exception(self):
        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(Exception, match="500"):
                await gitea_api("https://gitea.example.com/api/v1/test")


# ---------------------------------------------------------------------------
# fetch_file_content
# ---------------------------------------------------------------------------

class TestFetchFileContent:

    async def test_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "file content here"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_file_content("https://example.com/file.py")

        assert result == "file content here"

    async def test_non_200_returns_none(self):
        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_file_content("https://example.com/missing.py")

        assert result is None

    async def test_exception_returns_none(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            result = await fetch_file_content("https://example.com/file.py")

        assert result is None

    async def test_custom_headers_passed(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "ok"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.scanner.httpx.AsyncClient", return_value=mock_client):
            await fetch_file_content("https://example.com/file.py", headers={"Authorization": "Bearer x"})

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Authorization"] == "Bearer x"

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import agent_tasks, auth, config, embedding_config, scan
from app.services.archive import extract_zip
from app.models.audit import AuditTask, source_position
from app.services import scanner
from app.services.llm.service import OutputLimitError
from app.services.llm.types import LLMConfig, LLMProvider, trusted_model_endpoint
from app.services.rag.embeddings import EmbeddingService


@pytest.mark.parametrize("value,expected", [(None, None), ("c5fc", None), ("8", 8),
                                           (0, None), (True, None), (2**32, None)])
def test_optional_positions(value, expected):
    assert source_position(value) == expected


async def test_public_registration_disabled_before_database_lookup(monkeypatch):
    monkeypatch.setattr(auth.settings, "PUBLIC_REGISTRATION_ENABLED", False)
    db = AsyncMock()
    request = auth.RegisterRequest(email="member@example.com", password="example", full_name="Member")
    with pytest.raises(HTTPException) as error:
        await auth.register(db=db, user_in=request)
    assert error.value.status_code == 403
    db.execute.assert_not_called()


def test_approved_model_endpoints_apply_to_new_and_saved_configs(monkeypatch):
    from app.services.llm import types
    allowed = "http://models.internal:8001/v1"
    other = "https://other.example/v1"
    monkeypatch.setattr(types.settings, "MODEL_ALLOWED_ENDPOINTS", allowed)
    assert trusted_model_endpoint(allowed + "/") == allowed
    assert config.LLMConfigSchema(llmBaseUrl=allowed).llmBaseUrl == allowed
    for constructor in (
        lambda: config.LLMTestRequest(provider="openai", apiKey="", baseUrl=other),
        lambda: config.LLMConfigSchema(llmBaseUrl=other),
        lambda: embedding_config.EmbeddingConfig(provider="ollama", model="example", base_url=other),
        lambda: embedding_config.TestEmbeddingRequest(provider="openai", model="example", base_url=other),
        lambda: LLMConfig(LLMProvider.OPENAI, "", "example", base_url=other),
        lambda: EmbeddingService(provider="ollama", model="example", base_url=other),
        lambda: trusted_model_endpoint(allowed + "/extra"),
    ):
        with pytest.raises(ValueError, match="未获部署者授权"):
            constructor()


async def test_gitlab_pagination_accepts_small_provider_pages(monkeypatch):
    monkeypatch.setattr(scanner.settings, "GITLAB_ORIGIN", "https://gitlab.com")
    api = AsyncMock(side_effect=[[{"type": "tree", "path": "src"}],
                                 [{"type": "blob", "path": "src/main.ts"}], []])
    monkeypatch.setattr(scanner, "gitlab_api", api)
    files = await scanner.get_gitlab_files("https://gitlab.com/team/sub/app.git", "release", "token")
    assert [f["path"] for f in files] == ["src/main.ts"]
    assert [c.args[1] for c in api.await_args_list] == ["token"] * 3


async def test_github_truncated_tree_walks_each_directory(monkeypatch):
    api = AsyncMock(side_effect=[
        {"tree": [], "sha": "root", "truncated": True},
        {"tree": [{"type": "tree", "path": "src", "sha": "sub"}]},
        {"tree": [{"type": "blob", "path": "main #1.ts", "size": 10}]},
    ])
    monkeypatch.setattr(scanner, "github_api", api)
    files = await scanner.get_github_files("https://github.com/team/app", "release")
    assert [f["path"] for f in files] == ["src/main #1.ts"]
    assert "%23" in files[0]["url"]
    assert api.await_args_list[-1].args[0].endswith("/git/trees/sub")


async def test_gitea_tree_pages_are_complete(monkeypatch):
    monkeypatch.setattr(scanner.settings, "GITEA_ORIGIN", "https://git.example")
    api = AsyncMock(side_effect=[
        {"tree": [{"type": "blob", "path": "a.py"}], "sha": "root", "total_count": 2, "truncated": True},
        {"tree": [{"type": "blob", "path": "b.py"}], "page": 2, "truncated": False},
    ])
    monkeypatch.setattr(scanner, "gitea_api", api)
    files = await scanner.get_gitea_files("https://git.example/team/app", "main")
    assert [f["path"] for f in files] == ["a.py", "b.py"]
    assert "/git/trees/root?" in api.await_args_list[-1].args[0]


async def test_truncated_static_analysis_retries_with_same_rules_and_line_offsets():
    service = AsyncMock()
    service.analyze_code_with_rules.side_effect = [
        OutputLimitError(), {"issues": [{"line": 1}], "quality_score": 90},
        {"issues": [{"line": "2"}], "quality_score": 70},
    ]
    db = object()
    result = await scanner.analyze_scan_file(service, "a\nb\nc\nd", "text",
                                            {"rule_set_id": "rules", "prompt_template_id": "template"}, db)
    assert result == {"issues": [{"line": 1}, {"line": 4}], "quality_score": 80}
    for call in service.analyze_code_with_rules.await_args_list:
        assert call.kwargs == {"rule_set_id": "rules", "prompt_template_id": "template", "db_session": db}


@pytest.mark.parametrize("paths", [("a.py", "src/b.py"), ("src/a.py", "other/b.py"), ("pkg/src/a.py",)])
def test_archive_root_preserves_all_files(tmp_path, paths):
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        for path in paths:
            archive.writestr(path, "pass")
    with ZipFile(data) as archive:
        extract_zip(archive, str(tmp_path))
    assert all((tmp_path / path).read_text() == "pass" for path in paths)


async def test_report_matches_saved_rows_and_real_paths(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/code.py").write_text("x\ny\n")
    db = MagicMock(spec=AsyncSession)
    saved = await agent_tasks._save_findings(db, "task", [
        {"file_path": "src/code.py", "line": "2", "severity": "HIGH"},
        {"location": "code.py:8:2", "is_verified": True},
        {"file": "absent.py"},
    ], project_root=str(tmp_path))
    added = [c.args[0] for c in db.add.call_args_list]
    assert len(saved) == len(added) == 2
    assert [f.file_path for f in added] == ["src/code.py", "src/code.py"]
    assert [f.line_start for f in added] == [2, None]
    assert saved[0]["severity"] == "high" and saved[1]["is_verified"]


async def test_zip_failure_keeps_only_committed_counts(tmp_path, monkeypatch):
    archive = tmp_path / "test.zip"
    with ZipFile(archive, "w") as z:
        for name in ["one.py", "two.py"]:
            z.writestr(name, "pass")
    task = AuditTask(id="t", status="pending", scan_config="{}")
    db = MagicMock(spec=AsyncSession)
    db.get.return_value = task
    db.commit.side_effect = [None, None, ValueError("write failed"), None, None]
    @asynccontextmanager
    async def session():
        yield db
    llm = AsyncMock()
    llm.analyze_code.return_value = {"issues": [{"line": "c5fc"}], "quality_score": 80}
    monkeypatch.setattr(scan, "LLMService", lambda **kwargs: llm)
    monkeypatch.setattr(scan, "get_analysis_config", lambda _: {"max_analyze_files": 0, "llm_gap_ms": 0})
    await scan.process_zip_task("t", str(archive), session)
    db.rollback.assert_awaited_once()
    assert (task.status, task.scanned_files, task.total_files, task.issues_count) == ("failed", 1, 2, 1)
    assert "1 个文件分析失败" in task.scan_config

async def test_index_limits_stop_before_rebuilding_existing_collection(tmp_path, monkeypatch):
    from app.services.agent.config import get_agent_config
    from app.services.rag.indexer import CodeIndexer, IndexLimitError

    monkeypatch.setattr(get_agent_config(), "max_files_per_scan", 1)
    for filename in ("a.py", "b.py"):
        (tmp_path / filename).write_text("pass")
    indexer = CodeIndexer("test", embedding_service=MagicMock(), vector_store=AsyncMock(), splitter=MagicMock())
    indexer.initialize = AsyncMock()
    with pytest.raises(IndexLimitError, match="请缩小扫描范围"):
        await anext(indexer.smart_index_directory(str(tmp_path)))
    indexer.initialize.assert_not_awaited()


async def test_supervisor_times_out_worker_and_waits_for_cleanup(monkeypatch):
    from app.services.agent.config import get_agent_config

    db = MagicMock(spec=AsyncSession)
    db.get.return_value = SimpleNamespace(status="pending", timeout_seconds=60, created_by=None)
    db.scalar.return_value = "running"

    @asynccontextmanager
    async def session():
        yield db

    stopped = asyncio.Event()
    async def worker(_id, _config):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(get_agent_config(), "orchestrator_timeout_seconds", 0)
    monkeypatch.setattr(agent_tasks, "async_session_factory", session)
    monkeypatch.setattr(agent_tasks, "_run_agent_task", worker)
    await asyncio.wait_for(agent_tasks._execute_agent_task("deadline"), 1)
    db.commit.assert_awaited_once()
    assert stopped.is_set() and "deadline" not in agent_tasks._running_asyncio_tasks


async def test_explicit_branch_never_scans_default_after_an_error(monkeypatch):
    task = AuditTask(id="t", project_id="p", status="pending", branch_name="release",
                     scan_config='{"branch_name":"release"}')
    project = SimpleNamespace(source_type="repository", repository_type="github",
                              repository_url="https://github.com/team/app", default_branch="main")
    db = MagicMock(spec=AsyncSession)
    db.get.side_effect = [task, project]

    @asynccontextmanager
    async def session():
        yield db

    api = AsyncMock(side_effect=FileNotFoundError("GitHub API 404"))
    monkeypatch.setattr(scanner, "get_github_files", api)
    await scanner.scan_repo_task("t", session)
    assert task.status == "failed" and task.branch_name == "release"
    assert api.await_count == 1 and api.await_args.args[1] == "release"

@pytest.mark.parametrize("provider,model", [
    (LLMProvider.OPENAI, "gpt-4o-mini"), (LLMProvider.QWEN, "qwen-turbo"),
    (LLMProvider.DEEPSEEK, "deepseek-chat"), (LLMProvider.CLAUDE, "claude-3-5-sonnet-20241022"),
    (LLMProvider.GEMINI, "gemini-2.0-flash"), (LLMProvider.OLLAMA, "llama3"),
])
@pytest.mark.parametrize("streaming", [False, True])
async def test_model_requests_stop_on_redirect(monkeypatch, provider, model, streaming):
    import socket
    import httpx
    from app.services.llm.adapters.litellm_adapter import LiteLLMAdapter
    from app.services.llm.types import LLMRequest, LLMMessage

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    monkeypatch.setattr(socket, "getaddrinfo", MagicMock(side_effect=AssertionError("unexpected network request")))
    import litellm
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    paths = []

    def redirect(request):
        paths.append(request.url.path)
        if request.url.path == "/moved":
            return httpx.Response(404, request=request)
        return httpx.Response(307, headers={"Location": "/moved"}, request=request)

    async def send(_transport, request):
        return redirect(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", send)
    monkeypatch.setattr(AsyncHTTPHandler, "_create_async_transport", staticmethod(
        lambda **kwargs: httpx.MockTransport(redirect)))
    shared = AsyncHTTPHandler()
    monkeypatch.setattr(litellm, "module_level_aclient", shared)
    adapter = LiteLLMAdapter(LLMConfig(provider, "local-test", model))
    request = LLMRequest([LLMMessage("user", "hello")])
    try:
        if streaming:
            events = [event async for event in adapter.stream_complete(request)]
            assert any(event["type"] == "error" for event in events)
        else:
            with pytest.raises(Exception):
                await adapter._send_request(request)
        assert paths and "/moved" not in paths
    finally:
        await adapter.close()
        await shared.close()

def test_quick_scan_respects_explicit_zero_settings(monkeypatch):
    monkeypatch.setattr(scanner.settings, "MAX_ANALYZE_FILES", 50)
    config = scanner.get_analysis_config({"otherConfig": {"maxAnalyzeFiles": 0, "llmGapMs": 0}})
    assert (config["max_analyze_files"], config["llm_gap_ms"]) == (0, 0)


async def test_embedding_defaults_do_not_return_deployer_credentials(monkeypatch):
    monkeypatch.setattr(embedding_config.settings, "LLM_API_KEY", "private-default")
    monkeypatch.setattr(embedding_config.settings, "EMBEDDING_BASE_URL", "https://embed.example/v1")
    db = MagicMock(spec=AsyncSession)
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    response = await embedding_config.get_current_config(db, SimpleNamespace(id="u"))
    assert response.api_key is None and response.base_url == "https://embed.example/v1"


async def test_file_preparation_joins_worker_on_cancel():
    import time
    from app.utils.async_utils import prepare_in_thread

    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    ended = []

    def prepare(*, cancel_check):
        loop.call_soon_threadsafe(started.set)
        while not cancel_check():
            time.sleep(0.005)
        ended.append(True)

    operation = asyncio.create_task(prepare_in_thread(prepare))
    await asyncio.wait_for(started.wait(), 1)
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(operation, 1)
    assert ended == [True]

async def test_connection_test_distinguishes_output_limit_from_connection_failure(monkeypatch):
    from app.services.llm.adapters import LiteLLMAdapter
    from app.services.llm.types import LLMResponse

    db = MagicMock(spec=AsyncSession)
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    monkeypatch.setattr(LiteLLMAdapter, "complete", AsyncMock(return_value=LLMResponse("", finish_reason="length")))
    close = AsyncMock()
    monkeypatch.setattr(LiteLLMAdapter, "close", close)
    result = await config.test_llm_connection(config.LLMTestRequest(provider="openai", apiKey="test"),
                                              db, SimpleNamespace(id="member"))
    assert result.success and result.debug["finish_reason"] == "length"
    close.assert_awaited_once()

import io
import json
import shutil
from subprocess import CompletedProcess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, UploadFile

from app.api.v1.endpoints import agent_tasks, config, database
from app.services import scanner, zip_storage
from app.utils import repo_utils


async def test_configuration_defaults_do_not_return_operator_credentials(monkeypatch):
    for name in type(config.settings).model_fields:
        if name.endswith(("_API_KEY", "_TOKEN")):
            monkeypatch.setattr(config.settings, name, "operator-value")
    defaults = await config.get_default_config_endpoint()
    db = AsyncMock()
    db.execute.return_value = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = None
    personal = await config.get_my_config(db, SimpleNamespace(id="user"))
    assert personal.llmConfig == defaults["llmConfig"]
    assert personal.otherConfig == defaults["otherConfig"]
    assert "operator-value" not in json.dumps(defaults)
    assert all(defaults["llmConfig"][field] == "" for field in config.SENSITIVE_LLM_FIELDS)
    assert all(defaults["otherConfig"][field] == "" for field in config.SENSITIVE_OTHER_FIELDS)


async def test_import_refuses_a_path_as_a_project_id():
    user = SimpleNamespace(id="user")
    data = {"user": {"id": user.id}, "projects": [{"id": "group/project"}]}
    upload = UploadFile(io.BytesIO(json.dumps({"data": data}).encode()))
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        await database.import_database(upload, db, user)
    assert error.value.status_code == 400
    db.get.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("project_id", ["group/project", r"group\project", "/project", ".."])
async def test_storage_rejects_invalid_existing_ids(project_id):
    with pytest.raises(ValueError):
        zip_storage.get_project_zip_path(project_id)
    assert await zip_storage.load_project_zip(project_id) is None
    assert await zip_storage.get_project_zip_meta(project_id) is None
    assert not await zip_storage.delete_project_zip(project_id)


async def test_zip_and_metadata_replace_links_without_following_them(tmp_path, monkeypatch):
    monkeypatch.setattr(zip_storage.settings, "ZIP_STORAGE_PATH", str(tmp_path / "storage"))
    project_id = "older.project-1"
    source = tmp_path / "upload"
    source.write_bytes(b"archive")
    existing = tmp_path / "existing"
    existing.write_bytes(b"original")
    archive = zip_storage.get_project_zip_path(project_id)
    metadata = zip_storage.get_project_zip_meta_path(project_id)
    for path in (archive, metadata):
        path.symlink_to(existing)

    assert not await zip_storage.has_project_zip(project_id)
    assert await zip_storage.get_project_zip_meta(project_id) is None
    result = await zip_storage.save_project_zip(project_id, str(source), "upload.zip")
    assert existing.read_bytes() == b"original"
    assert archive.read_bytes() == source.read_bytes()
    assert result == await zip_storage.get_project_zip_meta(project_id)
    assert await zip_storage.delete_project_zip(project_id)
    assert not archive.exists() and not metadata.exists()


@pytest.mark.parametrize("provider", ["gitlab", "gitea"])
@pytest.mark.parametrize("origin", ["https://other.example", "http://git.example", "https://git.example:444"])
async def test_branch_and_file_requests_require_the_configured_origin(monkeypatch, provider, origin):
    monkeypatch.setattr(repo_utils.settings, f"{provider.upper()}_ORIGIN", "https://git.example")
    url = f"{origin}/team/project"
    with patch.object(scanner.httpx, "AsyncClient") as client:
        with pytest.raises(ValueError):
            await getattr(scanner, f"get_{provider}_branches")(url)
        with pytest.raises(ValueError):
            await getattr(scanner, f"get_{provider}_files")(url, "main")
        client.assert_not_called()


async def test_trusted_gitlab_preserves_subgroups_and_scopes_token(monkeypatch):
    monkeypatch.setattr(repo_utils.settings, "GITLAB_ORIGIN", "https://git.example:8443")
    with patch.object(scanner, "gitlab_api", new_callable=AsyncMock) as api:
        api.side_effect = [[{"name": "main"}], []]
        result = await scanner.get_gitlab_branches("https://git.example:8443/team/sub/repo.git", "user-token")
    assert result == ["main"]
    base = "https://git.example:8443/api/v4/projects/team%2Fsub%2Frepo/repository/branches"
    assert api.await_args_list == [call(f"{base}?per_page=100&page={page}", "user-token") for page in (1, 2)]


async def test_agent_rejects_an_untrusted_origin_before_download_or_clone(monkeypatch):
    monkeypatch.setattr(repo_utils.settings, "GITLAB_ORIGIN", "https://git.example")
    project = SimpleNamespace(source_type="repository", repository_type="gitlab",
                              repository_url="https://other.example/team/project", default_branch="main")
    task_id = str(uuid4())
    try:
        with patch("httpx.AsyncClient") as http, patch("subprocess.run") as git:
            with pytest.raises(ValueError):
                await agent_tasks._get_project_root(project, task_id, gitlab_token="operator-value")
            http.assert_not_called()
            git.assert_not_called()
    finally:
        shutil.rmtree(Path("/tmp/deepaudit") / task_id, ignore_errors=True)


async def test_agent_redirect_falls_back_to_origin_scoped_git_auth(monkeypatch):
    origin = "https://git.example"
    monkeypatch.setattr(repo_utils.settings, "GITLAB_ORIGIN", origin)
    project = SimpleNamespace(source_type="repository", repository_type="gitlab",
                              repository_url=f"{origin}/team/sub/project", default_branch="main")
    task_id = str(uuid4())
    requests = []

    def redirect(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example/archive.zip"})

    def run_git(args, **kwargs):
        if "clone" in args:
            assert "http.followRedirects=false" in args
            assert f"--config-env=http.{origin}/.extraHeader=DEEPAUDIT_GIT_AUTH" in args
            assert kwargs["env"]["DEEPAUDIT_GIT_AUTH"].startswith("Authorization: Basic ")
            assert args[-2] == project.repository_url
            (Path(args[-1]) / "README").touch()
        return CompletedProcess(args, 0)

    client = httpx.AsyncClient
    transport = httpx.MockTransport(redirect)
    try:
        with patch("httpx.AsyncClient", side_effect=lambda **kw: client(transport=transport, **kw)), \
                patch("subprocess.run", side_effect=run_git), \
                patch.object(agent_tasks, "run_git_clone", side_effect=run_git):
            await agent_tasks._get_project_root(project, task_id, gitlab_token="operator-value")
        assert requests
        assert all(req.url.host == "git.example" and req.headers["PRIVATE-TOKEN"] == "operator-value"
                   for req in requests)
    finally:
        shutil.rmtree(Path("/tmp/deepaudit") / task_id, ignore_errors=True)

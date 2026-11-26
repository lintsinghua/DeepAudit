import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import config, database, embedding_config, members, projects, prompts, rules, users
from app.core.encryption import decrypt_sensitive_data, encryption_service, without_embedding_key
from app.models.user_config import UserConfig
from app.services.agent.tools.file_tool import FileReadTool
from app.utils.project_paths import resolve_project_path


@pytest.fixture
def db():
    session = create_autospec(AsyncSession, instance=True)
    session.execute.return_value = MagicMock()
    return session


async def test_project_access_and_profile_visibility(db):
    owner = SimpleNamespace(id="owner", is_superuser=False)
    member = SimpleNamespace(id="member", is_superuser=False)
    admin = SimpleNamespace(id="admin", is_superuser=True)
    project = SimpleNamespace(owner_id=owner.id)
    db.get.return_value = project
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as denied:
        await members.get_project_members("project", db, member)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        await projects.scan_project("project", BackgroundTasks(), db=db, current_user=member)
    assert denied.value.status_code == 403
    db.add.assert_not_called()

    db.execute.return_value.scalars.return_value.all.return_value = ["membership"]
    db.scalar.return_value = "membership"
    for viewer in (owner, member, admin):
        assert await members.get_project_members("project", db, viewer) == ["membership"]

    db.execute.return_value.scalars.return_value.first.return_value = owner
    for viewer in (owner, admin):
        assert await users.read_user(owner.id, db, viewer) == owner
    with pytest.raises(HTTPException) as denied:
        await users.read_user(owner.id, db, member)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("records", ["tasks", "issues"])
async def test_import_checks_parent_ownership_before_commit(db, records):
    owner = SimpleNamespace(id="owner")
    other_project = SimpleNamespace(owner_id="other")
    if records == "tasks":
        incoming = {"id": "task", "project_id": "project"}
        db.get.side_effect = [None, other_project]
    else:
        incoming = {"id": "issue", "task_id": "task"}
        db.get.side_effect = [None, SimpleNamespace(project_id="project", created_by="owner"), other_project]
    payload = {"data": {"user": {"id": owner.id}, records: [incoming]}}
    backup = UploadFile(io.BytesIO(json.dumps(payload).encode()))
    with pytest.raises(HTTPException) as denied:
        await database.import_database(backup, db, owner)
    assert denied.value.status_code == 403
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()


async def test_only_admin_can_change_shared_audit_settings(db):
    user = SimpleNamespace(id="member", is_superuser=False)
    shared = SimpleNamespace(is_system=True, is_active=True)
    db.execute.return_value.scalar_one_or_none.return_value = shared
    for handler, args in (
        (rules.update_rule_set, ("set", rules.AuditRuleSetUpdate(is_active=False))),
        (rules.toggle_rule, ("set", "rule")),
        (prompts.update_prompt_template, ("template", prompts.PromptTemplateUpdate(is_active=False))),
    ):
        with pytest.raises(HTTPException) as denied:
            await handler(*args, db=db, current_user=user)
        assert denied.value.status_code == 403
    assert shared.is_active
    db.commit.assert_not_awaited()


async def test_agent_reads_only_resolved_project_files(tmp_path):
    root = tmp_path / "project"
    sibling = tmp_path / "project-other"
    root.mkdir()
    sibling.mkdir()
    (root / "note.txt").write_text("project note")
    (root / "inside").symlink_to(root / "note.txt")
    (root / "outside").symlink_to(sibling, target_is_directory=True)
    assert resolve_project_path(str(root), "inside") == str((root / "note.txt").resolve())
    assert (await FileReadTool(str(root)).execute(file_path="inside")).success
    for name in ("outside", str(sibling), "../project-other"):
        with pytest.raises(ValueError):
            resolve_project_path(str(root), name)


async def test_saved_embedding_key_is_write_only_and_bound_to_its_service(db):
    user = SimpleNamespace(id="member")
    row = UserConfig(id="settings", user_id="member", llm_config="{}", other_config="{}")
    db.execute.return_value.scalar_one_or_none.return_value = row
    request = embedding_config.EmbeddingConfig(provider="openai", model="example", api_key="sample")
    await embedding_config.update_config(request, db, user)
    stored = json.loads(row.other_config)
    cipher = stored["embedding_config"]["api_key"]
    assert encryption_service.is_encrypted(cipher) and decrypt_sensitive_data(cipher) == "sample"
    public = await embedding_config.get_current_config(db, user)
    assert public.has_api_key and public.api_key is None
    assert "api_key" not in (await config.get_my_config(db, user)).otherConfig["embedding_config"]
    assert "api_key" not in without_embedding_key(stored)["embedding_config"]

    same = embedding_config.TestEmbeddingRequest(provider="openai", model="other")
    assert await embedding_config.resolve_embedding_key(same, db, user.id) == "sample"
    for change in ({"provider": "ollama"}, {"base_url": "https://api.openai.com/v1"}, {"api_key": None}):
        request = embedding_config.TestEmbeddingRequest(**{**same.model_dump(exclude_unset=True), **change})
        assert await embedding_config.resolve_embedding_key(request, db, user.id) is None


def test_embedding_data_migration_preserves_unrelated_settings(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/009_encrypt_embedding_keys.py"
    spec = importlib.util.spec_from_file_location("embedding_key_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with create_engine("sqlite://").begin() as connection:
        connection.execute(text("create table user_configs (id text, other_config text)"))
        raw = json.dumps({"theme": "dark", "embedding_config": {"api_key": "sample"}})
        connection.execute(text("insert into user_configs values ('user', :raw)"), {"raw": raw})
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        query = text("select other_config from user_configs")
        migration.upgrade()
        encrypted = connection.scalar(query)
        assert 'sample' not in encrypted
        assert json.loads(encrypted)["theme"] == "dark"
        migration.upgrade()
        assert connection.scalar(query) == encrypted
        migration.downgrade()
        assert json.loads(connection.scalar(query)) == json.loads(raw)

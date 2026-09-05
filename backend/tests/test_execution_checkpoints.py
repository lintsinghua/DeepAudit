from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services import audit_queue
from app.services.analysis_checkpoint import analyze_file
from app.services.agent.tools.sandbox_tool import SandboxManager


async def test_file_cache_reuses_result_and_invalidates_changed_source(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_queue.settings, "AUDIT_WORKSPACE_PATH", str(tmp_path))
    task_id = str(uuid4())
    service = SimpleNamespace(
        analyze_code=AsyncMock(return_value={"issues": [], "quality_score": 90})
    )
    first = await analyze_file(task_id, "app.py", "old", service, "python")
    assert await analyze_file(task_id, "app.py", "old", service, "python") == first
    assert service.analyze_code.await_count == 1
    await analyze_file(task_id, "app.py", "new", service, "python")
    assert service.analyze_code.await_count == 2
    for file in tmp_path.rglob("*.json"):
        file.write_text("corrupt")
    await analyze_file(task_id, "app.py", "new", service, "python")
    assert service.analyze_code.await_count == 3


async def test_failed_analysis_is_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_queue.settings, "AUDIT_WORKSPACE_PATH", str(tmp_path))
    service = SimpleNamespace(
        analyze_code=AsyncMock(side_effect=[RuntimeError("unavailable"), {"issues": []}])
    )
    task_id = str(uuid4())
    with pytest.raises(RuntimeError):
        await analyze_file(task_id, "a.py", "source", service, "python")
    assert not list(tmp_path.rglob("*.json"))
    assert await analyze_file(task_id, "a.py", "source", service, "python") == {"issues": []}


def test_sandbox_maps_shared_volume_to_daemon_path(monkeypatch):
    from pathlib import Path

    manager = SandboxManager()
    manager._docker_client = MagicMock()
    manager._docker_client.containers.get.return_value.attrs = {
        "Mounts": [
            {"Destination": "/app", "Source": "/daemon/app"},
            {"Destination": "/app/uploads", "Source": "/daemon/volumes/uploads/_data"},
        ]
    }
    original = Path.exists
    monkeypatch.setattr(
        Path, "exists", lambda path: True if str(path) == "/.dockerenv" else original(path)
    )
    assert (
        manager._daemon_path("/app/uploads/task/source")
        == "/daemon/volumes/uploads/_data/task/source"
    )
    with pytest.raises(ValueError, match="shared worker volume"):
        manager._daemon_path("/tmp/not-shared")

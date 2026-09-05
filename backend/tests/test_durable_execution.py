"""Real PostgreSQL regressions. TEST_DATABASE_URL must name a disposable migrated DB.
Each test creates and removes only its own rows; no schema or database is truncated.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app import worker
from app.db import session
from app.models import User, Project
from app.models.audit import AuditTask, AuditIssue
from app.models.audit_job import AuditJob
from app.models.agent_task import AgentTask, AgentEvent, AgentFinding
from app.services import audit_queue
from app.services.agent_audit import events

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="disposable PostgreSQL not configured"
)


@pytest_asyncio.fixture
async def queue_db(monkeypatch, tmp_path):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for module in [worker, session, audit_queue]:
        monkeypatch.setattr(module, "AsyncSessionLocal", factory)
    monkeypatch.setattr(worker, "engine", engine)
    monkeypatch.setattr(events, "async_session_factory", factory)
    monkeypatch.setattr(worker.settings, "AUDIT_WORKSPACE_PATH", str(tmp_path))
    monkeypatch.setattr(worker.settings, "SANDBOX_ENABLED", False)
    monkeypatch.setattr(worker.settings, "WORKER_HEARTBEAT_SECONDS", 0.05)
    user = User(email=f"{uuid4()}@example.com", hashed_password="test")
    async with factory() as db:
        db.add(user)
        await db.flush()
        project = Project(
            name="Queue regression",
            owner_id=user.id,
            source_type="repository",
            repository_url="https://example.com/source.git",
        )
        db.add(project)
        await db.commit()
    ids = []

    async def create(kind="repository", **kwargs):
        async with factory() as db:
            model = AgentTask if kind == "agent" else AuditTask
            task = model(
                project_id=project.id,
                created_by=user.id,
                task_type="agent_audit" if kind == "agent" else "repository",
                **kwargs,
            )
            db.add(task)
            await audit_queue.enqueue(db, task, kind)
            await db.commit()
            ids.append(task.id)
            return task

    yield SimpleNamespace(factory=factory, create=create, project=project, user=user, ids=ids)
    async with factory() as db:
        await db.execute(delete(AuditJob).where(AuditJob.id.in_(ids)))
        await db.execute(delete(AuditIssue).where(AuditIssue.task_id.in_(ids)))
        await db.execute(delete(AuditTask).where(AuditTask.id.in_(ids)))
        await db.execute(delete(Project).where(Project.id == project.id))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()
    await engine.dispose()


async def finish(factory, task_id, kind="repository"):
    async with factory() as db:
        model = AgentTask if kind == "agent" else AuditTask
        await db.execute(update(model).where(model.id == task_id).values(status="completed"))
        await db.commit()


async def test_enqueue_rolls_back_with_task(queue_db):
    async with queue_db.factory() as db:
        task = AuditTask(
            project_id=queue_db.project.id, created_by=queue_db.user.id, task_type="repository"
        )
        db.add(task)
        await audit_queue.enqueue(db, task, "repository")
        task_id = task.id
        await db.rollback()
    async with queue_db.factory() as db:
        assert await db.get(AuditJob, task_id) is None
        assert await db.get(AuditTask, task_id) is None


async def test_snapshot_encrypted_and_independent_of_project_changes(queue_db):
    task = await queue_db.create()
    async with queue_db.factory() as db:
        job = await db.get(AuditJob, task.id)
        assert job.payload["user_config"] != "{}"
        await db.execute(
            update(Project)
            .where(Project.id == task.project_id)
            .values(repository_url="https://example.com/changed.git")
        )
        await db.commit()
    snapshot = await audit_queue.project_snapshot(task.id, None)
    assert snapshot.repository_url == "https://example.com/source.git"


async def test_expired_lease_does_not_allow_concurrent_execution(queue_db, monkeypatch):
    task = await queue_db.create()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def execute(job):
        calls.append(job.id)
        started.set()
        await release.wait()
        await finish(queue_db.factory, job.id)

    monkeypatch.setattr(worker, "execute_payload", execute)
    running = asyncio.create_task(worker.run_job(task.id))
    await asyncio.wait_for(started.wait(), 5)
    try:
        async with queue_db.factory() as db:
            await db.execute(
                update(AuditJob)
                .where(AuditJob.id == task.id)
                .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=100))
            )
            await db.commit()
        assert await worker.run_job(task.id) is False
    finally:
        release.set()
        await asyncio.wait_for(running, 5)
    assert calls == [task.id]
    async with queue_db.factory() as db:
        job = await db.get(AuditJob, task.id)
        assert (job.status, job.attempts) == ("completed", 1)


async def test_recovery_after_lock_owner_process_dies(queue_db, monkeypatch):
    task = await queue_db.create()
    code = """import asyncio, asyncpg, sys
async def main():
 c = await asyncpg.connect(sys.argv[1])
 await c.execute('SELECT pg_advisory_lock($1)', int(sys.argv[3]))
 await c.execute("UPDATE audit_jobs SET status='running', attempts=1, lease_until=now()-interval '1 minute' WHERE id=$1", sys.argv[2])
 print('locked', flush=True)
 await asyncio.Event().wait()
asyncio.run(main())"""
    process = await asyncio.create_subprocess_exec(
        os.sys.executable,
        "-c",
        code,
        os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql"),
        task.id,
        str(audit_queue.advisory_key(task.id)),
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        assert await asyncio.wait_for(process.stdout.readline(), 10) == b"locked\n"
        assert await worker.run_job(task.id) is False
    finally:
        process.kill()
        await process.wait()

    async def execute(job):
        await finish(queue_db.factory, job.id)

    monkeypatch.setattr(worker, "execute_payload", execute)
    assert task.id in await worker.candidate_ids()
    assert await worker.run_job(task.id)
    async with queue_db.factory() as db:
        job = await db.get(AuditJob, task.id)
        assert (job.status, job.attempts) == ("completed", 2)


async def test_durable_cancel_stops_running_work(queue_db, monkeypatch):
    task = await queue_db.create()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def execute(job):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker, "execute_payload", execute)
    running = asyncio.create_task(worker.run_job(task.id))
    await asyncio.wait_for(started.wait(), 5)
    async with queue_db.factory() as db:
        await audit_queue.request_cancel(db, task.id)
        await db.commit()
    await asyncio.wait_for(running, 5)
    assert cancelled.is_set()
    async with queue_db.factory() as db:
        assert (await db.get(AuditJob, task.id)).status == "cancelled"
        assert (await db.get(AuditTask, task.id)).status == "cancelled"


@pytest.mark.parametrize(
    "state,attempts,expected", [("completed", 1, "completed"), ("pending", 3, "failed")]
)
async def test_completed_result_and_recovery_limit_never_reexecute(
    queue_db, monkeypatch, state, attempts, expected
):
    task = await queue_db.create(status=state)
    async with queue_db.factory() as db:
        await db.execute(
            update(AuditJob)
            .where(AuditJob.id == task.id)
            .values(status="running", attempts=attempts)
        )
        await db.commit()
    execute = AsyncMock()
    monkeypatch.setattr(worker, "execute_payload", execute)
    await worker.run_job(task.id)
    execute.assert_not_called()
    async with queue_db.factory() as db:
        assert (await db.get(AuditJob, task.id)).status == expected


async def test_checkpoint_and_findings_replay_are_idempotent(queue_db):
    from app.services.agent_audit.results import _save_findings

    task = await queue_db.create("agent")
    await audit_queue.save_checkpoint(task.id, project_root="/snapshot")
    await audit_queue.save_checkpoint(task.id, result={"success": True})
    assert await audit_queue.load_checkpoint(task.id) == {
        "project_root": "/snapshot",
        "result": {"success": True},
    }
    findings = [
        {
            "file_path": "app.py",
            "line": 5,
            "title": "Untrusted query",
            "severity": "high",
            "vulnerability_type": "sql_injection",
            "description": "unsafe query",
        }
    ]
    async with queue_db.factory() as db:
        await _save_findings(db, task.id, findings + findings)
        await _save_findings(db, task.id, findings)
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AgentFinding)
                .where(AgentFinding.task_id == task.id)
            )
            == 1
        )


async def test_stream_replay_broadcast_and_token_batching(queue_db):
    from app.services.agent.event_manager import EventManager, AgentEventEmitter, AgentEventData

    task = await queue_db.create("agent")
    manager = EventManager(db_session_factory=queue_db.factory)
    emitter = AgentEventEmitter(task.id, manager)
    await emitter.emit(AgentEventData(event_type="thinking_token", metadata={"token": "hello "}))
    await emitter.emit(AgentEventData(event_type="thinking_token", metadata={"token": "world"}))
    await emitter.emit(AgentEventData(event_type="task_complete", message="done"))
    await finish(queue_db.factory, task.id, "agent")
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    async def collect(cursor=0):
        return [item async for item in events.stream_events(task.id, request, cursor)]

    first, second = await asyncio.gather(collect(), collect())
    assert first == second
    assert len(first) == 3
    assert "hello world" in first[0] and "id: 2" in first[0]
    assert "id: 3" in first[1]
    assert await collect(2) == first[1:]


async def test_sql_pagination_total_and_owner_isolation(queue_db):
    from fastapi import Response
    from app.api.v1.endpoints.tasks import list_tasks
    from app.services.project_stats import project_stats

    tasks = [await queue_db.create(status="completed") for _ in range(3)]
    async with queue_db.factory() as db:
        response = Response()
        page = await list_tasks(
            response=response,
            skip=1,
            limit=1,
            status="completed",
            search="Queue",
            db=db,
            current_user=queue_db.user,
        )
        assert len(page) == 1 and response.headers["X-Total-Count"] == "3"
        assert page[0].id in {t.id for t in tasks}
        assert (
            await list_tasks(skip=0, limit=10, db=db, current_user=SimpleNamespace(id=str(uuid4())))
            == []
        )
        stats = await project_stats(db, queue_db.user.id)
        assert stats["total_tasks"] == stats["completed_tasks"] == 3
        assert stats["total_projects"] == 1


async def test_live_tree_published_for_another_api_process(queue_db, monkeypatch):
    from app.services.agent_audit import progress
    from app.services.agent_audit.runtime import _running_orchestrators
    from app.services.agent.core import agent_registry
    from app.api.v1.endpoints.agent_inspection import get_agent_tree

    task = await queue_db.create("agent", status="running")
    monkeypatch.setattr(progress, "AsyncSessionLocal", queue_db.factory)
    monkeypatch.setitem(_running_orchestrators, task.id, object())
    monkeypatch.setattr(
        agent_registry,
        "get_agent_tree",
        lambda: {
            "root_agent_id": "root",
            "nodes": {
                "root": {
                    "id": "root",
                    "name": "Orchestrator",
                    "type": "orchestrator",
                    "status": "running",
                },
            },
        },
    )
    monkeypatch.setattr(
        agent_registry,
        "get_agent",
        lambda _: SimpleNamespace(
            get_stats=lambda: {"iterations": 2, "tool_calls": 3, "tokens_used": 50}
        ),
    )
    await progress.publish_progress(task.id)
    async with queue_db.factory() as db:
        persisted = await db.get(AgentTask, task.id)
        assert (persisted.total_iterations, persisted.tool_calls_count, persisted.tokens_used) == (
            2,
            3,
            50,
        )
        tree = await get_agent_tree(task.id, db=db, current_user=queue_db.user)
        assert tree.root_agent_id == "root" and tree.running_agents == 1
        assert tree.nodes[0].agent_name == "Orchestrator"


async def test_token_batches_keep_agents_separate(queue_db):
    from app.services.agent.event_manager import EventManager

    task = await queue_db.create("agent")
    manager = EventManager(db_session_factory=queue_db.factory)
    for sequence, name in enumerate(["first", "second"], 1):
        await manager.add_event(
            task.id,
            "thinking_token",
            sequence=sequence,
            metadata={"token": name, "agent_name": name},
        )
    await manager.flush_tokens()
    async with queue_db.factory() as db:
        rows = list(
            await db.scalars(
                select(AgentEvent)
                .where(AgentEvent.task_id == task.id)
                .order_by(AgentEvent.sequence)
            )
        )
        assert [row.event_metadata for row in rows] == [
            {"token": "first", "agent_name": "first"},
            {"token": "second", "agent_name": "second"},
        ]


async def test_zip_worker_runs_real_pipeline_and_reuses_file_outputs(
    queue_db, monkeypatch, tmp_path
):
    import zipfile
    from app.services import zip_scan

    task = await queue_db.create("zip")
    source = tmp_path / "original.zip"
    with zipfile.ZipFile(source, "w") as output:
        output.writestr("app.py", 'print("hello")')
    async with queue_db.factory() as db:
        job = await db.get(AuditJob, task.id)
        job.payload = {**job.payload, "source_zip": str(source)}
        await db.commit()
    llm = SimpleNamespace(
        analyze_code=AsyncMock(
            return_value={
                "quality_score": 95,
                "issues": [
                    {"line": 1, "type": "security", "severity": "high", "title": "Test issue"},
                ],
            }
        )
    )
    monkeypatch.setattr(zip_scan, "LLMService", lambda **_: llm)
    monkeypatch.setattr(
        zip_scan, "get_analysis_config", lambda _: {"max_analyze_files": 0, "llm_gap_ms": 0}
    )
    for attempt in range(2):
        assert await worker.run_job(task.id)
        async with queue_db.factory() as db:
            persisted = await db.get(AuditTask, task.id)
            assert persisted.status == "completed"
            assert (persisted.scanned_files, persisted.issues_count, persisted.quality_score) == (
                1,
                1,
                95,
            )
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditIssue)
                    .where(AuditIssue.task_id == task.id)
                )
                == 1
            )
            if attempt == 0:
                persisted.status = "running"
                job = await db.get(AuditJob, task.id)
                job.status = "running"
                await db.commit()
    assert llm.analyze_code.await_count == 1


async def test_completed_agent_checkpoint_finishes_without_model_calls(queue_db, monkeypatch, tmp_path):
    from app.services.agent_audit import execution
    from app.services.agent.tools import SandboxManager
    from app.services.agent.agents.base import AgentResult
    task = await queue_db.create('agent')
    root = tmp_path / 'snapshot'
    root.mkdir()
    (root / 'app.py').write_text('print("hello")')
    await audit_queue.save_checkpoint(task.id, result=AgentResult(success=True, data={'findings': []}, tokens_used=15).to_dict())
    monkeypatch.setattr(execution, '_get_project_root', AsyncMock(return_value=str(root)))
    initialize_tools = AsyncMock(side_effect=AssertionError('must reuse completed result'))
    monkeypatch.setattr(execution, '_initialize_tools', initialize_tools)
    monkeypatch.setattr(SandboxManager, 'initialize', AsyncMock())
    await worker.run_job(task.id)
    initialize_tools.assert_not_called()
    async with queue_db.factory() as db:
        persisted = await db.get(AgentTask, task.id)
        assert persisted.status == 'completed'
        assert persisted.tokens_used == 15
        assert (await db.get(AuditJob, task.id)).status == 'completed'


async def test_stream_authorization_releases_database_connection(queue_db):
    from app.api.v1.endpoints.agent_events import stream_agent_events
    task = await queue_db.create('agent', status='completed')
    request = SimpleNamespace(headers={'last-event-id': '7'}, is_disconnected=AsyncMock(return_value=False))
    async with queue_db.factory() as db:
        response = await stream_agent_events(task.id, request, after_sequence=0, db=db, current_user=queue_db.user)
        assert not db.in_transaction()
        chunks = [chunk async for chunk in response.body_iterator]
        assert len(chunks) == 1 and 'id: 7' in chunks[0]

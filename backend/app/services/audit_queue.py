"""Transactional queue operations. Task creation and enqueue share one commit."""

import asyncio
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.audit_job import AuditJob


def workspace_for(task_id: str) -> Path:
    from uuid import UUID

    UUID(task_id)  # Paths never accept arbitrary request text.
    return Path(settings.AUDIT_WORKSPACE_PATH).resolve() / task_id


async def enqueue(db, task, kind: str, *, zip_path: str | None = None):
    await db.flush()
    import json
    from app.core.encryption import encrypt_sensitive_data
    from app.models.project import Project
    from app.services.user_configuration import get_user_config_dict

    configuration = await get_user_config_dict(db, task.created_by)
    payload = {"user_config": encrypt_sensitive_data(json.dumps(configuration))}
    project = await db.get(Project, task.project_id)
    if project:
        payload["project"] = {
            name: getattr(project, name)
            for name in (
                "id",
                "name",
                "source_type",
                "repository_url",
                "repository_type",
                "default_branch",
            )
        }
    if zip_path:
        directory = workspace_for(task.id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "source.zip"
        await asyncio.to_thread(shutil.copyfile, zip_path, destination)
        payload["source_zip"] = str(destination)
    db.add(AuditJob(id=task.id, kind=kind, payload=payload))


async def project_snapshot(task_id: str, fallback):
    from types import SimpleNamespace

    async with AsyncSessionLocal() as db:
        job = await db.get(AuditJob, task_id)
        project = (job.payload or {}).get("project") if job else None
        return SimpleNamespace(**project) if project else fallback


async def request_cancel(db, task_id: str):
    await db.execute(
        update(AuditJob)
        .where(AuditJob.id == task_id)
        .values(
            cancel_requested=True,
            updated_at=datetime.now(timezone.utc),
        )
    )


async def load_checkpoint(task_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        job = await db.get(AuditJob, task_id)
        return dict(job.checkpoint or {}) if job else {}


async def save_checkpoint(task_id: str, **changes):
    async with AsyncSessionLocal() as db:
        job = await db.get(AuditJob, task_id, with_for_update=True)
        if job:
            job.checkpoint = {**(job.checkpoint or {}), **changes}
            if job.kind == "agent":
                import json
                from app.models.agent_task import AgentCheckpoint

                stage = "result" if "result" in changes else "workspace"
                db.add(
                    AgentCheckpoint(
                        task_id=task_id,
                        agent_id=task_id,
                        agent_name="Audit worker",
                        agent_type="worker",
                        status="running",
                        checkpoint_type="auto",
                        checkpoint_name=stage,
                        state_data=json.dumps(changes, ensure_ascii=False),
                    )
                )
            await db.commit()


def advisory_key(task_id: str) -> int:
    return int.from_bytes(hashlib.sha256(task_id.encode()).digest()[:8], "big", signed=True)

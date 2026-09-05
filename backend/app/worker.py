"""PostgreSQL-backed worker. Each job runs in its own process and holds a DB lock.

Run `python -m app.worker`; scale by starting more workers. No API process executes jobs.
Session advisory locks prevent simultaneous execution, including after a lease expires.
"""

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text, update, or_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import engine, AsyncSessionLocal
from app.models.audit_job import AuditJob
from app.models.audit import AuditTask, AuditIssue
from app.models.agent_task import AgentTask
from app.services.audit_queue import advisory_key

logger = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled"}


def heartbeat_file():
    return Path(settings.AUDIT_WORKSPACE_PATH) / ".workers" / socket.gethostname()


def touch_heartbeat():
    path = heartbeat_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


async def cleanup_artifacts():
    from app.services.audit_queue import workspace_for
    import shutil

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.WORKER_RETENTION_DAYS)
    cursor = ""
    while True:
        async with AsyncSessionLocal() as db:
            ids = list(
                await db.scalars(
                    select(AuditJob.id)
                    .where(
                        AuditJob.status.in_(TERMINAL),
                        AuditJob.updated_at < cutoff,
                        AuditJob.id > cursor,
                    )
                    .order_by(AuditJob.id)
                    .limit(500)
                )
            )
        if not ids:
            return
        for task_id in ids:
            await asyncio.to_thread(shutil.rmtree, workspace_for(task_id), True)
        cursor = ids[-1]


def cleanup_sandboxes(job_id):
    try:
        import docker

        with docker.from_env() as client:
            for container in client.containers.list(
                all=True, filters={"label": f"deepaudit.job_id={job_id}"}
            ):
                container.remove(force=True)
    except Exception:
        logger.debug("Sandbox cleanup unavailable", exc_info=True)


async def candidate_ids() -> list[str]:
    async with AsyncSessionLocal() as db:
        result = await db.scalars(
            select(AuditJob.id)
            .where(
                or_(
                    AuditJob.status == "queued",
                    (AuditJob.status == "running")
                    & (AuditJob.lease_until < datetime.now(timezone.utc)),
                )
            )
            .order_by(AuditJob.created_at, AuditJob.id)
            .limit(100)
        )
        return list(result)


async def execute_payload(job: AuditJob):
    from app.core.encryption import decrypt_sensitive_data
    from app.services.user_configuration import get_user_config_dict
    import json

    model = AgentTask if job.kind == "agent" else AuditTask
    async with AsyncSessionLocal() as db:
        task = await db.get(model, job.id)
        encoded_config = (job.payload or {}).get("user_config")
        config = (
            json.loads(decrypt_sensitive_data(encoded_config))
            if encoded_config
            else await get_user_config_dict(db, task.created_by)
        )
    if job.kind == "agent":
        from app.services.agent_audit.execution import _execute_agent_task

        await _execute_agent_task(job.id, user_config_override=config)
        return
    from app.services.zip_storage import load_project_zip

    async with AsyncSessionLocal() as db:
        task = await db.get(AuditTask, job.id)
        config["scan_config"] = json.loads(task.scan_config or "{}")
        # Per-file LLM outputs are cached durably; replay replaces derived rows.
        await db.execute(delete(AuditIssue).where(AuditIssue.task_id == task.id))
        task.scanned_files = task.total_lines = task.issues_count = 0
        await db.commit()
        project_id = task.project_id
    if job.kind == "zip":
        from app.services.zip_scan import process_zip_task

        source = (job.payload or {}).get("source_zip") or await load_project_zip(project_id)
        if not source:
            raise ValueError("ZIP source is no longer available")
        await process_zip_task(job.id, source, AsyncSessionLocal, config)
    elif job.kind == "repository":
        from app.models.project import Project
        from app.services.agent_audit.workspace import _get_project_root
        from app.services.zip_scan import process_zip_task

        async with AsyncSessionLocal() as db:
            project = await db.get(Project, project_id)
        other = config.get("otherConfig", {})
        ssh_key = other.get("sshPrivateKey")
        root = await _get_project_root(
            project,
            job.id,
            branch_name=task.branch_name,
            github_token=other.get("githubToken") or settings.GITHUB_TOKEN,
            gitlab_token=other.get("gitlabToken") or settings.GITLAB_TOKEN,
            gitea_token=other.get("giteaToken") or settings.GITEA_TOKEN,
            ssh_private_key=decrypt_sensitive_data(ssh_key) if ssh_key else None,
        )
        await process_zip_task(job.id, None, AsyncSessionLocal, config, project_root=root)
    else:
        raise ValueError(f"Unknown job kind: {job.kind}")


async def run_job(job_id: str) -> bool:
    """Return False if another process owns the job. Lock lasts until child exit."""
    async with engine.connect() as connection:
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": advisory_key(job_id)}
        )
        await connection.commit()
        if not acquired:
            return False
        try:
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                job = await db.get(AuditJob, job_id, with_for_update=True)
                if not job or job.status in TERMINAL:
                    return True
                model = AgentTask if job.kind == "agent" else AuditTask
                task = await db.get(model, job_id)
                if not task:
                    job.status = "cancelled"
                    await db.commit()
                    return True
                if task.status in TERMINAL:
                    job.status = task.status
                    await db.commit()
                    return True
                if job.cancel_requested or job.attempts >= settings.WORKER_MAX_ATTEMPTS:
                    job.status = task.status = "cancelled" if job.cancel_requested else "failed"
                    task.completed_at = datetime.now(timezone.utc)
                    job.error = (
                        "Cancelled" if job.cancel_requested else "Worker recovery limit exceeded"
                    )
                    await db.commit()
                    return True
                job.attempts += 1
                job.status = "running"
                job.worker_id = f"{socket.gethostname()}:{os.getpid()}"
                job.lease_until = datetime.now(timezone.utc) + timedelta(
                    seconds=settings.WORKER_LEASE_SECONDS
                )
                job.updated_at = datetime.now(timezone.utc)
                await db.commit()
                timeout = (
                    getattr(task, "timeout_seconds", None) or settings.WORKER_TASK_TIMEOUT_SECONDS
                )

            os.environ["DEEPAUDIT_JOB_ID"] = job_id
            if settings.SANDBOX_ENABLED:
                await asyncio.to_thread(cleanup_sandboxes, job_id)
            touch_heartbeat()
            work = asyncio.create_task(execute_payload(job))
            monitor_error = None

            async def heartbeat():
                nonlocal monitor_error
                while not work.done():
                    await asyncio.sleep(settings.WORKER_HEARTBEAT_SECONDS)
                    try:
                        result = await connection.execute(
                            update(AuditJob)
                            .where(AuditJob.id == job_id)
                            .values(
                                lease_until=datetime.now(timezone.utc)
                                + timedelta(seconds=settings.WORKER_LEASE_SECONDS),
                                updated_at=datetime.now(timezone.utc),
                            )
                            .returning(AuditJob.cancel_requested)
                        )
                        cancelled = result.scalar_one()
                        await connection.commit()
                        touch_heartbeat()
                    except Exception:
                        # The session owns the lock. Do not let execution outlive a lost session.
                        logger.exception("Lost worker lock connection; terminating job process")
                        os._exit(75)
                    from app.services.agent_audit.runtime import _running_event_managers

                    try:
                        from app.services.agent_audit.progress import publish_progress

                        await publish_progress(job_id)
                        for event_manager in list(_running_event_managers.values()):
                            await event_manager.flush_tokens()
                    except Exception as exc:
                        monitor_error = f"Event persistence failed: {type(exc).__name__}"
                        work.cancel()
                        return
                    if cancelled:
                        from app.services.agent_audit.runtime import _cancelled_tasks
                        from app.services.scanner import task_control

                        _cancelled_tasks.add(job_id)
                        task_control.cancel_task(job_id)
                        work.cancel()
                        return

            monitor = asyncio.create_task(heartbeat())
            error = None
            try:
                done, _ = await asyncio.wait({work}, timeout=timeout)
                if not done:
                    error = f"Task timeout after {timeout} seconds"
                    work.cancel()
                await asyncio.wait_for(work, timeout=10 if not done else None)
            except asyncio.CancelledError:
                error = error or "Execution interrupted"
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:1000]}"
                logger.exception("Job %s failed", job_id)
            finally:
                monitor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await monitor
            error = monitor_error or error
            await connection.rollback()
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                current = await db.get(AuditJob, job_id, with_for_update=True)
                task = await db.get(model, job_id)
                if current.cancel_requested:
                    current.status = "cancelled"
                elif error:
                    current.status = "failed"
                else:
                    current.status = task.status if task and task.status in TERMINAL else "failed"
                current.error = error
                current.lease_until = None
                current.updated_at = datetime.now(timezone.utc)
                if task:
                    task.status = current.status
                    task.completed_at = datetime.now(timezone.utc)
                    if error and hasattr(task, "error_message"):
                        task.error_message = error
                await db.commit()
            return True
        finally:
            with contextlib.suppress(Exception):
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": advisory_key(job_id)}
                )
                await connection.commit()


async def serve():
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    last_cleanup = 0.0
    while not stopping.is_set():
        try:
            touch_heartbeat()
            if time.monotonic() - last_cleanup >= 3600:
                await cleanup_artifacts()
                last_cleanup = time.monotonic()
            candidates = await candidate_ids()
            for job_id in candidates:
                if stopping.is_set():
                    break
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "app.worker",
                    "--job",
                    job_id,
                    start_new_session=True,
                )
                done = asyncio.create_task(process.wait())
                stop = asyncio.create_task(stopping.wait())
                finished, _ = await asyncio.wait(
                    {done, stop},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=settings.WORKER_TASK_TIMEOUT_SECONDS + 60,
                )
                if not finished:
                    os.killpg(process.pid, signal.SIGKILL)
                stop.cancel()
                if stopping.is_set() and process.returncode is None:
                    # Leave status running for recovery; never mark deployment shutdown as user cancellation.
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        await asyncio.wait_for(done, timeout=10)
                    except asyncio.TimeoutError:
                        os.killpg(process.pid, signal.SIGKILL)
                        await done
                else:
                    await done
        except Exception:
            logger.exception("Worker polling failed")
        try:
            await asyncio.wait_for(stopping.wait(), timeout=settings.WORKER_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["--health"]:
        try:
            sys.exit(0 if time.time() - heartbeat_file().stat().st_mtime < 60 else 1)
        except OSError:
            sys.exit(1)
    elif len(sys.argv) == 3 and sys.argv[1] == "--job":
        asyncio.run(run_job(sys.argv[2]))
    else:
        asyncio.run(serve())

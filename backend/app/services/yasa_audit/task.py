"""Run a DeepAudit agent task in YASA hybrid mode (task.audit_scope["mode"] == "yasa").

Stages, all bounded by one wall-clock budget (task.timeout_seconds, default 30 min):
  1. yasa-mcp navigation cache
  2. dataflow (agent builds engine rules -> YASA -> grouped triage)  } run side by side
  3. access control (deterministic route table -> grouped review)   }
Findings are saved through the regular agent_tasks._save_findings path, so the existing task pages,
reports and finding status workflow work unchanged.

agent_tasks passes its helpers in (save_findings, score, is_cancelled) to avoid an import cycle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from .config import AuditConfig
from .runner import (
    check_tools,
    init_navigation,
    run_authz,
    run_dataflow,
    split_workers,
    summarize,
    to_deepaudit_findings,
)

logger = logging.getLogger(__name__)
SOURCE_EXT = {".java", ".jsp", ".jspx", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "target", "vendor"}


def count_sources(root: Path) -> int:
    """Files the pipeline can analyse (Java/JSP, JS/TS), for the task's file counter."""
    n = 0
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        n += sum(1 for f in files if os.path.splitext(f)[1] in SOURCE_EXT)
    return n


RUNS_DIR = Path(os.environ.get("YASA_AUDIT_RUNS_DIR", "/tmp/deepaudit-yasa-runs"))


def config_from_llm(llm_config, workers: int = 6) -> AuditConfig:
    """AuditConfig from DeepAudit's resolved LLMConfig (user settings, then environment)."""
    cfg = AuditConfig()
    base = llm_config.base_url or ("https://api.openai.com/v1" if str(llm_config.provider).lower()
                                   .endswith("openai") else "")
    cfg.llm_base_url = base or cfg.llm_base_url
    cfg.llm_api_key = llm_config.api_key or cfg.llm_api_key
    cfg.llm_model = llm_config.model or cfg.llm_model
    cfg.llm_timeout_s = float(llm_config.timeout or cfg.llm_timeout_s)
    cfg.llm_temperature = float(llm_config.temperature if llm_config.temperature is not None
                                else cfg.llm_temperature)
    cfg.llm_max_tokens = int(llm_config.max_tokens or cfg.llm_max_tokens)
    cfg.workers = workers
    return cfg


async def execute_yasa_task(
    db, task, project_root: str, llm_config, emitter,
    is_cancelled: Callable[[], bool],
    save_findings: Callable[..., Awaitable[int]],
    score: Callable[[list], float],
) -> None:
    from app.models.agent_task import AgentTaskPhase, AgentTaskStatus

    scope = task.audit_scope or {}
    stages = scope.get("stages") or ["dataflow", "authz"]
    deploy = scope.get("deploy") or ""
    product = scope.get("product") or ""
    budget_s = int(task.timeout_seconds or 1800)

    cfg = config_from_llm(llm_config, workers=int(scope.get("workers") or 6))
    cfg.should_stop = is_cancelled
    cfg.time_budget_s = budget_s
    missing = check_tools(cfg)
    if missing:
        raise RuntimeError("YASA tools not found (run backend/scripts/setup_yasa.sh): " + ", ".join(missing))
    if not (cfg.llm_base_url and cfg.llm_api_key and cfg.llm_model):
        raise RuntimeError("YASA mode needs an OpenAI-compatible LLM (base URL, API key, model)")

    root = Path(project_root).resolve()
    task.total_files = count_sources(root)
    out = RUNS_DIR / task.id
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()
    deadline = start + budget_s

    await emitter.emit_phase_start("indexing", "🧭 YASA: building navigation cache")
    task.current_phase = AgentTaskPhase.INDEXING
    await db.commit()
    try:
        await asyncio.to_thread(init_navigation, cfg, root, min(600, budget_s // 3))
    except Exception as e:  # nav tools degrade to grep/read; the engine still runs
        logger.warning("yasa-mcp init failed: %s", e)
        await emitter.emit_warning(f"yasa-mcp init failed, navigation tools limited: {e}")

    if is_cancelled():
        raise asyncio.CancelledError("任务已取消")

    df_cfg, az_cfg = split_workers(cfg) if len(stages) > 1 else (cfg, cfg)
    await emitter.emit_phase_start("analysis", f"🔬 YASA: {' + '.join(stages)}, budget {budget_s // 60} min")
    task.current_phase = AgentTaskPhase.ANALYSIS
    await db.commit()

    async def stage(name: str, fn, *args):
        if name not in stages:
            return None
        try:
            r = await asyncio.to_thread(fn, *args)
        except Exception as e:
            logger.error("yasa %s stage failed: %s", name, e, exc_info=True)
            await emitter.emit_error(f"YASA {name} stage failed: {e}")
            return None
        await emitter.emit_info(f"✅ YASA {name}: {len(r['findings'])} candidates reviewed, "
                                f"{sum(f.get('verdict') in ('confirmed', 'likely') for f in r['findings'])} "
                                f"reported, {len(r['not_reviewed'])} not reviewed")
        return r

    df, az = await asyncio.gather(
        stage("dataflow", run_dataflow, df_cfg, root, out, deploy, start, deadline),
        stage("authz", run_authz, az_cfg, root, out, deploy, product, deadline))
    if is_cancelled():
        raise asyncio.CancelledError("任务已取消")
    if df is None and az is None:
        raise RuntimeError("all YASA stages failed")

    findings = (to_deepaudit_findings(df["findings"], "dataflow") if df else []) + \
               (to_deepaudit_findings(az["findings"], "authz") if az else [])
    m = summarize(df, az, start)
    if m["not_reviewed"]:
        await emitter.emit_warning(f"⏱ time budget reached: {len(m['not_reviewed'])} candidates not "
                                   f"reviewed (listed in {out})")

    await db.refresh(task)
    saved = await save_findings(db, task.id, findings, project_root=str(root))
    task.status = AgentTaskStatus.COMPLETED
    task.completed_at = datetime.now(UTC)
    task.current_phase = AgentTaskPhase.REPORTING
    task.findings_count = saved
    task.tokens_used = m["tokens"]
    task.analyzed_files = task.total_files
    task.files_with_findings = len({f["file_path"] for f in findings if f.get("file_path")})
    for f in findings:
        attr = f"{f['severity']}_count"
        if hasattr(task, attr):
            setattr(task, attr, (getattr(task, attr) or 0) + 1)
    task.verified_count = 0
    task.security_score = task.quality_score = score(findings)
    await db.commit()
    await emitter.emit_task_complete(findings_count=saved, duration_ms=int(m["wall_s"] * 1000))
    logger.info("YASA task %s done: %s", task.id, m)

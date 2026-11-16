"""Run a DeepAudit agent task in YASA mode (task.audit_scope["mode"] == "yasa").

Stages, all bounded by one wall-clock budget (task.timeout_seconds, default 30 min):
  1. code index (codegraph: calls, inheritance, routes; seconds to a minute)
  2. route reconnaissance: an agent works out the project's entry points
  3. one review per entry: scenario, access control, plausible risks traced to a verdict
Findings are saved through the regular agent_tasks._save_findings path, so the existing task pages,
reports and finding status workflow work unchanged.

agent_tasks passes its helpers in (save_findings, score, is_cancelled) to avoid an import cycle.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import shutil
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from .config import AuditConfig
from .discovery import snapshot_codegraph
from .runner import check_tools, init_navigation, run_entry_audit, to_deepaudit_findings

logger = logging.getLogger(__name__)
SOURCE_EXT = {".java", ".jsp", ".jspx", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".py", ".php",
              ".phtml"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "target", "vendor", "venv", ".venv", "__pycache__"}


def count_sources(root: Path) -> int:
    """Files the pipeline can analyse (Java/JSP, JS/TS, Python, PHP), for the task's file counter."""
    n = 0
    for _dir, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        n += sum(1 for f in files if os.path.splitext(f)[1] in SOURCE_EXT)
    return n


def _excluded(rel: str, patterns: list[str]) -> bool:
    """Same matching as DeepAudit's file tools: full relative path or basename, fnmatch."""
    name = os.path.basename(rel)
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(name, p) for p in patterns)


def scope_tree(root: Path, dest: Path, exclude_patterns: list[str] | None,
               target_files: list[str] | None) -> tuple[Path, int]:
    """Apply the task's exclude patterns and target files.

    Returns (directory to audit, number of files left out). When nothing is left out the project
    directory is used as is; otherwise the kept files are copied (same relative paths) into dest,
    so engine, navigation cache and agents all see the same scope.
    """
    patterns = [p.strip() for p in (exclude_patterns or []) if p and p.strip()]
    targets = {t.strip().lstrip("./") for t in (target_files or []) if t and t.strip()}
    dir_patterns = [p[:-3] if p.endswith("/**") else p for p in patterns]
    keep: list[str] = []
    dropped = 0
    for d, dirs, files in os.walk(root):
        rel_dir = os.path.relpath(d, root)
        rel_dir = "" if rel_dir == "." else rel_dir
        pruned = [x for x in dirs if _excluded(os.path.join(rel_dir, x), dir_patterns)]
        for x in pruned:
            dropped += sum(len(f) for _, _, f in os.walk(os.path.join(d, x)))
        dirs[:] = [x for x in dirs if x not in pruned]
        for f in files:
            rel = os.path.join(rel_dir, f)
            if _excluded(rel, patterns) or (targets and rel not in targets):
                dropped += 1
            else:
                keep.append(rel)
    if not dropped:
        return root, 0
    if dest.exists():
        shutil.rmtree(dest)
    for rel in keep:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dest / rel)
    dest.mkdir(parents=True, exist_ok=True)
    return dest, dropped


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
    deploy = scope.get("deploy") or ""
    product = scope.get("product") or ""
    budget_s = int(task.timeout_seconds or 1800)

    cfg = config_from_llm(llm_config, workers=int(scope.get("workers") or 16))
    cfg.should_stop = is_cancelled
    cfg.time_budget_s = budget_s
    missing = check_tools(cfg)
    if missing:
        raise RuntimeError("YASA tools not found (run backend/scripts/setup_yasa.sh): " + ", ".join(missing))
    if not (cfg.llm_base_url and cfg.llm_api_key and cfg.llm_model):
        raise RuntimeError("YASA mode needs an OpenAI-compatible LLM (base URL, API key, model)")

    project_dir = Path(project_root).resolve()
    out = RUNS_DIR / task.id
    out.mkdir(parents=True, exist_ok=True)
    root, dropped = scope_tree(project_dir, out / "src", getattr(task, "exclude_patterns", None),
                               getattr(task, "target_files", None))
    task.total_files = count_sources(root)
    start = time.time()
    deadline = start + budget_s

    if dropped:
        await emitter.emit_info(f"YASA scope: {dropped} files left out by exclude patterns / target files")
    await emitter.emit_phase_start("indexing", "🧭 YASA: building code index")
    task.current_phase = AgentTaskPhase.INDEXING
    await db.commit()
    # codegraph indexes even large projects in seconds to a minute; without an index the agents
    # still work with grep / read_file, so a failure is reported and the stages go on.
    t0 = time.time()
    try:
        await asyncio.to_thread(init_navigation, cfg, root, min(600, budget_s // 4), is_cancelled)
        await emitter.emit_info(f"🧭 code index ready after {time.time() - t0:.0f}s")
    except Exception as e:
        logger.warning("code index failed: %s", e)
        await emitter.emit_warning(f"code index failed, navigation limited to grep/read_file: {e}")
    try:  # one consistent copy for all stages
        await asyncio.to_thread(snapshot_codegraph, root, out)
    except Exception as e:
        logger.warning("codegraph snapshot failed: %s", e)

    if is_cancelled():
        raise asyncio.CancelledError("任务已取消")

    await emitter.emit_phase_start("analysis", f"🔬 YASA: route reconnaissance + entry review, "
                                               f"budget {budget_s // 60} min")
    task.current_phase = AgentTaskPhase.ANALYSIS
    await db.commit()
    r = await asyncio.to_thread(run_entry_audit, cfg, root, out, deploy, product, start, deadline)
    if is_cancelled():
        raise asyncio.CancelledError("任务已取消")
    rec, rv = r["recon"], r["review"]
    await emitter.emit_info(f"🧭 recon: {rec.get('entries', 0)} entries ({rec.get('resolved', 0)} resolved to code)")
    await emitter.emit_info(f"✅ review: {rv['reviewed_units']} of {rv['units']} handlers reviewed, "
                            f"{sum(f.get('verdict') in ('confirmed', 'likely') for f in r['findings'])} reported")
    if rv.get("operation_units") or rv.get("design_units"):
        open_items = sum(i["status"] in ("flaw", "owner_decision", "unclear")
                         for d in r.get("design_worksheet", []) for i in d["items"])
        await emitter.emit_info(f"🎯 sensitive operations: {rv.get('reviewed_operation_units', 0)} of "
                                f"{rv.get('operation_units', 0)} units reviewed; identity design: "
                                f"{rv.get('reviewed_design_units', 0)} subsystems, {open_items} checklist items "
                                f"for a human decision (design_worksheet in {out / 'review' / 'findings.json'})")
    findings = to_deepaudit_findings(r["findings"])
    if r["not_reviewed"]:
        await emitter.emit_warning(f"⏱ time budget reached: {len(r['not_reviewed'])} entries not "
                                   f"reviewed (listed in {out / 'review' / 'findings.json'})")

    await db.refresh(task)
    saved = await save_findings(db, task.id, findings, project_root=str(project_dir))
    task.status = AgentTaskStatus.COMPLETED
    task.completed_at = datetime.now(UTC)
    task.current_phase = AgentTaskPhase.REPORTING
    task.findings_count = saved
    task.tokens_used = r["tokens"]
    task.analyzed_files = task.total_files
    task.files_with_findings = len({f["file_path"] for f in findings if f.get("file_path")})
    for f in findings:
        attr = f"{f['severity']}_count"
        if hasattr(task, attr):
            setattr(task, attr, (getattr(task, attr) or 0) + 1)
    task.verified_count = 0
    task.security_score = task.quality_score = score(findings)
    await db.commit()
    await emitter.emit_task_complete(findings_count=saved, duration_ms=int((time.time() - start) * 1000))
    logger.info("YASA task %s done: %s", task.id, {k: v for k, v in r.items() if k != "findings"})

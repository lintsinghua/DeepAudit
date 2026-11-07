"""Glue between the YASA hybrid pipeline and DeepAudit's task system.

The pipeline itself is synchronous (threads + blocking HTTP). DeepAudit calls these helpers through
asyncio.to_thread and emits task events between stages. `to_deepaudit_findings` maps pipeline
findings to the dict shape that agent_tasks._save_findings understands.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .config import AuditConfig
from .pipeline import authz, build, triage

REPORTED = ("confirmed", "likely")

# CWE -> (DeepAudit vulnerability_type, default severity)
CWE_MAP: dict[str, tuple[str, str]] = {
    "CWE-89": ("sql_injection", "high"),
    "CWE-943": ("nosql_injection", "high"),
    "CWE-79": ("xss", "medium"),
    "CWE-78": ("command_injection", "critical"),
    "CWE-77": ("command_injection", "critical"),
    "CWE-94": ("code_injection", "critical"),
    "CWE-95": ("code_injection", "critical"),
    "CWE-22": ("path_traversal", "high"),
    "CWE-23": ("path_traversal", "high"),
    "CWE-73": ("path_traversal", "high"),
    "CWE-918": ("ssrf", "high"),
    "CWE-611": ("xxe", "high"),
    "CWE-502": ("deserialization", "critical"),
    "CWE-601": ("business_logic", "medium"),
    "CWE-1321": ("code_injection", "high"),
    "CWE-347": ("auth_bypass", "high"),
    "CWE-287": ("auth_bypass", "high"),
    "CWE-306": ("auth_bypass", "high"),
    "CWE-862": ("auth_bypass", "high"),
    "CWE-863": ("auth_bypass", "high"),
    "CWE-284": ("auth_bypass", "high"),
    "CWE-285": ("auth_bypass", "high"),
    "CWE-639": ("idor", "high"),
    "CWE-200": ("sensitive_data_exposure", "medium"),
    "CWE-538": ("sensitive_data_exposure", "medium"),
    "CWE-548": ("sensitive_data_exposure", "medium"),
    "CWE-552": ("sensitive_data_exposure", "medium"),
    "CWE-798": ("hardcoded_secret", "high"),
    "CWE-327": ("weak_crypto", "medium"),
    "CWE-328": ("weak_crypto", "medium"),
}
LOWER = {"critical": "high", "high": "medium", "medium": "low", "low": "low"}


def check_tools(cfg: AuditConfig) -> list[str]:
    """Names of missing executables (empty when the pipeline can run)."""
    missing = []
    for name, path in (("YASA_BIN", cfg.yasa_bin), ("YASAMCP_BIN", cfg.yasamcp_bin),
                       ("YASA_RG_BIN", cfg.rg_bin)):
        if not (Path(path).is_file() or shutil.which(path)):
            missing.append(f"{name}={path}")
    return missing


def init_navigation(cfg: AuditConfig, root: Path, timeout_s: int = 600) -> None:
    """Bound the whole navigation process tree, including native engine children."""
    command = [cfg.yasamcp_bin, "init", str(root), "--no-progress", "-b", cfg.yasamcp_tools_dir]
    log_path = root / ".yasa" / "navigation-init.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        with subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True) as process:
            try:
                code = process.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                # Killing only the CLI leaves its YASA/codegraph children running indefinitely.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise RuntimeError(f"yasa-mcp init timed out after {timeout_s}s; navigation process "
                                   f"group stopped; log: {log_path}") from exc
    if code:
        raise RuntimeError(f"yasa-mcp init exited with code {code}; log: {log_path}")


def _load(out: Path) -> dict:
    p = out / "findings.json"
    return json.loads(p.read_text()) if p.exists() else {"findings": [], "not_reviewed": []}


def run_dataflow(cfg: AuditConfig, root: Path, out: Path, deploy: str, start: float,
                 deadline: float) -> dict:
    """Build stage (rules + engine) then grouped triage. Returns metrics plus raw findings."""
    build_deadline = start + cfg.build_share * (deadline - start)
    b = build(cfg, root, out / "build", deploy, build_deadline)
    t = triage(cfg, root, out / "build", out / "triage", "file", deploy, deadline)
    data = _load(out / "triage")
    return {"build": b, "triage": t, "findings": data["findings"],
            "not_reviewed": data.get("not_reviewed", []),
            "tokens": b["prompt_tokens"] + b["completion_tokens"]
            + t["prompt_tokens"] + t["completion_tokens"]}


def run_authz(cfg: AuditConfig, root: Path, out: Path, deploy: str, product: str,
              deadline: float) -> dict:
    m = authz(cfg, root, out / "authz", deploy, product, deadline=deadline)
    data = _load(out / "authz")
    return {"authz": m, "findings": data["findings"], "not_reviewed": data.get("not_reviewed", []),
            "tokens": m["prompt_tokens"] + m["completion_tokens"]}


def split_workers(cfg: AuditConfig) -> tuple[AuditConfig, AuditConfig]:
    """Dataflow and access-control stages run side by side; give authz about a third."""
    a = max(1, cfg.workers // 3)
    return (dataclasses.replace(cfg, workers=max(1, cfg.workers - a)),
            dataclasses.replace(cfg, workers=a))


def _describe(f: dict, stage: str) -> str:
    parts = [f"[yasa_audit/{stage}] verdict: {f.get('verdict')}"]
    for key, label in (("source", "Source"), ("entry", "Entry"), ("sanitizers", "Guards/sanitizers")):
        if f.get(key):
            parts.append(f"{label}: {f[key]}")
    if f.get("hops"):
        parts.append("Path:\n" + "\n".join(f"  {i + 1}. {h}" for i, h in enumerate(f["hops"])))
    if f.get("yasa_ref"):
        parts.append(f"Engine evidence: {f['yasa_ref']}")
    return "\n".join(parts)


def to_deepaudit_findings(findings: list[dict], stage: str) -> list[dict]:
    """Reported (confirmed/likely) pipeline findings in agent_tasks._save_findings' input shape.

    The pipeline's 'confirmed' is an LLM triage verdict, not a sandbox verification, so it maps to
    confidence rather than to is_verified.
    """
    out, seen = [], set()
    for f in findings:
        if f.get("verdict") not in REPORTED:
            continue
        cwe = (f.get("cwe") or "").upper().replace(" ", "")
        key = (f.get("sink_file"), f.get("sink_line"), cwe)
        if key in seen:
            continue
        seen.add(key)
        vtype, sev = CWE_MAP.get(cwe, ("other", "medium"))
        if f.get("verdict") == "likely":
            sev = LOWER[sev]
        line = f.get("sink_line")
        out.append({
            "title": f"{f.get('vuln_type') or vtype} ({cwe or 'CWE-?'})",
            "vulnerability_type": vtype,
            "severity": sev,
            "file_path": f.get("sink_file"),
            "line_start": int(line) if str(line or "").isdigit() else None,
            "description": _describe(f, stage),
            "confidence": 0.85 if f.get("verdict") == "confirmed" else 0.6,
            "cwe_id": cwe or None,
            "verification_method": f"yasa_audit {stage} triage (static, not executed)",
        })
    return out


def summarize(df: dict | None, az: dict | None, start: float) -> dict:
    m: dict = {"wall_s": round(time.time() - start, 1), "tokens": 0, "not_reviewed": []}
    for part in (df, az):
        if part:
            m["tokens"] += part["tokens"]
            m["not_reviewed"] += part["not_reviewed"]
    if df:
        m["engine_candidates"] = df["triage"].get("engine_candidates", 0)
        m["dataflow_units"] = df["triage"].get("units", 0)
        m["yasa_runs"] = df["build"].get("yasa_runs", 0)
    if az:
        m["authz_entries"] = az["authz"].get("entries", 0)
    return m

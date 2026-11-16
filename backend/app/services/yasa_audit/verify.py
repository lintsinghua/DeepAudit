"""Refutation check: one fresh, sceptical agent per reported root cause.

Reviewers work one entry at a time under a step budget, and the most severe claims are the ones most
often wrong in the same way: the reviewer stopped one layer short of the check that stops the attack
(a model-level permission hook, schema validation that strips unknown fields, a global identifier
format, an output serializer, a guarded HTTP client). Each root cause gets an agent whose only task is
to find that check, reading the whole path. Its conclusion needs code quotes:

- refuted: the finding leaves the report (kept in findings.json under "refuted", with the reason);
- by_design: the path holds, but what it gives is within the designed power (access model) of the least
  privileged principal that can take it: the finding leaves the report, kept under "by_design" with that
  principal and the project's grant;
- upheld: the finding stays, marked verified;
- uncertain (or not checked in time): the finding stays, marked as not verified.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import pipeline
from .agent_loop import run_agent
from .config import AuditConfig
from .pipeline import _schedule
from .prompts import verify_prompt
from .toolbox import Toolbox, tool_schemas

PRIVILEGE_ORDER = {"public": 0, "none": 0, "authenticated": 1, "customer": 1, "privileged": 2, "admin": 2,
                   "operator_or_cli": 3}
CLAIM_FIELDS = ("title", "vuln_type", "cwe", "verdict", "required_privilege", "entry", "source", "sink_file",
                "sink_line", "root_cause", "impact", "route_evidence", "path", "evidence", "description")


def _groups(findings: list[dict]) -> list[tuple[str, list[dict]]]:
    """Findings by root cause (issue id), most exposed and most repeated first."""
    by: dict[str, list[dict]] = {}
    for n, f in enumerate(findings):
        by.setdefault(str(f.get("issue") or f"F{n + 1}"), []).append(f)
    return sorted(by.items(), key=lambda kv: (min(PRIVILEGE_ORDER.get(str(f.get("required_privilege")), 2)
                                                  for f in kv[1]), -len(kv[1]), kv[0]))


def _claim(iid: str, fs: list[dict]) -> str:
    rows = [{k: f.get(k) for k in CLAIM_FIELDS if f.get(k) not in (None, "", [])} for f in fs[:3]]
    more = f"\n({len(fs) - 3} more findings with the same root cause on other entries)" if len(fs) > 3 else ""
    return (f"Reported vulnerability {iid} ({len(fs)} finding(s) with this root cause). The reviewer's "
            "report, as data:\n" + json.dumps(rows, ensure_ascii=False, indent=1)[:9000] + more +
            "\n\nTry to refute it, then conclude.")


def _check(cfg: AuditConfig, root: Path, out: Path, iid: str, fs: list[dict], system: str,
           deadline: float | None, resolver: str | None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tb = Toolbox(cfg, root, out, unit=f"verify-{iid}")
    tb.resolver_code = resolver
    tb.finish_gates = [(lambda t: t.conclusion is None, "conclude first (upheld, refuted, by_design or uncertain)",
                        ["conclude"])]
    llm = pipeline.LLM(cfg)  # resolved at call time (tests replace it)
    res = run_agent(llm, tb, tool_schemas("verify"), system, _claim(iid, fs), cfg.verify_budget,
                    out / "transcript.jsonl", deadline=deadline)
    u = llm.usage
    return {"issue": iid, "conclusion": tb.conclusion or {"verdict": "uncertain",
                                                          "reason": "no conclusion within the budget"},
            "steps": res.get("steps"), "prompt_tokens": u.prompt, "completion_tokens": u.completion,
            "cached_tokens": u.cached, "findings": [], "cards": []}


def verify(cfg: AuditConfig, root: Path, review_dir: Path, deploy: str = "", product: str = "",
           access_model: dict | None = None, resolver: str | None = None,
           deadline: float | None = None) -> dict:
    """Check every root cause in review_dir/findings.json and rewrite it: refuted findings move to
    'refuted', those within a designed power to 'by_design'; kept ones carry 'verification'.
    Returns metrics."""
    t0 = time.time()
    path = review_dir / "findings.json"
    data = json.loads(path.read_text())
    findings = [f for f in data.get("findings", []) if f.get("verdict") in ("confirmed", "likely")]
    groups = _groups(findings)
    if not groups:
        return {"root_causes": 0}
    system = verify_prompt(cfg.verify_budget, deploy, product, access_model)
    out = review_dir / "verify"
    results, skipped = _schedule(
        groups, lambda i, g: _check(cfg, root, out / g[0], g[0], g[1], system, deadline, resolver),
        cfg.workers, deadline, cfg.stopped)
    conclusions = {r["issue"]: r["conclusion"] for r in results if r.get("issue")}
    for iid, _ in skipped:
        conclusions[iid] = {"verdict": "uncertain", "reason": "not checked: time budget"}
    out_of: dict[str, list[dict]] = {"refuted": [], "by_design": []}
    kept = []
    for iid, fs in groups:
        c = conclusions.get(iid, {"verdict": "uncertain", "reason": "not checked"})
        for f in fs:
            f["verification"] = c
            out_of.get(c["verdict"], kept).append(f)
    data["findings"] = kept + [f for f in data.get("findings", []) if f not in findings]
    for k, fs in out_of.items():
        data[k] = data.get(k, []) + fs
    refuted = out_of["refuted"]
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    (review_dir / "verify.json").write_text(json.dumps(conclusions, indent=1, ensure_ascii=False))
    verdicts: dict[str, int] = {}
    for c in conclusions.values():
        verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1
    s = lambda k: sum(r.get(k, 0) or 0 for r in results)  # noqa: E731
    return {"root_causes": len(groups), "verdicts": verdicts, "findings_kept": len(kept),
            "findings_refuted": len(refuted), "findings_by_design": len(out_of["by_design"]),
            "steps": s("steps"), "prompt_tokens": s("prompt_tokens"),
            "completion_tokens": s("completion_tokens"), "cached_tokens": s("cached_tokens"),
            "wall_s": round(time.time() - t0, 1)}

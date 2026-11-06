"""Hybrid audit pipeline (mode C) and the trace baseline (mode A).

Stage 1 build   : an agent writes a YASA ruleConfig for this project and runs the engine (<= 2 runs).
Stage 2 triage  : every engine finding is triaged in a fresh, bounded context, grouped by file.
Stage 3 residual: sink sites from a deterministic L0 inventory that the engine did not report
                  (after a constant-argument prefilter) are traced back to a source, grouped by file.
Stages 2 and 3 run as one batch of per-file units.
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .agent_loop import run_agent
from .config import AuditConfig
from .entrypoints import entries_for, global_guards_for
from .llm import LLM
from .prompts import authz_prompt, builder_prompt, trace_prompt, triage_prompt
from .toolbox import Toolbox, tool_schemas

L0_SINKS: dict[str, list[tuple[str, str]]] = {
    "ts": [
        (r"\.query\s*\(\s*`", "CWE-89"), (r"sequelize\.query\(", "CWE-89"),
        (r"\$where", "CWE-943"), (r"Collection\.(find|findOne|update|remove)\(", "CWE-943"),
        (r"\beval\s*\(", "CWE-94"), (r"vm\.runIn\w*Context\(", "CWE-94"), (r"new Function\(", "CWE-94"),
        (r"pug\.compile|pug\.render|ejs\.render|res\.render\(", "CWE-1336"),
        (r"child_process|\bexecSync\(|\bspawn\(", "CWE-78"),
        (r"res\.sendFile\(|createReadStream\(|createWriteStream\(|readFileSync\(|writeFileSync\(",
         "CWE-22"),
        (r"\bfetch\(|axios\.|request\(|http\.get\(", "CWE-918"),
        (r"yaml\.load\(|libxml|parseXml|XmlDocument", "CWE-611"),
        (r"res\.redirect\(", "CWE-601"),
        (r"bypassSecurityTrust|innerHTML", "CWE-79"),
    ],
    "java": [
        (r"\.execute(Query|Update)?\s*\(", "CWE-89"),
        (r"Runtime\.getRuntime\(\)\.exec|ProcessBuilder", "CWE-78"),
        (r"new File\(|FileInputStream\(|Paths\.get\(", "CWE-22"),
        (r"openConnection\(|HttpClient", "CWE-918"),
        (r"<%=", "CWE-79"), (r"sendRedirect\(", "CWE-601"), (r"readObject\(", "CWE-502"),
    ],
}
GLOBS = {"ts": ["*.ts", "*.js"], "java": ["*.java", "*.jsp"]}

MODULE_NAMES = {"path", "fs", "os", "JSON", "Math", "console", "process", "Buffer", "Object", "Array",
                "String", "Number", "Date", "Promise", "require", "true", "false", "null", "undefined",
                "this", "new", "await"}
STR_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\$]|\$(?!\{))*`")
ID_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)(?=\s*(\(|\.|))")


def detect_lang(root: Path) -> str:
    counts = {"ts": 0, "java": 0}
    for p in root.rglob("*"):
        if any(part in {"node_modules", ".git", ".yasa", ".codegraph"} for part in p.parts):
            continue
        if p.suffix in (".ts", ".js"):
            counts["ts"] += 1
        elif p.suffix in (".java", ".jsp"):
            counts["java"] += 1
    return max(counts, key=lambda k: counts[k])


def is_constant_call(code: str, pat: str) -> bool:
    """True when the arguments after the sink match contain no variable (literals, module names and
    function names only), e.g. res.sendFile(path.resolve('frontend/index.html'))."""
    m = re.search(pat, code)
    if not m:
        return False
    rest = code[m.end():]
    if "(" not in code[m.start():m.end()] and "(" in rest:
        rest = rest[rest.index("(") + 1:]
    rest = STR_RE.sub("", rest)
    for idm in ID_RE.finditer(rest):
        name, follow = idm.group(1), idm.group(2)
        if follow == "(" or name in MODULE_NAMES:
            continue
        return False
    return True


def inventory(tb: Toolbox, lang: str, extra_fsigs: list[str]) -> list[dict]:
    """Deterministic sink inventory: L0 patterns plus wrapper sinks named in the builder's rules."""
    pats = list(L0_SINKS[lang]) + [(re.escape(f.split(".")[-1]) + r"\s*\(", "wrapper")
                                   for f in extra_fsigs]
    hits: dict[tuple[str, int], dict] = {}
    for pat, cwe in pats:
        for g in GLOBS[lang]:
            for line in tb.grep(pat, glob=g, max_results=400).splitlines():
                m = re.match(r"^([^:]+):(\d+):(.*)$", line)
                if not m or "test" in m.group(1).lower() or is_constant_call(m.group(3), pat):
                    continue
                key = (m.group(1), int(m.group(2)))
                hits.setdefault(key, {"file": key[0], "line": key[1], "code": m.group(3).strip()[:200],
                                      "classes": set()})
                hits[key]["classes"].add(cwe)
    return list(hits.values())


# Lower is reviewed first: engine findings, then residual sinks by how bad the class usually is.
CLASS_RANK = {"CWE-94": 1, "CWE-78": 1, "CWE-89": 1, "CWE-943": 1, "CWE-502": 1,
              "CWE-611": 2, "CWE-22": 2, "CWE-918": 2, "CWE-1336": 2, "wrapper": 2,
              "CWE-79": 3, "CWE-601": 3}
MIN_UNIT_S = 90  # do not start a unit with less time left than this


def _cand_rank(c: dict) -> int:
    if c["origin"].startswith("engine:"):
        return 0
    return min((CLASS_RANK.get(k, 3) for k in c.get("suspected_classes", [])), default=3)


def _schedule(units: list, work, workers: int, deadline: float | None) -> tuple[list[dict], list]:
    """Run work(i, unit) for units in order with a thread pool. Units that would start with less
    than MIN_UNIT_S left before the deadline are skipped and returned separately."""
    skipped: list = []
    lock = threading.Lock()

    def guarded(i_unit: tuple[int, object]) -> dict | None:
        i, unit = i_unit
        if deadline is not None and time.time() > deadline - MIN_UNIT_S:
            with lock:
                skipped.append(unit)
            return None
        try:
            return work(i, unit)
        except Exception as e:  # keep the batch going
            return {"findings": [], "prompt_tokens": 0, "completion_tokens": 0, "steps": 0,
                    "error": str(e)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = [r for r in ex.map(guarded, enumerate(units)) if r is not None]
    return results, skipped


def _metrics(llm: LLM, extra: dict) -> dict:
    return {"prompt_tokens": llm.usage.prompt, "completion_tokens": llm.usage.completion,
            "llm_calls": llm.usage.calls, **extra}


def build(cfg: AuditConfig, root: Path, out: Path, deploy: str = "",
          deadline: float | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tb = Toolbox(cfg, root, out, enable_yasa=True)
    tb.deadline = deadline
    tools = tool_schemas(enable_yasa=True, with_report=False)
    llm = LLM(cfg)
    res = run_agent(llm, tb, tools, builder_prompt(cfg.builder_budget, cfg.builder_max_yasa_runs, deploy),
                    f"Build engine rules for the project. Top-level listing:\n{tb.list_dir('.', 1)}",
                    cfg.builder_budget, out / "transcript.jsonl", deadline=deadline)
    m = _metrics(llm, {"stage": "build", "yasa_runs": tb.yasa_runs,
                       "engine_findings": len(tb.registry), **res})
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    return m


def _wrapper_sinks(engine_dir: Path, lang: str) -> list[str]:
    generic = {"print", "write", "append", "execute", "send", "json", "log"}
    found = set()
    for rc in sorted(engine_dir.glob("yasa-*/rule_config.json")):
        for block in json.loads(rc.read_text()):
            for s in (block.get("sinks") or {}).get("FuncCallTaintSink", []):
                fsig = s.get("fsig", "")
                probe = "x." + fsig + "(`"
                if fsig and fsig.split(".")[-1] not in generic and not any(
                        re.search(p, probe) for p, _ in L0_SINKS[lang]):
                    found.add(fsig)
    return sorted(found)


def _triage_unit(cfg: AuditConfig, root: Path, out: Path, unit: dict, budget: int, deploy: str,
                 deadline: float | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    tb = Toolbox(cfg, root, out, enable_yasa=False)
    tools = [t for t in tool_schemas(enable_yasa=False) if t["function"]["name"] != "list_dir"]
    llm = LLM(cfg)
    res = run_agent(llm, tb, tools, triage_prompt(budget, deploy),
                    json.dumps(unit, ensure_ascii=False, indent=1), budget, out / "transcript.jsonl",
                    deadline=deadline)
    for f in tb.findings:
        f["_unit"] = unit["origin"]
    return {"findings": tb.findings, **_metrics(llm, res)}


def triage(cfg: AuditConfig, root: Path, engine_dir: Path, out: Path, group: str = "file",
           deploy: str = "", deadline: float | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lang = detect_lang(root)
    reg_path = engine_dir / "yasa_registry.json"
    registry = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    eng_by_sink: dict[str, tuple[str, dict]] = {}
    for fid in sorted(registry, key=lambda k: (-int(k.split("-")[0][1:]), k)):  # newest run first
        eng_by_sink.setdefault(registry[fid]["sink"], (fid, registry[fid]))

    cands = [{"origin": f"engine:{fid}", "yasa_ref": fid, "sink": sink,
              "engine_attribute": it.get("attribute"), "engine_trace": it.get("trace", [])[:12],
              "engine_sources": sorted(set(it.get("sources", [])))[:5]}
             for sink, (fid, it) in sorted(eng_by_sink.items())]
    eng_locs = {(s.rsplit(":", 1)[0], int(s.rsplit(":", 1)[1])) for s in eng_by_sink}
    tb = Toolbox(cfg, root, out, enable_yasa=False)
    inv = inventory(tb, lang, _wrapper_sinks(engine_dir, lang))
    residual = [h for h in inv
                if not any(h["file"] == f and abs(h["line"] - ln) <= 3 for f, ln in eng_locs)]
    cands += [{"origin": f"residual:{h['file']}:{h['line']}", "sink": f"{h['file']}:{h['line']}",
               "code": h["code"], "suspected_classes": sorted(h["classes"])} for h in residual]
    (out / "candidates.json").write_text(json.dumps(cands, indent=1, ensure_ascii=False))

    units: list[tuple[dict, int, int]] = []  # (unit, budget, priority)
    if group == "file":
        by_file: dict[str, list[dict]] = {}
        for c in cands:
            by_file.setdefault(c["sink"].rsplit(":", 1)[0], []).append(c)
        for f, cs in sorted(by_file.items()):
            rank = min(_cand_rank(c) for c in cs)
            if len(cs) == 1:
                units.append((cs[0], cfg.triage_budget, rank))
            else:
                units.append(({"origin": f"group:{f}", "candidates": cs},
                              min(cfg.triage_budget + 4 * (len(cs) - 1), cfg.triage_group_budget_cap),
                              rank))
    else:
        units = [(c, cfg.triage_budget, _cand_rank(c)) for c in cands]
    units.sort(key=lambda u: u[2])  # stable: engine first, then the worst residual classes

    results, skipped = _schedule(
        units, lambda i, u: _triage_unit(cfg, root, out / f"unit-{i:03d}", u[0], u[1], deploy, deadline),
        cfg.workers, deadline)
    not_reviewed = [c["origin"] for u, _, _ in skipped for c in u.get("candidates", [u])]

    findings = [f for r in results for f in r["findings"]]
    (out / "findings.json").write_text(json.dumps({"findings": findings, "not_reviewed": not_reviewed},
                                                  indent=1, ensure_ascii=False))
    m = {"stage": "triage", "engine_candidates": len(eng_by_sink), "inventory": len(inv),
         "residual": len(residual), "units": len(units), "group": group,
         "skipped_units": len(skipped), "not_reviewed": len(not_reviewed),
         "prompt_tokens": sum(r["prompt_tokens"] for r in results),
         "completion_tokens": sum(r["completion_tokens"] for r in results),
         "steps": sum(r["steps"] for r in results), "errors": sum(1 for r in results if r.get("error")),
         "wall_s": round(time.time() - t0, 1), "n_findings": len(findings)}
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    return m


def authz(cfg: AuditConfig, root: Path, out: Path, deploy: str = "", product: str = "",
          batch: int = 3, budget: int = 16, deadline: float | None = None) -> dict:
    """Access-control stage: deterministic entry inventory, then grouped review in fresh contexts.

    Every unit gets the full route table so reviewers can compare peers. No RAG index is needed:
    with the route table in hand, reviewers given a semantic search tool used it 0-1 times per run
    (see benchmarks/yasa_audit/README.md).
    """
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lang = detect_lang(root)
    entries = entries_for(root, lang)
    global_guards = global_guards_for(root, lang)
    table = [f"{e['method']} {e['route']} -> {e['file']}:{e['line']} guards={e['guards']}" for e in entries]
    by_file: dict[str, list[dict]] = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    files = sorted(by_file)
    units = [{"origin": f"authz:{','.join(files[i:i + batch])}", "batch_files": files[i:i + batch],
              "entries": [e for f in files[i:i + batch] for e in by_file[f]],
              "global_guards": global_guards, "route_table": table}
             for i in range(0, len(files), batch)]
    (out / "entries.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False))

    def review(i: int, unit: dict) -> dict:
        sub = out / f"unit-{i:03d}"
        sub.mkdir(parents=True, exist_ok=True)
        tb = Toolbox(cfg, root, sub, enable_yasa=False)
        tools = [t for t in tool_schemas(enable_yasa=False) if t["function"]["name"] != "list_dir"]
        llm = LLM(cfg)
        res = run_agent(llm, tb, tools, authz_prompt(budget, deploy, product),
                        json.dumps(unit, ensure_ascii=False, indent=1), budget, sub / "transcript.jsonl",
                        deadline=deadline)
        for f in tb.findings:
            f["_unit"] = unit["origin"]
        return {"findings": tb.findings, **_metrics(llm, res)}

    results, skipped = _schedule(units, review, cfg.workers, deadline)
    not_reviewed = [f for u in skipped for f in u["batch_files"]]
    findings = [f for r in results for f in r["findings"]]
    (out / "findings.json").write_text(json.dumps({"findings": findings, "not_reviewed": not_reviewed},
                                                  indent=1, ensure_ascii=False))
    m = {"stage": "authz", "entries": len(entries), "units": len(units), "skipped_units": len(skipped),
         "prompt_tokens": sum(r["prompt_tokens"] for r in results),
         "completion_tokens": sum(r["completion_tokens"] for r in results),
         "steps": sum(r["steps"] for r in results), "wall_s": round(time.time() - t0, 1),
         "n_findings": len(findings)}
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    return m


def trace(cfg: AuditConfig, root: Path, out: Path, deploy: str = "",
          deadline: float | None = None) -> dict:
    """Mode A baseline: one agent traces source -> sink with navigation tools only."""
    out.mkdir(parents=True, exist_ok=True)
    tb = Toolbox(cfg, root, out, enable_yasa=False)
    llm = LLM(cfg)
    res = run_agent(llm, tb, tool_schemas(enable_yasa=False), trace_prompt(cfg.trace_budget, deploy),
                    f"Audit the project. Top-level listing:\n{tb.list_dir('.', 1)}",
                    cfg.trace_budget, out / "transcript.jsonl", deadline=deadline)
    (out / "findings.json").write_text(json.dumps({"findings": tb.findings}, indent=1,
                                                  ensure_ascii=False))
    m = _metrics(llm, {"stage": "trace", "n_findings": len(tb.findings), **res})
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    return m

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
from .discovery import discover, reachable_files, snapshot_codegraph
from .engine_scope import build_engine_src
from .entrypoints import global_guards_for
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
    "py": [
        (r"\.execute(many)?\s*\(|\.raw\s*\(|\bextra\s*\(|text\s*\(\s*f?[\"']", "CWE-89"),
        (r"os\.system\(|os\.popen\(|subprocess\.\w+\(|commands\.getoutput\(", "CWE-78"),
        (r"(?<![\w.])(eval|exec)\s*\(", "CWE-94"),
        (r"render_template_string\(|Template\s*\(|from_string\(|mark_safe\(|Markup\(|\|\s*safe", "CWE-1336"),
        (r"(?<![\w.])open\s*\(|send_file\(|send_from_directory\(|FileResponse\(|os\.remove\(|shutil\.",
         "CWE-22"),
        (r"requests\.(get|post|put|request)\(|urlopen\(|httpx\.|aiohttp\.ClientSession", "CWE-918"),
        (r"pickle\.loads?\(|yaml\.load\(|marshal\.loads\(|jsonpickle\.decode\(", "CWE-502"),
        (r"etree\.(parse|fromstring)\(|xml\.dom\.minidom|XMLParser\(", "CWE-611"),
        (r"(?<![\w.])redirect\s*\(|HttpResponseRedirect\(", "CWE-601"),
    ],
    "php": [
        (r"mysqli?_query\s*\(|->query\s*\(|->exec\s*\(|pg_query\s*\(|DB::(raw|select|statement)\(|"
         r"whereRaw\(|selectRaw\(|orderByRaw\(", "CWE-89"),
        (r"(?<![\w>])(system|exec|shell_exec|passthru|popen|proc_open|pcntl_exec)\s*\(|`[^`]*\$", "CWE-78"),
        (r"(?<![\w>])(eval|assert|create_function)\s*\(|preg_replace\s*\(\s*['\"].*/e", "CWE-94"),
        (r"(include|require)(_once)?\s*\(?\s*[^;]*\$", "CWE-98"),
        (r"(?<![\w>])(file_get_contents|file_put_contents|fopen|readfile|unlink|move_uploaded_file|copy|"
         r"file)\s*\(", "CWE-22"),
        (r"curl_exec\s*\(|curl_setopt\s*\([^,]+,\s*CURLOPT_URL", "CWE-918"),
        (r"(?<![\w>])unserialize\s*\(", "CWE-502"),
        (r"simplexml_load_string\(|->loadXML\(|LIBXML_NOENT", "CWE-611"),
        (r"(echo|print)\s+[^;]*\$_(GET|POST|REQUEST|COOKIE|SERVER)|<\?=\s*\$|\{!!", "CWE-79"),
        # HTML assembled in a string with a variable: '<pre>' . $x, "<pre>{$x}", "<b>$x"
        (r"['\"][^'\"]*<[a-zA-Z][^'\"]*(['\"]\s*\.\s*\$\w|\{\$\w|\$\w)", "CWE-79"),
        (r"header\s*\(\s*['\"](?i:location)\s*:[^;]*\$", "CWE-601"),
    ],
}
GLOBS = {"ts": ["*.ts", "*.js"], "java": ["*.java", "*.jsp"], "py": ["*.py"],
         "php": ["*.php", "*.phtml", "*.inc"]}
# Languages the YASA engine is used for. PHP script entries reach the engine through the Service
# wrapper in engine_scope (the PHP analyzer ignores ruleConfig entrypoints).
ENGINE_LANGS = {"ts", "java", "py", "php"}
# Above this many source files the engine gets the entry-scoped copy instead of the whole tree.
ENGINE_SCOPE_MIN_FILES = 1500
EXT_LANG = {".ts": "ts", ".js": "ts", ".java": "java", ".jsp": "java", ".py": "py", ".php": "php",
            ".phtml": "php"}
SKIP_PARTS = {"node_modules", ".git", ".yasa", ".codegraph", "vendor", "venv", ".venv", "site-packages",
              "__pycache__"}

MODULE_NAMES = {"path", "fs", "os", "JSON", "subprocess", "shutil", "json", "yaml", "pickle", "None", "True",
                "False", "settings", "BASE_DIR", "__file__", "__DIR__", "__FILE__", "Math", "console", "process", "Buffer", "Object", "Array",
                "String", "Number", "Date", "Promise", "require", "true", "false", "null", "undefined",
                "this", "new", "await"}
STR_RE = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\$]|\$(?!\{))*`")
ID_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)(?=\s*(\(|\.|))")


def detect_lang(root: Path) -> str:
    """Majority language among analysable source files: ts (JS/TS), java (incl. JSP), py, php."""
    counts = dict.fromkeys(GLOBS, 0)
    for p in root.rglob("*"):
        if any(part in SKIP_PARTS for part in p.parts):
            continue
        lang = EXT_LANG.get(p.suffix)
        if lang:
            counts[lang] += 1
    return max(counts, key=lambda k: counts[k])


def is_constant_call(code: str, pat: str) -> bool:
    """True when the arguments after the sink match contain no variable (literals, module names and
    function names only), e.g. res.sendFile(path.resolve('frontend/index.html'))."""
    m = re.search(pat, code)
    if not m:
        return False
    if re.search(r"\$\w", m.group(0)):  # the match itself contains a variable (PHP echo $_GET[...])
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
            for line in tb.grep_rows(pat, glob=g):
                m = re.match(r"^([^:]+):(\d+):(.*)$", line)
                if (not m or "test" in m.group(1).lower() or is_constant_call(m.group(3), pat)
                        or any(part in SKIP_PARTS for part in Path(m.group(1)).parts)):
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


def _schedule(units: list, work, workers: int, deadline: float | None,
              stop=None) -> tuple[list[dict], list]:
    """Run work(i, unit) for units in order with a thread pool. Units that would start with less
    than MIN_UNIT_S left before the deadline are skipped and returned separately."""
    skipped: list = []
    lock = threading.Lock()

    def guarded(i_unit: tuple[int, object]) -> dict | None:
        i, unit = i_unit
        if (stop and stop()) or (deadline is not None and time.time() > deadline - MIN_UNIT_S):
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


RULE_DEFAULTS = Path(__file__).parent / "kb" / "rule_defaults"
YASA_LANG = {"java": "java", "py": "python", "php": "php"}
MAX_AUTO_ENTRYPOINTS = 60


def auto_engine_plan(lang: str, entries: list[dict]) -> dict:
    """Deterministic first engine run: default rules for the language plus the discovered entries.

    JS/TS: the engine only starts from listed entrypoints, and must start in the function whose body
    registers the routes (a file-level start only defines that function: 0 sources on Ghost). Other
    languages: the engine collects framework entries itself (Spring, Flask/Django, PHP *Service
    wrappers from engine_scope).
    """
    if lang == "ts":
        ts = sum(1 for e in entries if str(e.get("registered_at") or e["file"]).split(":")[0].endswith((".ts", ".tsx")))
        language = "typescript" if ts * 2 > len(entries) else "javascript"
        eps, seen = [], set()
        for e in entries:
            site = str(e.get("registered_at") or "").split(":")[0] or e["file"]
            fn = e.get("registration_fn") or ""
            if fn.startswith("#") or not site:
                continue  # private class members cannot be looked up through module exports
            key = (site, fn)
            if key in seen:
                continue
            seen.add(key)
            ep = {"filePath": "/" + site, "attribute": "HTTP"}
            if fn:
                ep["functionName"] = fn
            eps.append(ep)
        rules = json.loads((RULE_DEFAULTS / "javascript.json").read_text())
        for block in rules:
            block["entrypoints"] = eps[:MAX_AUTO_ENTRYPOINTS]
        return {"language": language, "rule_config": rules, "checker_ids": rules[0]["checkerIds"],
                "entrypoint_mode": "ONLY_CUSTOM" if eps else "SELF_COLLECT", "entrypoints": len(eps)}
    language = YASA_LANG.get(lang, "java")
    rules = json.loads((RULE_DEFAULTS / f"{language}.json").read_text())
    return {"language": language, "rule_config": rules, "checker_ids": rules[0]["checkerIds"],
            "entrypoint_mode": "SELF_COLLECT", "entrypoints": 0}


def _auto_engine_run(tb: Toolbox, plan: dict, window_end: float | None) -> str:
    """Run the plan with at most half of the remaining build window, as one extra engine run."""
    saved = tb.deadline
    if window_end is not None:
        tb.deadline = time.time() + max(0.0, (window_end - time.time()) / 2)
    tb.max_yasa_runs += 1
    try:
        return tb.yasa_run(plan["rule_config"], plan["language"], checker_ids=plan["checker_ids"],
                           entrypoint_mode=plan["entrypoint_mode"],
                           preprocess_jsp=plan["language"] == "java" and any((tb.engine_root or tb.root).rglob("*.jsp")))
    except Exception as e:  # the agent still gets its own runs
        return f"error: automatic engine run failed: {type(e).__name__}: {e}"
    finally:
        tb.deadline = saved


def build(cfg: AuditConfig, root: Path, out: Path, deploy: str = "",
          deadline: float | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    lang = detect_lang(root)
    if lang not in ENGINE_LANGS:  # no engine for this language: triage covers residual sinks only
        m = {"stage": "build", "skipped": f"no engine support for {lang}", "language": lang,
             "prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "yasa_runs": 0,
             "engine_findings": 0, "steps": 0, "wall_s": 0.0, "finished": True, "timed_out": False}
        (out / "metrics.json").write_text(json.dumps(m, indent=1))
        return m
    tb = Toolbox(cfg, root, out, enable_yasa=True)
    tb.deadline = deadline
    try:
        snapshot_codegraph(root, out)
    except Exception:  # discovery falls back to the live index
        pass
    try:
        entries, disc = discover(root, lang, cfg.yasamcp_bin, cfg.codegraph_bin)
    except Exception as e:  # never lose the stage over entry discovery
        entries, disc = [], {"error": f"{type(e).__name__}: {e}", "codegraph_routes": 0, "yasamcp_apis": 0,
                             "dispatchers": 0}
    scope_note = ""
    n_src = sum(1 for p in root.rglob("*") if p.suffix in EXT_LANG and not any(x in SKIP_PARTS for x in p.parts))
    if entries and (lang == "php" or n_src > ENGINE_SCOPE_MIN_FILES):
        scope = build_engine_src(root, out / "engine_src", entries)
        if scope["files"]:
            tb.engine_root = out / "engine_src"
            scope_note = (
                f"\nThe engine runs on a scoped copy: {scope['files']} files that codegraph links to the "
                f"{len(entries)} discovered entries (of {n_src} source files); source_subdir is relative to it."
                + (f" {scope['php_wrapped']} PHP entry scripts are wrapped as YasaEntry*Service::run() so the "
                   "PHP checker collects them (use entrypoint_mode SELF_COLLECT; superglobal sources are "
                   "self-collected, so list sinks and sanitizers)." if scope["php_wrapped"] else ""))
        (out / "engine_scope.json").write_text(json.dumps(scope, indent=1))
    (out / "discovery.json").write_text(json.dumps(disc, indent=1))
    sample = "\n".join(f"  {e['method']} {e['route']} -> {e['file']}:{e['line']} ({e['via']})"
                       for e in entries[:40])
    plan = auto_engine_plan(lang, entries)
    auto = _auto_engine_run(tb, plan, deadline)
    (out / "auto_run.txt").write_text(auto)
    t_start = time.time()
    tools = tool_schemas(enable_yasa=True, with_report=False)
    llm = LLM(cfg)

    def _late_without_own_run(steps: int, t: Toolbox) -> bool:
        if deadline is None or t.yasa_runs > 1:
            return False
        return time.time() > t_start + 0.6 * max(0.0, deadline - t_start)

    res = run_agent(llm, tb, tools, builder_prompt(cfg.builder_budget, cfg.builder_max_yasa_runs, deploy),
                    f"Build engine rules for the project. Top-level listing:\n{tb.list_dir('.', 1)}\n"
                    f"Discovered entries ({len(entries)}; {json.dumps({k: disc[k] for k in ('codegraph_routes', 'yasamcp_apis', 'dispatchers')})}):\n"
                    f"{sample}{scope_note}\n\nEngine run #1 was made automatically with the default "
                    f"{plan['language']} rules and {plan['entrypoints'] or 'self-collected'} entrypoints "
                    f"(mode {plan['entrypoint_mode']}); its output, findings registered as R1-F*:\n{auto[:6000]}\n"
                    "Improve on it: add the project's sources, sinks and sanitizers, fix entrypoints that "
                    "were not found, then run again.",
                    cfg.builder_budget, out / "transcript.jsonl", deadline=deadline,
                    reminders=[(lambda steps, t: steps >= cfg.builder_budget // 2 and t.yasa_runs <= 1,
                                "You have used half of your budget without running the engine. Stop "
                                "exploring: write the ruleConfig now from what you know and call yasa_run."),
                               (_late_without_own_run,
                                "60% of the build time is gone and you have not run the engine yourself. Call "
                                "yasa_run now; a run started with less than two minutes left is refused.")])
    m = _metrics(llm, {"stage": "build", "yasa_runs": tb.yasa_runs, "auto_run": plan | {"rule_config": None},
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
    # Engine first, then the worst residual classes; within a class, sinks in files that codegraph
    # links to a discovered entry come first (a tie-breaker only: dynamic dispatch hides edges).
    try:  # ordering aid only: any index problem must not stop the stage
        snapshot_codegraph(root, out)
        reach = reachable_files(root, [e["file"] for e in discover(root, lang, "", "")[0]])
    except Exception:
        reach = set()
    if reach:
        def _file(u: dict) -> str:
            return (u.get("candidates") or [u])[0]["sink"].rsplit(":", 1)[0]
        units.sort(key=lambda u: (u[2], _file(u[0]) not in reach))
    else:
        units.sort(key=lambda u: u[2])

    results, skipped = _schedule(
        units, lambda i, u: _triage_unit(cfg, root, out / f"unit-{i:03d}", u[0], u[1], deploy, deadline),
        cfg.workers, deadline, cfg.stopped)
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


ROUTE_TABLE_CAP = 200


def _peer_table(table: list[str], batch_files: list[str]) -> list[str] | dict:
    """Full table when small; otherwise the rows of the batch's directories plus a sample, so every
    unit can still compare peers without the prompt growing with the project."""
    if len(table) <= ROUTE_TABLE_CAP:
        return table
    dirs = {f.rsplit("/", 1)[0] if "/" in f else "" for f in batch_files}
    near = [r for r in table if any(f" -> {d}/" in r or (not d and "/" not in r.split(" -> ")[1].split(":")[0])
                                    for d in dirs)]
    rest = [r for r in table if r not in near]
    step = max(1, len(rest) // max(1, ROUTE_TABLE_CAP - len(near)))
    return {"rows_near_this_batch": near[:ROUTE_TABLE_CAP], "sample_of_other_rows": rest[::step][:ROUTE_TABLE_CAP],
            "total_rows": len(table)}


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
    try:
        snapshot_codegraph(root, out)
        entries, discovery = discover(root, lang, cfg.yasamcp_bin, cfg.codegraph_bin)
    except Exception as e:  # fall back to the regex extractors
        from .entrypoints import entries_for
        entries, discovery = entries_for(root, lang), {"error": f"{type(e).__name__}: {e}"}
    global_guards = global_guards_for(root, lang)
    table = [f"{e['method']} {e['route']} -> {e['file']}:{e['line']} guards={e['guards']}"
             + (f" dispatcher={e['dispatcher']!r}" if e.get("dispatcher") else "")
             + (f" web_server_denied={e['web_server_denied']!r}" if e.get("web_server_denied") else "")
             for e in entries]
    (out / "discovery.json").write_text(json.dumps(discovery, indent=1))
    by_file: dict[str, list[dict]] = {}
    for e in entries:
        by_file.setdefault(e["file"], []).append(e)
    files = sorted(by_file)
    # Dispatchers first: one of them can stand for hundreds of targets.
    files.sort(key=lambda f: (not any(e.get("dispatcher") for e in by_file[f]), f))
    units = [{"origin": f"authz:{','.join(files[i:i + batch])}", "batch_files": files[i:i + batch],
              "entries": [e for f in files[i:i + batch] for e in by_file[f]],
              "global_guards": global_guards, "route_table": _peer_table(table, files[i:i + batch])}
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

    results, skipped = _schedule(units, review, cfg.workers, deadline, cfg.stopped)
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

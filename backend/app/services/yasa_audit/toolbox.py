"""Tools exposed to the agents.

- Navigation: list_dir / read_file / grep (ripgrep) and code-index queries (functions, callers, call graph,
  symbol search), answered from codegraph's index (see graph.py).
- Recon: codegraph's route evidence, `run_extractor` (the agent writes a small program that enumerates
  the project's entries; the tool runs it and checks the result), `check_coverage` (are the places
  that read request data reachable from the entries found so far?).
- Review: `record_card` (what an entry does and its access-control verdict), `report_finding`,
  `add_fact` (a verified project fact shared with later reviewers).

All file access is confined to the project root (realpath + is_relative_to).
"""

from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from .config import AuditConfig

SKIP_DIRS = {".yasa", ".codegraph", "node_modules", ".git"}
MAX_OUT = 8000
ENTRY_KEYS = ("route", "method", "handler_file", "handler", "handler_line", "auth", "exposure", "declared_at",
              "kind")
EXPOSURES = ("public", "authenticated", "privileged", "operator", "unknown")
FINDING_REQUIRED = ("vuln_type", "cwe", "sink_file", "sink_line", "source", "entry", "required_privilege", "verdict",
                    "route_evidence", "impact")


def clip(text: str, limit: int = MAX_OUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars; narrow the query]"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def verify_evidence(root: Path, evidence: list[dict]) -> str | None:
    """None when every {file, line, quote} is found in the code within a few lines of `line`."""
    if not evidence:
        return "evidence is required: [{file, line, quote}]"
    for ev in evidence:
        if not isinstance(ev, dict):
            return "each evidence item is an object {file, line, quote}"
        p = (root / str(ev.get("file", "")).lstrip("/")).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            return f"evidence file not found: {ev.get('file')}"
        lines = p.read_text(errors="ignore").splitlines()
        line, quote = int(ev.get("line") or 0), _norm(str(ev.get("quote") or ""))
        if not quote:
            return "each evidence item needs a quote copied from the code"
        # A few lines around the cited line, extended so that a quote spanning several lines (a route
        # registration with its middleware) fits.
        end = line + 3
        while end < len(lines) and end - line < 60 and len(_norm(" ".join(lines[max(0, line - 1):end]))) < len(quote) + 40:
            end += 1
        window = _norm(" ".join(lines[max(0, line - 4):end]))
        if quote not in window:
            return f"quote not found near {ev.get('file')}:{line}"
    return None


class FactBook:
    """Project facts shared by all review units.

    A fact is accepted only when every piece of evidence (file, line, quote) is found in the code, so
    reviewers cannot pass on guesses. Facts are short and numbered; reviewers cite the ids they relied
    on (record_card.facts_used), and the block given to later units keeps the most cited facts within a
    character budget, so foundational facts are not pushed out by recent, narrow ones.
    """

    MAX_STATEMENT = 240

    def __init__(self, root: Path, char_budget: int = 9000):
        self.root, self.char_budget = root, char_budget
        self.facts: list[dict] = []
        self._lock = threading.Lock()

    def verify(self, evidence: list[dict]) -> str | None:
        return verify_evidence(self.root, evidence)

    def add(self, statement: str, evidence: list[dict], unit: str) -> str:
        statement = _norm(statement)
        if len(statement) > self.MAX_STATEMENT:
            return (f"rejected: the statement has {len(statement)} characters; state the fact in at most "
                    f"{self.MAX_STATEMENT} (one claim, no explanation)")
        err = self.verify(evidence)
        if err:
            return f"rejected: {err}"
        with self._lock:
            for f in self.facts:
                if f["statement"].lower() == statement.lower():
                    return f"already known as {f['id']}"
            fid = f"F{len(self.facts) + 1}"
            self.facts.append({"id": fid, "statement": statement, "evidence": evidence, "unit": unit,
                               "cited": 0})
        return f"accepted as {fid}"

    def cite(self, ids: Any) -> list[str]:
        """Count citations; returns the ids that do not exist."""
        unknown = []
        with self._lock:
            by_id = {f["id"]: f for f in self.facts}
            for i in ids if isinstance(ids, list) else []:
                if str(i) in by_id:
                    by_id[str(i)]["cited"] += 1
                else:
                    unknown.append(str(i))
        return unknown

    def since(self, seen: set[str], unit: str) -> list[dict]:
        """Facts other units added that `seen` does not contain yet (marks them seen)."""
        with self._lock:
            new = [f for f in self.facts if f["id"] not in seen and f["unit"] != unit]
        seen.update(f["id"] for f in new)
        return new

    def prompt_block(self) -> str:
        with self._lock:
            facts = sorted(self.facts, key=lambda f: (-f["cited"], int(f["id"][1:])))
        rows, used = [], 0
        for f in facts:
            where = ", ".join(f"{e.get('file')}:{e.get('line')}" for e in f["evidence"][:2])
            row = f"- {f['id']}: {f['statement']} ({where})"
            if used + len(row) > self.char_budget:
                continue
            rows.append(row)
            used += len(row) + 1
        if not rows:
            return ""
        return ("Verified project facts (rely on them instead of re-deriving; cite the ids you used in "
                "record_card.facts_used):\n" + "\n".join(rows))


class IssueBoard:
    """Root causes already reported in this run, shared with later reviewers.

    The same flaw often appears behind several entries (one helper, one pattern copied into sibling
    modules). A reviewer whose entry has a known root cause links its finding to it (same_as) instead
    of re-deriving the shared part, and the output groups findings by root cause.
    """

    def __init__(self) -> None:
        self.issues: list[dict] = []
        self._lock = threading.Lock()

    def register(self, finding: dict) -> str:
        """Attach the finding to an existing issue (same_as) or open a new one; returns the issue id."""
        with self._lock:
            ref = str(finding.get("same_as") or "")
            issue = next((i for i in self.issues if i["id"] == ref), None)
            if issue is None:
                issue = {"id": f"I{len(self.issues) + 1}", "root_cause": _norm(str(finding.get("root_cause"))),
                         "cwe": finding.get("cwe"), "where": f"{finding.get('sink_file')}:{finding.get('sink_line')}",
                         "entries": [], "unit": finding.get("_unit")}
                self.issues.append(issue)
            issue["entries"].append(finding.get("entry"))
            return issue["id"]

    def since(self, seen: set[str], unit: str) -> list[dict]:
        with self._lock:
            new = [i for i in self.issues if i["id"] not in seen and i.get("unit") != unit]
        seen.update(i["id"] for i in new)
        return new

    def prompt_block(self, char_budget: int = 4000) -> str:
        with self._lock:
            issues = list(self.issues)
        rows, used = [], 0
        for i in issues:
            row = f"- {i['id']} ({i['cwe']}, {i['where']}, {len(i['entries'])} entries): {i['root_cause']}"
            if used + len(row) > char_budget:
                break
            rows.append(row)
            used += len(row) + 1
        if not rows:
            return ""
        return ("Root causes already reported in this run (if this entry has one of them, report it with "
                "same_as=<id> and this entry's own route and evidence; do not re-derive the shared part):\n"
                + "\n".join(rows))


class Toolbox:
    def __init__(self, cfg: AuditConfig, root: str | Path, run_dir: Path, facts: FactBook | None = None,
                 unit: str = "", issues: IssueBoard | None = None):
        self.cfg = cfg
        self.root = Path(root).resolve()
        self.run_dir = run_dir
        self.facts = facts
        self.issues = issues
        self.unit = unit
        self.findings: list[dict] = []
        self.cards: list[dict] = []
        self.finished = False
        self.notes = ""
        self.extractors: dict[str, dict] = {}  # name -> {"code", "entries"}
        self.manual: list[dict] = []
        self.coverage: dict | None = None
        self.access_model: dict | None = None
        self.resolver_code: str | None = None
        self.known_entries: dict[tuple, dict] = {}  # (METHOD, route) -> entry, so who_can_call sees the handler
        self.extractor_best: dict[str, int] = {}  # most entries any version of each extractor produced
        self.regressions_shown: set[tuple] = set()
        self.reconcile_groups: dict[str, list[str]] = {}  # group id -> entry ids (reconcile pass)
        self.on_resolver_installed = None  # reconcile: regroups the disagreements for a new resolver
        self.conclusion: dict | None = None  # refutation check
        self.unenumerated: list[str] = []  # recon: dispatchers found but not enumerated yet
        self.decisions: dict[str, dict] = {}  # the access agent's who-can-call program
        # (condition, message): finish is refused while a condition holds (e.g. no access model yet)
        self.finish_gates: list[tuple[Any, str]] = []
        # the sensitive-asset map (assets agent): operation recipes, absent classes, identity subsystems
        self.recipes: dict[str, dict] = {}
        self.absent: dict[str, str] = {}
        self.identity_none: dict[str, str] = {}  # identity kind -> what was searched
        self.identity: list[dict] | None = None
        self.entries_source: Any = None  # callable: the entries the surface agent has enumerated so far
        self._calls: Any = None
        self.reach: Any = None  # assets.Reach of the run: who can run a piece of code (who_reaches)
        self.design: dict[str, dict] = {}  # identity design review: checklist item -> answer
        self.coverage: Any = None  # assets.Coverage shared by the review units
        self.records_reads = False  # entry units: the code read counts as reviewed for operation units

    # ---------- helpers ----------
    def _safe(self, rel: str) -> Path:
        p = (self.root / str(rel).lstrip("/")).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("path escapes project root")
        return p

    def _graph(self):
        """codegraph's index of the project, or None (then agents use grep / read_file)."""
        from .discovery import codegraph_db
        from .graph import CodeGraph
        db = codegraph_db(self.root)
        return CodeGraph(db, self.root) if db is not None else None

    def _ask_graph(self, question: str, *args: Any, **kw: Any) -> str:
        g = self._graph()
        if g is None:
            return "error: no code index for this project (use grep / read_file)"
        try:
            return clip(getattr(g, question)(*args, **kw))
        except Exception as e:  # a damaged or still-written index must not end the agent's turn
            return f"error: code index query failed ({type(e).__name__}: {e}); use grep / read_file"

    # ---------- navigation ----------
    def list_dir(self, path: str = ".", depth: int = 2) -> str:
        base = self._safe(path)
        lines = []
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base)
            if any(part in SKIP_DIRS for part in rel.parts) or len(rel.parts) > int(depth):
                continue
            lines.append("  " * (len(rel.parts) - 1) + rel.name + ("/" if p.is_dir() else ""))
        return clip("\n".join(lines) or "(empty)")

    def read_file(self, path: str, start_line: int = 1, end_line: int = 0) -> str:
        p = self._safe(path)
        if not p.is_file():
            return f"error: not a file: {path}"
        lines = p.read_text(errors="ignore").splitlines()
        start = max(1, int(start_line or 1))
        end = int(end_line or 0) or min(len(lines), start + 119)
        end = min(end, start + 249, len(lines))
        body = "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(start, end + 1))
        if self.records_reads and self.coverage is not None:
            self.coverage.read(self.unit, str(p.relative_to(self.root)), start, end)
        return clip(f"{path} lines {start}-{end} of {len(lines)}\n{body}")

    def grep_rows(self, pattern: str, glob: str = "") -> list[str]:
        """All matching "file:line:code" rows, paths relative to the project root.

        ripgrep resolves a --glob that contains '/' against its working directory, so it runs inside
        the project root and searches '.'; otherwise path globs such as app/**/*.php never match.
        Case-sensitive unless the pattern says otherwise ((?i)).
        """
        cmd = [self.cfg.rg_bin, "-n", "--no-heading", "-s", "-M", "300", "--engine", "auto"]
        for d in SKIP_DIRS:
            cmd += ["-g", f"!{d}"]
        if glob:
            cmd += ["-g", glob]
        cmd += ["-e", pattern, "."]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90, cwd=self.root)
        return sorted(line[2:] if line.startswith("./") else line for line in r.stdout.splitlines())

    def grep(self, pattern: str, glob: str = "", max_results: int = 60) -> str:
        try:
            rows = self.grep_rows(pattern, glob)
        except FileNotFoundError:
            return "error: ripgrep not found (set YASA_RG_BIN)"
        except subprocess.TimeoutExpired:
            return "error: search timed out; narrow the pattern or the glob"
        more = f"\n...[{len(rows) - int(max_results)} more matches]" if len(rows) > int(max_results) else ""
        return clip("\n".join(rows[: int(max_results)]) + more or "(no matches)")

    def find_function(self, name: str, file_path: str = "", detail: str = "summary") -> str:
        return self._ask_graph("find_function", str(name), str(file_path or ""), str(detail or "summary"))

    def find_callers(self, name: str, file_path: str = "", line: int = 0) -> str:
        return self._ask_graph("find_callers", str(name), str(file_path or ""))

    def call_graph(self, name: str, depth: int = 2, file_path: str = "") -> str:
        return self._ask_graph("call_graph", str(name), int(depth or 2), str(file_path or ""))

    def search_symbol(self, query: str) -> str:
        return self._ask_graph("search_symbol", str(query))

    # ---------- recon ----------
    def codegraph_routes(self, contains: str = "", limit: int = 40) -> str:
        """Routes codegraph's framework resolvers recognised (evidence, possibly incomplete or empty)."""
        from .discovery import codegraph_db, codegraph_routes
        db = codegraph_db(self.root)
        if db is None:
            return "no codegraph index"
        routes = [r for r in codegraph_routes(db, self.root)
                  if not contains or contains in r["route"] or contains in r["file"]]
        head = f"{len(routes)} routes recognised by codegraph"
        rows = [f"{r['method']} {r['route']} -> {r['file']}:{r['line']} {r.get('handler', '')}"
                for r in routes[: int(limit)]]
        return clip(head + ("\n" + "\n".join(rows) if rows else ""))

    def entries(self) -> list[dict]:
        """Union of all extractor outputs and manual entries. One entry per (method, route, handler file):
        the most recently run extractor wins, and an entry whose handler does not resolve is dropped when
        another one for the same request does (two services may serve the same path from different files)."""
        # sorted() copies the values before calling the key: another agent's thread reads the entries
        # while this one adds extractors
        runs = sorted(self.extractors.values(), key=lambda ex: ex.get("run", 0))
        by_req: dict[tuple, dict[str, dict]] = {}
        for e in [x for ex in runs for x in ex["entries"]] + list(self.manual):  # later ones replace earlier ones
            by_req.setdefault((e.get("method", "ANY"), e.get("route")), {})[str(e.get("handler_file"))] = e
        out = []
        for cands in by_req.values():
            ok = [e for e in cands.values() if self._check_entry(e) is None]
            out += ok or list(cands.values())
        return out

    def overlaps(self) -> list[tuple]:
        """Requests that several extractors map to different handlers."""
        seen: dict[tuple, set] = {}
        for name, ex in self.extractors.items():
            for e in ex["entries"]:
                seen.setdefault((e.get("method", "ANY"), e.get("route")), set()).add(
                    (name, e.get("handler_file"), e.get("handler")))
        return [(k, v) for k, v in seen.items() if len({(f, h) for _, f, h in v}) > 1 and len({n for n, _, _ in v}) > 1]

    def _check_entry(self, e: dict) -> str | None:
        """None when the handler is concrete code in the project, else the reason it is not."""
        f = str(e.get("handler_file") or "")
        if not f:
            return "no handler_file"
        try:
            p = self._safe(f)
        except ValueError:
            return "handler_file escapes the project"
        if not p.is_file():
            return "handler_file does not exist"
        text = p.read_text(errors="ignore")
        h = str(e.get("handler") or "").split("::")[-1].split(".")[-1].split("#")[-1]
        if h and h not in text:
            return f"handler '{h}' does not occur in handler_file"
        if e.get("handler_line") and not 0 < int(e["handler_line"]) <= text.count("\n") + 1:
            return "handler_line is outside handler_file"
        return None

    def _clean(self, raw: Any, origin: str) -> tuple[list[dict], list[str]]:
        if not isinstance(raw, list):
            return [], ["output must be a JSON list of entry objects"]
        out, problems = [], []
        for e in raw:
            if not isinstance(e, dict) or not e.get("route"):
                problems.append(f"skipped item without route: {str(e)[:120]}")
                continue
            e = {k: e.get(k) for k in ENTRY_KEYS if e.get(k) not in (None, "")} | {"origin": origin}
            e["handler_file"] = str(e.get("handler_file", "")).lstrip("./") if e.get("handler_file") else ""
            try:
                e["handler_line"] = int(e["handler_line"]) if e.get("handler_line") else None
            except (TypeError, ValueError):
                e["handler_line"] = None
            if not e["handler_line"]:
                e.pop("handler_line")
            if e.get("exposure") not in EXPOSURES:
                e["exposure"] = "unknown"
            e["method"] = str(e.get("method") or "ANY").upper()
            out.append(e)
        return out, problems

    def _summary(self, entries: list[dict]) -> dict:
        bad = [(e, why) for e in entries if (why := self._check_entry(e))]
        by_exp: dict[str, int] = {}
        for e in entries:
            by_exp[e["exposure"]] = by_exp.get(e["exposure"], 0) + 1
        ok = [e for e in entries if not self._check_entry(e)]
        rnd = random.Random(len(entries))
        return {"entries": len(entries), "handler_resolved": len(ok), "handler_unresolved": len(bad),
                "by_exposure": by_exp,
                "unresolved_samples": [f"{e['route']} -> {e.get('handler_file')}::{e.get('handler')} ({why})"
                                       for e, why in bad[:8]],
                "random_resolved_samples_to_check_by_reading": [
                    f"{e['method']} {e['route']} -> {e['handler_file']}::{e.get('handler', '')} "
                    f"auth={e.get('auth', '?')} exposure={e['exposure']}"
                    for e in rnd.sample(ok, min(8, len(ok)))]}

    def _run_python(self, code: str, prefix: str, stdin: str = "", timeout: int = 180) -> tuple[bool, str]:
        """Run a program an agent wrote: `python -I <script> <project root>`, standard library only,
        in a scratch directory. Returns (ok, stdout) or (False, error text)."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=f"{prefix}-", dir=str(self.run_dir)))
        script = work / f"{prefix}.py"
        script.write_text(code)
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}
        try:
            r = subprocess.run([sys.executable, "-I", str(script), str(self.root)], capture_output=True,
                               text=True, timeout=timeout, cwd=work, env=env, input=stdin)
        except subprocess.TimeoutExpired:
            return False, (f"error: program ran longer than {timeout} s. Reading and parsing source files takes "
                           "seconds; a run this long is almost always a loop that does not advance (a while "
                           "loop whose index is not moved on every branch) or a regex that backtracks on long "
                           "input. Fix that rather than narrowing the input.")
        if r.returncode:
            return False, clip(f"error: program exited {r.returncode}\n{r.stderr[-3000:]}", 4000)
        return True, r.stdout

    RESOLVER_FIELDS = ("kind", "handler_file", "handler", "handler_line")

    def resolve_access(self, requests: list[dict], code: str | None = None) -> list[dict] | str:
        """Run the who-can-call program on requests ({method, route} plus, when known, the entry's kind and
        handler location); a list of results in the same order, or an error text. Each result:
        least_privileged (public|authenticated|privileged|denied|unknown), principals (list), rule (where
        the decision comes from)."""
        code = code or self.resolver_code
        if not code:
            return "error: no resolver"
        reqs = []
        for r in requests:
            q = {"method": str(r.get("method") or "GET").upper(), "route": str(r.get("route") or "")}
            q.update({k: r[k] for k in self.RESOLVER_FIELDS if r.get(k) not in (None, "")})
            reqs.append(q)
        ok, out = self._run_python(code, "resolver", json.dumps(reqs), timeout=120)
        if not ok:
            return out
        try:
            res = json.loads(out)
        except json.JSONDecodeError as e:
            return clip(f"error: stdout is not JSON ({e}); first bytes: {out[:300]!r}", 2000)
        if not isinstance(res, list) or len(res) != len(reqs):
            return f"error: expected a JSON list of {len(reqs)} results (one per request, same order)"
        clean = []
        for r in res:
            r = r if isinstance(r, dict) else {}
            lp = str(r.get("least_privileged") or "unknown")
            clean.append({"least_privileged": lp if lp in (*EXPOSURES, "denied") else "unknown",
                          "principals": [str(p) for p in (r.get("principals") or [])][:8],
                          "rule": str(r.get("rule") or "")[:200]})
        return clean

    def write_access_resolver(self, code: str, samples: Any) -> str:
        """Install the who-can-call program after running it on sample requests."""
        samples = [x for x in (samples or []) if isinstance(x, dict) and x.get("route")]
        if len(samples) < 3:
            return ("rejected: give at least 3 sample requests {method, route, handler_file, handler, ...}, of "
                    "different privilege levels")
        res = self.resolve_access(samples, code)
        if isinstance(res, str):
            return res
        self.resolver_code = code
        (self.run_dir / "resolver.py").write_text(code)
        rows = [f"{s.get('method', 'GET')} {s['route']} -> {r['least_privileged']} {r['principals']} ({r['rule']})"
                for s, r in zip(samples, res, strict=True)]
        unknown = sum(r["least_privileged"] == "unknown" for r in res)
        text = ("resolver installed. Check each result against the code you read; fix and resend if any is "
                f"wrong{' (unknown results: ' + str(unknown) + ')' if unknown else ''}:\n" + "\n".join(rows))
        if self.on_resolver_installed is not None:
            text += "\n\n" + self.on_resolver_installed()
        return clip(text, 12000)

    def who_reaches(self, pattern: str, glob: str = "") -> str:
        """The code matching a pattern and who can run it. Its main use is the step across storage: the
        pattern of the code that writes a stored value gives the value's writers and their callers."""
        from .assets import REACH_SITES
        if self.reach is None:
            return "error: not available in this stage; use grep and find_callers"
        try:
            rows = self.grep_rows(str(pattern or ""), str(glob or ""))
        except subprocess.TimeoutExpired:
            return "error: search timed out; narrow the pattern or the glob"
        if len(rows) > REACH_SITES:
            return (f"rejected: {len(rows)} matches. Match the code that does one thing (the assignments or "
                    "calls that write this one field, file or key), not every mention of a name: narrow the "
                    "pattern or give a glob")
        return clip(self.reach.report(str(pattern), rows))

    def who_can_call(self, method: str, path: str) -> str:
        req = {**self.known_entries.get((str(method or "GET").upper(), str(path)), {}),
               "method": method, "route": path}
        res = self.resolve_access([req])
        if isinstance(res, str):
            return res + ("; work it out from the access model" if "no resolver" in res else "")
        return json.dumps(res[0], ensure_ascii=False)

    def run_probe(self, code: str) -> str:
        """Run a throwaway Python program over the project (root in sys.argv[1]) and show its output.
        Nothing it prints becomes part of the surface."""
        ok, out = self._run_python(code, "probe", timeout=120)
        return clip(out, 6000) or "(no output)"

    def drop_extractor(self, name: str) -> str:
        if self.extractors.pop(str(name), None) is None:
            return f"error: no extractor {name!r}; extractors: {', '.join(self.extractors) or 'none'}"
        self.extractor_best.pop(str(name), None)
        return f"dropped {name}; total entries now {len(self.entries())}"

    def run_extractor(self, name: str, code: str) -> str:
        """Run a Python program the agent wrote. It receives the project root as sys.argv[1] and must
        print a JSON list of entries. The result replaces any earlier extractor of the same name."""
        if not re.fullmatch(r"[\w-]{1,40}", str(name)):
            return "error: name must be 1-40 letters, digits, '-' or '_'"
        ok, out = self._run_python(code, "extractor", timeout=60)
        if not ok:
            return out
        try:
            raw = json.loads(out)
        except json.JSONDecodeError as e:
            return clip(f"error: stdout is not JSON ({e}); first bytes: {out[:300]!r}", 2000)
        entries, problems = self._clean(raw, f"extractor:{name}")
        prev = self.extractors.get(name)
        self._runs = getattr(self, "_runs", 0) + 1
        self.extractors[name] = {"code": code, "entries": entries, "run": self._runs}
        self.extractor_best[name] = max(self.extractor_best.get(name, 0), len(entries))
        (self.run_dir / "extractors").mkdir(exist_ok=True)
        (self.run_dir / "extractors" / f"{name}.py").write_text(code)
        res = {"extractor": name, **self._summary(entries), "problems": problems[:5],
               "total_entries_all_extractors": len(self.entries())}
        if prev is not None:  # a rewrite must not silently lose part of the surface
            key = lambda e: (e.get("method"), e.get("route"))  # noqa: E731
            old, new = {key(e): e for e in prev["entries"]}, {key(e): e for e in entries}
            removed = [old[k] for k in old.keys() - new.keys()]
            by_dir: dict[str, int] = {}
            for e in removed:
                d = "/".join(os.path.dirname(str(e.get("handler_file") or "?")).split("/")[:4]) or "."
                by_dir[d] = by_dir.get(d, 0) + 1
            res["change_from_previous_version"] = {
                "previous": len(old), "now": len(new), "added": len(new.keys() - old.keys()),
                "removed": len(removed),
                "removed_by_directory": sorted(by_dir.items(), key=lambda kv: -kv[1])[:10]}
            if len(removed) > max(5, len(old) // 5):
                res["warning"] = (f"this version lost {len(removed)} of {len(old)} entries of the previous "
                                  "one; check that this was intended (a bug in the rewrite, an exception "
                                  "caught too broadly, a changed path) before you finish")
        return clip(json.dumps(res, ensure_ascii=False, indent=1))

    def extractor_regressions(self) -> list[str]:
        """Extractors whose latest version yields far fewer entries than an earlier version did, not yet
        pointed out to the agent. Each is pointed out once: a smaller surface can be the right answer."""
        out = []
        for name, best in self.extractor_best.items():
            es = self.extractors.get(name, {}).get("entries", [])
            now = len(es)
            if best - now > max(5, best // 5) and (name, now) not in self.regressions_shown:
                self.regressions_shown.add((name, now))
                out.append(f"{name} now yields {now} entries, an earlier version yielded {best}")
            bad = sum(self._check_entry(e) is not None for e in es)
            if now and bad * 2 > now and (name, "unresolved", now) not in self.regressions_shown:
                self.regressions_shown.add((name, "unresolved", now))
                out.append(f"{name}: {bad} of {now} entries do not resolve to code (fix it, or drop_extractor "
                           "if it was a probe)")
        ov = self.overlaps()
        if ov and ("overlaps", len(ov)) not in self.regressions_shown:
            self.regressions_shown.add(("overlaps", len(ov)))
            (m, r), v = ov[0]
            out.append(f"{len(ov)} requests are mapped to different handlers by different extractors, e.g. {m} {r}: "
                       + "; ".join(f"{n} -> {f}::{h}" for n, f, h in sorted(v, key=str)[:4])
                       + " (drop or fix the extractors that are wrong)")
        return out

    def add_entries(self, entries: list[dict]) -> str:
        """Add entries by hand (a few special ones an extractor would not cover)."""
        clean, problems = self._clean(entries, "manual")
        self.manual += clean
        return clip(json.dumps({**self._summary(clean), "problems": problems[:5],
                                "total_entries_all_extractors": len(self.entries())}, ensure_ascii=False))

    def check_coverage(self, request_read_pattern: str, glob: str = "", depth: int = 3) -> str:
        """Places that read request data (ripgrep pattern for THIS project's request API) that are not
        in, or reachable within `depth` codegraph edges from, any entry's handler file. Uncovered places
        point at entry points the extractors have missed (or at code that is not request-reachable)."""
        from .discovery import reachable_files
        try:
            rows = self.grep_rows(request_read_pattern, glob)
        except subprocess.TimeoutExpired:
            return "error: search timed out; narrow the pattern"
        sites = [r.split(":", 2) for r in rows if r.count(":") >= 2]
        files = sorted({s[0] for s in sites})
        handlers = sorted({e["handler_file"] for e in self.entries() if e.get("handler_file")})
        reach = reachable_files(self.root, handlers, depth=int(depth)) or set(handlers)
        unc = [s for s in sites if s[0] not in reach]
        result = {"pattern": request_read_pattern, "sites": len(sites), "files": len(files),
                  "covered_sites": len(sites) - len(unc), "uncovered_sites": len(unc),
                  "handler_files_matched": len(set(files) & set(handlers)), "handler_files": len(handlers)}
        # A narrower pattern finds fewer reads, not better coverage: the broadest check is the record.
        if self.coverage is None or result["sites"] >= self.coverage["sites"]:
            self.coverage = result
        elif result["sites"] < self.coverage["sites"]:
            result["note"] = (f"this pattern matches fewer read sites than an earlier check "
                              f"({self.coverage['sites']}: {self.coverage['pattern']}); the earlier, broader "
                              "check stays the recorded coverage")
        if len(handlers) >= 10 and result["handler_files_matched"] * 4 < len(handlers):
            result["note"] = (f"the pattern matches request reads in only {result['handler_files_matched']} of "
                              f"{len(handlers)} handler files, so most handlers read requests some other way "
                              "and this check says little; use a pattern that matches how they read it")
        by_file: dict[str, list[str]] = {}
        for f, ln, code in unc:
            by_file.setdefault(f, []).append(f"{ln}: {code.strip()[:120]}")
        res = {**result,
               "uncovered_files": len(by_file),
               "account_for_each": ("each file below reads request data but no entry reaches it: add the "
                                    "entries that reach it, or say in your finish notes why it is not "
                                    "request-reachable (test, CLI, dead code)") if by_file else "",
               "uncovered": [{"file": f, "reads": rows[:3], "more": max(0, len(rows) - 3)}
                             for f, rows in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:25]]}
        return clip(json.dumps(res, ensure_ascii=False, indent=1))

    # ---------- sensitive-asset map ----------
    def call_index(self):
        from .assets import CallIndex
        if self._calls is None:
            self._calls = CallIndex(self.root)
        return self._calls

    def _entries_now(self) -> list[dict]:
        return list(self.entries_source()) if self.entries_source is not None else []

    def run_recipe(self, name: str, op_class: str, pattern: str, glob: str = "", exclude: str = "",
                   guard: str = "", why: str = "") -> str:
        """Expand a recipe for one form of a sensitive operation over the whole project and place every
        site in the call graph. The same name replaces the earlier version."""
        from .assets import (
            MAX_SITES,
            OP_CLASSES,
            check_recipe,
            counters,
            entry_reach,
            expand,
            scoped_rows,
        )
        r = {"name": str(name), "op_class": str(op_class), "pattern": str(pattern or ""), "glob": str(glob or ""),
             "exclude": str(exclude or ""), "guard": str(guard or ""), "why": str(why or "")[:400]}
        err = check_recipe(r)
        if err:
            return f"rejected: {err}"
        entries = self._entries_now()
        index = self.call_index()
        try:
            rows, outside = scoped_rows(self.grep_rows, r, entry_reach(index, entries), index.unparsed)
        except subprocess.TimeoutExpired:
            return "error: search timed out; narrow the pattern or the glob"
        if len(rows) > MAX_SITES:
            return (f"rejected: {len(rows)} matches. A recipe matches the operation itself (the call or "
                    "assignment that performs it), not every mention of a word: narrow it")
        sites = expand(r, rows, index, entries)
        self.recipes[r["name"]] = r
        self.absent.pop(r["op_class"], None)
        res = counters(r, sites, len(entries), outside_glob=outside)
        if not self.call_index().indexed:
            res["note_index"] = "no code index: every site counts as file-level code, reach is by handler file"
        if self.entries_source is not None:
            res["entries_note"] = "the surface agent is still enumerating entries; reach is against those so far"
        left = [c for c in OP_CLASSES if c not in {x["op_class"] for x in self.recipes.values()}
                and c not in self.absent]
        res["classes_left"] = left
        return clip(json.dumps(res, ensure_ascii=False, indent=1))

    def drop_recipe(self, name: str) -> str:
        if self.recipes.pop(str(name), None) is None:
            return f"error: no recipe {name!r}; recipes: {', '.join(self.recipes) or 'none'}"
        return f"dropped {name}; recipes: {', '.join(self.recipes) or 'none'}"

    def class_absent(self, op_class: str, reason: str) -> str:
        """Say that the project does not perform a class of operation at all."""
        from .assets import OP_CLASSES
        if op_class not in OP_CLASSES:
            return f"rejected: op_class must be one of {', '.join(OP_CLASSES)}"
        if not str(reason or "").strip():
            return "rejected: give the reason (what you searched and found)"
        if any(r["op_class"] == op_class for r in self.recipes.values()):
            return f"rejected: a recipe for {op_class} exists; drop_recipe it first if it was wrong"
        self.absent[op_class] = str(reason)[:400]
        return f"recorded: {op_class} absent"

    def identity_absent(self, kind: str, reason: str) -> str:
        """Say that the project has no subsystem of an identity kind, with what was searched."""
        from .assets import IDENTITY_KINDS
        if kind not in IDENTITY_KINDS:
            return f"rejected: kind must be one of {', '.join(IDENTITY_KINDS)}"
        if not str(reason or "").strip():
            return "rejected: give the reason (what you searched and found)"
        if any(g["kind"] == kind for g in self.identity or []):
            return f"rejected: a subsystem of kind {kind} is recorded"
        self.identity_none[kind] = str(reason)[:400]
        return f"recorded: no {kind} subsystem"

    def identity_left(self) -> list[str]:
        """Identity kinds neither recorded nor declared absent."""
        from .assets import IDENTITY_KINDS
        done = {g["kind"] for g in self.identity or []} | set(self.identity_none)
        return [k for k in IDENTITY_KINDS if k not in done]

    def record_identity(self, subsystems: Any) -> str:
        """Record identity subsystems; a later record with the same name replaces that subsystem, so they
        can be sent one per call."""
        from .assets import check_identity, group_identity, merge_identity
        if isinstance(subsystems, dict):
            subsystems = [subsystems]
        clean, problems = check_identity(subsystems, self.root)
        if problems and not clean:
            return "rejected: " + "; ".join(problems[:6])
        self.identity = merge_identity(self.identity, clean)
        entries = self._entries_now()
        rows = [f"- {g['name']} ({g['kind']}): {len(group_identity(g, entries, [])['entry_ids'])} entries so far, "
                f"{len(g['files'])} files, {len(g['settings'])} settings" for g in clean]
        return ("recorded " + str(len(clean)) + " subsystem(s)" + (":\n" + "\n".join(rows) if rows else "")
                + f"\n{len(self.identity)} subsystem(s) recorded in all"
                + (f"\nkinds still to record or declare absent (identity_absent): {', '.join(self.identity_left())}"
                   if self.identity_left() else "")
                + ("\nnot recorded: " + "; ".join(problems[:6]) if problems else ""))

    def record_design(self, items: Any = None, item: str = "", status: str = "", answer: str = "",
                      evidence: Any = None, to_verify: str = "") -> str:
        """Answers to the identity checklist, several in `items` or one in the top-level fields; each
        replaces an earlier answer to the same item."""
        from .assets import DESIGN_STATUSES, IDENTITY_CHECKLIST
        items = [items] if isinstance(items, dict) else items if isinstance(items, list) else []
        if item:
            items.append({"item": item, "status": status, "answer": answer, "evidence": evidence,
                          "to_verify": to_verify})
        if not items:
            return ("rejected: send one answer as item, status, answer (and evidence, to_verify), or several "
                    "in items")
        errors = []
        for it in items:
            it = it if isinstance(it, dict) else {}
            key, status = str(it.get("item") or ""), it.get("status")
            if key not in IDENTITY_CHECKLIST:
                errors.append(f"unknown item {key!r}")
                continue
            if status not in DESIGN_STATUSES:
                errors.append(f"{key}: status must be one of {', '.join(DESIGN_STATUSES)}")
                continue
            if not str(it.get("answer") or "").strip():
                errors.append(f"{key}: answer is required")
                continue
            ev = it.get("evidence") or []
            ev = [ev] if isinstance(ev, dict) else ev if isinstance(ev, list) else []
            if status in ("sound", "flaw", "owner_decision"):
                err = verify_evidence(self.root, ev) if ev else "evidence is required for this status"
                if err:
                    errors.append(f"{key}: {err}")
                    continue
            self.design[key] = {"item": key, "status": status, "answer": str(it["answer"])[:1500],
                                "evidence": ev[:6], "to_verify": str(it.get("to_verify") or "")[:400]}
        left = [k for k in IDENTITY_CHECKLIST if k not in self.design]
        return "; ".join(errors + [f"answered: {len(self.design)}",
                                   f"left: {', '.join(left)}" if left else "all items answered"])

    # ---------- review / output ----------
    def _anchor_ok(self, anchor: Any) -> bool:
        m = re.match(r"^\s*([^:\s]+):(\d+)", str(anchor or ""))
        if not m:
            return False
        try:
            p = self._safe(m.group(1))
        except ValueError:
            return False
        return p.is_file() and 0 < int(m.group(2)) <= len(p.read_text(errors="ignore").splitlines())

    def record_card(self, **card: Any) -> str:
        """Record (or replace) this unit's card. Every hypothesis must name the operation that makes the
        risk plausible, as file:line, so risks are derived from code rather than from a checklist."""
        hyps = card.get("hypotheses") or []
        bad = [str(h.get("risk", "?")) for h in hyps if isinstance(h, dict) and not self._anchor_ok(h.get("anchor"))]
        if bad:
            return ("rejected: these hypotheses have no anchor (file:line of the operation in the code that "
                    f"makes the risk plausible): {bad[:6]}. Anchor them, or drop risks the code gives no "
                    "reason to suspect.")
        bare = [str(h.get("risk", "?")) for h in hyps if isinstance(h, dict) and h.get("status") != "confirmed"
                and not str(h.get("why") or "").strip()]
        if bare:
            return ("rejected: these hypotheses have no why: " + str(bare[:6]) + ". A rejection needs its reason as "
                    "much as a finding does: the code that stops it (file:line); an open one says what is left "
                    "to read.")
        unknown = self.facts.cite(card.get("facts_used")) if self.facts is not None else []
        card["_unit"] = self.unit
        self.cards = [card]  # a later call updates the card
        if self.coverage is not None:
            for h in hyps:
                if isinstance(h, dict):
                    self.coverage.add(h.get("anchor"))
        return "card recorded" + (f" (unknown fact ids ignored: {unknown})" if unknown else "")

    UPHOLD_STAGES = ("input_validation", "permission", "operation")

    def conclude(self, verdict: str, reason: str = "", path: Any = None, power: Any = None) -> str:
        """Refutation check. path: the stages of the request as read in the code, each {stage, file,
        line, quote, effect} with effect 'passes' or 'stops'. upheld needs input_validation,
        permission and operation, each quoted and none stopping; refuted needs a quoted stage that
        stops it; by_design needs the principal whose designed power covers the outcome, with the
        quote where the project grants it; uncertain needs only the reason."""
        if verdict not in ("upheld", "refuted", "by_design", "uncertain"):
            return "rejected: verdict must be upheld, refuted, by_design or uncertain"
        if not str(reason or "").strip():
            return "rejected: reason is required"
        path = [p for p in ([path] if isinstance(path, dict) else (path or [])) if isinstance(p, dict)]
        if verdict == "by_design":
            power = power if isinstance(power, dict) else {}
            if not str(power.get("principal") or "").strip():
                return ("rejected: by_design needs power: {principal, file, line, quote}: the least privileged "
                        "principal that can take the path, and where the project grants it this capability")
            err = verify_evidence(self.root, [power])
            if err:
                return f"rejected: power: {err}"
            self.conclusion = {"verdict": verdict, "reason": str(reason)[:1500], "path": path[:10],
                               "power": {k: power.get(k) for k in ("principal", "file", "line", "quote")}}
            return f"concluded: {verdict}"
        if verdict != "uncertain":
            err = verify_evidence(self.root, path) if path else "path is required"
            if err:
                return f"rejected: path: {err}"
            stops = [p for p in path if p.get("effect") == "stops"]
            if verdict == "refuted" and not stops:
                return "rejected: refuted needs the stage that stops the attack (effect: stops)"
            if verdict == "upheld":
                if stops:
                    return "rejected: a stage you quoted stops the attack; conclude refuted"
                missing = [x for x in self.UPHOLD_STAGES if x not in {p.get("stage") for p in path}]
                if missing:
                    return (f"rejected: upheld needs the code of each stage the request passes, quoted: missing "
                            f"{', '.join(missing)}. Open it (framework validators, the permission hook of "
                            "the model or service, the code that performs the operation) rather than "
                            "assuming what it does; quote where you looked if a stage does not exist.")
        self.conclusion = {"verdict": verdict, "reason": str(reason)[:1500], "path": path[:10]}
        return f"concluded: {verdict}"

    SETTLE_VERDICTS = ("resolver_wrong", "declared_wrong", "inconsistent_code")

    def settle(self, decisions: Any) -> str:
        """Decide groups of disagreements between the resolver and the declared exposure, in one call."""
        if isinstance(decisions, dict):
            decisions = [decisions]
        errors = []
        for d in decisions if isinstance(decisions, list) else []:
            d = d if isinstance(d, dict) else {}
            g, v = str(d.get("group", "")), d.get("verdict")
            if g not in self.reconcile_groups:
                errors.append(f"unknown group {g!r}")
            elif v not in self.SETTLE_VERDICTS:
                errors.append(f"{g}: verdict must be one of {', '.join(self.SETTLE_VERDICTS)}")
            else:
                self.decisions[g] = {"verdict": v, "reason": str(d.get("reason", ""))[:400]}
        left = [g for g in self.reconcile_groups if g not in self.decisions]
        return "; ".join(errors + [f"decided: {len(self.decisions)}",
                                   f"undecided: {', '.join(left)}" if left else "all groups decided"])

    ACCESS_FIELDS = ("authentication", "authorization", "permission_mapping", "principals", "shared_protections")

    def record_access_model(self, **model: Any) -> str:
        """The project-wide model of how requests are authenticated and authorized (recon stage). Parts are
        accepted: each call sets the fields it gives and keeps the others, so the model is recorded as it is
        worked out instead of in one long call at the end (where an output limit or one bad field loses it)."""
        draft = dict(self.access_model or {})
        problems = []
        for k in (*self.ACCESS_FIELDS, "public_by_default"):
            if str(model.get(k) or "").strip():
                draft[k] = model[k]
        if model.get("ladder") is not None:
            ladder = [str(x).strip() for x in model["ladder"] if str(x).strip()] \
                if isinstance(model["ladder"], list) else []
            if ladder:
                draft["ladder"] = ladder[:12]
            else:
                problems.append("ladder must be a list of principals, least privileged first")
        if model.get("evidence"):
            err = verify_evidence(self.root, model["evidence"])
            if err:
                problems.append(f"evidence not recorded: {err}")
            else:
                draft["evidence"] = model["evidence"]
        if model.get("powers") is not None:
            powers, err = self._powers(model.get("powers"))
            if err:
                problems.append(f"powers not recorded: {err}")
            else:
                draft["powers"] = powers
        legacy = [str(x).strip() for x in model.get("scoped_roles") or [] if str(x).strip()] \
            if isinstance(model.get("scoped_roles"), list) else []
        draft["scoped_roles"] = list(dict.fromkeys(
            [p["principal"] for p in draft.get("powers") or [] if p["held_for_one_object"]]
            + legacy + list(draft.get("scoped_roles") or [])))[:12]
        missing = [k for k in self.ACCESS_FIELDS if not str(draft.get(k) or "").strip()] \
            + ([] if draft.get("ladder") else ["ladder"]) + ([] if draft.get("evidence") else ["evidence"])
        if len(missing) == len(self.ACCESS_FIELDS) + 2:
            return "rejected: nothing recorded; " + "; ".join(problems or ["give at least one field"])
        if missing == ["evidence"] and not problems and not self.access_model:
            return "rejected: evidence is required (file, line, quote for the statements above)"
        draft["incomplete"] = missing
        if not missing:
            draft.pop("incomplete")
        self.access_model = draft
        if missing:
            out = "access model recorded so far; still to record (later calls add to it): " + ", ".join(missing)
        elif not draft.get("powers"):
            out = ("access model recorded, but without powers: add them (record_access_model with powers), or "
                   "reviewers cannot tell a designed capability from an escalation")
        else:
            out = "access model recorded"
        return out + ("\n" + "; ".join(problems) if problems else "")

    def _powers(self, rows: Any) -> tuple[list[dict], str]:
        """What each principal is designed to be able to do, with where the project says so."""
        out: list[dict] = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict) or not str(r.get("principal") or "").strip() \
                    or not str(r.get("power") or "").strip():
                return [], "each row needs principal and power"
            ev = r.get("evidence")
            ev = [ev] if isinstance(ev, dict) else [e for e in ev or [] if isinstance(e, dict)]
            if ev and (err := verify_evidence(self.root, ev)):
                return [], f"{r['principal']}: {err}"
            out.append({"principal": str(r["principal"]).strip()[:80], "power": _norm(str(r["power"]))[:400],
                        "held_for_one_object": bool(r.get("held_for_one_object")), "evidence": ev[:2]})
        return out[:24], ""

    def report_finding(self, **finding: Any) -> str:
        missing = [k for k in FINDING_REQUIRED if finding.get(k) in (None, "")]
        if missing:
            return f"rejected: missing {', '.join(missing)}; send the finding again with them"
        if finding.get("verdict") not in ("confirmed", "likely"):
            return "rejected: verdict must be confirmed or likely (record rejected risks in record_card)"
        ev = finding.get("route_evidence")
        err = verify_evidence(self.root, [ev] if isinstance(ev, dict) else (ev or []))
        if err:
            return (f"rejected: route_evidence: {err}. The entry list comes from automated recon and can be "
                    "wrong: show where this route is registered or generated in the code (file, line, quote) "
                    "and check that it really serves the path you report.")
        if not str(finding.get("root_cause") or "").strip() and not finding.get("same_as"):
            return "rejected: root_cause is required (one sentence: the underlying flaw), or same_as=<issue id>"
        rc = _norm(str(finding.get("root_cause") or ""))
        if len(rc) > 240:  # a key for grouping findings, not the explanation: keep its start
            finding["root_cause"] = rc[:239].rsplit(" ", 1)[0] + "…"
        if finding.get("documented_intent"):
            di = finding["documented_intent"]
            err = verify_evidence(self.root, [di] if isinstance(di, dict) else di)
            if err:
                return f"rejected: documented_intent: {err}"
        finding["_unit"] = self.unit
        if self.issues is not None:
            finding["issue"] = self.issues.register(finding)
        self.findings.append(finding)
        return f"recorded #{len(self.findings)}" + (f" as part of {finding['issue']}" if finding.get("issue") else "")

    def add_fact(self, statement: str, evidence: Any) -> str:
        if self.facts is None:
            return "error: no fact book in this stage"
        if isinstance(evidence, dict):
            evidence = [evidence]
        return self.facts.add(str(statement), evidence if isinstance(evidence, list) else [], self.unit)

    def finish(self, notes: str = "", unenumerated: Any = None, _force: bool = False) -> str:
        for cond, msg, *_ in self.finish_gates:
            if not _force and cond(self):
                return f"not finished: {msg(self) if callable(msg) else msg}"
        self.finished = True
        self.notes = notes
        self.unenumerated = [str(x)[:400] for x in (unenumerated or []) if str(x).strip()][:12] \
            if isinstance(unenumerated, list) else []
        return f"finished ({len(self.findings)} findings, {len(self.cards)} cards)"


def tool_schemas(role: str) -> list[dict]:
    """role: 'recon' (surface), 'access' (access-control model), 'assets' (sensitive-asset map),
    'review' (entry and operation units), 'design' (identity design units) or 'verify' (refutation)."""
    from .assets import DESIGN_STATUSES, IDENTITY_CHECKLIST, IDENTITY_KINDS, OP_CLASSES
    def fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    s, i = {"type": "string"}, {"type": "integer"}
    tools = [
        fn("list_dir", "List files under a project directory (relative path).", {"path": s, "depth": i}, []),
        fn("read_file", "Read a file with line numbers (default 120 lines, at most 250 per call).",
           {"path": s, "start_line": i, "end_line": i}, ["path"]),
        fn("grep", "Ripgrep regex over the project, case-sensitive ((?i) for insensitive). Returns "
                   "file:line:text. glob is relative to the project root, e.g. app/**/*.php or *.xml.",
           {"pattern": s, "glob": s, "max_results": i}, ["pattern"]),
        fn("find_function", "Find a function or method definition by name (or a qualified name such as "
           "Class::method); file_path narrows it. detail=full includes the body.",
           {"name": s, "file_path": s, "detail": {"type": "string", "enum": ["summary", "full"]}}, ["name"]),
        fn("find_callers", "Call sites of a function or method (file_path = the file that defines it), "
           "including calls made through an interface or parent method it implements.",
           {"name": s, "file_path": s}, ["name"]),
        fn("call_graph", "What a function calls, as a tree with file:line; calls to interface or abstract "
           "methods show their implementations. From a static index: calls on untyped or dynamic receivers can "
           "be missing or attributed to a same-named function.", {"name": s, "depth": i, "file_path": s},
           ["name"]),
        fn("search_symbol", "Search functions/classes/files by name.", {"query": s}, ["query"]),
    ]
    entry = {"type": "object", "properties": {
        "route": s, "method": s, "handler_file": s, "handler": s, "handler_line": i, "kind": s, "declared_at": s,
        "auth": {"type": "string", "description": "what the code/config says about authentication or "
                 "authorization for this entry, verbatim where possible"},
        "exposure": {"type": "string", "enum": list(EXPOSURES)}}}
    req = {"type": "object", "properties": {"method": s, "route": s, "kind": s, "handler_file": s, "handler": s,
                                            "handler_line": i}}
    if role == "access":
        tools += [
            fn("write_access_resolver",
               "Install a who-can-call program: Python 3 (standard library only) that gets the project root "
               "as sys.argv[1], reads a JSON list of requests from stdin and prints a JSON list with one "
               "result per request, same order. A request is an entry of the attack surface: method, route "
               "(in whatever shape the surface agent wrote it), and when known kind, handler_file, handler, "
               "handler_line. A result is {least_privileged: public|authenticated|privileged|denied|unknown, "
               "principals: [roles or principal kinds allowed, named as in your ladder], rule: where the "
               "decision comes from (file:line "
               "or config key)}. least_privileged is the least privileged principal whose request gets the "
               "handler's operation done: count the shared gates AND the checks the handler itself makes (the "
               "program can read the handler's code). Answer unknown for requests whose shape you do not "
               "recognise, rather than guessing. It applies the project's real access rules (route tables, "
               "role definitions, middleware or filter order, checks in handlers) as you read them. It is run "
               "on your samples now, and later on every entry and by reviewers.",
               {"code": s, "samples": {"type": "array", "items": req}}, ["code", "samples"]),
            fn("settle",
               "Only when asked to reconcile: decide groups of disagreements, all in one call. resolver_wrong: "
               "the declared exposure is right; declared_wrong: the resolver is right; inconsistent_code: both "
               "readings follow real code that disagrees (a likely access-control bug).",
               {"decisions": {"type": "array", "items": {"type": "object", "properties": {
                   "group": s, "verdict": {"type": "string", "enum": ["resolver_wrong", "declared_wrong",
                                                                      "inconsistent_code"]},
                   "reason": {"type": "string", "description": "the code that decides it (file:line)"}},
                   "required": ["group", "verdict", "reason"]}}}, ["decisions"]),
            fn("record_access_model",
               "Record how THIS project authenticates and authorizes requests, once, before finish. "
               "Reviewers of every entry rely on it instead of re-reading the security chain.",
               {"authentication": {"type": "string", "description": "how a request gets an identity "
                                   "(sessions, tokens, filters) and what an anonymous request is"},
                "authorization": {"type": "string", "description": "where access is decided (file:line) "
                                  "and what happens when no rule matches"},
                "permission_mapping": {"type": "string", "description": "how a request (method, path, "
                                       "resource) is turned into the permission that is checked"},
                "principals": {"type": "string", "description": "the roles/principals from least to most "
                               "privileged, who gets each (any visitor, any registered user, ...), and how "
                               "to tell from an entry's declaration which is the least one that can call it"},
                "public_by_default": s,
                "shared_protections": {"type": "string", "description": "protections every request or outgoing "
                                       "operation passes whatever the handler does, with file:line: input "
                                       "validation in the framework, output filtering, wrappers for outbound "
                                       "HTTP, file paths, queries, templates"},
                "ladder": {"type": "array", "items": s, "description": "the principals' names from least to "
                           "most privileged, as this project calls them (e.g. visitor, member, editor, admin); "
                           "the resolver's principals use these names"},
                "powers": {"type": "array", "description": "what each principal is DESIGNED to be able to "
                           "do, one row per role, permission or scope that grants something different (each "
                           "scope of a token, not only the ladder's names): what it may read, change, run or "
                           "grant, and what the project says it must not do. Take it from the project's own "
                           "statements: documentation, comments, the checks and restrictions it adds, its "
                           "security fixes. Reviewers judge a capability against this: within the power is "
                           "designed, beyond it is an escalation.",
                           "items": {"type": "object", "properties": {
                               "principal": s, "power": s,
                               "held_for_one_object": {"type": "boolean", "description": "a role held for ONE "
                                                       "object (team, organization, project or workspace admin "
                                                       "or owner) that an ordinary user can obtain by creating "
                                                       "such an object or being made its admin"},
                               "evidence": {"type": "object", "properties": {"file": s, "line": i, "quote": s}}},
                               "required": ["principal", "power"]}},
                "evidence": {"type": "array", "items": {"type": "object", "properties": {
                    "file": s, "line": i, "quote": s}}}},
               ["authentication", "authorization", "permission_mapping", "principals", "ladder",
                "shared_protections", "evidence"]),
        ]
    elif role == "recon":
        tools += [
            fn("codegraph_routes", "Routes that codegraph's framework resolvers recognised. Evidence only: "
               "may be empty or incomplete for this project.", {"contains": s, "limit": i}, []),
            fn("run_probe", "Run a throwaway Python 3 program (standard library; project root in sys.argv[1]) "
               "to explore the code, e.g. list files or test a regex; prints its output. Nothing becomes an "
               "entry: use it instead of run_extractor while you are still finding out.", {"code": s}, ["code"]),
            fn("drop_extractor", "Remove an extractor and its entries (e.g. one used as a probe).",
               {"name": s}, ["name"]),
            fn("run_extractor",
               "Run a Python 3 program you wrote that enumerates entries of THIS project. It gets the "
               "project root as sys.argv[1], may read any file there (standard library only, no network) "
               "and must print a JSON list of objects with keys route, method, handler_file (relative), "
               "handler (function/method name), handler_line (first line of the code that runs; required "
               "when the handler is anonymous, e.g. a callback or lambda), kind, auth, exposure (public|"
               "authenticated|privileged|unknown), declared_at (file:line). Returns counts, unresolved handlers and random samples "
               "to verify. Several extractors may cover different parts of the surface; the same name "
               "replaces the earlier version.", {"name": s, "code": s}, ["name", "code"]),
            fn("add_entries", "Add a few entries by hand (same keys as extractor output).",
               {"entries": {"type": "array", "items": entry}}, ["entries"]),
            fn("check_coverage",
               "Coverage check: give a ripgrep pattern matching how THIS project reads request data "
               "(e.g. the request object's getter calls). Lists read sites not reachable from any "
               "entry handler found so far, grouped by directory.",
               {"request_read_pattern": s, "glob": s, "depth": i}, ["request_read_pattern"]),
        ]
    elif role == "assets":
        tools += [
            fn("run_probe", "Run a throwaway Python 3 program (standard library; project root in sys.argv[1]) "
               "to explore the code, e.g. list the fields of every model; prints its output.", {"code": s},
               ["code"]),
            fn("run_recipe",
               "Expand a recipe for one form of a sensitive operation over the whole project. pattern: a "
               "ripgrep regex (case-sensitive, (?i) for insensitive) matching the code that PERFORMS the "
               "operation in this project (the call, assignment or output), not every mention of a word. "
               "glob narrows the files (relative to the root). exclude: a Python regex; matching lines are "
               "dropped. guard: a Python regex for the check this project applies to this operation (a "
               "permission or ownership check, an escaping or allowlist call); each site says whether it "
               "is in the operation's function before it or in a close caller. Returns, for the sites, "
               "whether an entry reaches them, whether anything calls them, the guard counts and samples to "
               "read. The same name replaces the earlier version.",
               {"name": s, "op_class": {"type": "string", "enum": list(OP_CLASSES)}, "pattern": s, "glob": s,
                "exclude": s, "guard": s,
                "why": {"type": "string", "description": "how this project performs the operation and the "
                        "evidence (file:line); reviewers read it"}}, ["name", "op_class", "pattern", "why"]),
            fn("drop_recipe", "Remove a recipe and its sites.", {"name": s}, ["name"]),
            fn("class_absent", "Say that the project does not perform a class of operation at all, with what "
               "you searched.", {"op_class": {"type": "string", "enum": list(OP_CLASSES)}, "reason": s},
               ["op_class", "reason"]),
            fn("identity_absent", "Say that the project has no subsystem of one identity kind, with what you "
               "searched.", {"kind": {"type": "string", "enum": list(IDENTITY_KINDS)}, "reason": s},
               ["kind", "reason"]),
            fn("record_identity",
               "Record identity subsystems, one per call (a later record with the same name replaces it). Every "
               "identity kind is either recorded or declared absent with identity_absent.",
               {"subsystems": {"type": "array", "items": {"type": "object", "properties": {
                   "name": s, "kind": {"type": "string", "enum": list(IDENTITY_KINDS)},
                   "routes": {"type": "array", "items": s, "description": "regular expressions over route "
                              "paths as the surface agent writes them (e.g. ^/users/(register|signup))"},
                   "files": {"type": "array", "items": s, "description": "controllers, services, directories"},
                   "models": {"type": "array", "items": s, "description": "model, schema or migration files"},
                   "settings": {"type": "array", "items": s, "description": "configuration keys that change "
                                "its behaviour, with their defaults and file:line"},
                   "notes": s}, "required": ["name", "kind"]}}}, ["subsystems"]),
        ]
    elif role == "verify":
        tools += [
            fn("who_can_call", "Who can call a request (method, path) under the project's access rules, "
               "computed by the access agent's resolver program.", {"method": s, "path": s}, ["method", "path"]),
            fn("conclude", "Your conclusion on the reported vulnerability, with the request's path as you read "
               "it in the code: one item per stage (entry, input_validation, permission, handler, "
               "operation, output) with file, line, a quote and its effect on the attack (passes or stops). "
               "refuted: a quoted stage stops it. by_design: the path holds but what it gives is within the "
               "designed power of the least privileged principal that can take it (power: that principal "
               "and the quote where the project grants it). upheld: input_validation, permission and "
               "operation are quoted, none stops it, and it gives more than that power. uncertain: say "
               "what is left to check.",
               {"verdict": {"type": "string", "enum": ["upheld", "refuted", "by_design", "uncertain"]},
                "reason": s,
                "power": {"type": "object", "properties": {"principal": s, "file": s, "line": i, "quote": s}},
                "path": {"type": "array", "items": {"type": "object", "properties": {
                    "stage": {"type": "string", "enum": ["entry", "input_validation", "permission", "handler",
                                                         "operation", "output"]},
                    "file": s, "line": i, "quote": s,
                    "effect": {"type": "string", "enum": ["passes", "stops"]}}}}}, ["verdict", "reason"]),
        ]
    else:
        tools += [
            fn("record_card",
               "Record this entry's card: first as soon as you know the scenario and access control, "
               "then again with every hypothesis's final status (a later call replaces the card).",
               {"function": {"type": "string", "description": "what the entry does, in business terms"},
                "callers": {"type": "string", "description": "who can call it, with the evidence"},
                "open_leads": {"type": "array", "items": s, "description": "suspicions you could not verify "
                               "to the harmful operation: file:line and what is left to check (kept for "
                               "follow-up, not reported as findings)"},
                "least_privileged_caller": {"type": "string", "description": "who can actually call it, as you "
                                            "established from the code (put a wrong recon exposure right "
                                            "here, not in report_finding)",
                                            "enum": ["public", "authenticated", "privileged", "denied"]},
                "authz_verdict": {"type": "string", "enum": ["ok", "missing_authentication",
                                                             "missing_authorization", "object_level",
                                                             "unclear"]},
                "authz_evidence": {"type": "string", "description": "file:line of the checks that apply"},
                "inputs": s, "objects": {"type": "string", "description": "data/resources it reads or changes"},
                "persists": {"type": "string", "description": "user-controlled values it stores, and where"},
                "hypotheses": {"type": "array", "items": {"type": "object", "properties": {
                    "risk": s,
                    "anchor": {"type": "string", "description": "file:line of the operation that makes this "
                               "risk plausible (where the request value is stored, queried, fetched, "
                               "rendered, used to pick an object, ...)"},
                    "why": {"type": "string", "description": "rejected: the code that stops it (file:line). "
                            "open: what is left to read (it is followed up in a fresh context)."},
                    "status": {"type": "string", "enum": ["confirmed", "rejected", "open"]},
                    "evidence": s}, "required": ["risk", "anchor", "status"]}},
                "facts_used": {"type": "array", "items": s,
                               "description": "ids of verified facts you relied on (e.g. F3)"}},
               ["function", "callers", "authz_verdict", "hypotheses"]),
            fn("report_finding", "Record ONE vulnerability (access control or data flow) you confirmed or "
               "consider likely, with file:line hops.",
               {"vuln_type": s, "cwe": s, "sink_file": s, "sink_line": i,
                "source": {"type": "string", "description": "attacker-controlled input and where"},
                "entry": {"type": "string", "description": "route and who can reach it"},
                "required_privilege": {"type": "string", "description": "least privileged principal that can "
                                       "exploit it", "enum": ["public", "authenticated", "privileged",
                                                              "operator_or_cli"]},
                "hops": {"type": "array", "items": s},
                "sanitizers": s,
                "impact": {"type": "string", "description": "what the attacker concretely gains: data read, "
                           "state changed, privilege obtained, code run (not 'a check is skipped')"},
                "root_cause": {"type": "string", "description": "one sentence naming the underlying flaw, so "
                               "the same flaw behind other entries is recognised"},
                "same_as": {"type": "string", "description": "id of an already reported root cause (e.g. I2) "
                            "that this entry also suffers from"},
                "documented_intent": {"type": "object", "description": "where the project states this behaviour "
                                      "is intended or accepted (code comment, doc), if it does (file, line, "
                                      "quote); the finding is then reported as an accepted risk",
                                      "properties": {"file": s, "line": i, "quote": s}},
                "route_evidence": {"type": "object", "description": "where the code registers or generates "
                                   "the route you report (file, line, quote); the recon entry list can be wrong",
                                   "properties": {"file": s, "line": i, "quote": s}},
                "verdict": {"type": "string", "enum": ["confirmed", "likely"]}},
               ["vuln_type", "cwe", "sink_file", "sink_line", "source", "entry", "required_privilege",
                "verdict", "route_evidence", "impact"]),
            fn("who_can_call", "Who can call a request (method, path) under the project's access rules, "
               "computed by the access agent's resolver program.", {"method": s, "path": s}, ["method", "path"]),
            fn("who_reaches", "The code matching a regex, by function, with the entries that reach each "
               "function through calls and their least privileged caller. It is the step across storage "
               "that find_callers is across a call: give the pattern of the code that WRITES a stored value "
               "(a field assignment, a setter, a file or key write) to learn who can put a value there. From "
               "a static index: a caller through an untyped or dynamic receiver can be missing, so read a "
               "writer's callers when its list looks short.",
               {"pattern": s, "glob": s}, ["pattern"]),
            fn("add_fact", "Share a project fact other reviewers can rely on: one claim, at most 240 "
               "characters (e.g. how a helper escapes, that all data access goes through a typed query API, "
               "which base class enforces login). Rejected unless each quote is found at file:line.",
               {"statement": s, "evidence": {"type": "array", "items": {"type": "object", "properties": {
                   "file": s, "line": i, "quote": s}}}}, ["statement", "evidence"]),
        ]
    if role == "design":
        evidence = {"type": "object", "properties": {"file": s, "line": i, "quote": s}}
        tools.append(fn(
            "record_design",
            "Answer checklist items of the identity design review, one per call (item, status, answer, evidence, "
            "to_verify) or several in items; a later answer to an item replaces the earlier one. status: sound (the design holds, evidence quoted), flaw (it does not; also "
            "report_finding when you traced the harm), owner_decision (a risky default or trade-off the "
            "owner must accept or change, evidence quoted), unclear (say what is left to read), "
            "not_applicable.",
            {"item": {"type": "string", "enum": list(IDENTITY_CHECKLIST)},
             "status": {"type": "string", "enum": list(DESIGN_STATUSES)},
             "answer": {"type": "string", "description": "the design as the code implements it, and why it "
                        "holds or not"},
             "evidence": {"type": "array", "items": evidence},
             "to_verify": {"type": "string", "description": "for a flaw or unclear answer: the function or "
                           "file:line still to read to confirm it; a fresh reviewer is sent there"},
             "items": {"type": "array", "description": "several answers at once (same fields)",
                       "items": {"type": "object", "properties": {
                           "item": {"type": "string", "enum": list(IDENTITY_CHECKLIST)},
                           "status": {"type": "string", "enum": list(DESIGN_STATUSES)}, "answer": s,
                           "evidence": {"type": "array", "items": evidence}, "to_verify": s},
                           "required": ["item", "status", "answer"]}}},
            []))
    if role == "recon":
        tools.append(fn("finish", "Call once when you are done. unenumerated: every dispatcher you found but "
                        "did not enumerate (yet), each with where its routes are declared; another pass will "
                        "enumerate them.", {"notes": s, "unenumerated": {"type": "array", "items": s}}, []))
    else:
        tools.append(fn("finish", "Call once when you are done.", {"notes": s}, []))
    return tools

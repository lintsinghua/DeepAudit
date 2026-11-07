"""Tools exposed to the agents.

- Navigation: list_dir / read_file / grep (ripgrep) and yasa-mcp queries (functions, callers,
  call graph, route -> handler, symbol search) against a cache built with `yasa-mcp init`.
- yasa_run: runs the YASA taint engine with an agent-written ruleConfig; findings get global ids
  ("R<run>-F<i>") that later stages must cite (evidence binding).
- report_finding / finish: incremental, structured output.

All file access is confined to the project root (realpath + is_relative_to).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import AuditConfig
from .jsp2java import class_name, convert

SKIP_DIRS = {".yasa", ".codegraph", "node_modules", ".git"}
MAX_OUT = 8000


def clip(text: str, limit: int = MAX_OUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...[truncated {len(text) - limit} chars; narrow the query]"


def parse_sarif(data: dict, norm: Callable[[str], str]) -> dict[str, dict]:
    """Group YASA SARIF results by sink location 'file:line'."""
    by_sink: dict[str, dict] = {}
    for run in data.get("runs", []):
        for res in run.get("results", []):
            loc = res["locations"][0]["physicalLocation"]
            sink = f"{norm(loc['artifactLocation']['uri'])}:{loc['region']['startLine']}"
            hops = []
            for cf in res.get("codeFlows", []):
                for tf in cf.get("threadFlows", []):
                    for step in tf.get("locations", []):
                        p = step["location"]["physicalLocation"]
                        snip = p["region"].get("snippet", {})
                        txt = snip.get("text", "")
                        kind = next(
                            (t for t in ("SOURCE", "SINK", "Var Pass", "CALL", "ARG PASS", "Return")
                             if f"{t}:" in txt),
                            "",
                        )
                        hops.append(
                            f"{norm(p['artifactLocation']['uri'])}:{p['region']['startLine']} "
                            f"{kind} {snip.get('affectedNodeName', '')}"[:160]
                        )
            ep = res.get("entrypoint", {})
            item = by_sink.setdefault(
                sink,
                {
                    "sink": sink,
                    "attribute": res.get("sinkInfo", {}).get("sinkAttribute"),
                    "entry": f"{ep.get('filePath')}::{ep.get('functionName')}",
                    "sources": [],
                    "trace": hops,
                    "sanitizer_tags": res.get("matchedSanitizerTags") or "",
                },
            )
            if hops:
                item["sources"].append(hops[0])
    return by_sink


class Toolbox:
    def __init__(self, cfg: AuditConfig, root: str | Path, run_dir: Path, enable_yasa: bool):
        self.cfg = cfg
        self.root = Path(root).resolve()
        self.run_dir = run_dir
        self.enable_yasa = enable_yasa
        self.max_yasa_runs = cfg.builder_max_yasa_runs
        self.compact_engine_output = True
        self.yasa_runs = 0
        # Scoped, line-preserving engine copy (engine_scope.build_engine_src); same relative paths.
        self.engine_root: Path | None = None
        self.deadline: float | None = None  # epoch seconds; engine runs never exceed it
        self.registry: dict[str, dict] = {}
        self.findings: list[dict] = []
        self.finished = False
        self.notes = ""
        self.recon_entries: list[dict] = []
        self.recon_recipe: dict | None = None

    # ---------- helpers ----------
    def _safe(self, rel: str) -> Path:
        p = (self.root / str(rel).lstrip("/")).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("path escapes project root")
        return p

    def _mcp(self, args: list[str], timeout: int = 60) -> str:
        cmd = [self.cfg.yasamcp_bin, *args, "-p", str(self.root), "-j"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "error: navigation query timed out"
        except FileNotFoundError:
            return "error: yasa-mcp is not installed (see backend/scripts/setup_yasa.sh)"
        out = (r.stdout or "") + ("\n" + r.stderr[-1500:] if r.returncode and r.stderr else "")
        return clip(out.strip() or "(no result)")

    def _yasa_index_ready(self) -> bool:
        """yasa-mcp's func/callers/callgraph need the YASA call graph written by init."""
        d = self.root / ".yasa" / "yasamcp"
        # fingerprint_cache.json is written after the call graph has been imported
        return (d / "yasa.db").exists() and (d / "fingerprint_cache.json").exists()

    def _codegraph(self, args: list[str], timeout: int = 60) -> str:
        """Same questions answered from codegraph's index (built in seconds even for large projects)."""
        if not (self.root / ".codegraph" / "codegraph.db").exists():
            return "error: no navigation index for this project (use grep / read_file)"
        cmd = [self.cfg.codegraph_bin, *args, "-p", str(self.root)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return "error: navigation query timed out"
        except FileNotFoundError:
            return "error: codegraph is not installed (see backend/scripts/setup_yasa.sh)"
        out = (r.stdout or "") + ("\n" + r.stderr[-1500:] if r.returncode and r.stderr else "")
        return clip("[codegraph]\n" + (out.strip() or "(no result)"))

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
        end = int(end_line or 0) or min(len(lines), start + 199)
        end = min(end, start + 249, len(lines))
        body = "\n".join(f"{i:5d}| {lines[i - 1]}" for i in range(start, end + 1))
        return clip(f"{path} lines {start}-{end} of {len(lines)}\n{body}")

    def grep_rows(self, pattern: str, glob: str = "", per_file: int = 20) -> list[str]:
        """All matching "file:line:code" rows, uncapped (deterministic inventory; not a model tool)."""
        cmd = [self.cfg.rg_bin, "-n", "--no-heading", "-S", "-M", "300", "--max-count", str(per_file),
               "--engine", "auto"]  # PCRE2 when a pattern needs look-around
        for d in SKIP_DIRS:
            cmd += ["-g", f"!{d}"]
        if glob:
            cmd += ["-g", glob]
        cmd += ["-e", pattern, str(self.root)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return sorted(line.replace(str(self.root) + "/", "") for line in r.stdout.splitlines())

    def grep(self, pattern: str, glob: str = "", max_results: int = 60) -> str:
        try:
            rows = self.grep_rows(pattern, glob)
        except FileNotFoundError:
            return "error: ripgrep not found (set YASA_RG_BIN)"
        more = f"\n...[{len(rows) - max_results} more matches]" if len(rows) > max_results else ""
        return clip("\n".join(rows[: int(max_results)]) + more or "(no matches)")

    def find_function(self, name: str, file_path: str = "", detail: str = "summary") -> str:
        if not self._yasa_index_ready():
            return self._codegraph(["node", name])
        args = ["func", "--name", name, "--detail", detail, "--max-results", "10"]
        if file_path:
            args += ["--file-path", file_path]
        return self._mcp(args)

    def find_callers(self, name: str, file_path: str = "", line: int = 0) -> str:
        if not self._yasa_index_ready():
            return self._codegraph(["callers", name, "-l", "30"])
        args = ["callers", name, "--max-results", "30"]
        if file_path:
            args += ["--file-path", file_path]
        if line:
            args += ["--line", str(line)]
        return self._mcp(args)

    def call_graph(self, name: str, depth: int = 2, file_path: str = "") -> str:
        if not self._yasa_index_ready():
            return self._codegraph(["callees", name, "-l", "30"])
        args = ["callgraph", name, "--depth", str(depth), "--maxcallees", "8"]
        if file_path:
            args += ["--file-path", file_path]
        return self._mcp(args)

    def find_api(self, api_name: str) -> str:
        if not self._yasa_index_ready():
            return self._codegraph(["query", api_name, "-l", "20"])
        return self._mcp(["api", api_name, "--max-results", "20"])

    def search_symbol(self, query: str) -> str:
        if not self._yasa_index_ready():
            return self._codegraph(["query", query, "-l", "20"])
        return self._mcp(["search", query, "--max-results", "20"])

    # ---------- output ----------
    def report_finding(self, **finding: Any) -> str:
        if self.enable_yasa and finding.get("verdict") in ("confirmed", "likely"):
            ref = finding.get("yasa_ref", "")
            if ref not in self.registry:
                return f"rejected: yasa_ref '{ref}' is not an engine finding id (e.g. R2-F3)"
        self.findings.append(finding)
        return f"recorded #{len(self.findings)}"

    def try_recipe(self, recipe: Any) -> str:
        """Expand a routing recipe over the whole project and resolve handlers to real code.

        Returns coverage counters and samples so the agent can correct the recipe. The last recipe
        tried is kept as the recon result (the agent calls finish when the coverage looks right).
        """
        from . import routing
        from .discovery import codegraph_db
        if isinstance(recipe, str):
            try:
                recipe = json.loads(recipe)
            except json.JSONDecodeError as e:
                return f"error: recipe is not valid JSON: {e}"
        if not isinstance(recipe, dict) or recipe.get("family") not in routing.FAMILIES:
            return f"error: recipe needs a 'family' in {routing.FAMILIES}"
        services = recipe.get("services")
        try:
            entries = routing.expand(self.root, recipe)
        except Exception as e:
            return f"error: expand failed: {type(e).__name__}: {e}"
        if not entries:
            return ("0 routes matched. Check the file glob and the route element/attribute names against "
                    "a real config file (read one first).")
        rep = routing.resolve(self.root, codegraph_db(self.root), entries, services)
        self.recon_entries, self.recon_recipe = entries, recipe
        pub = sum(1 for e in entries if e.get("public") is True)
        auth = sum(1 for e in entries if e.get("public") is False)
        sample = [f"{e['route']} public={e.get('public')} -> "
                  f"{(e.get('file') + ':' + str(e.get('line'))) if e.get('resolved') else '(unresolved)'}"
                  for e in entries[:12]]
        return clip(json.dumps({"routes": len(entries), "resolved": rep["resolved"],
                                "unresolved": rep["unresolved"], "public": pub, "auth_required": auth,
                                "unknown_auth": len(entries) - pub - auth,
                                "sample": sample, "unresolved_samples": rep["unresolved_samples"][:8]},
                               ensure_ascii=False, indent=1))

    def finish(self, notes: str = "") -> str:
        self.finished = True
        self.notes = notes
        return f"finished with {len(self.findings)} findings"

    # ---------- YASA engine ----------
    def _prepare_jsp(self, src_root: Path, out_dir: Path) -> tuple[Path, dict[str, str]]:
        tmp = Path(tempfile.mkdtemp(prefix="yasa-src-", dir=str(out_dir)))
        for f in src_root.rglob("*.java"):
            if any(p in SKIP_DIRS for p in f.parts):
                continue
            dst = tmp / f.relative_to(src_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
        (tmp / "jsp").mkdir(exist_ok=True)
        jsp_map = {}
        for jsp in src_root.rglob("*.jsp"):
            cls = class_name(jsp.stem)
            (tmp / "jsp" / f"{cls}.java").write_text(convert(jsp.read_text(errors="ignore"), cls))
            jsp_map[f"jsp/{cls}.java"] = str(jsp.relative_to(self.root))
        return tmp, jsp_map

    def yasa_run(
        self,
        rule_config: Any,
        language: str,
        checker_ids: Any = None,
        checker_pack_ids: Any = None,
        analyzer: str = "",
        entrypoint_mode: str = "",
        preprocess_jsp: bool = False,
        source_subdir: str = "",
    ) -> str:
        if not self.enable_yasa:
            return "error: yasa_run is not available in this stage"
        if self.yasa_runs >= self.max_yasa_runs:
            return f"error: yasa_run budget ({self.max_yasa_runs} runs) exhausted"
        timeout = self.cfg.yasa_timeout_s
        if self.deadline is not None:
            timeout = int(min(timeout, self.deadline - time.time()))
            if timeout < 120:  # a shorter run only times out (Ghost: 69 s) and wastes the slot
                return "error: not enough time left for another engine run; call finish"
        self.yasa_runs += 1
        n = self.yasa_runs
        out_dir = self.run_dir / f"yasa-{n}"
        out_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(rule_config, str):
            try:
                rule_config = json.loads(rule_config)
            except json.JSONDecodeError as e:
                return f"error: rule_config is not valid JSON: {e}"
        if isinstance(rule_config, dict):
            rule_config = [rule_config]
        rc_path = out_dir / "rule_config.json"
        rc_path.write_text(json.dumps(rule_config, indent=1, ensure_ascii=False))

        base = self.engine_root or self.root
        if source_subdir:
            self._safe(source_subdir)  # path check against the project
            src_root = (base / source_subdir).resolve()
            if not src_root.is_relative_to(base.resolve()) or not src_root.exists():
                return f"error: {source_subdir} is not in the engine scope"
        else:
            src_root = base
        jsp_map: dict[str, str] = {}
        if preprocess_jsp:
            source_path, jsp_map = self._prepare_jsp(src_root, out_dir)
            prefix_rel = None
        else:
            source_path = src_root
            prefix_rel = src_root.relative_to(base.resolve()) if src_root != base else Path(".")

        cmd = [self.cfg.yasa_bin, "--sourcePath", str(source_path), "--language", language,
               "--ruleConfigFile", str(rc_path), "--report", str(out_dir / "report")]
        if language == "python":
            # The released package embeds a uast4py for the wrong platform; the one shipped next to
            # the engine works, so point the engine at it explicitly.
            uast = Path(self.cfg.yasa_bin).parent / "deps" / "uast4py"
            if uast.exists():
                cmd += ["--uastSDKPath", str(uast)]

        def as_csv(v: Any) -> str:
            return ",".join(v) if isinstance(v, list) else str(v)

        if checker_ids:
            cmd += ["--checkerIds", as_csv(checker_ids)]
        if checker_pack_ids:
            cmd += ["--checkerPackIds", as_csv(checker_pack_ids)]
        if analyzer:
            cmd += ["--analyzer", analyzer]
        if entrypoint_mode:
            cmd += ["--entrypointMode", entrypoint_mode]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return (f"error: YASA timed out after {timeout}s; narrow the entrypoints "
                    "(see playbook: bootstrap file as the only entrypoint) or finish")
        except FileNotFoundError:
            return "error: YASA binary not found (set YASA_BIN or run setup_yasa.sh)"
        (out_dir / "stdout.txt").write_text(r.stdout[-200000:] + "\n" + r.stderr[-50000:])

        stats: dict[str, Any] = {}
        summ = out_dir / "report" / "scan_summary.json"
        if summ.exists():
            s = json.loads(summ.read_text())
            s = json.loads(s["string3"]) if "string3" in s else s
            stats = {k: s.get(k) for k in ("fileCount", "lineCount", "entryPointCount",
                                           "markedSourceCount", "matchedSinkCount",
                                           "findingCount", "totalTimeMs")}
        errors = [line for line in (r.stdout + r.stderr).splitlines() if "rror" in line][:8]

        def norm(uri: str) -> str:
            u = uri.replace("file://", "")
            sp = str(source_path)
            if u.startswith(sp):
                u = u[len(sp):]
            u = u.lstrip("/")
            if u in jsp_map:
                return jsp_map[u]
            return str(prefix_rel / u) if prefix_rel and str(prefix_rel) != "." else u

        sarif = out_dir / "report" / "report.sarif"
        by_sink = parse_sarif(json.loads(sarif.read_text()), norm) if sarif.exists() else {}

        lines = [f"yasa run #{n}: exit={r.returncode} stats={json.dumps(stats)}"]
        if errors:
            lines.append("errors: " + " | ".join(errors))
        if preprocess_jsp:
            lines.append(f"jsp preprocessed: {len(jsp_map)} files")
        for i, (sink, it) in enumerate(sorted(by_sink.items()), 1):
            fid = f"R{n}-F{i}"
            self.registry[fid] = it
            srcs = sorted(set(it["sources"]))
            if self.compact_engine_output:
                lines.append(f"{fid} sink={sink} attr={it['attribute']} "
                             f"first_source={srcs[0] if srcs else '-'}")
            else:
                lines.append(f"{fid} sink={sink} attr={it['attribute']} entry={it['entry']} "
                             f"sources({len(srcs)})={srcs[:3]}")
                lines.append("    trace: " + " -> ".join(it["trace"][:8]))
        if not by_sink:
            lines.append("no findings")
        (self.run_dir / "yasa_registry.json").write_text(
            json.dumps(self.registry, indent=1, ensure_ascii=False)
        )
        return clip("\n".join(lines), 4000 if self.compact_engine_output else 12000)


def tool_schemas(enable_yasa: bool, with_report: bool = True, with_recipe: bool = False) -> list[dict]:
    def fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}

    s = {"type": "string"}
    i = {"type": "integer"}
    tools = [
        fn("list_dir", "List files under a project directory (relative path).",
           {"path": s, "depth": i}, []),
        fn("read_file", "Read a file with line numbers. At most 250 lines per call.",
           {"path": s, "start_line": i, "end_line": i}, ["path"]),
        fn("grep", "Ripgrep regex search over the project. Returns file:line:text.",
           {"pattern": s, "glob": {"type": "string", "description": "e.g. *.java or routes/**"},
            "max_results": i}, ["pattern"]),
        fn("find_function", "Find a function definition by name. detail=full returns the body.",
           {"name": s, "file_path": s, "detail": {"type": "string", "enum": ["summary", "full"]}},
           ["name"]),
        fn("find_callers", "Find call sites of a function.",
           {"name": s, "file_path": s, "line": i}, ["name"]),
        fn("call_graph", "Call graph (callees) of a function to a given depth.",
           {"name": s, "depth": i, "file_path": s}, ["name"]),
        fn("find_api", "Map an HTTP route / API name to its implementing function.",
           {"api_name": s}, ["api_name"]),
        fn("search_symbol", "Search functions/classes/files by name.", {"query": s}, ["query"]),
    ]
    if with_report:
        props = {
            "vuln_type": s, "cwe": s, "sink_file": s, "sink_line": i,
            "source": {"type": "string", "description": "attacker-controlled input and where (file:line)"},
            "entry": {"type": "string", "description": "route / entry point and who can reach it"},
            "hops": {"type": "array", "items": s, "description": "file:line steps from source to sink"},
            "sanitizers": {"type": "string",
                           "description": "sanitizers seen and why they do or do not stop this class"},
            "verdict": {"type": "string", "enum": ["confirmed", "likely", "false_positive"]},
            "yasa_ref": {"type": "string", "description": "engine finding id (e.g. R2-F3), if any"},
        }
        tools.append(fn("report_finding",
                        "Record ONE finding, or one rejected candidate with verdict false_positive.",
                        props, ["vuln_type", "cwe", "sink_file", "sink_line", "source", "verdict"]))
    if with_recipe:
        tools.append(fn(
            "try_recipe",
            "Expand a routing recipe over the whole project and resolve each route's handler to real "
            "code. Returns route/auth/resolution counters and samples. Call it repeatedly, refining the "
            "recipe, until coverage looks right; the last recipe is kept.",
            {"recipe": {"type": "object", "description": "a routing recipe: family (config-xml | "
                        "annotation), the file glob, and how to read the route uri, auth, handler and "
                        "view; optionally a 'services' section for a request->service->impl hop"}},
            ["recipe"]))
    tools.append(fn("finish", "Call once when you are done.", {"notes": s}, []))
    if enable_yasa:
        tools.append(fn(
            "yasa_run",
            "Run the YASA taint engine with a rule config you wrote. Returns scan counters "
            "(fileCount, entryPointCount, markedSourceCount, matchedSinkCount, findingCount) and "
            "findings deduplicated by sink, each with an id R<run>-F<i>.",
            {"rule_config": {"type": "array", "items": {"type": "object"},
                             "description": "YASA ruleConfig JSON array"},
             "language": {"type": "string",
                          "enum": ["java", "javascript", "typescript", "python", "golang", "php"]},
             "checker_ids": {"type": "array", "items": s},
             "checker_pack_ids": {"type": "array", "items": s},
             "analyzer": s,
             "entrypoint_mode": {"type": "string", "enum": ["BOTH", "SELF_COLLECT", "ONLY_CUSTOM"]},
             "preprocess_jsp": {"type": "boolean",
                                "description": "convert JSP scriptlets to line-preserving Java first"},
             "source_subdir": s},
            ["rule_config", "language"]))
    return tools

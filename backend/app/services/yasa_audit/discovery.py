"""Entry-point discovery from the indexes yasa-mcp already builds, independent of language and project.

Layers, each entry tagged with `via`:

1. codegraph  - `route` nodes of codegraph's framework resolvers (Spring, Laravel, Drupal, Django,
                Flask, FastAPI, Express, NestJS, Go, Rails, ASP.NET, ...). The handler comes from the
                route node's calls/references edges.
2. yasa-mcp   - `yasamcp api` interface / RPC implementations (Java, Python services).
3. script     - URL-addressable files for script-style code (PHP, JSP, ...). If most files share a
                direct-access guard (`if (!defined('X')) die`), the entries are the files that define X
                and are not guarded themselves; JSP pages outside WEB-INF are entries. Otherwise: files
                with top-level code that read request input and that no other file includes.
4. regex      - the framework extractors in entrypoints.py, only where layers 1-3 found nothing for a
                file, plus guard annotations for entries found by layers 1-3.

Entries that pick the code to run from request data (dynamic include, `new $x`, call_user_func,
`$obj->$m()`, getattr, reflection) are flagged `dispatcher`, so a reviewer resolves the convention
once instead of every target file being treated as an entry.

codegraph's index (<root>/.codegraph/codegraph.db) is written by `yasamcp init` within seconds to a
minute; it stays usable when the slower YASA call-graph step of init times out.
"""

from __future__ import annotations

import collections
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path

from .entrypoints import entries_for as regex_entries

SKIP_RE = re.compile(r"(^|/)(tests?|__tests__|spec|vendor|node_modules|\.git|\.yasa|\.codegraph|venv|\.venv|"
                     r"site-packages|examples?|docs?)/")
SCRIPT_EXT = (".php", ".phtml", ".jsp", ".jspx")
REQUEST_RE = re.compile(r"\$_(GET|POST|REQUEST|COOKIE|FILES|SERVER)\b|php://input|getParameter\s*\(|"
                        r"getQueryString\s*\(|getInputStream\s*\(|request\.(args|form|GET|POST|body|query)")
GUARD_RE = re.compile(r"""if\s*\(\s*!\s*defined\s*\(\s*['"](\w+)['"]\s*\)[^)]*\)\s*\{?\s*"""
                      r"""(die|exit|header|return|throw)""")
DISPATCH_RE = re.compile(
    r"\b(include|require)(_once)?(\s+|\s*\()\s*(\"[^\"\n]*\$\w+|[^;'\"\n]*\$\w+)|"  # PHP include of a variable path
    r"new\s+\$\w+|call_user_func(_array)?\s*\(|\$\w+->\$\w+\s*\(|\$\w+::\$\w+\s*\(|"
    r"getattr\s*\([^)]*request|importlib\.import_module\s*\(\s*[^'\")]|"
    r"Class\.forName\s*\([^)]*getParameter|\.getMethod\s*\([^)]*getParameter|"
    r"\[\s*req(uest)?\.(params|query|body)\.\w+\s*\]\s*\(")
HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ANY", "USE", "ALL"}


# Test code, fixtures and demos are not entries, whatever framework resolver produced them.
NOISE_RE = re.compile(r"(^|/)(tests?|__tests__|__mocks__|spec|e2e|fixtures?|demos?|examples?|stories|storybook|"
                      r"mocks?)/|\.(test|spec|stories|e2e)\.[cm]?[jt]sx?$|_test\.(py|go)$|(^|/)test_[^/]+\.py$")
# Client-side component files: their routes (React Router, Vue Router, ...) are not server entries.
FRONTEND_EXT = (".tsx", ".jsx", ".vue", ".svelte")

CLIENT_DEPS = {"react", "react-dom", "vue", "svelte", "@angular/core", "preact", "solid-js", "ember-source"}
SERVER_DEPS = {"express", "koa", "fastify", "@hapi/hapi", "hapi", "@nestjs/core", "next", "nuxt", "@remix-run/node",
               "restify", "@sveltejs/kit", "sails", "loopback", "@adonisjs/core", "egg"}
_CLIENT_PKG: dict[str, bool] = {}


def is_client_package(root: Path, rel: str) -> bool:
    """rel lies in a JS package that depends on a UI framework and on no server framework."""
    parts = Path(rel).parts[:-1]
    for i in range(len(parts), -1, -1):
        d = root.joinpath(*parts[:i]) if i else root
        pj = d / "package.json"
        if not pj.exists():
            continue
        key = str(pj)
        if key not in _CLIENT_PKG:
            try:
                data = json.loads(pj.read_text(errors="ignore"))
            except ValueError:
                data = {}
            deps = set()
            for k in ("dependencies", "devDependencies", "peerDependencies"):
                deps |= set((data.get(k) or {}).keys())
            _CLIENT_PKG[key] = bool(deps & CLIENT_DEPS) and not (deps & SERVER_DEPS)
        return _CLIENT_PKG[key]
    return False


_SNAPSHOTS: dict[str, Path] = {}


def codegraph_db(root: Path) -> Path | None:
    """The codegraph index for root: a private snapshot when one was taken, else the live file."""
    snap = _SNAPSHOTS.get(str(root.resolve()))
    if snap is not None and snap.exists():
        return snap
    p = root / ".codegraph" / "codegraph.db"
    return p if p.exists() and p.stat().st_size > 0 else None


def snapshot_codegraph(root: Path, dest_dir: Path) -> Path | None:
    """Copy the live index (WAL mode, still opened by a background yasa-mcp init) into dest_dir.

    Later reads use the copy, so they neither wait on nor race with the init process. Returns None
    (and the live index stays in use) when there is no complete index or the copy fails.
    """
    key = str(root.resolve())
    if key in _SNAPSHOTS and _SNAPSHOTS[key].exists():
        return _SNAPSHOTS[key]
    live = root / ".codegraph" / "codegraph.db"
    if not codegraph_ready(root):
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "codegraph.snapshot.db"
    try:
        src = sqlite3.connect(f"file:{live}?mode=ro", uri=True, timeout=30)
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.Error:
        dest.unlink(missing_ok=True)
        return None
    _SNAPSHOTS[key] = dest
    return dest


def codegraph_ready(root: Path) -> bool:
    """codegraph has finished writing its index (it records index_state=complete)."""
    db = root / ".codegraph" / "codegraph.db"
    if not db.exists() or db.stat().st_size == 0:
        return False
    try:
        con = _connect(db)
        try:
            row = con.execute("select value from project_metadata where key = 'index_state'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return bool(row and row[0] == "complete")


def ensure_codegraph(codegraph_bin: str, root: Path, timeout_s: int = 300) -> Path | None:
    """Build codegraph's index directly when yasa-mcp init did not leave one."""
    if (db := codegraph_db(root)) is not None:
        return db
    if not Path(codegraph_bin).exists():
        return None
    try:
        subprocess.run([codegraph_bin, "init", str(root)], capture_output=True, timeout=timeout_s,
                       start_new_session=True)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return codegraph_db(root)


def _connect(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)


def _split_route(name: str) -> tuple[str, str]:
    """codegraph names routes 'GET /x' (or just '/x' for some resolvers)."""
    head, _, tail = name.partition(" ")
    if tail and head.upper() in HTTP_VERBS:
        return head.upper(), tail
    return "ANY", name


def _enclosing_functions(con: sqlite3.Connection, files: set[str]) -> dict[str, list[tuple]]:
    """file -> [(start, end, name, exported)] of functions / methods, for registration-site lookup."""
    out: dict[str, list[tuple]] = collections.defaultdict(list)
    try:
        rows = con.execute("select file_path, start_line, end_line, name, is_exported from nodes "
                           "where kind in ('function', 'method')").fetchall()
    except sqlite3.Error:  # older index without spans: routes still work, without registration_fn
        return out
    for path, start, end, name, exported in rows:
        if path in files:
            out[path].append((start or 0, end or 0, name, bool(exported)))
    return out


def codegraph_routes(db: Path, root: Path | None = None) -> list[dict]:
    """Server routes from codegraph. root is the project directory (db may be a snapshot elsewhere)."""
    root = root or db.parent.parent
    con = _connect(db)
    try:
        routes = [r for r in con.execute("select id, name, file_path, start_line from nodes where kind='route'")
                  if not NOISE_RE.search(r[2] or "")]
        functions = _enclosing_functions(con, {r[2] for r in routes})
        handlers: dict[str, list[tuple]] = collections.defaultdict(list)
        for src, _kind, name, path, line in con.execute(
                "select e.source, t.kind, t.name, t.file_path, t.start_line from edges e "
                "join nodes s on s.id = e.source join nodes t on t.id = e.target "
                "where s.kind = 'route' and e.kind in ('calls', 'references') "
                "and t.kind in ('function', 'method')"):
            handlers[src].append((name, path, line))
    finally:
        con.close()
    out = []
    lines_cache: dict[str, list[str]] = {}
    for rid, name, path, line in routes:
        method, route = _split_route(name)
        hs = handlers.get(rid, [])
        if path not in lines_cache:
            p = root / path
            lines_cache[path] = p.read_text(errors="ignore").splitlines() if p.is_file() else []
        reg = " ".join(lines_cache[path][max(0, line - 1):line + 2])
        # Handler = the referenced function named last on the registration line (earlier ones are
        # middleware); resolvers that point at the decorated function have it on the next lines.
        named = sorted((reg.rfind(h[0]), h) for h in hs if h[0] and reg.rfind(h[0]) >= 0)
        h = named[-1][1] if named else (hs[-1] if hs else None)
        if method == "ANY" and (path.endswith(FRONTEND_EXT) or (h and str(h[1]).endswith(FRONTEND_EXT))):
            continue  # client-side router (React Router, Vue Router ...): not a server entry
        if path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte")) and is_client_package(root, path):
            continue  # code of a UI package (client fetch calls, routers), not served by the backend
        if h and NOISE_RE.search(str(h[1])):
            continue
        # The function whose body registers the route: the engine has to start there, because a
        # file-level start only defines it (e.g. module.exports = function apiRoutes() { router.get(...) }).
        around = [f for f in functions.get(path, []) if f[0] <= line <= f[1]]
        reg_fn = min(around, key=lambda f: f[1] - f[0]) if around else None
        out.append({"route": route, "method": method, "file": h[1] if h else path,
                    "line": h[2] if h else line, "handler": h[0] if h else "",
                    "registered_at": f"{path}:{line}",
                    "registration_fn": reg_fn[2] if reg_fn else "",
                    "middleware": [x[0] for _, x in named[:-1]] if named else [],
                    "guards": [], "via": "codegraph"})
    return out


def yasamcp_apis(yasamcp_bin: str, root: Path, timeout_s: int = 60) -> list[dict]:
    try:
        r = subprocess.run([yasamcp_bin, "api", ".*", "--use-regex", "--max-results", "0", "-j",
                            "-p", str(root)], capture_output=True, text=True, timeout=timeout_s)
        items = json.loads(r.stdout or "{}").get("results", [])
    except (subprocess.TimeoutExpired, OSError, ValueError, AttributeError):
        return []
    out = []
    for it in items:
        loc = it.get("location") or {}
        line = loc.get("start_line") or loc.get("startLine") or loc.get("line") or 1
        out.append({"route": it.get("api_name", ""), "method": "RPC", "file": it.get("filepath", ""),
                    "line": line, "handler": it.get("full_name", ""), "guards": [], "via": "yasa-mcp"})
    return out


def _script_files(root: Path) -> list[str]:
    files = []
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if not x.startswith(".")]
        for f in fs:
            if f.endswith(SCRIPT_EXT):
                rel = os.path.relpath(os.path.join(d, f), root)
                if not SKIP_RE.search("/" + rel) and not NOISE_RE.search(rel):
                    files.append(rel)
    return sorted(files)


def _included_files(db: Path | None) -> set[str]:
    if db is None:
        return set()
    con = _connect(db)
    try:
        return {r[0] for r in con.execute(
            "select distinct t.file_path from edges e join nodes s on s.id = e.source "
            "join nodes t on t.id = e.target where e.kind = 'imports' and t.kind = 'file' "
            "and s.file_path <> t.file_path")}
    finally:
        con.close()


_DECL_ONLY = re.compile(
    r"(?s)\s*(<\?php)?\s*(namespace[^;]+;\s*|(use|require|include)(_once)?[^;]+;\s*|"
    r"if\s*\(\s*!\s*defined\([^)]*\)\s*\)\s*(\{[^}]*\}|[^;]+;)\s*|global\s+[^;]+;\s*)*"
    r"((abstract\s+|final\s+|readonly\s+)*(class|interface|trait|enum|function)\b.*)?")


def script_entries(root: Path, db: Path | None = None) -> tuple[list[dict], dict]:
    """URL-addressable script files. Returns (entries, info about the rule that was applied)."""
    files = _script_files(root)
    if not files:
        return [], {"rule": "none"}
    text = {f: (root / f).read_text(errors="ignore") for f in files}
    guards = collections.Counter(m.group(1) for t in text.values() if (m := GUARD_RE.search(t[:4000])))
    out = []
    jsp = [f for f in files if f.endswith((".jsp", ".jspx")) and "WEB-INF/" not in f]
    for f in jsp:
        out.append({"route": "/" + f.split("WebContent/", 1)[-1].split("webapp/", 1)[-1], "method": "GET/POST",
                    "file": f, "line": 1, "guards": [], "via": "script"})
    php = [f for f in files if not f.endswith((".jsp", ".jspx"))]
    const, n_guarded = guards.most_common(1)[0] if guards else ("", 0)
    if php and n_guarded >= max(5, len(php) // 10):
        rule = {"rule": "direct-access guard", "constant": const, "guarded_files": n_guarded}
        define_re = re.compile(rf"""(?<!\w)define\s*\(\s*['"]{const}['"]""")

        def guarded(t: str) -> bool:
            return any(m.group(1) == const for m in GUARD_RE.finditer(t[:4000]))
        chosen = [f for f in php if define_re.search(text[f]) and not guarded(text[f])]
    else:
        included = _included_files(db)
        rule = {"rule": "not included + top-level code + reads request input"}
        chosen = [f for f in php if f not in included and REQUEST_RE.search(text[f])
                  and not _DECL_ONLY.fullmatch(re.sub(r"(?s)/\*.*?\*/|//[^\n]*|#[^\n]*", "", text[f]))]
    for f in chosen:
        out.append({"route": "/" + f, "method": "GET/POST", "file": f, "line": 1, "guards": [],
                    "via": "script"})
    rule["entries"] = len(out)
    return out, rule


# Web-server access rules, wherever they are written: .htaccess / web.config / nginx or Apache
# configs in the repo, or rule templates that an installer writes from code.
DENY_RES = [
    re.compile(r"RedirectMatch\s+(?:403|404)\s+(?:\{\$\w+\}|\(\?i\))?\s*(\S+)"),
    re.compile(r"RewriteRule\s+(\S+)\s+-\s+\[[^\]]*\b(F|forbidden|G|gone)\b", re.I),
    re.compile(r"location\s+~\*?\s+(\S+)\s*\{[^}]*\bdeny\s+all", re.S),
]
CONF_NAMES = (".htaccess", "web.config", "nginx.conf", "httpd.conf", "apache.conf")


def web_server_denies(root: Path, lang_files: list[str] | None = None) -> list[dict]:
    """Deny rules found in server config files, and in code that writes them (installer templates)."""
    out: list[dict] = []
    sources: list[str] = []
    for d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if not x.startswith(".") and x not in ("node_modules", "vendor")]
        for f in fs:
            if f in CONF_NAMES or f.endswith((".conf", ".htaccess")):
                sources.append(os.path.relpath(os.path.join(d, f), root))
    sources += [f for f in (lang_files or []) if "htaccess" in f.lower() or "install" in f.lower()]
    for rel in dict.fromkeys(sources):
        p = root / rel
        txt = p.read_text(errors="ignore") if p.is_file() else ""
        if not re.search(r"RedirectMatch|RewriteRule|deny\s+all|Require all denied", txt):
            continue
        for rx in DENY_RES:
            for m in rx.finditer(txt):
                pat = m.group(1).strip("\"'")
                try:
                    out.append({"pattern": pat, "re": re.compile(pat, re.I),
                                "where": f"{rel}:{txt[:m.start()].count(chr(10)) + 1}"})
                except re.error:
                    continue
    return out


def mark_server_denies(entries: list[dict], denies: list[dict]) -> None:
    for e in entries:
        url = e.get("route") if e.get("via") == "script" else None
        if not url:
            continue
        hits = [d for d in denies if d["re"].search(url)]
        if hits:
            e["web_server_denied"] = f"{hits[0]['pattern']} ({hits[0]['where']})"


def mark_dispatchers(root: Path, entries: list[dict]) -> None:
    cache: dict[str, str] = {}
    for e in entries:
        f = e.get("file") or ""
        if f not in cache:
            p = root / f
            cache[f] = p.read_text(errors="ignore") if p.is_file() else ""
        txt = cache[f]
        if e.get("via") != "script":  # route handler: look at the handler body only
            lines = txt.splitlines()
            start = max(0, int(e.get("line") or 1) - 1)
            txt = "\n".join(lines[start:start + 60])
        m = DISPATCH_RE.search(txt)
        if m and REQUEST_RE.search(txt):
            e["dispatcher"] = re.sub(r"\s+", " ", m.group(0))[:80]


def discover(root: Path, lang: str, yasamcp_bin: str = "", codegraph_bin: str = "") -> tuple[list[dict], dict]:
    """All layers merged. Returns (entries, summary of what each layer contributed)."""
    db = codegraph_db(root) or (ensure_codegraph(codegraph_bin, root) if codegraph_bin else None)
    layers: dict[str, list[dict]] = {
        "codegraph": codegraph_routes(db, root) if db else [],
        "yasa-mcp": yasamcp_apis(yasamcp_bin, root) if yasamcp_bin else [],
    }
    scripts, rule = script_entries(root, db)
    layers["script"] = scripts
    try:
        regex = [dict(e, via="regex") for e in regex_entries(root, lang) if not NOISE_RE.search(e.get("file", ""))]
    except Exception:  # extractor gaps must not break discovery
        regex = []

    entries: list[dict] = []
    seen_file_line: set[tuple] = set()
    for name in ("codegraph", "yasa-mcp", "script"):
        for e in layers[name]:
            key = (e["file"], e["line"], e["route"])
            if key not in seen_file_line:
                seen_file_line.add(key)
                entries.append(e)
    # Regex extractors: guard annotations for entries we have, new entries only for uncovered files.
    by_site = {e["registered_at"]: e for e in entries if e.get("registered_at")}
    by_handler = {(e["file"], e["line"]): e for e in entries}
    covered_files = {e["file"] for e in entries}
    added = 0
    for r in regex:
        if scripts and r["file"].endswith(SCRIPT_EXT) and not r.get("handler"):
            continue  # the regex "every script is an entry" fallback; the script layer decided
        hit = by_site.get(r.get("registered_at", "")) or by_handler.get((r["file"], r["line"]))
        if hit is not None:
            # the regex extractor resolves handlers through imports and computes effective guards
            for k in ("route", "file", "line", "handler"):
                if r.get(k) and hit.get("via") == "codegraph" and r.get("registered_at"):
                    hit[k] = r[k]
            hit["guards"] = list(dict.fromkeys(hit["guards"] + r.get("guards", [])))
            hit["via"] = hit["via"] + "+regex"
        elif r["file"] not in covered_files:
            entries.append(r)
            added += 1
    entries = [e for e in entries
               if not (str(e.get("file", "")).endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte"))
                       and is_client_package(root, e["file"]))]
    mark_dispatchers(root, entries)
    php_like = [e["file"] for e in scripts]
    denies = web_server_denies(root, [f for f in _script_files(root) if f not in php_like] if scripts else [])
    mark_server_denies(entries, denies)
    summary = {"codegraph_index": bool(db), "codegraph_routes": len(layers["codegraph"]),
               "yasamcp_apis": len(layers["yasa-mcp"]), "script": rule, "regex_added": added,
               "total": len(entries), "dispatchers": sum(1 for e in entries if e.get("dispatcher")),
               "web_server_deny_rules": [{"pattern": d["pattern"], "where": d["where"]} for d in denies][:30],
               "denied_entries": sum(1 for e in entries if e.get("web_server_denied"))}
    return entries, summary


def reachable_files(root: Path, entry_files: list[str], depth: int = 6) -> set[str]:
    """Files reachable from entry files over codegraph's static edges (empty without an index)."""
    db = codegraph_db(root)
    if db is None or not entry_files:
        return set()
    con = _connect(db)
    try:
        graph: dict[str, set[str]] = collections.defaultdict(set)
        for a, b in con.execute(
                "select distinct s.file_path, t.file_path from edges e join nodes s on s.id = e.source "
                "join nodes t on t.id = e.target where e.kind in ('calls', 'imports', 'instantiates', "
                "'references', 'extends', 'implements') and s.file_path <> t.file_path"):
            graph[a].add(b)
    finally:
        con.close()
    seen = set(entry_files)
    frontier = set(entry_files)
    for _ in range(depth):
        frontier = {b for a in frontier for b in graph.get(a, ())} - seen
        if not frontier:
            break
        seen |= frontier
    return seen

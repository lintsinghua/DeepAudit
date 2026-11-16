"""What is worth protecting: sensitive operations and identity subsystems, mapped once per project.

Entry-first review starts where requests come in and reads forward. It stops at the first sanitizer,
does not see code that no route reaches directly (render pipelines, hooks, extension points), and judges
one route at a time, never the design of a module. This stage maps the other end, so the review can
also start there:

operations  A fixed set of classes of harmful operation (OP_CLASSES). They describe effects, not
            frameworks. An agent finds how THIS project performs each class: the sensitive fields of
            its data model, the guards the project applies itself (permission and ownership checks,
            escaping, allowlists), the helpers the operations go through. It writes each form as a
            declarative recipe: a search pattern and, optionally, the project's guard for it. The
            executor here expands a recipe over the whole project and places every site in the call
            graph. It reports which entries reach the site, whether anything calls it at all (an
            extension point), and whether the guard is on the way. The agent refines its recipes on
            these counters, the same way it refines extractors on coverage. Each site becomes part of
            a review unit that works backward from the operation to every way of reaching it.
identity    The subsystems that create or prove an identity (registration, login, recovery, SSO,
            tokens, account linking, user management), each with its routes, files, models and
            settings. Each subsystem gets one design review against a fixed checklist
            (IDENTITY_CHECKLIST). The flaws in these subsystems sit in how the parts fit together,
            not on one route.

Everything in this module is deterministic: the agents decide what to look for, and this code
expands it and does the counting.
"""

from __future__ import annotations

import collections
import json
import os
import random
import re
import threading
from pathlib import Path
from typing import Any, Final

from .discovery import _connect, codegraph_db

# The classes are fixed and framework-independent; their concrete forms come from the project. Each
# description says what the operation does, then (in brackets) the forms it usually takes.
OP_CLASSES: dict[str, str] = {
    "credential_or_privilege_write": "sets or changes what an account is or may do: its password or other "
                                     "credentials, tokens, role, group memberships or permissions (registration, "
                                     "profile updates, role and permission grants)",
    "act_on_other_account": "acts on an account other than the caller's: sets its password or credentials, issues "
                            "it an invitation, reset link, key or session, rotates its key, changes its role or "
                            "memberships, disables or deletes it (user, member and key management on someone "
                            "else's behalf)",
    "bulk_field_assignment": "copies request fields onto a stored object without naming each field (mass "
                             "assignment: fill, update or merge with the request body, model binding, spreading "
                             "request data into a create or update call)",
    "object_by_request_id": "loads, changes or deletes a stored object chosen by an id, key, slug or path taken "
                            "from the request (find by id, delete by key, lookups of files, records or settings)",
    "personal_data_output": "puts personal or secret fields of a record into something a person other than its "
                            "owner can read (email, IP address, phone, address, password hash or token in a "
                            "response, export, feed, notification or log)",
    "query_construction": "builds a database or search query from text or structures that contain request or "
                          "stored data (raw SQL and SQL fragments, column or sort names, NoSQL filter objects "
                          "and operators, search-engine query strings)",
    "code_or_command_execution": "runs code or commands that are not fixed in the program text (shell commands "
                                 "and process spawning, eval and dynamic code, includes or imports chosen at run "
                                 "time, templates compiled from data, object deserialization, XML parsing with "
                                 "external entities)",
    "outbound_request": "makes the server fetch a URL or connect to a host (HTTP clients, URL openers, mail and "
                        "webhook senders, embed, preview and import fetchers)",
    "raw_markup_output": "writes stored or request data into HTML, markup or an attribute without the project's "
                         "escaping (raw template output, innerHTML, unescaped attributes, and directive, "
                         "shortcode or Markdown processing that runs after sanitizing)",
    "file_write": "writes, moves, extracts or deletes a file (uploads, exports, caches, archive extraction, "
                  "generated code or configuration)",
    "state_change_in_read_path": "changes persistent state on a path that is meant only to read (GET handlers, "
                                 "permission or visibility callbacks, renderers, getters, feeds)",
    "secret_generation_or_check": "creates or checks a secret value (reset and verification codes, API and "
                                  "one-time tokens, share or preview links, signed URLs, webhook signatures, CSRF "
                                  "tokens, encryption keys: how it is generated, compared, stored, and whether it "
                                  "is hard-coded)",
}

IDENTITY_KINDS = ("registration", "login", "password_recovery", "sso", "api_token", "account_linking",
                  "invitation", "mfa", "session", "user_management")

# One design question per item, the same for every project and subsystem.
IDENTITY_CHECKLIST: dict[str, str] = {
    "identity_binding": "How is an external or asserted identity (SSO/OAuth subject, email, username, "
                        "invitation, token owner) bound to a local account? Is the key immutable and "
                        "verified, or a field the user or the provider can change (email, username, "
                        "display name)? Can one identity reach another's account?",
    "record_claiming": "Can an existing record that is not an active, credentialed account (deactivated, "
                       "guest, pending, invited, imported, soft-deleted, unverified) be claimed by "
                       "registration, login, SSO or recovery, and what does the claimant inherit (groups, "
                       "roles, data, history)?",
    "token_lifecycle": "For each secret the subsystem issues (reset codes, activation and invitation links, "
                       "API or access tokens, remember-me, sessions, MFA codes): does it expire, is it "
                       "single-use, bound to the account and purpose, stored hashed, compared in constant "
                       "time, and revoked when the password, email or role changes?",
    "defaults": "What does an install with no configuration allow (open registration, the role of new "
                "accounts, verification off, SSO auto-create or auto-link, token scopes), and which "
                "security settings are off by default?",
    "privilege_ceiling": "For each principal this subsystem creates or manages (its roles, scopes, tokens), "
                         "compare what it can reach with its designed power in the access model: can it grant "
                         "or reach more than it holds (assign roles, groups, permissions or scopes above its "
                         "own, change the credentials, email or MFA of a more privileged account), directly or "
                         "indirectly (groups, invitations, impersonation, token scopes)?",
}
DESIGN_STATUSES = ("sound", "flaw", "owner_decision", "unclear", "not_applicable")

# Code that is not the product: tests, vendored dependencies, built bundles.
NOISE_PATH = re.compile(r"(^|/)(tests?|spec|specs|__tests__|__mocks__|fixtures?|vendor|node_modules|"
                        r"bower_components)(/|$)|\.(test|spec)\.\w+$|\.min\.js$")
MAX_SITES = 1500  # a recipe matching more is a word search, not an operation
ANCESTOR_DEPTH = 6
GUARD_DEPTH = 3  # the guard counts when it is in the operation's function or a caller this close
FILE_GUARD_LINES = 40  # for code outside any function: how far above the operation the guard counts
REACH_ORDER = {"handler": 0, "entry": 1, "unindexed": 2, "no_callers": 2, "internal": 3}
# Files that are documentation or data, not code: a match there is a mention, not an operation
NOT_CODE: Final = (".md", ".rst", ".txt", ".lock", ".csv", ".svg", ".map", ".log", ".json", ".min.js", ".yaml",
                   ".yml", ".toml", ".ini", ".proto", ".example", ".css", ".less", ".scss", ".sass")
HUB_ENTRIES = 20  # a function reached by this many entries is shared infrastructure: review its contract once
DESIGN_SPLIT_ENTRIES = 40  # a subsystem with more entries is reviewed in parts of at most this many
CROSS_CUTTING_SHARE = 1 / 3  # a subsystem matching more of all entries than this is a mechanism they pass
REACH_DEPTH = 8  # calls followed from an entry's handler when deciding which code the entries reach
CALLER_KINDS = ("file", "module", "component")  # non-function nodes that can call (module-level code)

FUNCS = ("function", "method")
TYPES = ("class", "interface", "trait", "enum", "struct")


# ----------------------------------------------------------------- the call index

def _tail(name: str) -> str:
    return re.split(r"::|\.|#|->|\\", name or "")[-1]


class CallIndex:
    """Function spans and reverse call edges from codegraph's index, loaded once.

    A call to an interface or parent method counts as a call to the implementations of it (the same
    rule graph.py follows for find_callers). Without an index every site is file-level code.
    """

    def __init__(self, root: Path):
        self.root = root
        self.spans: dict[str, list[tuple[int, int, str]]] = collections.defaultdict(list)
        self.loc: dict[str, tuple[str, int, int, str]] = {}  # id -> (file, start, end, qualified name)
        self.callers: dict[str, set[str]] = collections.defaultdict(set)
        self.overrides: dict[str, list[str]] = collections.defaultdict(list)  # method -> parent methods
        self.callees: dict[str, set[str]] = collections.defaultdict(set)
        # for reachability only: names a node uses (a class put in a registry, a function passed as a
        # callback) and the methods of each type, since an object reached is an object whose methods run
        self.uses: dict[str, set[str]] = collections.defaultdict(set)
        self.members: dict[str, list[str]] = collections.defaultdict(list)
        self.file_of: dict[str, str] = {}  # every loaded node -> its file
        self.parsed: set[str] = set()  # files the index has nodes for (it parses their language)
        self._lines: dict[str, list[str]] = {}
        db = codegraph_db(root)
        self.indexed = db is not None
        if db is not None:
            self._load(db)

    def _load(self, db: Path) -> None:
        con = _connect(db)
        try:
            kinds = (*FUNCS, *TYPES, *CALLER_KINDS)
            nodes = con.execute("select id, kind, name, qualified_name, file_path, start_line, end_line from nodes "
                                f"where kind in ({','.join('?' * len(kinds))})", kinds).fetchall()
            edges = con.execute("select source, target, kind from edges where kind in "
                                "('calls', 'instantiates', 'contains', 'extends', 'implements', 'references')"
                                ).fetchall()
        finally:
            con.close()
        kind_of, name_of = {}, {}
        for nid, kind, name, qn, f, s, e in nodes:
            kind_of[nid], name_of[nid] = kind, name
            if f:
                self.file_of[nid] = f
                self.parsed.add(f)
            if kind in FUNCS and f:
                self.loc[nid] = (f, int(s or 0), int(e or s or 0), qn or name)
                self.spans[f].append((int(s or 0), int(e or s or 0), nid))
        methods: dict[tuple[str, str], list[str]] = collections.defaultdict(list)  # (type, name) -> methods
        owner: dict[str, str] = {}
        parents: dict[str, list[str]] = collections.defaultdict(list)
        for src, dst, kind in edges:
            if kind in ("calls", "instantiates"):
                # a call from a test or vendored code is not a way in: it would turn an extension point
                # (no callers) into "internal" and take part in reach and guard decisions
                if not NOISE_PATH.search(self.file_of.get(src, "")):
                    self.callers[dst].add(src)
                    self.callees[src].add(dst)
            elif kind == "references" and not NOISE_PATH.search(self.file_of.get(src, "")):
                self.uses[src].add(dst)
            elif kind == "contains" and kind_of.get(src) in TYPES and kind_of.get(dst) in FUNCS:
                owner[dst] = src
                methods[(src, name_of[dst])].append(dst)
                self.members[src].append(dst)
            elif kind in ("extends", "implements"):
                parents[src].append(dst)
        for m, t in owner.items():
            for p in parents.get(t, []):
                self.overrides[m] += methods.get((p, name_of[m]), [])
        for f in self.spans:
            self.spans[f].sort()

    def lines(self, file: str) -> list[str]:
        if file not in self._lines:
            p = self.root / file
            try:
                self._lines[file] = p.read_text(errors="ignore").splitlines() if p.is_file() else []
            except OSError:
                self._lines[file] = []
        return self._lines[file]

    def enclosing(self, file: str, line: int) -> str | None:
        """The innermost function or method whose span contains file:line."""
        best = None
        for s, e, nid in self.spans.get(file, ()):
            if s > line:
                break
            if s <= line <= e and (best is None or e - s < best[1] - best[0]):
                best = (s, e, nid)
        return best[2] if best else None

    def named(self, file: str, name: str) -> str | None:
        """A function or method of the file called `name` (the last part of a qualified name)."""
        tail = _tail(name)
        return next((nid for _s, _e, nid in self.spans.get(file, ()) if _tail(self.loc[nid][3]) == tail), None)

    def direct_callers(self, fid: str) -> set[str]:
        out = set(self.callers.get(fid, ()))
        for p in self.overrides.get(fid, ()):
            out |= self.callers.get(p, set())
        return out - {fid}

    def ancestors(self, fid: str, depth: int = ANCESTOR_DEPTH, cap: int = 800) -> dict[str, int]:
        """Functions that reach fid through calls, with their distance."""
        seen, frontier = {fid: 0}, [fid]
        for d in range(1, depth + 1):
            nxt = []
            for f in frontier:
                for c in self.direct_callers(f):
                    if c not in seen:
                        seen[c] = d
                        nxt.append(c)
            frontier = nxt
            if not frontier or len(seen) > cap:
                break
        seen.pop(fid)
        return seen

    def span_text(self, fid: str) -> tuple[str, int, list[str]] | None:
        """The code of a function or method; None for other callers (module-level code, class bodies)."""
        if fid not in self.loc:
            return None
        f, s, e, _ = self.loc[fid]
        return f, s, self.lines(f)[max(0, s - 1):e]

    def unparsed(self, file: str) -> bool:
        """Product code in a language the index does not parse (shell scripts, templates, ...): nothing is
        known about what runs it, so it cannot be ruled out of reach either."""
        return (self.indexed and file not in self.parsed and not NOISE_PATH.search(file)
                and not file.lower().endswith(NOT_CODE))

    def loaded_by_name(self) -> set[str]:
        """Product files that no other file calls, instantiates or names. Code like that is either dead or
        loaded by name at run time (a registry, a lazy import, a plugin directory, a hook table), and the
        static index cannot tell which, so it stays reachable."""
        named: set[str] = set()
        for edges in (self.callers, self.uses):
            for src_or_dst, others in edges.items():
                for o in others:
                    a, b = (o, src_or_dst) if edges is self.callers else (src_or_dst, o)  # a uses b
                    fa, fb = self.file_of.get(a), self.file_of.get(b)
                    if fa and fb and fa != fb:
                        named.add(fb)
        return {f for f in self.spans if f not in named and not NOISE_PATH.search(f)}

    def reachable_files(self, start: set[str], files: set[str], depth: int = REACH_DEPTH) -> set[str]:
        """Files of the code reached from `start` (function ids) and from every function of `files`
        (handlers written as file-level code), plus those files themselves. A node reaches what it calls,
        instantiates or names; a type reached brings its methods, because code chosen at run time
        (a provider looked up in a registry, a plugin class) runs through an object of that type."""
        seen: set[str] = set(start) | {nid for f in files for _s, _e, nid in self.spans.get(f, ())}
        frontier = list(seen)
        for _ in range(depth):
            frontier = list({c for f in frontier
                             for c in (*self.callees.get(f, ()), *self.uses.get(f, ()), *self.members.get(f, ()))
                             if c not in seen})
            if not frontier:
                break
            seen.update(frontier)
        return {self.file_of[n] for n in seen if n in self.file_of} | set(files)


def _entry_maps(index: CallIndex, entries: list[dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Entry ids by the function that handles them, and by handler file."""
    by_fn: dict[str, list[str]] = collections.defaultdict(list)
    by_file: dict[str, list[str]] = collections.defaultdict(list)
    for i, e in enumerate(entries):
        eid, f = str(e.get("id") or f"#{i}"), str(e.get("handler_file") or "")
        if not f:
            continue
        by_file[f].append(eid)
        fid = (index.enclosing(f, int(e["handler_line"])) if e.get("handler_line") else None) \
            or index.named(f, str(e.get("handler") or ""))
        if fid:
            by_fn[fid].append(eid)
    return by_fn, by_file


# ----------------------------------------------------------------- recipes

RECIPE_KEYS = ("name", "op_class", "pattern", "glob", "exclude", "guard", "why")


def check_recipe(r: dict) -> str | None:
    if not re.fullmatch(r"[\w-]{1,40}", str(r.get("name") or "")):
        return "name must be 1-40 letters, digits, '-' or '_'"
    if r.get("op_class") not in OP_CLASSES:
        return f"op_class must be one of {', '.join(OP_CLASSES)}"
    if not str(r.get("pattern") or "").strip():
        return "pattern is required"
    for k in ("exclude", "guard"):
        if r.get(k):
            try:
                re.compile(r[k])
            except re.error as e:
                return f"{k} is not a Python regular expression: {e}"
    return None


def expand(recipe: dict, rows: list[str], index: CallIndex, entries: list[dict],
           maps: tuple[dict, dict] | None = None) -> list[dict]:
    """The sites of a recipe (ripgrep rows "file:line:code"), each placed in the call graph."""
    by_fn, by_file = maps or _entry_maps(index, entries)
    exclude = re.compile(recipe["exclude"]) if recipe.get("exclude") else None
    guard = re.compile(recipe["guard"]) if recipe.get("guard") else None
    sites = []
    for row in rows:
        parts = row.split(":", 2)
        if len(parts) < 3 or not parts[1].isdigit() or NOISE_PATH.search(parts[0]):
            continue
        file, line, code = parts[0], int(parts[1]), parts[2].strip()
        if exclude and exclude.search(code):
            continue
        fid = index.enclosing(file, line)
        site: dict[str, Any] = {"recipe": recipe["name"], "op_class": recipe["op_class"], "file": file,
                                "line": line, "code": code[:200]}
        if fid is None:  # file-level code: a script, a template, a module body
            site.update(function=f"<{file}>", span=[1, len(index.lines(file))])
            ids = by_file.get(file, [])
            site["reach"] = "handler" if ids else "unindexed" if index.unparsed(file) else "no_callers"
            site["entries"] = ids[:40]
            near: dict[str, int] = {}
        else:
            f, s, e, qn = index.loc[fid]
            site.update(function=qn, span=[s, e])
            near = index.ancestors(fid)
            if by_fn.get(fid):
                site["reach"], ids = "handler", list(by_fn[fid])
            else:
                ids = sorted({x for a in near for x in by_fn.get(a, ())})
                site["reach"] = "entry" if ids else ("internal" if near else "no_callers")
            site["entries"] = ids[:40]
            site["callers"] = len(index.direct_callers(fid))
        site["entries_total"] = len(ids)
        if guard is not None:
            site["guard_at"] = _guard_at(index, guard, file, line, fid, near)
        sites.append(site)
    return sites


def _guard_at(index: CallIndex, guard: re.Pattern, file: str, line: int, fid: str | None,
              near: dict[str, int]) -> str | None:
    """Where the project's guard for this operation is applied on the way to it: in the operation's
    function before the operation, or in a caller within GUARD_DEPTH calls. None when it is not.
    File-level code has no function boundary: only the FILE_GUARD_LINES before the operation count."""
    if fid is None:
        first = max(0, line - FILE_GUARD_LINES)
        hit = next((first + i + 1 for i, t in enumerate(index.lines(file)[first:line]) if guard.search(t)), None)
        return f"{file}:{hit}" if hit else None
    scopes = [(fid, line)] + [(a, None) for a, d in sorted(near.items(), key=lambda kv: kv[1]) if d <= GUARD_DEPTH]
    for nid, until in scopes[:60]:
        code = index.span_text(nid)
        if code is None:
            continue
        f, s, body = code
        for i, t in enumerate(body):
            if until is not None and s + i > until:
                break
            if guard.search(t):
                return f"{f}:{s + i}"
    return None


def site_key(s: dict) -> str:
    return f"{s['file']}:{s['line']}"


def entry_reach(index: CallIndex, entries: list[dict], maps: tuple[dict, dict] | None = None) -> set[str]:
    """Files the entries can reach: their handlers, code loaded by name (which the index cannot rule out),
    and the code those call (without an index, the handler files only)."""
    by_fn, by_file = maps or _entry_maps(index, entries)
    return index.reachable_files(set(by_fn), set(by_file) | index.loaded_by_name())


REACH_SITES = 60  # who_reaches answers for the code that does one thing (the writes to one stored value)
_WEAKEST = {"public": 0, "unknown": 1, "authenticated": 2, "privileged": 3}


class Reach:
    """Who can run a piece of code: the call index and the entries by the function that handles them,
    built on first use and shared by a run's reviewers (read-only afterwards)."""

    def __init__(self, root: Path, entries: list[dict]):
        self.root, self.entries = root, entries
        self._built: tuple | None = None
        self._lock = threading.Lock()

    def get(self) -> tuple[CallIndex, tuple[dict, dict], dict[str, dict]]:
        with self._lock:
            if self._built is None:
                index = CallIndex(self.root)
                by_id = {str(e.get("id") or f"#{i}"): e for i, e in enumerate(self.entries)}
                self._built = (index, _entry_maps(index, self.entries), by_id)
            return self._built

    def report(self, pattern: str, rows: list[str]) -> str:
        """The code matching `pattern` (ripgrep rows) by function, with the entries that reach each and
        their least privileged caller. A trace that arrives at stored data continues at its writers:
        this is the step across storage that find_callers is across a call."""
        index, maps, by_id = self.get()
        sites = expand({"name": "", "op_class": "", "pattern": pattern}, rows, index, [], maps)
        if not sites:
            return "no matches in product code (tests and vendored code are left out)"
        groups: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for site in sites:
            groups[(site["file"], site["function"])].append(site)
        out, overall = [], None
        for (file, fn), ss in groups.items():
            ids = sorted({i for x in ss for i in x["entries"]},
                         key=lambda i: _WEAKEST.get(by_id.get(i, {}).get("exposure"), 1))
            total = max(x["entries_total"] for x in ss)
            weakest = by_id.get(ids[0], {}).get("exposure", "unknown") if ids else None
            if weakest is not None and (overall is None or _WEAKEST[weakest] < _WEAKEST[overall]):
                overall = weakest
            out.append(f"{fn}  ({ss[0]['reach']}" + (f"; {total} entries, weakest caller: {weakest}" if ids
                                                     else "") + ")")
            out += [f"  {file}:{x['line']}  {x['code'][:140]}" for x in ss[:6]]
            out += [f"    <- {by_id[i].get('method', 'ANY')} {by_id[i].get('route')}  "
                    f"[{by_id[i].get('exposure')}" + (f": {by_id[i]['least_principal']}"
                                                      if by_id[i].get("least_principal") else "") + "]"
                    for i in ids[:5] if i in by_id]
        kinds = {x["reach"] for x in sites}
        notes = [f"{k}: {v}" for k, v in (
            ("internal", "called, but by no enumerated entry: read its callers"),
            ("no_callers", "nothing in the index calls it: a hook, a job, an extension point, or dead code"),
            ("unindexed", "in a language the index does not parse: find what runs it")) if k in kinds]
        head = f"{len(sites)} matches in {len(groups)} functions" + (
            f"; least privileged caller that reaches any of them: {overall}" if overall else
            "; no enumerated entry reaches them through calls")
        return "\n".join([head, *out, *notes])


def scoped_rows(grep: Any, recipe: dict, reachable: set[str],
                unparsed: Any = None) -> tuple[list[str], list[str]]:
    """The recipe's matches: those in its glob, plus those outside the glob in code the entries reach or
    in code the index does not parse (`unparsed(file)`: what runs it is unknown, so it is not ruled out).
    A glob says where the agent looked; it cannot take code a request reaches out of the map.
    Returns (all rows, the rows the glob left out)."""
    rows: Final = grep(recipe["pattern"], recipe.get("glob") or "")
    if not recipe.get("glob"):
        return rows, []
    have: Final = set(rows)
    keep = (lambda f: f in reachable or unparsed(f)) if unparsed else (lambda f: f in reachable)
    extra: Final = [r for r in grep(recipe["pattern"], "") if r not in have and keep(r.split(":", 1)[0])]
    return rows + extra[:MAX_SITES], extra[:MAX_SITES]


def unparsed_files(root: Path, index: CallIndex, limit: int = 4000) -> list[str]:
    """Product files the index does not parse (see CallIndex.unparsed)."""
    if not index.indexed:
        return []
    out: list[str] = []
    for d, ds, fs in os.walk(root):
        ds[:] = sorted(x for x in ds if not x.startswith(".") and not NOISE_PATH.search(x + "/"))
        for f in sorted(fs):
            if f.startswith("."):  # tool configuration
                continue
            rel = os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
            if index.unparsed(rel) and _text(root / rel, script=os.path.splitext(f)[1] == ""):
                out.append(rel)
                if len(out) >= limit:
                    return out
    return out


def _text(p: Path, script: bool) -> bool:
    """A text file (not a font, an image or an archive); without an extension, only a script (#!)."""
    try:
        with open(p, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return b"\0" not in head and (not script or head.startswith(b"#!"))


def unparsed_summary(root: Path, index: CallIndex) -> str:
    """One line for the assets agent: which product code the index cannot see into."""
    files: Final = unparsed_files(root, index)
    if not files:
        return ""
    by: collections.Counter = collections.Counter(
        (f.rsplit("/", 1)[0] if "/" in f else ".", os.path.splitext(f)[1] or "(none)") for f in files)
    top = ", ".join(f"{d}/*{ext} ({n})" for (d, ext), n in by.most_common(10))
    return (f"The code index does not parse {len(files)} product files (a language it does not read: shell "
            f"scripts, templates, ...), e.g. {top}. Recipes still match them and their sites are part of the "
            "map; nothing is known about what runs them, so read who does when they matter (a task runner, a "
            "script the application executes, a template it renders).")


def merge_site(sites: dict[str, dict], site: dict) -> None:
    """One site per file:line. When two recipes find the same operation, both classes stay on it, and a
    recipe whose guard is missing there wins the guard verdict (a missing guard is the signal)."""
    key: Final = site_key(site)
    old: Final = sites.get(key)
    if old is None:
        sites[key] = site
        return
    if site["op_class"] != old["op_class"] and site["op_class"] not in old.setdefault("also", []):
        old["also"].append(site["op_class"])
    if "guard_at" in site and ("guard_at" not in old or (old["guard_at"] and not site["guard_at"])):
        old["guard_at"], old["guard_recipe"] = site["guard_at"], site["recipe"]


def counters(recipe: dict, sites: list[dict], entries_known: int, seed: int = 0,
             outside_glob: list[str] | None = None) -> dict:
    """What the agent refines a recipe on."""
    reach = collections.Counter(s["reach"] for s in sites)
    out: dict[str, Any] = {
        "recipe": recipe["name"], "op_class": recipe["op_class"], "sites": len(sites),
        "files": len({s["file"] for s in sites}), "functions": len({(s["file"], s["function"]) for s in sites}),
        "reach": {k: reach.get(k, 0) for k in REACH_ORDER},
        "reach_meaning": "handler: in an entry's handler; entry: an entry reaches it through calls; no_callers: "
                         "nothing in the repository calls it (framework hook, extension point, public API, "
                         "or dead code); internal: called, but no enumerated entry reaches it; unindexed: in a "
                         "language the code index does not parse, so who runs it is unknown",
        "entries_known": entries_known}
    if recipe.get("guard"):
        g = [s for s in sites if s.get("guard_at")]
        out["guard"] = {"pattern": recipe["guard"], "guarded": len(g), "unguarded": len(sites) - len(g)}
    rnd = random.Random(seed or len(sites))
    fmt = lambda s: (f"{site_key(s)} in {s['function']} [{s['reach']}"  # noqa: E731
                     + (f", guard at {s['guard_at']}" if s.get("guard_at") else
                        ", no guard" if recipe.get("guard") else "") + f"] {s['code'][:110]}")
    out["samples_to_read"] = [fmt(s) for s in rnd.sample(sites, min(6, len(sites)))]
    if recipe.get("guard"):
        out["unguarded_samples"] = [fmt(s) for s in sites if not s.get("guard_at")][:6]
    if outside_glob:
        out["reachable_outside_glob"] = {
            "matches": len(outside_glob), "samples": [r[:160] for r in outside_glob[:5]],
            "note": "these matches lie outside your glob in code the entries reach, so they are part of the map; "
                    "narrow the pattern or use exclude if they are not this operation"}
    if not sites:
        out["note"] = "no site: check the pattern against code you have read (ripgrep syntax, case-sensitive)"
    return out


# ----------------------------------------------------------------- identity subsystems

def check_identity(subsystems: Any, root: Path) -> tuple[list[dict], list[str]]:
    """Clean the agent's identity subsystems; problems are returned to it."""
    if not isinstance(subsystems, list):
        return [], ["subsystems must be a list (empty if the project creates no identities)"]
    out, problems = [], []
    for s in subsystems:
        if not isinstance(s, dict) or not str(s.get("name") or "").strip():
            problems.append(f"skipped an item without a name: {str(s)[:100]}")
            continue
        kind = str(s.get("kind") or "")
        if kind not in IDENTITY_KINDS:
            problems.append(f"{s['name']}: kind must be one of {', '.join(IDENTITY_KINDS)}")
            continue
        routes = [str(r) for r in (s.get("routes") or []) if str(r).strip()]
        bad = []
        for r in routes:
            try:
                re.compile(r)
            except re.error:
                bad.append(r)
        files = [str(f).strip().lstrip("./") for f in (s.get("files") or []) + (s.get("models") or [])
                 if str(f).strip()]
        missing = [f for f in files if not (root / f).exists()]
        if bad or missing or not (routes or files):
            problems.append(f"{s['name']}: " + "; ".join(
                x for x in (f"routes that are not regular expressions: {bad}" if bad else "",
                            f"files that do not exist: {missing[:5]}" if missing else "",
                            "give its routes or files" if not (routes or files) else "") if x))
            continue
        out.append({"name": str(s["name"])[:80], "kind": kind, "routes": routes[:12],
                    "files": [str(f).strip().lstrip("./") for f in (s.get("files") or [])][:20],
                    "models": [str(f).strip().lstrip("./") for f in (s.get("models") or [])][:10],
                    "settings": [str(x)[:200] for x in (s.get("settings") or [])][:12],
                    "notes": str(s.get("notes") or "")[:1500]})
    return out, problems


def merge_identity(current: list[dict] | None, new: list[dict]) -> list[dict]:
    """A later record of a subsystem with the same name replaces it; the others stay."""
    names: Final = {g["name"] for g in new}
    return [g for g in (current or []) if g["name"] not in names] + new


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def group_identity(subsystem: dict, entries: list[dict], sites: list[dict]) -> dict:
    """The entries and operation sites that belong to an identity subsystem."""
    rx = [re.compile(r, re.I) for r in subsystem["routes"]]
    files = subsystem["files"] + subsystem["models"]
    ids = [str(e.get("id") or f"#{i}") for i, e in enumerate(entries)
           if any(r.search(str(e.get("route") or "")) for r in rx) or _under(str(e.get("handler_file") or ""), files)]
    own = set(ids)
    near = [s for s in sites if _under(s["file"], files) or own & set(s.get("entries") or [])]
    return {**subsystem, "entry_ids": ids, "site_keys": [site_key(s) for s in near]}


# ----------------------------------------------------------------- the map

def build(tb: Any, recipes: dict[str, dict], identity: list[dict] | None, absent: dict[str, str],
          entries: list[dict]) -> dict:
    """Expand every recipe over the final entries, group the identity subsystems: recon/assets.json."""
    index = tb.call_index()
    maps = _entry_maps(index, entries)
    reachable: Final = entry_reach(index, entries, maps)
    sites: dict[str, dict] = {}
    per_recipe = {}
    for r in recipes.values():
        try:
            rows, _ = scoped_rows(tb.grep_rows, r, reachable, index.unparsed)
        except Exception:  # a pattern that times out now is left out, not the whole map
            continue
        found = expand(r, rows, index, entries, maps)
        per_recipe[r["name"]] = len(found)
        for s in found:
            merge_site(sites, s)
    groups = [group_identity(s, entries, list(sites.values())) for s in (identity or [])]
    reach = collections.Counter(s["reach"] for s in sites.values())
    return {"recipes": list(recipes.values()), "absent": absent, "sites": list(sites.values()),
            "identity": groups,
            "summary": {"recipes": per_recipe, "sites": len(sites), "indexed": index.indexed,
                        "by_class": dict(collections.Counter(s["op_class"] for s in sites.values())),
                        "by_reach": dict(reach),
                        "unguarded": sum(1 for s in sites.values() if "guard_at" in s and not s["guard_at"]),
                        "absent": sorted(absent), "identity_subsystems": len(groups),
                        "reachable_files": len(reachable)}}


# ----------------------------------------------------------------- review units

class Coverage:
    """What entry reviewers have covered, shared by the units running in parallel: the anchors of their
    hypotheses, and the code each one read. An operation whose function an entry reviewer read in full, or
    whose line one anchored, is not reviewed a second time (its card and findings are shared)."""

    def __init__(self) -> None:
        self._anchors: dict[str, set[int]] = collections.defaultdict(set)
        self._read: dict[tuple[str, str], list[tuple[int, int]]] = collections.defaultdict(list)  # (unit, file)
        self._lock = threading.Lock()

    def add(self, anchor: Any) -> None:
        m = re.match(r"^\s*([^:\s]+):(\d+)", str(anchor or ""))
        if m:
            with self._lock:
                self._anchors[m.group(1).lstrip("./")].add(int(m.group(2)))

    def read(self, unit: str, file: str, start: int, end: int) -> None:
        with self._lock:
            self._read[(unit, file.lstrip("./"))].append((int(start), int(end)))

    def covers(self, file: str, line: int, slack: int = 2) -> bool:
        with self._lock:
            return any(abs(x - line) <= slack for x in self._anchors.get(file, ()))

    def read_in_full(self, file: str, start: int, end: int) -> bool:
        """Whether one unit read every line of file:start-end."""
        with self._lock:
            spans = [sorted(v) for (_, f), v in self._read.items() if f == file]
        for intervals in spans:
            reach = start - 1
            for a, b in intervals:
                if a > reach + 1:
                    break
                reach = max(reach, b)
            if reach >= end:
                return True
        return False

    def covered(self, unit: dict) -> bool:
        if unit.get("hub"):  # a contract review is not what an entry reviewer did
            return False
        s, e = unit["span"]
        return self.read_in_full(unit["handler_file"], s, e) or all(
            self.covers(x["file"], x["line"]) for x in unit["sites"])


def operation_units(sites: list[dict], entries: list[dict], entry_units: list[dict],
                    rank: dict[str, int]) -> list[dict]:
    """One unit per function that performs sensitive operations outside an entry's handler, most exposed
    and unguarded first. Sites inside a handler go to that entry's unit instead (the same code is
    reviewed once, with the operation pointed out)."""
    by_id = {e.get("id"): e for e in entries}
    unit_of = {e.get("id"): u for u in entry_units for e in u["entries"]}
    groups: dict[tuple, list[dict]] = collections.defaultdict(list)
    for s in sites:
        owners = [unit_of[i] for i in s.get("entries") or [] if i in unit_of]
        if s["reach"] == "handler" and owners:
            for u in {id(u): u for u in owners}.values():
                u.setdefault("operations", []).append(s)
            continue
        groups[(s["file"], s["function"])].append(s)
    units = []
    for (file, fn), ss in groups.items():
        reached = [by_id[i] for i in sorted({i for s in ss for i in s.get("entries") or []}) if i in by_id]
        exposure = min((e.get("exposure", "unknown") for e in reached), key=lambda x: rank.get(x, 1),
                       default="unknown")
        fan_in: Final = max(s.get("entries_total", 0) for s in ss)
        units.append({"kind": "operation", "handler_file": file, "handler": fn, "span": ss[0]["span"],
                      "sites": sorted(ss, key=lambda s: s["line"]), "entries": reached, "exposure": exposure,
                      "reach": min((s["reach"] for s in ss), key=REACH_ORDER.get), "fan_in": fan_in,
                      "hub": fan_in >= HUB_ENTRIES,
                      "unguarded": any("guard_at" in s and not s["guard_at"] for s in ss)})
    units.sort(key=lambda u: (rank.get(u["exposure"], 1), not u["unguarded"], REACH_ORDER[u["reach"]],
                              -len(u["sites"]), u["handler_file"], u["sites"][0]["line"]))
    return units


def _parts(entries: list[dict], size: int) -> list[list[dict]]:
    """Entries in parts of at most `size`, entries of one handler file kept together where they fit."""
    by_file: dict[str, list[dict]] = collections.defaultdict(list)
    for e in entries:
        by_file[str(e.get("handler_file") or "")].append(e)
    parts: list[list[dict]] = []
    for es in sorted(by_file.values(), key=len, reverse=True):
        for i in range(0, len(es), size):
            chunk = es[i:i + size]
            fit = next((p for p in parts if len(p) + len(chunk) <= size), None)
            if fit is None:
                parts.append(list(chunk))
            else:
                fit.extend(chunk)
    return parts


def design_units(identity: list[dict], entries: list[dict], sites: list[dict], limit: int,
                 split: int = DESIGN_SPLIT_ENTRIES) -> list[dict]:
    """Design-review units for the identity subsystems (the ones with the most code first). A subsystem
    with more than `split` entries is reviewed in parts, each with the subsystem's models and settings
    and its own entries and the operations behind them: one context cannot read a hundred handlers."""
    by_id = {e.get("id"): e for e in entries}
    by_key = {site_key(s): s for s in sites}
    units = []
    for g in identity:
        es = [by_id[i] for i in g.get("entry_ids", []) if i in by_id]
        ss = [by_key[k] for k in g.get("site_keys", []) if k in by_key]
        if len(es) > split and len(es) > len(entries) * CROSS_CUTTING_SHARE:
            # a mechanism most requests pass (a session check, a token gate): its design is in its own
            # files, which every part would read again; its entries are everyone's
            files = set(g.get("files") or [])
            units.append({"kind": "design", "handler_file": "", "subsystem": g, "entries": [],
                          "sites": [s for s in ss if s["file"] in files], "handler": g["name"], "part": None,
                          "cross_cutting": len(es)})
            continue
        parts = _parts(es, split) if len(es) > split else [es]
        for n, part in enumerate(parts, 1):
            ids, files = {e.get("id") for e in part}, {e.get("handler_file") for e in part}
            mine = ss if len(parts) == 1 else [s for s in ss if s["file"] in files or ids & set(s.get("entries") or [])]
            units.append({"kind": "design", "handler_file": "", "subsystem": g, "entries": part, "sites": mine,
                          "handler": g["name"] if len(parts) == 1 else f"{g['name']} (part {n}/{len(parts)})",
                          "part": None if len(parts) == 1 else (n, len(parts))})
    units.sort(key=lambda u: -(len(u["entries"]) + len(u["sites"]) + len(u["subsystem"]["files"])))
    return units[:limit]


def interleave(first: list, second: list, every: int) -> list:
    """`second` takes every `every`-th slot from the start, so neither kind of unit waits for the other
    to be used up (the time budget usually ends before both are)."""
    if every < 2:
        return first + second
    out: list = []
    i = j = 0
    while i < len(first) or j < len(second):
        if j < len(second) and (i >= len(first) or (len(out) + 1) % every == 0):
            out.append(second[j])
            j += 1
        else:
            out.append(first[i])
            i += 1
    return out


def _site_row(s: dict) -> str:
    g = ""
    if "guard_at" in s:
        g = f"  [project's guard {'at ' + s['guard_at'] if s['guard_at'] else 'not found on the way'}]"
    return f"- {site_key(s)} ({s['op_class']}, recipe {s['recipe']}): {s['code'][:160]}{g}"


def _entry_row(e: dict) -> str:
    who = (e.get("who_can_call") or {}).get("least_privileged")
    return (f"- {e.get('id')} {e.get('method', 'ANY')} {e.get('route')} -> {e.get('handler_file')}::"
            f"{e.get('handler', '')} exposure={e.get('exposure')}" + (f" who_can_call={who}" if who else ""))


def handler_operations(unit: dict, guarded: dict[str, list[dict]] | None = None) -> str:
    """For an entry unit: the sensitive operations in its handler, from the project's operation map, with
    sibling sites that have the guard this one lacks."""
    ss = unit.get("operations") or []
    if not ss:
        return ""
    rows = [_site_row(s) for s in ss[:12]]
    for s in ss[:12]:
        if "guard_at" in s and not s["guard_at"]:
            sib = [x for x in (guarded or {}).get(s.get("guard_recipe") or s["recipe"], []) if x["file"] != s["file"]]
            rows += [f"    the same operation WITH the guard: {site_key(x)}: {x['code'][:120]}" for x in sib[:2]]
    return ("Sensitive operations in this handler (from the project's operation map; check who can make "
            "each happen and with which values):\n" + "\n".join(rows))


def operation_brief(unit: dict, siblings: list[dict], recipes: dict[str, dict]) -> str:
    """The user message of an operation unit."""
    ss = unit["sites"]
    classes = sorted({s["op_class"] for s in ss})
    rows = [f"Sensitive operation(s) to review, in {unit['handler_file']}::{unit['handler']} "
            f"(lines {unit['span'][0]}-{unit['span'][1]}):"]
    rows += [_site_row(s) for s in ss[:12]]
    rows += [f"Class {c}: {OP_CLASSES[c]}" for c in classes]
    whys = {s["recipe"]: recipes.get(s["recipe"], {}).get("why") for s in ss}
    rows += [f"Recipe {k}: {v}" for k, v in whys.items() if v]
    if unit.get("hub"):
        rows.append(f"This function is shared infrastructure: {unit['fan_in']} entries reach it. Do not trace "
                    "the paths one by one. Review its CONTRACT: for this operation to be safe, what must its "
                    "callers guarantee (a value validated, an object already filtered to the caller's tenant, an "
                    "authority already checked), and does the function enforce any of it itself? Record the "
                    "contract with add_fact (one sentence: callers of X must ...; X itself checks / does not "
                    "check ...) so the reviewers of every entry apply it. Report a finding only when the "
                    "function is unsafe whatever its callers do, or for a caller you found that breaks it.")
        rows += [_entry_row(e) for e in unit["entries"][:8]]
    elif unit["entries"]:
        rows.append(f"Entries that reach it through calls ({len(unit['entries'])}; the static call graph can "
                    "miss some):")
        rows += [_entry_row(e) for e in unit["entries"][:15]]
    elif unit["reach"] == "unindexed":
        rows.append("The code index does not parse this file's language, so nothing is known about what runs "
                    "it: find what runs, sources or renders it (a task runner, a command the application "
                    "executes, a template engine).")
    elif unit["reach"] == "no_callers":
        rows.append("Nothing in the repository calls this code: it is a framework hook, an extension point, "
                    "a public API for plugins or themes, file-level code the framework loads, or dead code. "
                    "Find out which.")
    else:
        rows.append("It is called, but no enumerated entry reaches it: find the callers (hooks, events, "
                    "jobs, render pipelines, entries the reconnaissance missed).")
    if siblings:
        rows.append("The same operation elsewhere, WITH the project's guard on the way (compare: what do "
                    "they check that this code does not?):")
        rows += [_site_row(s) for s in siblings[:6]]
    return "\n".join(rows)


def design_brief(unit: dict) -> str:
    """The user message of an identity design unit."""
    g = unit["subsystem"]
    rows = [f"Identity subsystem to review: {g['name']} (kind: {g['kind']})"]
    if unit.get("part"):
        rows.append(f"It is large, so it is reviewed in {unit['part'][1]} parts; this is part {unit['part'][0]}, "
                    "with the entries below. Answer the checklist for what this part does; the models and "
                    "settings are shared by all parts.")
    for label, key in (("Files", "files"), ("Models", "models"), ("Settings and defaults", "settings")):
        if g.get(key):
            rows.append(f"{label}: " + ", ".join(g[key]))
    if g.get("notes"):
        rows.append("Notes from the agent that mapped it: " + g["notes"])
    if unit.get("cross_cutting"):
        rows.append(f"Its routes match {unit['cross_cutting']} entries, most of the project: it is a mechanism "
                    "requests pass through, not a set of routes. Review it from its files, models and settings.")
    if unit["entries"]:
        rows.append(f"Its entries ({len(unit['entries'])}):")
        rows += [_entry_row(e) for e in unit["entries"][:25]]
    if unit["sites"]:
        rows.append("Sensitive operations in or behind it:")
        rows += [_site_row(s) for s in unit["sites"][:15]]
    rows.append("Checklist (answer every item with record_design):")
    rows += [f"- {k}: {q}" for k, q in IDENTITY_CHECKLIST.items()]
    return "\n".join(rows)


FOLLOW_UPS_PER_DESIGN = 3


def follow_ups(unit: dict, answers: list[dict], reported: bool) -> list[dict]:
    """Verification units for what a design review left open: a flaw it did not turn into a finding, and
    any flaw or unclear item that names the code still to read (to_verify). Each gets a fresh context."""
    open_items: Final = [a for a in answers if a["status"] in ("flaw", "unclear") and a.get("to_verify")]
    open_items += [a for a in answers if a["status"] == "flaw" and not reported and a not in open_items]
    return [{"kind": "lead", "handler_file": "", "handler": f"{unit['handler']}: {a['item']}",
             "subsystem": unit["subsystem"], "entries": unit["entries"], "sites": unit["sites"], "answer": a}
            for a in open_items[:FOLLOW_UPS_PER_DESIGN]]


class LeadBoard:
    """Hypotheses left open by entry and operation reviewers, claimed once per anchor for the whole run
    (units run in parallel, and several of them often reach the same code)."""

    PER_UNIT: Final = 1  # follow-ups one review may start; the rest stay in the card's open leads

    def __init__(self) -> None:
        self._claimed: set[str] = set()
        self._lock = threading.Lock()

    def follow_ups(self, unit: dict, cards: list[dict]) -> list[dict]:
        """Lead units for what a review left open (a hypothesis with status open): each gets a fresh
        context and its own budget, the same way as an open design conclusion."""
        out: list[dict] = []
        for card in cards:
            for h in card.get("hypotheses") or []:
                if len(out) >= self.PER_UNIT:
                    return out
                if not isinstance(h, dict) or h.get("status") != "open":
                    continue
                anchor = re.sub(r"\s+", "", str(h.get("anchor") or ""))
                with self._lock:
                    if not anchor or anchor in self._claimed:
                        continue
                    self._claimed.add(anchor)
                out.append({"kind": "lead", "handler_file": "", "handler": f"{unit['handler']}: {anchor}",
                            "entries": unit.get("entries") or [], "sites": unit.get("sites") or [],
                            "hypothesis": {**{k: h.get(k) for k in ("risk", "anchor", "why", "evidence")},
                                           "unit": card.get("function", "")[:300]}})
        return out


def lead_brief(unit: dict) -> str:
    """The user message of a follow-up unit: one open conclusion to confirm or refute."""
    if "hypothesis" in unit:
        h: Final = unit["hypothesis"]
        rows = [f"A reviewer of: {h['unit']}", "left this hypothesis open within its budget:",
                f"risk: {h.get('risk')}", f"anchor: {h.get('anchor')}"]
        rows += [f"{k}: {h[k]}" for k in ("why", "evidence") if h.get(k)]
        rows.append("Read the code from the anchor, follow the value to everything that consumes it, and settle "
                    "it: when it holds, trace it to concrete requests and report_finding (preconditions in the "
                    "impact); when it does not, record_card with the code that stops it.")
        if unit["entries"]:
            rows.append("Entries of the unit that raised it:")
            rows += [_entry_row(e) for e in unit["entries"][:15]]
        return "\n".join(rows)
    a: Final = unit["answer"]
    rows = [f"A design review of the identity subsystem {unit['subsystem']['name']} concluded, for the checklist "
            f"item {a['item']} ({IDENTITY_CHECKLIST[a['item']]}):", f"status: {a['status']}", a["answer"]]
    if a.get("evidence"):
        rows.append("Its evidence: " + "; ".join(f"{x.get('file')}:{x.get('line')} {str(x.get('quote'))[:100]}"
                                                for x in a["evidence"] if isinstance(x, dict)))
    if a.get("to_verify"):
        rows.append(f"What it left to read: {a['to_verify']}")
    rows.append("Read that code and settle it: when the flaw holds, trace it to concrete requests and "
                "report_finding (preconditions in the impact); when it does not, record_card with the code that "
                "stops it.")
    if unit["entries"]:
        rows.append("Entries of the subsystem:")
        rows += [_entry_row(e) for e in unit["entries"][:15]]
    return "\n".join(rows)


def classes_text() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in OP_CLASSES.items())


def dump(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

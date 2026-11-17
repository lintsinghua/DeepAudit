"""Component units: sibling entries reviewed side by side, with a guard table computed from the code.

The most common access-control flaw is one entry that lacks the check its siblings make (a read method
without the view check, a write method checked only for view, a check on one object while another is
loaded). Reviewing each entry in its own context finds it only when the reviewer happens to compare, and
every context re-derives how the framework dispatches and checks. A component unit puts siblings in one
context: the entries the project writes the same way (one file's methods, or every plugin's API file),
one row each:

- the checks its code makes: calls whose names say they check, verify, require or grant (an English naming
  convention, not a project rule) and the project's own guard calls named in the access model's evidence,
  in the handler and in the helpers of the same file it calls;
- the sensitive operations in it, from the operation map;
- who can call it.

Computing the table is mechanical and covers every entry; judging it is the reviewer's job. Entries anyone
can call stay in entry units of their own (the anonymous surface gets a full forward trace), and so do
small groups.
"""

from __future__ import annotations

import collections
import re
from typing import Any

from .assets import CallIndex, _tail

COMPONENT_MIN = 4  # entries of one file (authenticated or privileged) that make a component unit
COMPONENT_ROWS = 40  # rows per unit; a larger file is reviewed in parts, in line order

_CALL = re.compile(r"([A-Za-z_$][\w$\\]*(?:(?:::|->|\.)[A-Za-z_$][\w$]*)*)\s*\(")
# a verb or state at the start of the name, then a word boundary of camelCase, snake_case or the end
_VERB = re.compile(r"^(?i:check|verify|validate|assert|ensure|require|authori[sz]e|deny|forbid|guard|allow|permit"
                   r"|confirm|can|must)(?=[A-Z_]|$)")
_STATE = re.compile(r"^(?i:is|has)(?=[A-Z_])\w*(?i:access|admin|owner|allowed|permi|role|super|grant|capabilit"
                    r"|authori|privileg|logged|anonymous)")
_NOT_A_CALL = {"if", "for", "foreach", "while", "switch", "catch", "function", "fn", "return", "array", "isset",
               "empty", "list", "new", "echo", "print"}
# calls written in prose or quotes: the name touches its parenthesis
_CALL_TIGHT = re.compile(r"([A-Za-z_$][\w$\\]*(?:(?:::|->|\.)[A-Za-z_$][\w$]*)*)\(")
# names that fetch, build or move data rather than decide: not guards even when the model's text shows them
_NOT_A_GUARD = re.compile(r"^(get|set|load|find|fetch|read|create|new|build|make|to|from|parse|format|render|call"
                          r"|dispatch|apply|init|extract|process|run|handle|send|write|save|add|update|delete|"
                          r"prepare|normalize|should|was)(?=[A-Z_]|$)|^(true|false|null|none)$")


def guard_vocabulary(access_model: dict | None) -> set[str]:
    """Names of the calls the access model's evidence and text show the project checking with."""
    if not access_model:
        return set()
    text = " ".join(str(access_model.get(k) or "") for k in
                    ("authentication", "authorization", "permission_mapping", "shared_protections"))
    text += " " + " ".join(str(e.get("quote") or "") for e in access_model.get("evidence") or []
                           if isinstance(e, dict))
    for p in access_model.get("powers") or []:
        text += " " + " ".join(str(e.get("quote") or "") for e in p.get("evidence") or [] if isinstance(e, dict))
    names = {_tail(m.group(1)) for m in _CALL_TIGHT.finditer(text)}
    return {n.lower() for n in names if len(n) > 3 and n.lower() not in _NOT_A_CALL and not _NOT_A_GUARD.match(n)}


def is_guard(name: str, vocab: set[str]) -> bool:
    tail = _tail(name)
    return bool(tail) and (tail.lower() in vocab or bool(_VERB.match(tail)) or bool(_STATE.match(tail)))


def _args(line: str, start: int) -> str:
    """The call's arguments as written, up to the closing parenthesis on the same line."""
    depth, out = 0, []
    for ch in line[start:]:
        if ch == "(":
            depth += 1
            if depth == 1:
                continue
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
        out.append(ch)
    return "".join(out).strip()[:48]


def _function(index: CallIndex, entry: dict) -> str | None:
    f = str(entry.get("handler_file") or "")
    if entry.get("handler"):
        nid = index.named(f, str(entry["handler"]))
        if nid:
            return nid
    line = entry.get("handler_line")
    return index.enclosing(f, int(line)) if line else None


def guard_row(index: CallIndex, entry: dict, operations: list[dict], vocab: set[str]) -> dict:
    """What one entry's code checks and does: its handler and the same-file helpers it calls."""
    nid = _function(index, entry)
    row: dict[str, Any] = {"id": entry.get("id"), "request": f"{entry.get('method', 'ANY')} {entry.get('route')}",
                           "handler": entry.get("handler"), "exposure": entry.get("exposure"),
                           "least_principal": entry.get("least_principal"), "span": None, "guards": [], "ops": []}
    if nid is None:
        return row
    f, start, end, _qn = index.loc[nid]
    row["span"] = (start, end)
    bodies = [(nid, "")]
    for c in sorted(index.callees.get(nid, ())):
        if c in index.loc and index.loc[c][0] == f:
            bodies.append((c, _tail(index.loc[c][3])))
    lines = index.lines(f)
    seen = set()
    for fid, via in bodies:
        _f, s, e, _ = index.loc[fid]
        for n in range(max(1, s), min(len(lines), e) + 1):
            text = lines[n - 1]
            for m in _CALL.finditer(text):
                name = m.group(1)
                if _tail(name).lower() in _NOT_A_CALL or not is_guard(name, vocab):
                    continue
                key = (_tail(name), _args(text, m.end() - 1))
                if key in seen:
                    continue
                seen.add(key)
                row["guards"].append(f"{_tail(name)}({key[1]})" + (f" via {via}" if via else "") + f" L{n}")
    spans = [(index.loc[fid][1], index.loc[fid][2]) for fid, _ in bodies]
    row["ops"] = sorted({s["op_class"] for s in operations
                         if s.get("file") == f and any(a <= int(s.get("line") or 0) <= b for a, b in spans)})
    return row


def component_units(units: list[dict], rank: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """Entries grouped by their role in the architecture, the name of their handler file (every plugin's
    API.php, every route module's index.js): siblings are the entries the project writes the same way,
    whether in one file or in many. A generic handler (one function serving many resources) is a group of
    its own, its resources side by side. A group of COMPONENT_MIN or more becomes component units of at most
    COMPONENT_ROWS rows, a file kept in one part where it fits. Entries anyone can call and small groups stay
    entry units. Returns (entry units kept, component units)."""
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    keep: list[dict] = []
    for u in units:
        if not u.get("handler_file") or rank.get(u.get("exposure", "unknown"), 1) == 0:
            keep.append(u)  # anyone can call it: a full forward trace of its own
        elif u.get("generic"):  # one handler serving many resources: its resources side by side
            groups[f"{u['handler_file']}::{u['handler']}"].append(u)
        else:
            groups[u["handler_file"].rsplit("/", 1)[-1]].append(u)
    comps: list[dict] = []
    for name, us in groups.items():
        if len(us) < COMPONENT_MIN and not us[0].get("generic"):
            keep += us
            continue
        by_file: dict[str, list[dict]] = collections.defaultdict(list)
        for u in us:
            by_file[u["handler_file"]].append(u)
        parts: list[list[dict]] = [[]]
        for f in sorted(by_file):
            rows = sorted(by_file[f], key=lambda u: (int(u.get("handler_line") or 0), str(u.get("handler"))))
            if parts[-1] and len(parts[-1]) + len(rows) > COMPONENT_ROWS:
                parts.append([])
            for i in range(0, len(rows), COMPONENT_ROWS):  # a file larger than a part is split in line order
                if parts[-1] and len(parts[-1]) + len(rows[i:i + COMPONENT_ROWS]) > COMPONENT_ROWS:
                    parts.append([])
                parts[-1] += rows[i:i + COMPONENT_ROWS]
        for n, part in enumerate(parts):
            files = sorted({u["handler_file"] for u in part})
            comps.append({"kind": "component", "handler_file": files[0] if len(files) == 1 else name,
                          "files": files, "part": f"{name}:{n + 1}/{len(parts)}",
                          "handler": f"{len(part)} entries in {len(files)} file(s) named {name}"
                                     + (f", part {n + 1} of {len(parts)}" if len(parts) > 1 else ""),
                          "exposure": min((u["exposure"] for u in part), key=lambda x: rank.get(x, 1)),
                          "members": part, "entries": [e for u in part for e in u["entries"]],
                          "operations": [s for u in part for s in u.get("operations") or []]})
    # within an exposure level, the largest first: one unit covers many entries
    comps.sort(key=lambda c: (rank.get(c["exposure"], 1), -len(c["entries"]), c["part"]))
    return keep, comps


def brief(unit: dict, rows: list[dict]) -> str:
    """The user message of a component unit."""
    no_guard = [r for r in rows if not r["guards"]]
    files = unit.get("files") or [unit["handler_file"]]
    where = files[0] if len(files) == 1 else f"{len(files)} files written the same way ({', '.join(files[:6])}" + (
        ", ..." if len(files) > 6 else "") + ")"
    out = [f"Component to review: {where} ({unit['handler']}). Each row is one entry: the checks "
           "its code makes (calls whose names check, verify, require or grant, and the project's guards from the "
           "access model; in the handler and in the same-file helpers it calls, with the line), the sensitive "
           "operations in it, and who can call it. A check made outside these functions (a constructor or init "
           "hook, a base class, the dispatcher, middleware) is not in the table: find those first.",
           ""]
    handlers = {(r["handler"], r["span"]) for r in rows}
    if len(rows) > 1 and len(handlers) == 1:  # a generic handler: the same code for every row
        r = rows[0]
        out[0] = (f"Component to review: {r['handler']} in {unit['handler_file']} serves {len(rows)} resources "
                  "with the same code. Its checks (in the handler and the same-file helpers it calls): "
                  + ("; ".join(r["guards"][:8]) if r["guards"] else "NONE in its code")
                  + ". Find where the resource is resolved and whether access, ownership or validation differ "
                  "by resource (a resource whose own rules the shared code does not apply is the flaw).")
        out += [f"- {x['id']} {x['request']} [{x.get('least_principal') or x.get('exposure')}]" for x in rows]
        return "\n".join(out)
    for r in rows:
        span = f"L{r['span'][0]}-{r['span'][1]}" if r["span"] else "L?"
        who = r.get("least_principal") or r.get("exposure")
        out.append(f"- {r['id']} {r['request']} -> {r['handler']} {span} [{who}]")
        out.append("    checks: " + ("; ".join(r["guards"][:8]) if r["guards"] else "NONE in its code"))
        if r["ops"]:
            out.append("    operations: " + ", ".join(r["ops"]))
    if no_guard and len(no_guard) < len(rows):
        out += ["", f"{len(no_guard)} of {len(rows)} rows make no check in their own code while their siblings do: "
                "start with them, then the rows whose check is weaker than what they do."]
    return "\n".join(out)


# ----------------------------------------------------------------- operation tables

def operation_tables(ops: list[dict], rank: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """Operation units (one per function outside the handlers) grouped by the recipe that found them: one
    kind of operation across the project, side by side, the most exposed and unguarded rows first (the
    order operation_units gives). Shared infrastructure (hub units, reviewed for its contract) and recipes
    with few functions stay operation units. Returns (operation units kept, table units)."""
    keep = [u for u in ops if u.get("hub")]
    groups: dict[str, list[dict]] = collections.defaultdict(list)
    for u in ops:
        if not u.get("hub"):
            lead = next((s for s in u["sites"] if "guard_at" in s and not s["guard_at"]), u["sites"][0])
            groups[str(lead.get("recipe"))].append(u)
    tables: list[dict] = []
    for recipe, us in groups.items():
        if len(us) < COMPONENT_MIN:
            keep += us
            continue
        parts = [us[i:i + COMPONENT_ROWS] for i in range(0, len(us), COMPONENT_ROWS)]
        for n, part in enumerate(parts):
            reached = {id(e): e for u in part for e in u["entries"]}
            tables.append({"kind": "optable", "recipe": recipe, "op_class": part[0]["sites"][0]["op_class"],
                           "handler_file": recipe, "part": f"{recipe}:{n + 1}/{len(parts)}",
                           "handler": f"{len(part)} functions found by recipe {recipe}"
                                      + (f", part {n + 1} of {len(parts)}" if len(parts) > 1 else ""),
                           "rows": part, "sites": [s for u in part for s in u["sites"]],
                           "entries": list(reached.values()),
                           "exposure": min((u["exposure"] for u in part), key=lambda x: rank.get(x, 1)),
                           "unguarded": any(u["unguarded"] for u in part)})
    tables.sort(key=lambda t: (rank.get(t["exposure"], 1), not t["unguarded"], t["part"]))
    keep.sort(key=lambda u: (rank.get(u["exposure"], 1), not u["unguarded"]))
    return keep, tables


def table_brief(unit: dict, recipe: dict | None, class_text: str) -> str:
    """The user message of an operation-table unit."""
    r = recipe or {}
    out = [f"Operation to review across the project: class {unit['op_class']} ({class_text}).",
           f"Recipe {unit['recipe']}: pattern {r.get('pattern', '?')!r}"
           + (f", the project's guard {r['guard']!r}" if r.get("guard") else ", no guard pattern")
           + (f". Why: {r['why']}" if r.get("why") else "."),
           f"{len(unit['rows'])} functions perform it outside the entry handlers (the most exposed and "
           "unguarded first). Each row: the function, how entries reach it and the least privileged caller, "
           "whether the project's guard is on the way, and the code at each site.", ""]
    for u in unit["rows"]:
        ids = [e.get("id") for e in u["entries"][:4]]
        more = f" +{len(u['entries']) - 4}" if len(u["entries"]) > 4 else ""
        guard = "" if not any("guard_at" in s for s in u["sites"]) else \
            "  guard NOT on the way" if u["unguarded"] else "  guarded"
        out.append(f"- {u['handler_file']}::{u['handler']} L{u['span'][0]}-{u['span'][1]} reach={u['reach']} "
                   f"[{u['exposure']}] entries {', '.join(map(str, ids)) or 'none'}{more}{guard}")
        for s in u["sites"][:2]:
            out.append(f"    L{s['line']}: {str(s.get('code') or '')[:140]}")
    return "\n".join(out)

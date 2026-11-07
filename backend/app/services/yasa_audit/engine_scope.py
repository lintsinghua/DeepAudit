"""Engine input built from discovered entries: a scoped, line-preserving shadow copy of the project.

YASA builds a call graph over everything under its source path, which does not finish within the
budget on large projects (SuiteCRM, 760k LOC: >15 min), and it only starts taint analysis from entries
it recognises. Both are addressed generically here:

* Scope: the files codegraph links to the discovered entries (calls / imports / instantiates /
  references / extends, depth-bounded), not the whole tree. Unrelated modules, data files, tests and
  vendored code drop out without per-project exclude lists.
* Entries the engine can start from:
  - JSP pages become Java servlets (jsp2java, existing).
  - PHP script entries (top-level code reached by URL) are wrapped, on their first and last lines only,
    into `class YasaEntry<N>Service { public function run($yasa_req) { ... } }`. YASA's PHP checker
    self-collects public methods of *Service classes (SOA convention); entries listed in ruleConfig are
    collected by the checker but never run by the PHP analyzer, so a custom entrypoint list does not work
    for PHP. Superglobal sources are self-collected inside the wrapped body.
  - Framework routes (Spring, Flask, Express ...) are left as they are; YASA collects them itself or the
    builder lists them as file-level entrypoints (playbook V6).

Line numbers are unchanged, so engine findings map back to the original files.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .discovery import reachable_files

# Source and config files the engine may need besides code reachable through edges.
KEEP_EXT = {".php", ".phtml", ".inc", ".java", ".jsp", ".jspx", ".xml", ".properties", ".py", ".js", ".ts",
            ".mjs", ".cjs", ".tsx", ".jsx", ".json", ".go"}
# Only within one line: `\s` would also eat the newline before it and shift every following line.
PHP_TOP_ONLY = re.compile(r"^[ \t]*(namespace[ \t]+[^;{\n]+;|use[ \t]+[\w\\, {}]+;|declare[ \t]*\([^)\n]*\)[ \t]*;)[ \t]*$",
                          re.M)


CLASS_START = re.compile(r"(?<![\w$>:])((abstract|final|readonly)\s+)*(class|interface|trait|enum)\s+\w+[^{;]*\{")


def _top_level_classes(code: str) -> list[tuple[int, int]]:
    """(start, end) offsets of class-like blocks at brace depth 0 in PHP code (strings and comments skipped)."""
    blocks, depth, i, n = [], 0, 0, len(code)
    cur = None
    while i < n:
        c = code[i]
        if c in "'\"":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            i = j + 1
            continue
        if code.startswith("//", i) or c == "#":
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if code.startswith("<<<", i):
            m = re.match(r"<<<\s*['\"]?(\w+)['\"]?", code[i:])
            if m:
                j = code.find("\n" + m.group(1), i)
                i = n if j < 0 else j + len(m.group(1)) + 1
                continue
        if depth == 0 and cur is None and (m := CLASS_START.match(code, i)):
            cur = i
            depth = 1
            i = m.end()
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and cur is not None:
                blocks.append((cur, i + 1))
                cur = None
        i += 1
    return blocks


def wrap_php_script(text: str, n: int) -> str | None:
    """Wrap a PHP script's top-level code into Service methods without changing line numbers.

    Top-level class-like declarations stay at file level (PHP does not allow nested classes): the
    wrapper method is closed before each one and a new one opened after it, so every top-level code
    segment becomes its own entry. Returns None for namespaced files or files without a PHP open tag.
    """
    if re.search(r"^\s*namespace\s+[\w\\]+\s*[;{]", text, re.M):
        return None
    m = re.search(r"<\?php\b", text)
    if not m:
        return None
    seg = [0]

    def head() -> str:
        seg[0] += 1
        return f" class YasaEntry{n}_{seg[0]}Service {{ public function run($yasa_req) {{ "

    pre, body = text[:m.start()], text[m.end():]
    # `use` / `declare` are only valid at file level; blank them in place (same line count).
    body = PHP_TOP_ONLY.sub("", body)
    first = head()
    parts, last = [], 0
    for a, b in _top_level_classes(body):
        # PHP 8 attributes (#[...]) on their own lines belong to the class: close before them.
        if (attr := re.search(r"(#\[[^\n]*\][ \t]*\n\s*)+$", body[last:a])):
            a = last + attr.start()
        parts.append(body[last:a])
        parts.append(" }} " + body[a:b] + head())
        last = b
    parts.append(body[last:])
    wrapped = "<?php" + first + ("?>" + pre + "<?php" if pre.strip() else "") + "".join(parts)
    if pre and not pre.strip():
        wrapped = pre + wrapped
    # Does the file end in HTML mode? A '?>' inside a string literal does not count: after the last
    # '?>' there must be no PHP statement ending (';', '{', '}') at the end of the file.
    tail = wrapped[wrapped.rfind("?>") + 2:] if "?>" in wrapped else None
    html_end = tail is not None and (not tail.strip() or not re.search(r"[;{}]\s*$", tail.strip()))
    return wrapped + ("\n<?php }}\n" if html_end else "\n}}\n")


SERVICE_CLASS_RE = re.compile(r"\b(?:class|interface|trait)\s+(\w*(?:[Ss]ervice|[Ss]vc))\b")


def _neutralise_service_classes(dest: Path) -> list[str]:
    """Rename the project's own *Service / *Svc classes in the copy (same length, every occurrence).

    YASA's PHP checker treats every public method of such a class as an entry. Only the wrappers
    should be entries: the project's service classes are reached through them like any other code,
    and starting from each of them multiplies run time and memory (SuiteCRM: an OOM kill at the 13th
    of 156 collected entries).
    """
    files = [p for p in dest.rglob("*") if p.suffix in (".php", ".phtml", ".inc")]
    texts = {p: p.read_text(errors="ignore") for p in files}
    names = sorted({m.group(1) for t in texts.values() for m in SERVICE_CLASS_RE.finditer(t)
                    if not m.group(1).startswith("YasaEntry")})
    if not names:
        return []
    alias = {n: n[:-1] + "_" for n in names}  # FooService -> FooServic_, FooSvc -> FooSv_
    rx = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b")
    for p, t in texts.items():
        new = rx.sub(lambda m: alias[m.group(1)], t)
        if new != t:
            p.write_text(new)
    return names


def build_engine_src(root: Path, dest: Path, entries: list[dict], max_files: int = 3000,
                     depth: int = 6) -> dict:
    """Write the scoped shadow copy to dest. Returns a summary (files, wrapped entries, skipped)."""
    entry_files = sorted({e["file"] for e in entries if e.get("file")})
    reach = reachable_files(root, entry_files, depth=depth) or set(entry_files)
    # Keep the closest files first if the slice is still too large for the budget.
    files = sorted(reach, key=lambda f: (f not in entry_files, f))[:max_files]
    if dest.exists():
        shutil.rmtree(dest)
    script_entries = {e["file"] for e in entries if e.get("via") == "script" and e["file"].endswith(".php")}
    wrapped, not_wrapped = [], []
    for i, rel in enumerate(files):
        src = root / rel
        if not src.is_file() or os.path.splitext(rel)[1] not in KEEP_EXT:
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel in script_entries:
            w = wrap_php_script(src.read_text(errors="ignore"), i)
            if w is not None:
                out.write_text(w)
                wrapped.append(rel)
                continue
            not_wrapped.append(rel)
        shutil.copy2(src, out)
    renamed = _neutralise_service_classes(dest) if wrapped else []
    return {"files": len(files), "reachable": len(reach), "entry_files": len(entry_files),
            "service_classes_renamed": len(renamed),
            "php_wrapped": len(wrapped), "php_not_wrapped": not_wrapped[:20],
            "truncated": len(reach) > max_files}

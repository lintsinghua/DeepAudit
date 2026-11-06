"""Deterministic entry-point inventory for the access-control stage.

- Java web apps: @WebServlet URL patterns and every JSP page.
- Express apps: route registrations in the bootstrap file (server.ts / app.ts). For each route the
  *effective* guards are computed: global app.use(guard) + app.use('/prefix', guard...) whose prefix
  matches + inline middleware. Handlers are resolved to files through the bootstrap's imports.

The result is a route table that the reviewer agents get in full, so they can compare peers.
"""

from __future__ import annotations

import re
from pathlib import Path

ROUTE_RE = re.compile(r"\s*app\.(use|get|post|put|patch|delete)\((.*)\)\s*$")
IMPORT_RE = re.compile(r"import\s+(?:\{([^}]+)\}|\*\s+as\s+(\w+)|(\w+))\s+from\s+'(\.[^']+)'")
WRAPPERS = {"utils.asyncHandler", "uploadToMemory.single", "uploadToDisk.single"}


MAPPING_RE = re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\b(\((.*)\))?")
ANNOT_RE = re.compile(r"^\s*@(\w+)(\(.*)?$")
METHOD_RE = re.compile(r"^\s*(public|protected|private)?\s*[\w<>\[\], ?.]+\s+(\w+)\s*\(")


def _mapping_path(args: str | None) -> str:
    """First path in a mapping annotation: a string literal, or the raw constant expression."""
    if not args:
        return ""
    m = re.search(r'"([^"]*)"', args)
    if m:
        return m.group(1)
    m = re.search(r"(?:value|path)\s*=\s*\{?\s*([\w.]+)", args) or re.match(r"\s*\{?\s*([\w.]+)", args)
    return "{" + m.group(1) + "}" if m and m.group(1) not in ("method", "produces", "consumes") else ""


def _annotation_block(lines: list[str], idx: int) -> list[str]:
    """Annotation lines directly above line idx (0-based), skipping javadoc and blank lines."""
    out: list[str] = []
    j = idx - 1
    while j >= 0:
        s = lines[j].strip()
        if s.startswith("@"):
            out.insert(0, s)
        elif s in ("", "*/") or s.startswith(("*", "/*", "//")):
            pass
        else:
            break
        j -= 1
    return out


def spring_entries(root: Path) -> list[dict]:
    """@RestController / @Controller handler methods with the non-mapping annotations as guards."""
    out = []
    for f in sorted(root.rglob("*.java")):
        if "/test/" in str(f):
            continue
        txt = f.read_text(errors="ignore")
        if not re.search(r"@(Rest)?Controller\b", txt):
            continue
        lines = txt.splitlines()
        cls_idx = next((i for i, ln in enumerate(lines) if re.search(r"\bclass\s+\w+", ln)), None)
        if cls_idx is None:
            continue
        cls_annots = _annotation_block(lines, cls_idx)
        prefix = next((_mapping_path(m.group(3)) for a in cls_annots if (m := MAPPING_RE.search(a))), "")
        cls_guards = [a for a in cls_annots if not MAPPING_RE.search(a)
                      and not re.match(r"@(Rest)?Controller|@Slf4j|@RequiredArgsConstructor|@Api\b|@Tag", a)]
        for i in range(cls_idx + 1, len(lines)):
            mm = METHOD_RE.match(lines[i])
            if not mm or lines[i].strip().startswith(("return", "if", "for", "while", "new ")):
                continue
            annots = _annotation_block(lines, i)
            mapping = next((MAPPING_RE.search(a) for a in annots if MAPPING_RE.search(a)), None)
            if not mapping:
                continue
            verb = mapping.group(1).upper() if mapping.group(1) != "Request" else "ANY"
            guards = cls_guards + [a for a in annots if not MAPPING_RE.search(a)
                                   and not a.startswith(("@Override", "@Operation", "@ApiOperation"))]
            out.append({"route": prefix + _mapping_path(mapping.group(3)), "method": verb,
                        "file": str(f.relative_to(root)), "line": i + 1, "handler": mm.group(2),
                        "guards": guards})
    return out


def java_global_guards(root: Path) -> list[str]:
    """Interceptor registrations and Spring Security path rules, as compact source snippets."""
    out = []
    for f in sorted(root.rglob("*.java")):
        if "/test/" in str(f):
            continue
        txt = f.read_text(errors="ignore")
        rel = str(f.relative_to(root))
        for m in re.finditer(r"registry\.addInterceptor\([^;]*;", txt, re.S):
            line = txt[: m.start()].count("\n") + 1
            out.append(f"{rel}:{line} " + re.sub(r"\s+", " ", m.group(0))[:300])
        for m in re.finditer(r"\.(antMatchers|requestMatchers|mvcMatchers)\([^)]*\)\s*\.\w+\(\)", txt):
            line = txt[: m.start()].count("\n") + 1
            out.append(f"{rel}:{line} " + re.sub(r"\s+", " ", m.group(0))[:200])
    return out


def java_entries(root: Path) -> list[dict]:
    out = spring_entries(root)
    for f in sorted(root.rglob("*.java")):
        txt = f.read_text(errors="ignore")
        for m in re.finditer(r'@WebServlet\(\s*(?:urlPatterns\s*=\s*)?\{?\s*"([^"]+)"', txt):
            out.append({"route": m.group(1), "method": "GET/POST", "file": str(f.relative_to(root)),
                        "line": txt[: m.start()].count("\n") + 1, "guards": []})
    for f in sorted(root.rglob("*.jsp")):
        rel = f.relative_to(root)
        route = "/" + str(rel).split("WebContent/", 1)[-1]
        out.append({"route": route, "method": "GET/POST", "file": str(rel), "line": 1, "guards": []})
    return out


def find_bootstrap(root: Path) -> Path | None:
    for name in ("server.ts", "app.ts", "server.js", "app.js", "index.ts", "index.js"):
        p = root / name
        if p.exists() and re.search(r"\bapp\.(get|post|use)\(", p.read_text(errors="ignore")):
            return p
    return None


def express_entries(root: Path, boot: Path | None = None) -> list[dict]:
    boot = boot or find_bootstrap(root)
    if boot is None:
        return []
    txt = boot.read_text(errors="ignore")
    boot_rel = str(boot.relative_to(root))
    imports: dict[str, str] = {}
    for m in IMPORT_RE.finditer(txt):
        target = m.group(4).lstrip("./")
        target = target if target.endswith((".ts", ".js")) else target + ".ts"
        names = [n.strip().split(" as ")[-1] for n in (m.group(1) or "").split(",") if n.strip()]
        for n in names + [m.group(2) or "", m.group(3) or ""]:
            if n:
                imports[n] = target

    global_guards: list[str] = []
    prefix_guards: list[tuple[str, list[str]]] = []
    routes: list[dict] = []
    for i, line in enumerate(txt.splitlines(), 1):
        m = ROUTE_RE.match(line)
        if not m:
            continue
        verb, args = m.group(1), m.group(2)
        pm = re.match(r"\s*'([^']+)'\s*,?\s*(.*)", args)
        path, rest = (pm.group(1), pm.group(2)) if pm else (None, args)
        calls = [c for c in re.findall(r"([\w.]+)\(", rest) if c not in WRAPPERS]
        guards = [c for c in calls if c.startswith("security.") or c.startswith("serveIndex")]
        handler = next((c for c in reversed(calls) if c.split(".")[0] in imports and c not in guards), None)
        last_arg = rest.strip().split(",")[-1].strip()
        if not handler and last_arg in imports:
            handler = last_arg
        if path is None:
            global_guards += guards
        elif handler is None and verb == "use" and guards:
            if any(g.startswith("serveIndex") for g in guards):
                routes.append({"route": path, "method": "GET", "file": boot_rel, "line": i,
                               "handler": "serveIndex (directory listing)", "inline": []})
            else:
                prefix_guards.append((path, guards))
        elif handler:
            routes.append({"route": path, "method": verb.upper(), "file": imports[handler.split(".")[0]],
                           "line": i, "handler": handler, "registered_at": f"{boot_rel}:{i}",
                           "inline": guards})
    for r in routes:
        eff = list(global_guards)
        for pfx, g in prefix_guards:
            if r["route"].startswith(pfx.split("/:")[0]):
                eff += g
        r["guards"] = eff + r.pop("inline")
    return routes


def entries_for(root: Path, lang: str) -> list[dict]:
    return java_entries(root) if lang == "java" else express_entries(root)


def global_guards_for(root: Path, lang: str) -> list[str]:
    return java_global_guards(root) if lang == "java" else []

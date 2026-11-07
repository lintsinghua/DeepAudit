"""Project-agnostic entry extraction driven by a recipe the recon agent writes.

The pipeline must not carry a hand-written extractor per framework (that is the special-case treadmill:
Spring, Express, Flask, Laravel, OFBiz controller.xml, ...). Instead the agent, having read the
project, describes its routing in a small closed schema -- a *recipe* -- and this module expands the
recipe across the whole project deterministically and resolves every entry's handler to real code.
No framework or project name appears here; a recipe names a structural *family* and its parameters.

Families (how a project binds a request path to the code that runs):
  config-xml  routes declared in XML config (OFBiz controller.xml, Spring MVC/Struts XML, web.xml):
              a route element with a uri attribute, optional nested security / handler / view elements.
  annotation  a handler method carrying a route annotation (Spring @*Mapping, JAX-RS @Path, NestJS).
  call        a registration call, framework.verb(path, ...handlers) (Express, Koa, Fastify, Gin).
  decorator   a handler decorated with a route decorator (Flask, FastAPI, Django path()).

`expand(root, recipe)` returns the entries; `resolve(root, db, entries)` binds each handler to a
file:line and reports what did not resolve, so the agent can correct the recipe and re-run.
"""

from __future__ import annotations

import collections
import re
import xml.etree.ElementTree as ET
from pathlib import Path

FAMILIES = ("config-xml", "annotation", "call", "decorator")
_HTTP = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "ANY", "USE", "ALL", "REQUEST"}


def _iter_files(root: Path, globs: list[str]):
    seen = set()
    for g in globs:
        for p in sorted(root.glob(g)):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield p


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else tag


def _attr(el: ET.Element, name: str) -> str | None:
    """Attribute by local name, so namespaced configs work without the caller knowing the prefix."""
    if name in el.attrib:
        return el.attrib[name]
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


def _child(el: ET.Element, tag: str) -> ET.Element | None:
    return next((c for c in el if _local(c.tag) == tag), None)


def _children(el: ET.Element, tag: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == tag]


def _route_lines(text: str, route_tag: str) -> list[int]:
    """Line of each `<route_tag` opening tag, in document order (ElementTree drops line numbers)."""
    rx = re.compile(r"<" + re.escape(route_tag) + r"(?=[\s/>])")
    return [i for i, line in enumerate(text.splitlines(), 1) for _ in rx.finditer(line)]


def _expand_config_xml(root: Path, recipe: dict) -> list[dict]:
    globs = recipe.get("files") or []
    globs = [globs] if isinstance(globs, str) else globs
    route_tag = recipe["route"]
    uri_attr = recipe.get("uri_attr", "uri")
    method_attr = recipe.get("method_attr")
    auth = recipe.get("auth") or {}
    handler = recipe.get("handler") or {}
    view = recipe.get("view") or {}
    out: list[dict] = []
    for f in _iter_files(root, globs):
        text = f.read_text(errors="ignore")
        try:
            tree = ET.fromstring(text)
        except ET.ParseError:
            continue
        routes = [el for el in tree.iter() if _local(el.tag) == route_tag]
        lines = _route_lines(text, route_tag)
        rel = str(f.relative_to(root))
        for i, el in enumerate(routes):
            uri = _attr(el, uri_attr)
            if not uri:
                continue
            e: dict = {"route": "/" + uri.lstrip("/"), "file": rel,
                       "line": lines[i] if i < len(lines) else 1,
                       "method": (_attr(el, method_attr) or "ANY").upper() if method_attr else "ANY",
                       "via": "recipe:config-xml", "registered_at": f"{rel}:{lines[i] if i < len(lines) else 1}"}
            if auth:
                sec = _child(el, auth.get("tag", "security"))
                val = _attr(sec, auth.get("attr", "auth")) if sec is not None else None
                pub = [str(x).lower() for x in (auth.get("public_values") or ["false"])]
                e["public"] = (val.lower() in pub) if val is not None else None
                e["auth_raw"] = ET.tostring(sec, encoding="unicode").strip()[:120] if sec is not None else "inherit"
            if handler:
                hs = _children(el, handler.get("tag", "event"))
                e["handlers"] = [{k: _attr(h, a) for k, a in (handler.get("attrs") or {}).items()} for h in hs]
            if view:
                vs = [v for v in _children(el, view.get("tag", "response"))
                      if not view.get("when_attr") or _attr(v, view["when_attr"]) == view.get("when_value")]
                e["views"] = [_attr(v, view.get("value_attr", "value")) for v in vs]
            out.append(e)
    return out


ANNOT_METHOD_RE = re.compile(r"^\s*(?:public|protected|private|async|def|fun|func|static|final|\s)*"
                             r"[\w<>\[\],.? ]*?\b(\w+)\s*\(")


def _expand_annotation(root: Path, recipe: dict) -> list[dict]:
    globs = recipe.get("files") or ["**/*.java"]
    globs = [globs] if isinstance(globs, str) else globs
    annot = re.compile(recipe["annotation"])
    prefix_annot = re.compile(recipe["prefix_annotation"]) if recipe.get("prefix_annotation") else None
    guard_names = set(recipe.get("guard_annotations") or [])
    out: list[dict] = []
    for f in _iter_files(root, globs):
        lines = f.read_text(errors="ignore").splitlines()
        rel = str(f.relative_to(root))
        prefix = ""
        if prefix_annot:
            for ln in lines[:80]:
                if (m := prefix_annot.search(ln)):
                    prefix = (m.groupdict().get("path") or (m.group(1) if m.groups() else "")) or ""
                    break
        for i, ln in enumerate(lines):
            m = annot.search(ln)
            if not m:
                continue
            uri = m.groupdict().get("path") if "path" in m.groupdict() else (m.group(1) if m.groups() else "")
            verb = (m.groupdict().get("verb") or "ANY").upper()
            j = i + 1
            guards = [ln.strip()]
            while j < len(lines) and (lines[j].strip().startswith("@") or not lines[j].strip()):
                if lines[j].strip().startswith("@"):
                    guards.append(lines[j].strip())
                j += 1
            hm = ANNOT_METHOD_RE.match(lines[j]) if j < len(lines) else None
            out.append({"route": "/" + (prefix + (uri or "")).lstrip("/"), "method": verb, "file": rel,
                        "line": j + 1, "handler": hm.group(1) if hm else "",
                        "guards": [g for g in guards if any(n in g for n in guard_names)],
                        "via": "recipe:annotation", "registered_at": f"{rel}:{i + 1}"})
    return out


def expand(root: Path, recipe: dict) -> list[dict]:
    fam = recipe.get("family")
    if fam == "config-xml":
        return _expand_config_xml(root, recipe)
    if fam == "annotation":
        return _expand_annotation(root, recipe)
    raise ValueError(f"family {fam!r} is not one of {FAMILIES}")


# ----------------------------------------------------------------- handler resolution

def _component_path(root: Path, ref: str) -> Path | None:
    """Resolve an OFBiz-style component://<name>/<rest>[#anchor] reference to a file on disk."""
    m = re.match(r"\w+://([\w.-]+)/(.+)", ref)
    if not m:
        return None
    name, rest = m.group(1), m.group(2).split("#", 1)[0]
    for base in ("framework", "applications", "plugins", "themes", "specialpurpose", "."):
        cand = root / base / name / rest
        if cand.is_file():
            return cand
    hits = list(root.glob(f"**/{name}/{rest}"))
    return hits[0] if hits else None


def _qualified_index(db: Path):
    import sqlite3
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        by_qual: dict[str, tuple] = {}
        by_name: dict[str, list] = collections.defaultdict(list)
        for qn, name, fp, ln, kind in con.execute(
                "select qualified_name, name, file_path, start_line, kind from nodes "
                "where kind in ('function', 'method', 'class')"):
            rec = (fp, ln or 1, kind)
            if qn:
                by_qual[qn] = rec
            if name:
                by_name[name].append(rec)
    finally:
        con.close()
    return by_qual, by_name


def build_service_index(root: Path, spec: dict) -> dict[str, dict]:
    """name -> {engine, location, invoke, auth} from service-definition config (generic second hop)."""
    globs = spec.get("files") or []
    globs = [globs] if isinstance(globs, str) else globs
    elem = spec.get("element", "service")
    idx: dict[str, dict] = {}
    for f in _iter_files(root, globs):
        try:
            tree = ET.fromstring(f.read_text(errors="ignore"))
        except ET.ParseError:
            continue
        for el in tree.iter():
            if _local(el.tag) != elem:
                continue
            name = _attr(el, spec.get("name_attr", "name"))
            if name:
                idx[name] = {"engine": _attr(el, spec.get("engine_attr", "engine")),
                             "location": _attr(el, spec.get("location_attr", "location")) or "",
                             "invoke": _attr(el, spec.get("invoke_attr", "invoke")) or "",
                             "auth": _attr(el, spec.get("auth_attr", "auth"))}
    return idx


def resolve(root: Path, db: Path | None, entries: list[dict], services: dict | None = None) -> dict:
    """Bind each entry's handler to a real file:line. Mutates entries (adds file/line/resolved).

    `services` (optional) is a recipe section describing where service definitions live, for the
    request -> service -> implementation hop. Returns resolved/unresolved counts and samples so the
    recon agent can fix the recipe.
    """
    by_qual, by_name = _qualified_index(db) if db else ({}, {})
    svc_idx = build_service_index(root, services) if services else {}
    resolved = unresolved = 0
    missing: list[str] = []
    for e in entries:
        handlers = e.get("handlers") or ([{"type": "method", "invoke": e["handler"]}] if e.get("handler") else [])
        # Follow service handlers one hop to their implementation (engine/location/invoke).
        expanded = []
        for h in handlers:
            sname = h.get("invoke") if (h.get("type") or "").startswith("service") else None
            svc = svc_idx.get(sname) if sname else None
            if svc and svc.get("location"):
                expanded.append({"type": svc["engine"], "path": svc["location"], "invoke": svc["invoke"]})
                if svc.get("auth") and e.get("public") is None:
                    e["public"] = svc["auth"].lower() == "false"
            else:
                expanded.append(h)
        handlers = expanded
        target = None
        for h in handlers:
            path, invoke = h.get("path") or "", h.get("invoke") or ""
            if path.startswith(("component://", "ofbiz://")) or path.endswith((".groovy", ".py", ".xml")):
                p = _component_path(root, path) if "://" in path else (root / path if (root / path).is_file() else None)
                if p is not None:
                    target = (str(p.relative_to(root)), 1)
                    break
            if path and invoke and (rec := by_qual.get(f"{path}.{invoke}") or by_qual.get(f"{path}#{invoke}")):
                target = rec[:2]
                break
            if invoke and by_name.get(invoke):
                cands = [r for r in by_name[invoke] if not path or path.split(".")[-1] in r[0]]
                if cands:
                    target = cands[0][:2]
                    break
            if path and by_name.get(path.split(".")[-1]):
                target = by_name[path.split(".")[-1]][0][:2]
                break
        if target:
            e["file"], e["line"], e["resolved"] = target[0], target[1], True
            resolved += 1
        else:
            e["resolved"] = False
            unresolved += 1
            if len(missing) < 25:
                missing.append(f"{e['route']} -> {handlers[:2]}")
    return {"entries": len(entries), "resolved": resolved, "unresolved": unresolved,
            "unresolved_samples": missing}

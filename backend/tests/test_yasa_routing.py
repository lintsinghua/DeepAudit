"""Recipe-driven, project-agnostic routing extraction (routing.py). Synthetic fixtures only."""

import sqlite3

from pathlib import Path

from app.services.yasa_audit.routing import build_service_index, expand, resolve

CONTROLLER = """<?xml version="1.0"?>
<site-conf xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <request-map uri="login">
        <security https="true" auth="false"/>
        <event type="java" path="com.x.LoginEvents" invoke="login"/>
        <response name="success" type="view" value="main"/>
    </request-map>
    <request-map uri="createThing">
        <security auth="true"/>
        <event type="service" invoke="createThing"/>
    </request-map>
    <request-map uri="viewReport">
        <security https="true" auth="true"/>
        <response name="success" type="view" value="Report"/>
    </request-map>
</site-conf>
"""

SERVICES = """<?xml version="1.0"?>
<services>
    <service name="createThing" engine="java" location="com.x.ThingServices" invoke="createThing" auth="false"/>
    <service name="autoThing" engine="entity-auto" invoke="create"/>
</services>
"""

RECIPE = {"family": "config-xml", "files": "**/controller.xml", "route": "request-map", "uri_attr": "uri",
          "auth": {"tag": "security", "attr": "auth", "public_values": ["false"]},
          "handler": {"tag": "event", "attrs": {"type": "type", "path": "path", "invoke": "invoke"}},
          "view": {"tag": "response", "when_attr": "type", "when_value": "view", "value_attr": "value"}}
SERVICES_SPEC = {"files": "**/servicedef/*.xml", "element": "service", "name_attr": "name",
                 "engine_attr": "engine", "location_attr": "location", "invoke_attr": "invoke", "auth_attr": "auth"}


def _tree(tmp_path):
    (tmp_path / "webapp/WEB-INF").mkdir(parents=True)
    (tmp_path / "webapp/WEB-INF/controller.xml").write_text(CONTROLLER)
    (tmp_path / "servicedef").mkdir()
    (tmp_path / "servicedef/services.xml").write_text(SERVICES)


def _codegraph(tmp_path, nodes):
    (tmp_path / ".codegraph").mkdir(exist_ok=True)
    con = sqlite3.connect(tmp_path / ".codegraph" / "codegraph.db")
    con.execute("create table nodes (qualified_name text, name text, file_path text, start_line int, kind text)")
    con.executemany("insert into nodes values (?,?,?,?,?)", nodes)
    con.commit()
    con.close()
    return tmp_path / ".codegraph" / "codegraph.db"


def test_expand_config_xml_routes_auth_views_lines(tmp_path):
    _tree(tmp_path)
    es = {e["route"]: e for e in expand(tmp_path, RECIPE)}
    assert set(es) == {"/login", "/createThing", "/viewReport"}
    assert es["/login"]["public"] is True and es["/viewReport"]["public"] is False
    assert es["/login"]["line"] == 3  # the <request-map uri="login"> line
    assert es["/login"]["handlers"] == [{"type": "java", "path": "com.x.LoginEvents", "invoke": "login"}]
    assert es["/viewReport"]["views"] == ["Report"] and es["/viewReport"]["handlers"] == []
    assert es["/login"]["via"] == "recipe:config-xml"


def test_service_index_and_resolution_through_service_hop(tmp_path):
    _tree(tmp_path)
    db = _codegraph(tmp_path, [
        ("com.x.LoginEvents.login", "login", "src/LoginEvents.java", 10, "method"),
        ("com.x.ThingServices.createThing", "createThing", "src/ThingServices.java", 20, "method"),
    ])
    idx = build_service_index(tmp_path, SERVICES_SPEC)
    assert idx["createThing"]["location"] == "com.x.ThingServices" and idx["autoThing"]["engine"] == "entity-auto"
    es = expand(tmp_path, RECIPE)
    rep = resolve(tmp_path, db, es, SERVICES_SPEC)
    by = {e["route"]: e for e in es}
    assert by["/login"]["resolved"] and (by["/login"]["file"], by["/login"]["line"]) == ("src/LoginEvents.java", 10)
    # request -> service -> java implementation, and the service's auth="false" fills unknown auth
    assert by["/createThing"]["resolved"] and by["/createThing"]["file"] == "src/ThingServices.java"
    assert rep["resolved"] == 2 and by["/viewReport"]["resolved"] is False  # view-only, no code hop


def test_component_uri_resolves_to_file(tmp_path):
    (tmp_path / "framework/webtools/groovyScripts").mkdir(parents=True)
    (tmp_path / "framework/webtools/groovyScripts/X.groovy").write_text("// script")
    (tmp_path / "ctrl.xml").write_text('<c><request-map uri="x"><event type="groovy" '
                                       'path="component://webtools/groovyScripts/X.groovy" invoke="run"/>'
                                       '</request-map></c>')
    es = expand(tmp_path, {"family": "config-xml", "files": "ctrl.xml", "route": "request-map",
                           "uri_attr": "uri", "handler": {"tag": "event",
                           "attrs": {"type": "type", "path": "path", "invoke": "invoke"}}})
    resolve(tmp_path, None, es)
    assert es[0]["resolved"] and es[0]["file"] == "framework/webtools/groovyScripts/X.groovy"


def test_annotation_family_with_prefix_and_guards(tmp_path):
    (tmp_path / "C.java").write_text(
        '@RequestMapping("/api")\n@PreAuthorize("x")\nclass C {\n'
        '  @GetMapping("/users/{id}")\n  @Secured\n  public User get(int id) {}\n'
        '  @PostMapping("/users")\n  public User add() {}\n}\n')
    es = {e["route"]: e for e in expand(tmp_path, {
        "family": "annotation", "files": "**/*.java",
        "annotation": r'@(?P<verb>Get|Post|Put|Delete)Mapping\("(?P<path>[^"]*)"',
        "prefix_annotation": r'@RequestMapping\("(?P<path>[^"]*)"', "guard_annotations": ["Secured", "PreAuthorize"]})}
    assert set(es) == {"/api/users/{id}", "/api/users"}
    assert es["/api/users/{id}"]["method"] == "GET" and es["/api/users/{id}"]["handler"] == "get"
    assert es["/api/users/{id}"]["guards"] == ["@Secured"]


def test_recon_stage_uses_agent_recipe_and_writes_entries(tmp_path, monkeypatch):
    """The recon stage: a scripted agent calls try_recipe, and its entries become entries.json."""
    import json as _json
    from types import SimpleNamespace

    from app.services.yasa_audit import pipeline
    from app.services.yasa_audit.config import AuditConfig

    root = tmp_path / "proj"
    (root / "webapp/WEB-INF").mkdir(parents=True)
    (root / "webapp/WEB-INF/controller.xml").write_text(CONTROLLER)
    (root / "servicedef").mkdir()
    (root / "servicedef/services.xml").write_text(SERVICES)

    recipe = {**RECIPE, "services": SERVICES_SPEC}

    class FakeLLM:
        def __init__(self, cfg):
            self.usage = SimpleNamespace(prompt=10, completion=5, calls=1)
            self._done = False

        def chat(self, messages, tools=None):
            if not self._done:
                self._done = True
                call = SimpleNamespace(id="c1", function=SimpleNamespace(
                    name="try_recipe", arguments=_json.dumps({"recipe": recipe})))
                return SimpleNamespace(content="", tool_calls=[call])
            call = SimpleNamespace(id="c2", function=SimpleNamespace(name="finish", arguments="{}"))
            return SimpleNamespace(content="", tool_calls=[call])

    monkeypatch.setattr(pipeline, "LLM", FakeLLM)
    monkeypatch.setattr(pipeline, "snapshot_codegraph", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "detect_lang", lambda r: "java")
    m = pipeline.recon(AuditConfig(), root, tmp_path / "out")
    assert m["source"] == "recipe" and m["entries"] == 3 and m["recon_entries"] == 3
    entries = _json.loads((tmp_path / "out" / "entries.json").read_text())
    assert {e["route"] for e in entries} == {"/login", "/createThing", "/viewReport"}
    # entries.json drives a later stage's route table, in either entry shape
    row = pipeline._entry_row(next(e for e in entries if e["route"] == "/login"))
    assert "public=True" in row and "/login" in row

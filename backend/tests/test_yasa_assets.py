"""The sensitive-asset map (assets.py) and the operation and identity design review units."""

import json
import shutil
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.yasa_audit import assets
from app.services.yasa_audit.config import AuditConfig
from app.services.yasa_audit.toolbox import Toolbox, tool_schemas

RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(RG is None, reason="ripgrep not installed")


def _cfg(**kw):
    cfg = AuditConfig(**kw)
    if RG:
        cfg.rg_bin = RG
    return cfg


def _write(root, files):
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt)


def _index(root, nodes, edges):
    """A codegraph.db with the columns assets.CallIndex reads."""
    (root / ".codegraph").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / ".codegraph" / "codegraph.db")
    con.execute("create table nodes (id text primary key, kind text, name text, qualified_name text, "
                "file_path text, start_line int, end_line int)")
    con.execute("create table edges (source text, target text, kind text, line int)")
    con.executemany("insert into nodes values (?,?,?,?,?,?,?)", nodes)
    con.executemany("insert into edges values (?,?,?,?)", [(*e, None) for e in edges])
    con.commit()
    con.close()


def _call(name, args, cid):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)
        self.usage = SimpleNamespace(prompt=0, completion=0, cached=0, reasoning=0, calls=0)

    def chat(self, messages, tools=None):
        self.usage.calls += 1
        name, args = self.script.pop(0) if self.script else ("finish", {"notes": "done"})
        return SimpleNamespace(content="", tool_calls=[_call(name, args, f"c{self.usage.calls}")])


USERS = "\n".join([
    "<?php",                                       # 1
    "class Users {",                               # 2
    "  function actionSave($u) {",                 # 3
    "    $this->requireAdmin();",                  # 4
    "    $u->role = $_POST['role'];",              # 5
    "  }",                                         # 6
    "  function actionPromote($u) {",              # 7
    "    $this->roles->setRole($u, 'editor');",    # 8
    "  }",                                         # 9
    "}", ""])
ROLES = "<?php\nclass Roles {\n  function setRole($u, $r) {\n    $u->role = $r;\n  }\n}\n"
HOOKS = "<?php\nclass Hooks {\n  /** Plugins call this with imported rows. */\n  function onImport($u, $row) {\n" \
        "    $u->role = $row['role'];\n  }\n}\n"


def _project(tmp_path):
    _write(tmp_path, {"app/Users.php": USERS, "app/Roles.php": ROLES, "app/Hooks.php": HOOKS,
                      "tests/UsersTest.php": "<?php\n$u->role = 'admin';\n"})
    _index(tmp_path, [
        ("c_users", "class", "Users", "Users", "app/Users.php", 2, 10),
        ("m_save", "method", "actionSave", "Users::actionSave", "app/Users.php", 3, 6),
        ("m_promote", "method", "actionPromote", "Users::actionPromote", "app/Users.php", 7, 9),
        ("c_roles", "class", "Roles", "Roles", "app/Roles.php", 2, 6),
        ("m_setrole", "method", "setRole", "Roles::setRole", "app/Roles.php", 3, 5),
        ("c_hooks", "class", "Hooks", "Hooks", "app/Hooks.php", 2, 7),
        ("m_import", "method", "onImport", "Hooks::onImport", "app/Hooks.php", 4, 6),
    ], [("c_users", "m_save", "contains"), ("c_users", "m_promote", "contains"),
        ("c_roles", "m_setrole", "contains"), ("c_hooks", "m_import", "contains"),
        ("m_promote", "m_setrole", "calls")])
    return [{"id": "E1", "method": "POST", "route": "/users/save", "handler_file": "app/Users.php",
             "handler": "actionSave", "exposure": "privileged"},
            {"id": "E2", "method": "POST", "route": "/users/promote", "handler_file": "app/Users.php",
             "handler": "actionPromote", "exposure": "authenticated"}]


@needs_rg
def test_recipe_places_every_site_in_the_call_graph_with_its_guard(tmp_path):
    entries = _project(tmp_path)
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    tb.entries_source = lambda: entries
    assert tb.run_recipe("r", "made_up_class", "x", why="").startswith("rejected: op_class")
    assert "rejected: guard" in tb.run_recipe("r", "file_write", "x", guard="(", why="")
    res = json.loads(tb.run_recipe("role-write", "credential_or_privilege_write", r"->role\s*=",
                                   guard=r"requireAdmin\(|->can\(", why="role column of the users table"))
    # the test file is not product code; the other three are the handler, a callee, an extension point
    assert res["sites"] == 3 and res["reach"] == {"handler": 1, "entry": 1, "unindexed": 0, "no_callers": 1,
                                                  "internal": 0}
    assert res["guard"] == {"pattern": r"requireAdmin\(|->can\(", "guarded": 1, "unguarded": 2}
    assert "credential_or_privilege_write" not in res["classes_left"] and "file_write" in res["classes_left"]
    sites = {s["function"]: s for s in assets.expand(tb.recipes["role-write"],
                                                     tb.grep_rows(r"->role\s*="), tb.call_index(), entries)}
    assert sites["Users::actionSave"]["reach"] == "handler" and sites["Users::actionSave"]["guard_at"] == \
        "app/Users.php:4"
    # reached from E2 through a call; the guard in the sibling handler does not count for it
    assert sites["Roles::setRole"]["entries"] == ["E2"] and sites["Roles::setRole"]["guard_at"] is None
    assert sites["Hooks::onImport"]["reach"] == "no_callers" and sites["Hooks::onImport"]["entries"] == []
    assert "rejected: a recipe" in tb.class_absent("credential_or_privilege_write", "none")
    assert tb.class_absent("file_write", "no file APIs: grep fopen|file_put_contents finds nothing") == \
        "recorded: file_write absent"


@needs_rg
def test_a_recipe_that_matches_every_mention_is_rejected(tmp_path, monkeypatch):
    _write(tmp_path, {"a.php": "role\nrole\nrole\n"})
    monkeypatch.setattr(assets, "MAX_SITES", 2)
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    assert "rejected: 3 matches" in tb.run_recipe("w", "credential_or_privilege_write", "role", why="")
    assert tb.recipes == {}


def test_calls_through_a_parent_method_reach_the_implementation(tmp_path):
    _write(tmp_path, {"a.php": "\n" * 30})
    _index(tmp_path, [("i", "interface", "Store", "Store", "a.php", 1, 3), ("i_save", "method", "save", "Store::save",
                                                                          "a.php", 2, 2),
                      ("c", "class", "Db", "Db", "a.php", 5, 9), ("c_save", "method", "save", "Db::save", "a.php", 6, 8),
                      ("h", "method", "handle", "Ctl::handle", "a.php", 11, 14)],
           [("i", "i_save", "contains"), ("c", "c_save", "contains"), ("c", "i", "implements"),
            ("h", "i_save", "calls")])
    idx = assets.CallIndex(tmp_path)
    assert idx.enclosing("a.php", 7) == "c_save" and idx.ancestors("c_save") == {"h": 1}


def test_operations_in_a_handler_join_its_unit_and_the_rest_are_units_of_their_own():
    entries = [{"id": "E1", "route": "/a", "exposure": "public"}, {"id": "E2", "route": "/b", "exposure": "privileged"}]
    entry_units = [{"kind": "entry", "entries": [entries[0]]}, {"kind": "entry", "entries": [entries[1]]}]
    site = lambda f, ln, reach, ids, guard=None: {  # noqa: E731
        "recipe": "r", "op_class": "file_write", "file": f, "line": ln, "code": "write()", "function": f + "::fn",
        "span": [1, 50], "reach": reach, "entries": ids, **({"guard_at": guard} if guard is not False else {})}
    sites = [site("h.php", 3, "handler", ["E1"], False), site("deep.php", 9, "entry", ["E2"], None),
             site("deep.php", 12, "entry", ["E2"], None), site("ext.php", 4, "no_callers", [], None),
             site("pub.php", 5, "entry", ["E1"], "pub.php:2")]
    ops = assets.operation_units(sites, entries, entry_units, {"public": 0, "unknown": 1, "privileged": 3})
    assert entry_units[0]["operations"][0]["file"] == "h.php"  # reviewed with its handler, not twice
    assert "Sensitive operations in this handler" in assets.handler_operations(entry_units[0])
    # most exposed first; one unit per function (the two sites of deep.php together)
    assert [u["handler_file"] for u in ops] == ["pub.php", "ext.php", "deep.php"]
    assert [len(u["sites"]) for u in ops] == [1, 1, 2] and ops[0]["exposure"] == "public"
    assert ops[1]["reach"] == "no_callers" and ops[2]["unguarded"]
    order = assets.interleave(["a", "b", "c", "d"], ["X", "Y"], 3)
    assert order == ["a", "b", "X", "c", "d", "Y"] and assets.interleave(["a"], ["X", "Y"], 3) == ["a", "X", "Y"]
    brief = assets.operation_brief(ops[1], [sites[4]], {"r": {"why": "the cache writer"}})
    assert "Nothing in the repository calls this code" in brief and "WITH the project's guard" in brief
    assert "Recipe r: the cache writer" in brief


def test_identity_subsystems_and_the_design_checklist(tmp_path):
    _write(tmp_path, {"web/Register.php": "<?php\nfunction register() {\n  $u = User::findByEmail($e);\n}\n",
                      "config.php": "<?php\nreturn ['allowPublicRegistration' => true];\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    tb.entries_source = lambda: [{"route": "/register", "handler_file": "web/Register.php"},
                                 {"route": "/login", "handler_file": "web/Login.php"}]
    assert tb.record_identity([{"name": "x", "kind": "magic"}]).startswith("rejected")
    assert "do not exist" in tb.record_identity([{"name": "x", "kind": "login", "files": ["nope.php"]}])
    assert tb.identity is None  # nothing locates it, so nothing is recorded
    res = tb.record_identity([{"name": "registration", "kind": "registration", "routes": ["^/register"],
                               "files": ["web/Register.php"], "settings": ["config.php:2 allowPublicRegistration"]},
                              {"name": "broken", "kind": "sso", "routes": ["("]}])
    assert "registration (registration): 1 entries so far" in res and "not recorded: broken" in res
    g = assets.group_identity(tb.identity[0], [{"id": "E1", "route": "/register"}, {"id": "E2", "route": "/x",
                                                                                     "handler_file": "web/Register.php"}],
                              [{"file": "web/Register.php", "line": 3}])
    assert g["entry_ids"] == ["E1", "E2"] and g["site_keys"] == ["web/Register.php:3"]
    ev = [{"file": "web/Register.php", "line": 3, "quote": "User::findByEmail($e)"}]
    out = tb.record_design([{"item": "record_claiming", "status": "flaw", "answer": "loads by email"},
                            {"item": "defaults", "status": "owner_decision", "answer": "open", "evidence": [
                                {"file": "config.php", "line": 2, "quote": "'allowPublicRegistration' => true"}]},
                            {"item": "nope", "status": "sound", "answer": "x"}])
    assert "record_claiming: evidence is required" in out and "unknown item 'nope'" in out and "answered: 1" in out
    out = tb.record_design({"item": "record_claiming", "status": "flaw", "answer": "loads by email", "evidence": ev})
    assert "answered: 2" in out and "left: identity_binding, token_lifecycle, privilege_ceiling" in out
    names = {t["function"]["name"] for t in tool_schemas("design")}
    assert {"record_design", "report_finding", "record_card"} <= names
    assert {"run_recipe", "record_identity", "class_absent"} <= {t["function"]["name"] for t in tool_schemas("assets")}
    assert "record_design" not in {t["function"]["name"] for t in tool_schemas("review")}


@needs_rg
def test_run_maps_assets_and_reviews_operations_and_identity_design(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    proj = tmp_path / "p"
    _write(proj, {
        "web/Download.php": "<?php\nclass Download {\n  function execute() {\n    echo 'file';\n  }\n}\n",
        "web/Home.php": "<?php\nclass Home {\n  function execute() {\n    Cache::put($_GET['k']);\n  }\n}\n",
        "web/Register.php": "<?php\nclass Register {\n  function execute() {\n    $u = User::findByEmail($_POST['e']);\n"
                            "    $u->role = 'member';\n  }\n}\n",
        "lib/Cache.php": "<?php\nclass Cache {\n  static function put($k) {\n    file_put_contents('/c/' . $k, 1);\n"
                         "  }\n}\n",
        "lib/Hooks.php": "<?php\nclass Hooks {\n  function onImport($u, $row) {\n    $u->role = $row['role'];\n  }\n}\n",
        "config.php": "<?php\nreturn ['allowPublicRegistration' => true];\n"})
    extractor = ("import json, os, sys\nr = sys.argv[1]\nprint(json.dumps([{'route': '/' + f[:-4].lower(), "
                 "'handler_file': 'web/' + f, 'handler': 'execute', 'exposure': 'public'} "
                 "for f in sorted(os.listdir(os.path.join(r, 'web')))]))")
    model = {"authentication": "none", "authorization": "none", "permission_mapping": "none",
             "ladder": ["anonymous"], "shared_protections": "none", "principals": "anyone",
             "evidence": [{"file": "web/Home.php", "line": 3, "quote": "function execute()"}]}
    absent = [c for c in assets.OP_CLASSES if c not in ("credential_or_privilege_write", "file_write")]
    ok = lambda f, ln, q: [{"file": f, "line": ln, "quote": q}]  # noqa: E731
    reg = ("web/Register.php", 4, "User::findByEmail($_POST['e'])")
    scripts = {
        "recon": [("run_extractor", {"name": "web", "code": extractor}),
                  ("check_coverage", {"request_read_pattern": r"\$_(GET|POST)"}), ("finish", {"notes": "web/*"})],
        "access": [("record_access_model", model), ("finish", {})],
        "assets": [("finish", {}),  # refused: classes and identity left
                   ("run_recipe", {"name": "role-write", "op_class": "credential_or_privilege_write",
                                   "pattern": r"->role = ", "why": "users.role column"}),
                   ("run_recipe", {"name": "cache-write", "op_class": "file_write", "pattern": "file_put_contents",
                                   "why": "the file cache"}),
                   *[("class_absent", {"op_class": c, "reason": "searched, none"}) for c in absent],
                   ("record_identity", {"subsystems": [{"name": "registration", "kind": "registration",
                                                        "routes": ["^/register"], "files": ["web/Register.php"],
                                                        "settings": ["config.php:2 allowPublicRegistration"]}]}),
                   ("finish", {}),  # refused: identity kinds left
                   *[("identity_absent", {"kind": k, "reason": "searched, none"})
                     for k in assets.IDENTITY_KINDS if k != "registration"],
                   ("finish", {"notes": "mapped"})],
        "/download": [("record_card", {"function": "download", "callers": "anyone", "authz_verdict": "ok",
                                       "hypotheses": []})],
        # the entry reviewer traces the cache write: the operation unit for it is not run again
        "/home": [("record_card", {"function": "home", "callers": "anyone", "authz_verdict": "ok", "hypotheses": [
            {"risk": "path traversal in the cache key", "anchor": "lib/Cache.php:4", "status": "rejected",
             "why": "the key is a hash (lib/Cache.php:3)"}]})],
        "/register": [("record_card", {"function": "register", "callers": "anyone", "authz_verdict": "ok",
                                       "hypotheses": []})],
        "operation": [("record_card", {"function": "plugin import sets roles", "callers": "plugins (no caller)",
                                       "authz_verdict": "unclear", "hypotheses": [
                                           {"risk": "role from imported row", "anchor": "lib/Hooks.php:4",
                                            "status": "open", "why": "who writes the imported rows"}],
                                       "open_leads": ["lib/Hooks.php:4 role from row"]})],
        "design": [("finish", {}),  # refused: checklist not answered
                   ("record_design", {"items": [
                       {"item": "record_claiming", "status": "flaw", "answer": "an existing account is loaded by "
                        "email and given the posted password", "evidence": ok(*reg)},
                       {"item": "defaults", "status": "owner_decision", "answer": "registration open by default",
                        "evidence": ok("config.php", 2, "'allowPublicRegistration' => true")},
                       *[{"item": k, "status": "unclear", "answer": "not read"} for k in
                         ("identity_binding", "token_lifecycle", "privilege_ceiling")]]}),
                   ("report_finding", {"vuln_type": "Account takeover", "cwe": "CWE-287",
                                       "sink_file": "web/Register.php", "sink_line": 4, "source": "email",
                                       "entry": "POST /register (public)", "required_privilege": "public",
                                       "verdict": "likely", "root_cause": "registration reuses an account by email",
                                       "impact": "takes over an inactive account when registration is open",
                                       "route_evidence": {"file": reg[0], "line": 2, "quote": "class Register"}}),
                   ("finish", {})],
        "verify": [("conclude", {"verdict": "uncertain", "reason": "not settled"})],
    }
    users = {}

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and not self.usage.calls:  # a reminder may follow the first user message
                system, user = messages[0]["content"], messages[1]["content"]
                key = ("assets" if "worth protecting" in system else "access" if "controls ACCESS" in system
                       else "verify" if "Try to refute it" in user else "design" if "Identity subsystem" in user
                       else "operation" if "Sensitive operation(s) to review" in user
                       else next((k for k in ("/download", "/home", "/register") if f'"route": "{k}"' in user),
                                 "recon"))
                users.setdefault(key, user)
                self.script = list(scripts[key])
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg, **kw: Router([]))
    m = pipeline.run(_cfg(workers=1), proj, tmp_path / "out", deadline=time.time() + 600)
    a = m["recon"]["assets"]
    assert a["sites"] == 3 and a["by_class"] == {"credential_or_privilege_write": 2, "file_write": 1}
    assert a["identity_subsystems"] == 1 and a["finished"] and m["recon"]["assets_agent"]["steps"] >= 10
    rv = m["review"]
    assert rv["units"] == 3 and rv["reviewed_units"] == 3 and rv["design_units"] == 1
    # the role write in /register's handler goes to that entry; the cache write was traced by /home's
    # reviewer; only the extension point with no caller is reviewed as an operation unit
    assert rv["operation_units"] == 2 and rv["operation_units_covered_by_entry_review"] == 1
    assert rv["reviewed_operation_units"] == 1
    assert "Sensitive operations in this handler" in users["/register"] and "web/Register.php:5" in users["/register"]
    assert "Nothing in the repository calls this code" in users["operation"]
    assert "Checklist (answer every item with record_design)" in users["design"] and "allowPublicRegistration" in \
        users["design"]
    data = json.loads((tmp_path / "out" / "review" / "findings.json").read_text())
    (sheet,) = data["design_worksheet"]
    assert sheet["subsystem"] == "registration" and sheet["complete"] and len(sheet["items"]) == 5
    assert rv["design_items"] == {"flaw": 1, "owner_decision": 1, "unclear": 3}
    (f,) = data["findings"]
    assert f["unit_kind"] == "design" and f["handler"] == "identity:registration" and f["entries"]
    assert any(lead["handler"] == "lib/Hooks.php::<lib/Hooks.php>" for lead in data["open_leads"])
    assert data["not_reviewed_operations"] == [] and data["not_reviewed_design"] == []
    saved = json.loads((tmp_path / "out" / "recon" / "assets.json").read_text())
    assert {r["name"] for r in saved["recipes"]} == {"role-write", "cache-write"}


@needs_rg
def test_new_classes_have_recipes_and_appear_in_the_prompt(tmp_path):
    from app.services.yasa_audit.prompts import assets_prompt

    _write(tmp_path, {"app/Report.php": "<?php\nfunction byName($db, $n) {\n  $db->bind(':n', $n);\n"
                                        "  return $db->query('select * from t where n = :n');\n}\n"
                                        "function sorted($db, $col) {\n  return $db->query(\"select * from t order by $col\");\n}\n"})
    _index(tmp_path, [("f1", "function", "byName", "byName", "app/Report.php", 2, 5),
                      ("f2", "function", "sorted", "sorted", "app/Report.php", 6, 8)], [])
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    res = json.loads(tb.run_recipe("raw-query", "query_construction", r"->query\(", guard=r"->bind\(",
                                   why="Db::query runs SQL text as given"))
    assert res["sites"] == 2 and res["guard"]["guarded"] == 1 and len(res["unguarded_samples"]) == 1
    assert "order by $col" in res["unguarded_samples"][0]
    text = assets_prompt(40)
    for c in ("bulk_field_assignment", "query_construction", "code_or_command_execution",
              "secret_generation_or_check"):
        assert c in assets.OP_CLASSES and f"- {c}: " in text
    assert len(assets.OP_CLASSES) == 12 and AuditConfig().assets_budget == 40


@needs_rg
def test_module_level_and_test_callers_do_not_break_the_executor(tmp_path):
    _write(tmp_path, {"app/a.py": "def run(cmd):\n    os.system(cmd)\n\ndef hook(cmd):\n    os.system(cmd)\n",
                      "app/b.py": "import a\na.run('x')\n", "tests/test_a.py": "a.hook('x')\n"})
    _index(tmp_path, [("f_run", "function", "run", "a.run", "app/a.py", 1, 2),
                      ("f_hook", "function", "hook", "a.hook", "app/a.py", 4, 5),
                      ("file:app/b.py", "file", "b.py", "b", "app/b.py", 1, 2),
                      ("file:tests/test_a.py", "file", "test_a.py", "test_a", "tests/test_a.py", 1, 1)],
           [("file:app/b.py", "f_run", "calls"), ("file:tests/test_a.py", "f_hook", "calls")])
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    # the guard walk reaches module-level code (a file node), which has no function span: no KeyError
    res = json.loads(tb.run_recipe("shell", "code_or_command_execution", r"os\.system\(", guard="shlex", why="w"))
    assert res["sites"] == 2 and res["guard"]["unguarded"] == 2
    sites = {s["function"]: s for s in assets.expand(tb.recipes["shell"], tb.grep_rows(r"os\.system\("),
                                                     tb.call_index(), [])}
    assert sites["a.run"]["reach"] == "internal"  # called by module-level code
    assert sites["a.hook"]["reach"] == "no_callers"  # a test calling it is not a way in


def test_tool_calls_drop_unknown_arguments_and_ask_for_missing_ones(tmp_path):
    from app.services.yasa_audit.agent_loop import _invoke

    _write(tmp_path, {"a.py": "x = 1\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    spec = {t["function"]["name"]: t["function"] for t in tool_schemas("review")}
    out = _invoke(tb, spec["read_file"], {"path": "a.py", "unguarded": True})
    assert "a.py lines 1-1" in out and "ignored argument(s) this tool does not have: unguarded" in out
    assert _invoke(tb, spec["add_fact"], {"statement": "s"}) == "error: add_fact needs evidence; send the call " \
                                                               "again with them"


def test_design_answers_one_per_call_and_identity_records_merge_by_name(tmp_path):
    _write(tmp_path, {"web/Login.php": "<?php\nfunction login() {}\n", "web/Sso.php": "<?php\nfunction sso() {}\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    assert tb.record_design().startswith("rejected: send one answer")
    out = tb.record_design(item="defaults", status="unclear", answer="not read", to_verify="web/Login.php:2")
    assert "answered: 1" in out and tb.design["defaults"]["to_verify"] == "web/Login.php:2"
    tb.record_identity({"name": "login", "kind": "login", "files": ["web/Login.php"]})
    tb.record_identity([{"name": "sso", "kind": "sso", "files": ["web/Sso.php"]}])
    out = tb.record_identity({"name": "login", "kind": "login", "files": ["web/Login.php"], "notes": "again"})
    assert "2 subsystem(s) recorded in all" in out
    assert [(g["name"], g["notes"]) for g in tb.identity] == [("sso", ""), ("login", "again")]
    schema = next(t for t in tool_schemas("design") if t["function"]["name"] == "record_design")["function"]
    assert schema["parameters"]["required"] == [] and "to_verify" in schema["parameters"]["properties"]


def test_entries_an_object_scoped_role_can_call_are_not_privileged():
    from app.services.yasa_audit.pipeline import _scoped_exposure

    entries = [{"id": "E1", "exposure": "privileged", "who_can_call": {"principals": ["team_admin"]}},
               {"id": "E2", "exposure": "privileged", "who_can_call": {"principals": ["proxy_admin"]}},
               {"id": "E3", "exposure": "public", "who_can_call": {"principals": ["Team Admin"]}}]
    assert _scoped_exposure(entries, ["team admin", "team_admin"]) == 1
    assert [e["exposure"] for e in entries] == ["authenticated", "privileged", "public"]
    assert entries[0]["exposure_scoped_role"] == "team_admin"
    tb = Toolbox(_cfg(), ".", Path("."))
    model = {"authentication": "a", "authorization": "b", "permission_mapping": "c", "principals": "d",
             "shared_protections": "e", "ladder": ["user", "team_admin", "admin"], "scoped_roles": ["team_admin"],
             "evidence": [{"file": "tests/test_yasa_assets.py", "line": 1, "quote": '"""The sensitive-asset map'}]}
    assert tb.record_access_model(**model).startswith("access model recorded")
    from app.services.yasa_audit.prompts import access_model_text
    assert tb.access_model["scoped_roles"] == ["team_admin"] and "held for one object" in access_model_text(
        tb.access_model)


@needs_rg
def test_matches_outside_the_glob_in_code_the_entries_reach_stay_in_the_map(tmp_path):
    _write(tmp_path, {"app/h.py": "def handle(u):\n    return lib.fetch(u)\n",
                      "lib/net.py": "def fetch(u):\n    return http.get(u)\n",
                      # loaded by name (a provider registry, a lazy import): nothing names this file statically
                      "lib/provider.py": "def load(u):\n    return http.get(u)\n",
                      # named by other code, but by nothing an entry reaches
                      "lib/old.py": "def old(u):\n    return http.get(u)\n\ndef boot():\n    cli.main()\n",
                      "lib/cli.py": "def main():\n    old.old(1)\n",
                      "app/own.py": "def own(u):\n    return http.get(u)\n"})
    _index(tmp_path, [("h", "function", "handle", "h.handle", "app/h.py", 1, 2),
                      ("f", "function", "fetch", "net.fetch", "lib/net.py", 1, 2),
                      ("p", "function", "load", "provider.load", "lib/provider.py", 1, 2),
                      ("o", "function", "old", "old.old", "lib/old.py", 1, 2),
                      ("b", "function", "boot", "old.boot", "lib/old.py", 4, 5),
                      ("c", "function", "main", "cli.main", "lib/cli.py", 1, 2),
                      ("w", "function", "own", "own.own", "app/own.py", 1, 2)],
           [("h", "f", "calls"), ("c", "o", "calls"), ("b", "c", "calls")])
    entries = [{"id": "E1", "route": "/fetch", "handler_file": "app/h.py", "handler": "handle"}]
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    tb.entries_source = lambda: entries
    assert tb.call_index().loaded_by_name() == {"app/own.py", "lib/provider.py", "app/h.py"}
    res = json.loads(tb.run_recipe("fetch", "outbound_request", r"http\.get\(", glob="app/**", why="w"))
    assert res["sites"] == 3 and res["reachable_outside_glob"]["matches"] == 2  # net.py, provider.py
    data = assets.build(tb, tb.recipes, [], {}, entries)
    assert sorted(s["file"] for s in data["sites"]) == ["app/own.py", "lib/net.py", "lib/provider.py"]
    assert "act_on_other_account" in assets.OP_CLASSES


def test_shared_functions_get_a_contract_review_and_read_code_counts_as_reviewed():
    entries = [{"id": f"E{i}", "route": f"/r{i}", "exposure": "authenticated"} for i in range(25)]
    site = {"recipe": "r", "op_class": "query_construction", "file": "db.py", "line": 7, "code": "q(sql)",
            "function": "Db::run", "span": [5, 12], "reach": "entry", "entries": [e["id"] for e in entries],
            "entries_total": 25}
    (hub,) = assets.operation_units([site], entries, [], {"authenticated": 2})
    assert hub["hub"] and hub["fan_in"] == 25
    brief = assets.operation_brief(hub, [], {})
    assert "Review its CONTRACT" in brief and "add_fact" in brief
    cov = assets.Coverage()
    other = {**hub, "hub": False, "span": [5, 12]}
    cov.read("E1", "db.py", 1, 8)
    cov.read("E2", "db.py", 9, 12)
    assert not cov.covered(other)  # two units read parts of it: neither read it in full
    cov.read("E1", "db.py", 9, 20)
    assert cov.covered(other) and not cov.covered(hub)  # a contract review is not covered by entry reading


def test_a_large_identity_subsystem_is_reviewed_in_parts():
    entries = [{"id": f"E{i}", "route": f"/u/{i}", "handler_file": f"h{i % 3}.py"} for i in range(300)]
    g = {"name": "users", "kind": "user_management", "routes": [], "files": [], "models": [], "settings": [],
         "notes": "", "entry_ids": [e["id"] for e in entries[:90]], "site_keys": []}
    units = assets.design_units([g], entries, [], limit=10)
    assert len(units) == 3 and all(len(u["entries"]) <= 40 for u in units)
    assert {u["handler"] for u in units} == {f"users (part {n}/3)" for n in (1, 2, 3)}
    assert "this is part" in assets.design_brief(units[0])


def test_a_subsystem_most_entries_pass_is_reviewed_once_as_a_mechanism():
    entries = [{"id": f"E{i}", "route": f"/api/{i}", "handler_file": f"h{i % 3}.py"} for i in range(120)]
    sites = [{"recipe": "r1", "file": "auth/session.py", "line": 3, "function": "check",
              "op_class": "secret_generation_or_check",
              "code": "verify(token)", "reach": "entry", "entries": ["E1"]},
             {"recipe": "r2", "file": "h1.py", "line": 9, "function": "h", "op_class": "file_write",
              "code": "open(p, 'w')",
              "reach": "handler", "entries": ["E1"]}]
    g = {"name": "session", "kind": "session", "routes": ["^/api/.*$"], "files": ["auth/session.py"], "models": [],
         "settings": [], "notes": "", "entry_ids": [e["id"] for e in entries[:100]],
         "site_keys": ["auth/session.py:3", "h1.py:9"]}
    (unit,) = assets.design_units([g], entries, sites, limit=10)
    assert unit["handler"] == "session" and unit["entries"] == [] and unit["cross_cutting"] == 100
    assert [s["file"] for s in unit["sites"]] == ["auth/session.py"]
    assert "a mechanism requests pass through" in assets.design_brief(unit)


def test_follow_ups_run_before_the_units_not_started_yet():
    from app.services.yasa_audit.pipeline import _schedule

    order = []

    def work(i, unit):
        order.append(unit)
        return {"findings": [], "cards": [], "followups": ["a-check"] if unit == "a" else []}

    results, skipped = _schedule(["a", "b", "c"], work, workers=1, deadline=None)
    assert order == ["a", "a-check", "b", "c"] and len(results) == 4 and skipped == []


def test_open_design_answers_become_follow_up_units():
    unit = {"handler": "users", "subsystem": {"name": "users"}, "entries": [], "sites": []}
    answers = [{"item": "privilege_ceiling", "status": "flaw", "answer": "admins can invite anyone",
                "to_verify": "common_utils.py::admin_can_invite_user"},
               {"item": "defaults", "status": "unclear", "answer": "not read", "to_verify": ""},
               {"item": "identity_binding", "status": "flaw", "answer": "bound by email"}]
    leads = assets.follow_ups(unit, answers, reported=True)
    assert [x["answer"]["item"] for x in leads] == ["privilege_ceiling"]  # reported flaw without to_verify: done
    leads = assets.follow_ups(unit, answers, reported=False)
    assert [x["answer"]["item"] for x in leads] == ["privilege_ceiling", "identity_binding"]
    brief = assets.lead_brief(leads[0])
    assert "admin_can_invite_user" in brief and "report_finding" in brief


def test_review_sends_a_fresh_reviewer_to_settle_an_open_design_flaw(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    _write(tmp_path, {"web/Invite.php": "<?php\nfunction invite($uid) {\n  if (is_team_admin()) {\n"
                                        "    create_link($uid);\n  }\n}\n"})
    entries = [{"id": "E1", "method": "POST", "route": "/invite", "handler_file": "web/Invite.php",
                "handler": "invite", "exposure": "authenticated"}]
    g = {"name": "invitations", "kind": "invitation", "routes": ["^/invite"], "files": ["web/Invite.php"],
         "models": [], "settings": [], "notes": "", "entry_ids": ["E1"], "site_keys": []}
    ev = [{"file": "web/Invite.php", "line": 3, "quote": "if (is_team_admin())"}]
    answers = [{"item": k, "status": "sound", "answer": "ok", "evidence": ev}
               for k in assets.IDENTITY_CHECKLIST if k != "privilege_ceiling"]
    scripts = {
        "design": [*[("record_design", a) for a in answers],
                   ("record_design", {"item": "privilege_ceiling", "status": "flaw", "evidence": ev,
                                      "answer": "a team admin can invite any member, admins included",
                                      "to_verify": "web/Invite.php::create_link"}),
                   ("finish", {})],
        "lead": [("report_finding", {"vuln_type": "Privilege escalation", "cwe": "CWE-269",
                                     "sink_file": "web/Invite.php", "sink_line": 4, "source": "uid",
                                     "entry": "POST /invite (team admin)", "required_privilege": "authenticated",
                                     "verdict": "likely", "root_cause": "invitations ignore the target's role",
                                     "impact": "a team admin sets an admin's password",
                                     "route_evidence": {"file": "web/Invite.php", "line": 2,
                                                        "quote": "function invite($uid)"}})],
        "entry": [("record_card", {"function": "invite", "callers": "team admins", "authz_verdict": "ok",
                                   "hypotheses": []})],
    }
    seen = {}

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and not self.usage.calls:
                system, user = messages[0]["content"], messages[1]["content"]
                key = ("lead" if "has\nleft a conclusion open" in system else "design" if "Identity subsystem" in user
                       else "entry")
                seen.setdefault(key, user)
                self.script = list(scripts[key])
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg, **kw: Router([]))
    m = pipeline.review(_cfg(workers=1), tmp_path, tmp_path / "review", entries,
                        deadline=time.time() + 600, assets={"identity": [g], "sites": [], "recipes": []})
    assert m["reviewed_design_units"] == 1 and m["follow_up_units"] == 1 and m["reviewed_units"] == 1
    assert "web/Invite.php::create_link" in seen["lead"]
    data = json.loads((tmp_path / "review" / "findings.json").read_text())
    (f,) = data["findings"]
    assert f["unit_kind"] == "lead" and f["entries"] == ["E1"]
    (sheet,) = data["design_worksheet"]
    item = next(i for i in sheet["items"] if i["item"] == "privilege_ceiling")
    assert item["follow_up"]["findings"] == 1


def test_an_open_hypothesis_is_followed_up_once_per_anchor():
    board = assets.LeadBoard()
    unit = {"handler": "create", "handler_file": "api/env.ts", "entries": [{"id": "E1", "route": "/envs"}],
            "sites": []}
    card = {"function": "creates env rows and rewrites env.sh", "hypotheses": [
        {"risk": "names the runner reads", "anchor": "back/env.ts:273", "status": "rejected", "why": "denylist"},
        {"risk": "values reach the runner's commands", "anchor": "shell/otask.sh:79", "status": "open",
         "why": "did not follow conc/desi"},
        {"risk": "second open one", "anchor": "shell/otask.sh:185", "status": "open", "why": "x"}]}
    (lead,) = board.follow_ups(unit, [card])  # one per unit
    assert lead["kind"] == "lead" and lead["hypothesis"]["anchor"] == "shell/otask.sh:79"
    brief = assets.lead_brief(lead)
    assert "left this hypothesis open" in brief and "did not follow conc/desi" in brief and "/envs" in brief
    again = board.follow_ups({**unit, "handler": "update"}, [card])  # another unit, same open anchor
    assert [x["hypothesis"]["anchor"] for x in again] == ["shell/otask.sh:185"]


def test_code_the_index_does_not_parse_stays_in_the_map(tmp_path):
    _write(tmp_path, {"app/run.py": "def run(cmd):\n    os.system(cmd)\n",
                      "shell/task.sh": "#!/bin/bash\neval \"$CMD\"\n",
                      "shell/runner": "#!/bin/bash\neval \"$X\"\n", "LICENSE": "MIT\n", ".npmrc": "x=1\n",
                      "web/a.css": "a{}\n", "docs/usage.md": "eval \"$CMD\" in docs\n"})
    index = assets.CallIndex(tmp_path)
    index.indexed = True
    index.parsed = {"app/run.py"}
    assert index.unparsed("shell/task.sh") and not index.unparsed("app/run.py") and not index.unparsed("docs/usage.md")
    assert assets.unparsed_files(tmp_path, index) == ["shell/runner", "shell/task.sh"]
    assert "does not parse 2 product files" in assets.unparsed_summary(tmp_path, index)

    def grep(pattern, glob):
        rows = ["app/run.py:2:    os.system(cmd)", "shell/task.sh:2:eval \"$CMD\"", "docs/usage.md:1:eval in docs"]
        return [r for r in rows if not glob or r.startswith(glob.split("*")[0])]

    recipe = {"name": "exec", "op_class": "code_or_command_execution", "pattern": "eval|system", "glob": "app/**"}
    rows, outside = assets.scoped_rows(grep, recipe, set(), index.unparsed)
    assert outside == ["shell/task.sh:2:eval \"$CMD\""]
    sites = assets.expand(recipe, rows, index, [])
    assert {s["file"]: s["reach"] for s in sites}["shell/task.sh"] == "unindexed"


FEATURE = "\n".join([
    "class Feature {",                                  # 1
    "  function update(req) {",                         # 2
    "    this.row.description = req.body.description;",  # 3
    "    this.row.save();",                             # 4
    "  }",                                              # 5
    "  function importAll(rows) {",                     # 6
    "    for (r of rows) { r.description = r.text; }",  # 7
    "  }",                                              # 8
    "}", ""])


@needs_rg
def test_a_trace_crosses_storage_to_the_writers_and_who_can_run_them(tmp_path):
    """A stored value is as trusted as whoever can write it: who_reaches gives the writers of a store and
    the least privileged caller that reaches each, the way find_callers gives the callers of a function."""
    _write(tmp_path, {"app/Feature.js": FEATURE, "app/Order.js": "function buy(f) {\n  expand(f.description);\n}\n",
                      "shell/sync.sh": "#!/bin/sh\necho \"description = $1\" >> feature.conf\n",
                      "tests/feature.test.js": "x.description = 1;\n", "app/big.js": "n.count = 1;\n" * 70})
    _index(tmp_path, [("f", "class", "Feature", "Feature", "app/Feature.js", 1, 9),
                      ("f_u", "method", "update", "Feature::update", "app/Feature.js", 2, 5),
                      ("f_i", "method", "importAll", "Feature::importAll", "app/Feature.js", 6, 8),
                      ("o_b", "function", "buy", "buy", "app/Order.js", 1, 3)],
           [("f", "f_u", "contains"), ("f", "f_i", "contains")])
    entries = [{"id": "E1", "method": "POST", "route": "/features", "handler_file": "app/Feature.js",
                "handler": "update", "handler_line": 2, "exposure": "authenticated", "least_principal": "catalog_view"},
               {"id": "E2", "method": "POST", "route": "/admin/features", "handler_file": "app/Feature.js",
                "handler": "update", "handler_line": 2, "exposure": "privileged"}]
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    assert tb.who_reaches("description").startswith("error: not available")  # recon stages have no entries
    tb.reach = assets.Reach(tmp_path, entries)
    out = tb.who_reaches(r"description\s*=")
    assert out.splitlines()[0] == "3 matches in 3 functions; least privileged caller that reaches any of them: " \
                                  "authenticated"
    assert "Feature::update  (handler; 2 entries, weakest caller: authenticated)" in out
    assert "app/Feature.js:3  this.row.description = req.body.description;" in out
    assert "<- POST /features  [authenticated: catalog_view]" in out
    assert "Feature::importAll  (no_callers)" in out and "nothing in the index calls it" in out
    assert "<shell/sync.sh>  (unindexed)" in out and "does not parse" in out  # a writer in another language
    assert "tests/" not in out
    assert tb.who_reaches("count").startswith("rejected: 70 matches")
    assert "no matches" in tb.who_reaches("nothing_like_this")


def test_reviewers_follow_stored_values_and_the_special_cases_are_gone():
    from app.services.yasa_audit.prompts import review_prompt
    from app.services.yasa_audit.toolbox import tool_schemas

    for mode in ("entry", "operation", "design", "lead"):
        system = review_prompt(30, mode=mode)
        assert "A value is as trusted as whoever can write it" in system and "who_reaches(" in system
    names = lambda role: {t["function"]["name"] for t in tool_schemas(role)}  # noqa: E731
    assert "who_reaches" in names("review") and "who_reaches" in names("design")
    assert "who_reaches" not in names("recon") and "who_reaches" not in names("verify")
    # one principle instead of the rules that restated it for one situation each
    everything = review_prompt(30, mode="entry") + review_prompt(30, mode="operation") + \
        assets.IDENTITY_CHECKLIST["privilege_ceiling"]
    for gone in ("lists forbidden values", "A value read from storage is controlled", "later runs or obeys"):
        assert gone not in everything


def test_identity_records_keep_what_is_valid_and_every_kind_is_accounted_for(tmp_path):
    _write(tmp_path, {"web/Invite.php": "<?php\nfunction accept() {}\n", "lib/User.php": "<?php\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path / "out")
    tb.entries_source = lambda: []
    # an annotated path, a line suffix and a missing file: the bad item is dropped, not the subsystem
    out = tb.record_identity({"name": "invitations", "kind": "invitation", "routes": ["acceptInvitation"],
                              "files": ["web/Invite.php:2", "web/Gone.php"], "models": ["lib/User.php (user table)"]})
    assert "recorded 1 subsystem" in out and "Gone.php" in out
    assert tb.identity[0]["files"] == ["web/Invite.php"] and tb.identity[0]["models"] == ["lib/User.php"]
    assert "invitation" not in tb.identity_left() and "login" in tb.identity_left()
    assert tb.identity_absent("invitation", "x").startswith("rejected")  # it is recorded
    assert tb.identity_absent("sso", "searched for oauth/saml/oidc, none").startswith("recorded")
    assert "sso" not in tb.identity_left()
    assert "identity_absent" in {t["function"]["name"] for t in tool_schemas("assets")}

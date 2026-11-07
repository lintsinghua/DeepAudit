"""Entry discovery from codegraph's index, script rules and dispatcher marking (no tools needed)."""

import sqlite3

from app.services.yasa_audit.discovery import (
    codegraph_ready,
    codegraph_routes,
    discover,
    reachable_files,
    script_entries,
)


def _write(root, files):
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt)


def _codegraph(root, nodes, edges, complete=True):
    """Minimal codegraph.db: the columns discovery reads."""
    (root / ".codegraph").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / ".codegraph" / "codegraph.db")
    con.execute("create table nodes (id text, kind text, name text, file_path text, start_line int)")
    con.execute("create table edges (source text, target text, kind text)")
    con.execute("create table project_metadata (key text, value text)")
    con.executemany("insert into nodes values (?,?,?,?,?)", nodes)
    con.executemany("insert into edges values (?,?,?)", edges)
    con.execute("insert into project_metadata values ('index_state', ?)", ("complete" if complete else "running",))
    con.commit()
    con.close()


def test_codegraph_routes_pick_handler_named_on_registration_line(tmp_path):
    _write(tmp_path, {"server.ts": "\n" * 9 + "app.get('/orders/:id', auth.isAuthorized(), orders.show)\n",
                      "routes/orders.ts": "export function show() {}\n"})
    _codegraph(tmp_path, [
        ("r1", "route", "GET /orders/:id", "server.ts", 10),
        ("f1", "function", "isAuthorized", "lib/auth.ts", 3),
        ("f2", "function", "show", "routes/orders.ts", 1),
        ("f3", "function", "unrelated", "lib/x.ts", 1),
    ], [("r1", "f2", "references"), ("r1", "f1", "calls"), ("r1", "f3", "references")])
    (r,) = codegraph_routes(tmp_path / ".codegraph" / "codegraph.db")
    assert (r["method"], r["route"], r["file"], r["line"], r["handler"]) == \
        ("GET", "/orders/:id", "routes/orders.ts", 1, "show")
    assert r["middleware"] == ["isAuthorized"] and r["registered_at"] == "server.ts:10"
    assert codegraph_ready(tmp_path)


def test_direct_access_guard_rule(tmp_path):
    guard = "<?php\nif (!defined('appEntry') || !appEntry) die('Not A Valid Entry Point');\n"
    files = {f"modules/M{i}/action.php": guard + "echo $_GET['x'];\n" for i in range(12)}
    files["index.php"] = "<?php\nif (!defined('appEntry')) define('appEntry', true);\nrequire 'include/MVC/app.php';\n"
    files["soap.php"] = "<?php\ndefine('appEntry', true);\n$server->service($_POST);\n"
    files["include/lib.php"] = guard + "function helper() {}\n"
    _write(tmp_path, files)
    entries, rule = script_entries(tmp_path)
    assert rule["rule"] == "direct-access guard" and rule["constant"] == "appEntry"
    assert sorted(e["file"] for e in entries) == ["index.php", "soap.php"]


def test_script_fallback_rule_and_jsp(tmp_path):
    _write(tmp_path, {
        "login.php": "<?php\nsession_start();\n$u = $_POST['user'];\ninclude 'lib/db.php';\n",
        "lib/db.php": "<?php\nfunction q($s) { return $s; }\n",   # included, declarations only
        "lib/util.php": "<?php\nclass Util { function a() { return $_GET['x']; } }\n",  # declarations only
        "web/WEB-INF/x.jsp": "<% request.getParameter(\"a\"); %>",
        "web/view.jsp": "<% request.getParameter(\"a\"); %>",
    })
    _codegraph(tmp_path, [("a", "file", "login.php", "login.php", 1), ("b", "file", "db.php", "lib/db.php", 1)],
               [("a", "b", "imports")])
    entries, rule = script_entries(tmp_path, tmp_path / ".codegraph" / "codegraph.db")
    assert rule["rule"].startswith("not included")
    assert sorted(e["file"] for e in entries) == ["login.php", "web/view.jsp"]


def test_discover_marks_dispatchers_and_drops_regex_script_fallback(tmp_path):
    _write(tmp_path, {
        "index.php": "<?php\n$m = $_GET['module'];\nrequire_once \"modules/$m/controller.php\";\n",
        "page.php": "<?php\necho htmlspecialchars($_GET['q']);\n",
        "lib/helper.php": "<?php\nfunction h() {}\n",
    })
    entries, summary = discover(tmp_path, "php")
    by_file = {e["file"]: e for e in entries}
    assert set(by_file) == {"index.php", "page.php"}       # not every PHP file
    assert "require_once" in by_file["index.php"]["dispatcher"] and "dispatcher" not in by_file["page.php"]
    assert summary["dispatchers"] == 1 and summary["regex_added"] == 0


def test_dispatcher_ignores_literal_driver_loading(tmp_path):
    _write(tmp_path, {"web/a.jsp": "<% Class.forName(\"com.mysql.Driver\"); String id = request.getParameter(\"id\"); %>",
                      "web/b.jsp": "<% Class.forName(request.getParameter(\"cls\")).newInstance(); %>"})
    entries, _ = discover(tmp_path, "java")
    assert {e["file"]: bool(e.get("dispatcher")) for e in entries} == {"web/a.jsp": False, "web/b.jsp": True}


def test_reachable_files(tmp_path):
    _codegraph(tmp_path, [("a", "file", "a", "index.php", 1), ("b", "function", "b", "lib/b.php", 1),
                          ("c", "function", "c", "lib/c.php", 1), ("d", "function", "d", "lib/d.php", 1)],
               [("a", "b", "calls"), ("b", "c", "instantiates"), ("d", "a", "calls")])
    assert reachable_files(tmp_path, ["index.php"]) == {"index.php", "lib/b.php", "lib/c.php"}
    assert reachable_files(tmp_path, ["index.php"], depth=1) == {"index.php", "lib/b.php"}


def test_web_server_deny_rules_from_config_and_installer_code(tmp_path):
    guard = "<?php\nif (!defined('appEntry')) die('no');\n"
    files = {f"modules/M{i}/a.php": guard for i in range(12)}
    files.update({
        "index.php": "<?php\ndefine('appEntry', true);\n$x = $_GET['a'];\n",
        "modules/Contacts/tool.php": "<?php\ndefine('appEntry', true);\n$id = $_REQUEST['record'];\n",
        "cron.php": "<?php\ndefine('appEntry', true);\n",
        "install/install_utils.php": "<?php\n$rules = <<<EOQ\nRedirectMatch 403 {$ignoreCase}/+(include|modules)/+.*\\.(php|tpl)\n"
                                     "RedirectMatch 403 {$ignoreCase}/+cron\\.php\nEOQ;\n",
    })
    _write(tmp_path, files)
    entries, summary = discover(tmp_path, "php")
    denied = {e["file"]: e.get("web_server_denied", "") for e in entries}
    assert denied["index.php"] == ""
    assert "install/install_utils.php:3" in denied["modules/Contacts/tool.php"]
    assert "cron" in denied["cron.php"] and summary["denied_entries"] == 2

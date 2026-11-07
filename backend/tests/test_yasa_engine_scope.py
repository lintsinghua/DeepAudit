"""Scoped engine copy: PHP script wrapping keeps line numbers and stays valid PHP."""

import shutil
import subprocess

import pytest

from app.services.yasa_audit.engine_scope import (
    _top_level_classes,
    build_engine_src,
    wrap_php_script,
)

SCRIPT = """<?php
use Foo\\Bar;
require_once 'lib.php';
$id = $_GET['id'];
#[\\AllowDynamicProperties]
class Helper extends Base
{
    public function q($s) { return "<?xml version='1.0'?>" . $s; }
}
mysqli_query($c, "SELECT * FROM t WHERE id='$id'");
?>
<p>done</p>
"""


def _php_ok(path):
    php = shutil.which("php")
    if not php:
        pytest.skip("php not installed")
    r = subprocess.run([php, "-l", str(path)], capture_output=True, text=True)
    return "No syntax errors" in r.stdout


def test_wrap_keeps_lines_and_hoists_classes(tmp_path):
    out = wrap_php_script(SCRIPT, 3)
    assert out is not None
    orig, new = SCRIPT.splitlines(), out.splitlines()
    for i in range(1, len(orig)):  # every original line is still on its own line number
        if not orig[i].startswith("use "):
            assert orig[i].strip() in new[i], (i, orig[i], new[i])
    assert new[1].strip() == ""  # top-level `use` blanked in place
    assert "class YasaEntry3_1Service { public function run($yasa_req) {" in new[0]
    assert new[4].startswith(" }} #[")  # wrapper closed before the attribute, not between it and the class
    assert "YasaEntry3_2Service" in new[8] and out.rstrip().endswith("<?php }}")
    f = tmp_path / "a.php"
    f.write_text(out)
    assert _php_ok(f)


def test_wrap_skips_namespaced_and_tagless_files():
    assert wrap_php_script("<?php\nnamespace App\\Http;\nclass X {}\n", 1) is None
    assert wrap_php_script("<html>no php</html>", 1) is None


def test_top_level_classes_ignore_braces_in_strings_and_heredoc():
    code = "\n$a = '{';\n$b = <<<EOT\n}\nEOT;\nclass A {\n  function f() { return \"}\"; }\n}\n$x = 1;\n"
    (a, b), = _top_level_classes(code)
    assert code[a:b].startswith("class A") and code[a:b].endswith("}") and "$x" not in code[a:b]


def test_build_engine_src_scopes_wraps_and_renames_services(tmp_path):
    root = tmp_path / "p"
    (root / "lib").mkdir(parents=True)
    (root / "index.php").write_text("<?php\n$u = new UserService();\n$u->find($_GET['id']);\n")
    (root / "lib" / "UserService.php").write_text("<?php\nclass UserService {\n  public function find($id) {}\n}\n")
    (root / "unrelated.php").write_text("<?php\necho 1;\n")
    entries = [{"file": "index.php", "line": 1, "route": "/index.php", "via": "script"},
               {"file": "lib/UserService.php", "line": 2, "route": "UserService", "via": "regex"}]
    s = build_engine_src(root, tmp_path / "eng", entries)
    # no codegraph index: the scope falls back to the entry files themselves (unrelated.php dropped)
    assert s["files"] == 2 and s["php_wrapped"] == 1 and s["service_classes_renamed"] == 1
    assert not (tmp_path / "eng" / "unrelated.php").exists()
    assert "class UserServic_" in (tmp_path / "eng" / "lib" / "UserService.php").read_text()
    eng = (tmp_path / "eng" / "index.php").read_text()
    assert "YasaEntry0_1Service" in eng and "UserServic_" in eng and "UserService" not in eng
    assert eng.splitlines()[1:3] == (root / "index.php").read_text().replace("UserService", "UserServic_").splitlines()[1:3]


def test_scope_takes_small_packages_whole_and_skips_ui_packages(tmp_path):
    from app.services.yasa_audit.engine_scope import scope_files

    root = tmp_path / "repo"
    files = {
        "server/package.json": '{"dependencies": {"express": "4"}}',
        "server/routes.js": "x", "server/api/posts.js": "x", "server/api/posts.test.js": "x",
        "admin/package.json": '{"dependencies": {"react": "18"}}', "admin/src/App.js": "x",
    }
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt)
    got, how = scope_files(root, [{"file": "server/routes.js"}])
    # no codegraph edges reach api/posts.js (dynamic property access); the package brings it in
    assert got == {"server/routes.js", "server/api/posts.js", "server/package.json"} and how["packages"] == ["server"]


def test_auto_plan_uses_registration_functions_for_js():
    from app.services.yasa_audit.pipeline import auto_engine_plan

    entries = [
        {"file": "server/api/posts.js", "registered_at": "server/routes.js:3", "registration_fn": "apiRoutes"},
        {"file": "server/api/tags.js", "registered_at": "server/routes.js:4", "registration_fn": "apiRoutes"},
        {"file": "app.js", "registered_at": "app.js:10", "registration_fn": ""},
        {"file": "x.ts", "registered_at": "svc.ts:5", "registration_fn": "#createApp"},
    ]
    plan = auto_engine_plan("ts", entries)
    eps = plan["rule_config"][0]["entrypoints"]
    assert plan["entrypoint_mode"] == "ONLY_CUSTOM" and plan["language"] == "javascript"
    assert eps == [{"filePath": "/server/routes.js", "attribute": "HTTP", "functionName": "apiRoutes"},
                   {"filePath": "/app.js", "attribute": "HTTP"}]
    php = auto_engine_plan("php", [])
    assert php["entrypoint_mode"] == "SELF_COLLECT" and php["checker_ids"] == ["taint_flow_php_input"]

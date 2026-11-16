"""Unit tests for app.services.yasa_audit (no LLM, no YASA binary needed; ripgrep from PATH)."""

import importlib.util
import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.yasa_audit.assets import OP_CLASSES
from app.services.yasa_audit.config import AuditConfig
from app.services.yasa_audit.toolbox import FactBook, Toolbox, tool_schemas

BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "yasa_audit" / "eval.py"
RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(RG is None, reason="ripgrep not installed")


def _cfg(**kw) -> AuditConfig:
    cfg = AuditConfig(**kw)
    if RG:
        cfg.rg_bin = RG
    return cfg


def _write(root, files):
    for rel, txt in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(txt)


def _call(name, args, cid="c1"):
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class ScriptedLLM:
    """Returns the scripted tool calls in order, then finish."""

    def __init__(self, script):
        self.script = list(script)
        self.usage = SimpleNamespace(prompt=0, completion=0, cached=0, reasoning=0, calls=0)

    def chat(self, messages, tools=None):
        self.usage.calls += 1
        name, args = self.script.pop(0) if self.script else ("finish", {"notes": "done"})
        return SimpleNamespace(content="", tool_calls=[_call(name, args, f"c{self.usage.calls}")])


def _role(system):
    """Which recon agent a system prompt belongs to."""
    return "assets" if "worth protecting" in system else "access" if "controls ACCESS" in system else "recon"


# The asset agent of a test project that has none of the operations: every class absent, no identity.
ASSETS_NONE = [("class_absent", {"op_class": c, "reason": "not in this test project"}) for c in OP_CLASSES] + [
    ("record_identity", {"subsystems": []}), ("finish", {})]


def _script(scripts, key):
    return list(scripts.get("assets", ASSETS_NONE) if key == "assets" else scripts[key])


class ByRole:
    """LLM factory for recon tests: each agent gets the scripted model for its role, picked from its
    system prompt at the first call (the two agents start in parallel, in no fixed order)."""

    def __init__(self, **roles):
        self.roles = roles

    def __call__(self, cfg):
        roles = self.roles

        class Proxy:
            usage = SimpleNamespace(prompt=0, completion=0, cached=0, reasoning=0, calls=0)

            def chat(self, messages, tools=None):
                role = {"recon": "surface"}.get(_role(messages[0]["content"]), _role(messages[0]["content"]))
                if role not in roles:
                    roles[role] = ScriptedLLM(ASSETS_NONE)
                return roles[role].chat(messages, tools)

        return Proxy()


# ---------------------------------------------------------------- toolbox


def test_toolbox_confines_paths(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.ts").write_text("x\ny\n")
    (tmp_path / "proj_evil").mkdir()
    (tmp_path / "proj_evil" / "secret.txt").write_text("s")
    tb = Toolbox(AuditConfig(), tmp_path / "proj", tmp_path / "out")
    assert "a.ts lines 1-2" in tb.read_file("a.ts")
    with pytest.raises(ValueError):
        tb.read_file("../proj_evil/secret.txt")  # sibling dir with the same prefix
    (tmp_path / "proj" / "link").symlink_to(tmp_path / "proj_evil")
    with pytest.raises(ValueError):
        tb.read_file("link/secret.txt")


@needs_rg
def test_grep_path_globs_match_relative_to_project(tmp_path):
    """Regression: rg resolved globs containing '/' against the process cwd, so they never matched."""
    _write(tmp_path, {"app/code/A/Ctrl.php": "<?php $this->getRequest()->getParam('id');\n",
                      "lib/B.php": "<?php getParam('x');\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path)
    assert tb.grep("getParam", glob="app/**/*.php").splitlines() == [
        "app/code/A/Ctrl.php:1:<?php $this->getRequest()->getParam('id');"]
    assert len(tb.grep_rows("getParam")) == 2
    assert tb.grep("getparam") == "(no matches)"  # case-sensitive by default
    assert len(tb.grep_rows("(?i)getparam")) == 2


def test_tool_schemas_per_role():
    recon = {t["function"]["name"] for t in tool_schemas("recon")}
    review = {t["function"]["name"] for t in tool_schemas("review")}
    assert {"run_extractor", "check_coverage", "codegraph_routes", "finish"} <= recon
    assert {"record_card", "report_finding", "add_fact", "finish"} <= review
    assert not recon & {"report_finding", "record_card"} and not review & {"run_extractor"}


EXTRACTOR = """
import json, os, sys
root = sys.argv[1]
out = []
for d, _, fs in os.walk(os.path.join(root, 'controllers')):
    for f in sorted(fs):
        rel = os.path.relpath(os.path.join(d, f), root)
        out.append({'route': '/' + f[:-4].lower(), 'method': 'GET', 'handler_file': rel,
                    'handler': 'execute', 'exposure': 'public' if 'Public' in f else 'privileged',
                    'auth': 'none' if 'Public' in f else 'ACL admin'})
out.append({'route': '/ghost', 'handler_file': 'controllers/Missing.php', 'handler': 'execute'})
out.append({'no_route': True})
print(json.dumps(out))
"""


def test_run_extractor_runs_agent_code_and_checks_handlers(tmp_path):
    proj, out = tmp_path / "p", tmp_path / "o"
    out.mkdir()
    _write(proj, {"controllers/PublicView.php": "<?php class PublicView { function execute() {} }",
                  "controllers/AdminSave.php": "<?php class AdminSave { function execute() {} }",
                  "controllers/Broken.php": "<?php class Broken { function run() {} }"})
    tb = Toolbox(AuditConfig(), proj, out)
    res = json.loads(tb.run_extractor("pages", EXTRACTOR))
    assert res["entries"] == 4 and res["handler_resolved"] == 2 and res["handler_unresolved"] == 2
    assert res["by_exposure"] == {"privileged": 2, "public": 1, "unknown": 1}
    assert any("does not exist" in u for u in res["unresolved_samples"])
    assert any("does not occur" in u for u in res["unresolved_samples"])  # Broken has no execute()
    assert res["problems"] and len(res["random_resolved_samples_to_check_by_reading"]) == 2
    assert (out / "extractors" / "pages.py").read_text() == EXTRACTOR
    # same name replaces, another name adds; manual entries are merged and deduplicated
    tb.run_extractor("pages", "import json; print(json.dumps([{'route': '/a', "
                              "'handler_file': 'controllers/AdminSave.php'}]))")
    tb.add_entries([{"route": "/a", "handler_file": "controllers/AdminSave.php"},
                    {"route": "/b", "handler_file": "controllers/PublicView.php", "exposure": "public"}])
    assert [e["route"] for e in tb.entries()] == ["/a", "/b"]
    assert tb.run_extractor("bad name!", "").startswith("error")
    assert "exited 1" in tb.run_extractor("boom", "raise SystemExit(1)")
    assert "not JSON" in tb.run_extractor("text", "print('hello')")


@needs_rg
def test_check_coverage_reports_request_reads_outside_entries(tmp_path):
    _write(tmp_path, {"web/Page.php": "<?php $r->getParam('a');\n",
                      "api/Rest.php": "<?php $r->getParam('b');\n$r->getParam('c');\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path)
    tb.add_entries([{"route": "/page", "handler_file": "web/Page.php", "handler": "getParam"}])
    res = json.loads(tb.check_coverage(r"getParam\("))
    assert (res["sites"], res["covered_sites"], res["uncovered_sites"]) == (3, 1, 2)
    assert res["uncovered_files"] == 1 and res["uncovered"][0]["file"] == "api/Rest.php"
    assert len(res["uncovered"][0]["reads"]) == 2 and res["account_for_each"]


def test_factbook_accepts_only_evidence_found_in_code(tmp_path):
    _write(tmp_path, {"lib/Escaper.php": "<?php\nclass Escaper {\n  function escapeHtml($s) {\n"
                                         "    return htmlspecialchars($s, ENT_QUOTES);\n  }\n}\n"})
    fb = FactBook(tmp_path)
    ok = [{"file": "lib/Escaper.php", "line": 4, "quote": "htmlspecialchars($s,   ENT_QUOTES)"}]
    assert fb.add("escapeHtml HTML-escapes with ENT_QUOTES", ok, "u1") == "accepted as F1"
    assert fb.add("escapeHtml  html-escapes with ENT_QUOTES", ok, "u2") == "already known as F1"
    assert fb.add("x" * 300, ok, "u2").startswith("rejected: the statement has 300")
    assert fb.add("x", [{"file": "lib/Escaper.php", "line": 4, "quote": "strip_tags"}], "u3").startswith("rejected")
    assert fb.add("x", [{"file": "../etc/passwd", "line": 1, "quote": "root"}], "u3").startswith("rejected")
    assert fb.add("x", [], "u3").startswith("rejected")
    assert "F1: escapeHtml" in fb.prompt_block() and "lib/Escaper.php:4" in fb.prompt_block()
    assert len(fb.facts) == 1


# ---------------------------------------------------------------- pipeline


def test_units_dedupe_handlers_and_order_by_exposure():
    from app.services.yasa_audit.pipeline import _peers, _units

    entries = [
        {"id": "E1", "route": "/admin/x", "handler_file": "a/Admin.php", "handler": "execute",
         "exposure": "privileged"},
        {"id": "E2", "route": "/V1/carts/:id", "handler_file": "q/Cart.php", "handler": "get",
         "exposure": "authenticated"},
        {"id": "E3", "route": "/V1/guest-carts/:id", "handler_file": "q/Cart.php", "handler": "get",
         "exposure": "public"},
        {"id": "E4", "route": "/V1/carts/:id/items", "handler_file": "q/Item.php", "handler": "save",
         "exposure": "authenticated"},
        {"id": "E5", "route": "/broken", "handler_file": "x/Gone.php", "handler": "run", "exposure": "public",
         "resolved": False},
    ]
    units = _units(entries)
    # exposure first: an unresolved public entry still comes before authenticated and privileged ones
    assert [[e["id"] for e in u["entries"]] for u in units] == [["E2", "E3"], ["E5"], ["E4"], ["E1"]]
    assert units[0]["exposure"] == "public"  # the most exposed route of a handler decides
    peers = _peers(units[2], entries)  # the /V1/carts/:id/items unit
    assert any("/V1/carts/:id ->" in p for p in peers)


def test_handler_snippet_starts_at_the_handler(tmp_path):
    from app.services.yasa_audit.pipeline import _handler_snippet

    _write(tmp_path, {"C.php": "<?php\n" + "// pad\n" * 30 + "    public function execute()\n    {\n"})
    snip = _handler_snippet(tmp_path, {"handler_file": "C.php", "handler": "Ns\\C::execute"}, lines=3)
    assert snip.startswith("C.php lines 32-33") and "public function execute()" in snip


def test_recon_falls_back_to_codegraph_when_agent_finds_nothing(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: ScriptedLLM([]))
    monkeypatch.setattr(pipeline, "codegraph_db", lambda root: Path("x"))
    monkeypatch.setattr(pipeline, "codegraph_routes", lambda db, root: [
        {"route": "/orders/:id", "method": "GET", "file": "r.ts", "handler": "show"}])
    m = pipeline.recon(AuditConfig(), tmp_path, tmp_path / "recon")
    assert m["source"] == "codegraph-fallback" and m["entries"] == 1
    (e,) = json.loads((tmp_path / "recon" / "entries.json").read_text())
    assert e["id"] == "E1" and e["handler_file"] == "r.ts" and e["resolved"] is False


@needs_rg
def test_run_recon_then_review_end_to_end(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    proj = tmp_path / "p"
    _write(proj, {"web/Download.php": "<?php\nclass Download {\n  function execute() {\n"
                                      "    readfile('/srv/files/' . $_GET['name']);\n  }\n}\n",
                  "web/Home.php": "<?php\nclass Home {\n  function execute() { echo 'hi'; }\n}\n"})
    extractor = ("import json, os, sys\nr = sys.argv[1]\nprint(json.dumps([{'route': '/' + f[:-4].lower(), "
                 "'handler_file': 'web/' + f, 'handler': 'execute', 'exposure': 'public'} "
                 "for f in sorted(os.listdir(os.path.join(r, 'web')))]))")
    scripts = {
        "access": [("finish", {"notes": "too early"}),  # refused: no access model yet
                   ("record_access_model", {"authentication": "none", "authorization": "none",
                                            "permission_mapping": "none", "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anyone",
                                            "evidence": [{"file": "web/Home.php", "line": 3,
                                                          "quote": "function execute()"}]}),
                   ("write_access_resolver", {"code": "import json,sys; r=json.load(sys.stdin); print(json.dumps("
                                              "[{'least_privileged': 'public', 'rule': 'none'} for _ in r]))",
                                              "samples": [{"route": "/a"}, {"route": "/b"}, {"route": "/c"}]}),
                   ("finish", {"notes": "no access control"})],
        "recon": [("run_extractor", {"name": "web", "code": extractor}),
                  ("finish", {"notes": "too early"}),  # refused: coverage not checked
                  ("check_coverage", {"request_read_pattern": r"\$_GET"}),
                  ("finish", {"notes": "web/<Name>.php::execute serves /<name>"})],
        "/download": [("record_card", {"function": "file download", "callers": "anyone",
                                       "authz_verdict": "ok", "hypotheses": [
                                           {"risk": "path traversal", "why": "name joins a path",
                                            "status": "confirmed"}]}),  # refused: no anchor
                      ("record_card", {"function": "file download", "callers": "anyone",
                                       "authz_verdict": "ok", "facts_used": ["F9"], "hypotheses": [
                                           {"risk": "path traversal", "anchor": "web/Download.php:4",
                                            "why": "name joins a path", "status": "confirmed"}]}),
                      ("add_fact", {"statement": "Download reads files under /srv/files", "evidence": [
                          {"file": "web/Download.php", "line": 4, "quote": "readfile('/srv/files/'"}]}),
                      ("report_finding", {"vuln_type": "Path traversal", "cwe": "CWE-22",
                                          "sink_file": "web/Download.php", "sink_line": 4,
                                          "source": "$_GET['name']", "entry": "GET /download (public)",
                                          "required_privilege": "none", "verdict": "confirmed",
                                          "root_cause": "file name from the query joined to a path",
                                          "impact": "reads any file the server can read",
                                          "route_evidence": {"file": "web/Download.php", "line": 2,
                                                             "quote": "class Download"}})],
        "/home": [("record_card", {"function": "home page", "callers": "anyone", "authz_verdict": "ok",
                                   "open_leads": ["web/Home.php:3 echo of q: check the template escaping"],
                                   "hypotheses": []})],
    }
    scripts["verify"] = [("finish", {"notes": "too early"}),  # refused: no conclusion yet
                         ("conclude", {"verdict": "upheld", "reason": "nothing between $_GET and readfile",
                                       "path": [{"stage": "operation", "file": "web/Download.php", "line": 4,
                                                 "quote": "readfile('/srv/files/' . $_GET['name'])"}]}),
                         ("conclude", {"verdict": "upheld", "reason": "nothing between $_GET and readfile",
                                       "path": [{"stage": s, "file": "web/Download.php", "line": ln, "quote": q,
                                                 "effect": "passes"} for s, ln, q in (
                                           ("input_validation", 4, "$_GET['name']"),
                                           ("permission", 3, "function execute()"),
                                           ("operation", 4, "readfile('/srv/files/' . $_GET['name'])"))]})]
    users, systems = [], []

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and not self.usage.calls:  # a reminder may follow the first user message
                user = messages[1]["content"]
                users.append(user)
                systems.append(messages[0]["content"])
                key = ("verify" if "Try to refute it" in user else
                       next((k for k in ("/download", "/home") if f'"route": "{k}"' in user),
                            _role(messages[0]["content"])))
                self.script = _script(scripts, key)
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: Router([]))
    cfg = _cfg(workers=1)
    m = pipeline.run(cfg, proj, tmp_path / "out", deadline=time.time() + 600)
    assert m["recon"]["entries"] == 2 and m["recon"]["resolved"] == 2
    assert m["recon"]["access_model"]["principals"] == "anyone" and m["recon"]["coverage"]["sites"] == 1
    assert m["recon"]["notes"] == "web/<Name>.php::execute serves /<name>"  # the early finish was refused
    assert "- principals: anyone" in systems[-1]  # reviewers get the access model
    assert m["recon"]["resolver"] == {"installed": True, "entries": 2, "disagreements": 0, "unknown": 0}
    assert m["recon"]["reconcile"] is None  # nothing to reconcile
    assert any('"who_can_call": {"least_privileged": "public"' in u for u in users[1:])
    assert m["review"]["units"] == 2 and m["review"]["reviewed_units"] == 2 and m["review"]["facts"] == 1
    data = json.loads((tmp_path / "out" / "review" / "findings.json").read_text())
    (f,) = data["findings"]
    assert f["cwe"] == "CWE-22" and f["handler"] == "web/Download.php::execute" and data["not_reviewed"] == []
    assert f["verification"]["verdict"] == "upheld" and data["refuted"] == []
    assert m["verify"]["root_causes"] == 1 and m["verify"]["verdicts"] == {"upheld": 1}
    (lead,) = data["open_leads"]  # unverified suspicions are kept apart from findings
    assert lead["lead"] == "web/Home.php:3 echo of q: check the template escaping" and lead["entries"]
    cards = json.loads((tmp_path / "out" / "review" / "cards.json").read_text())
    assert {c["function"] for c in cards} == {"file download", "home page"}  # one card per unit
    assert next(c for c in cards if c["function"] == "file download")["hypotheses"][0]["anchor"] == \
        "web/Download.php:4"
    assert any("readfile('/srv/files/'" in u for u in users[1:])  # the handler's code is in the unit
    m2 = pipeline.run(cfg, proj, tmp_path / "out", deadline=time.time() + 600)  # recon reused
    assert m2["recon"].get("reused") is True


def test_schedule_respects_deadline_and_order():
    from app.services.yasa_audit.pipeline import MIN_UNIT_S, _schedule

    seen = []
    results, skipped = _schedule(["a", "b", "c"], lambda i, u: seen.append(u) or {"findings": [u]},
                                 workers=1, deadline=None)
    assert seen == ["a", "b", "c"] and skipped == []
    results, skipped = _schedule(["a", "b"], lambda i, u: {"findings": [u]}, workers=2,
                                 deadline=time.time() + MIN_UNIT_S / 2)
    assert results == [] and sorted(skipped) == ["a", "b"]


def test_schedule_skips_when_stopped():
    from app.services.yasa_audit.pipeline import _schedule

    results, skipped = _schedule([1, 2, 3], lambda i, u: {"u": u}, 2, None, stop=lambda: True)
    assert results == [] and skipped == [1, 2, 3]


# ---------------------------------------------------------------- agent loop and usage


def test_agent_loop_stops_after_deadline(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    res = run_agent(ScriptedLLM([("list_dir", {})] * 5), tb, tool_schemas("review"), "sys", "user",
                    budget=50, log_path=tmp_path / "t.jsonl", deadline=time.time() - 120)
    assert res["timed_out"] and res["steps"] == 0


def test_agent_loop_sends_reminder_once(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    seen_msgs = []

    class FakeLLM:
        def chat(self, messages, tools=None):
            seen_msgs.append([m["content"] for m in messages if m["role"] == "user"])
            return SimpleNamespace(content="", tool_calls=[_call("list_dir", {})])

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    run_agent(FakeLLM(), tb, tool_schemas("recon"), "sys", "user", budget=6,
              log_path=tmp_path / "t.jsonl", reminders=[(lambda steps, t: steps >= 2, "WRITE AN EXTRACTOR")])
    assert sum(m.count("WRITE AN EXTRACTOR") for m in seen_msgs[-1:]) == 1
    assert not any("WRITE AN EXTRACTOR" in m for m in seen_msgs[1])  # not before step 2


def test_agent_loop_stops_when_cancelled(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    class FakeLLM:
        def chat(self, messages, tools=None):  # pragma: no cover - must not be called
            raise AssertionError("LLM called after cancel")

    tb = Toolbox(AuditConfig(should_stop=lambda: True), tmp_path, tmp_path)
    res = run_agent(FakeLLM(), tb, tool_schemas("review"), "s", "u", budget=5, log_path=tmp_path / "t.jsonl")
    assert res["steps"] == 0 and not res["finished"]


def test_llm_usage_counts_cached_and_reasoning_tokens():
    from app.services.yasa_audit.llm import Usage

    u = Usage()
    u.add(SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                          prompt_tokens_details=SimpleNamespace(cached_tokens=64),
                          completion_tokens_details=SimpleNamespace(reasoning_tokens=12)), 1.0)
    u.add(SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None,
                          completion_tokens_details=None), 1.0)
    assert (u.prompt, u.completion, u.cached, u.reasoning, u.calls) == (110, 25, 64, 12, 2)


# ---------------------------------------------------------------- DeepAudit task integration


def test_to_deepaudit_findings_maps_privilege_and_filters():
    from app.services.yasa_audit.runner import to_deepaudit_findings

    raw = [
        {"vuln_type": "SQL injection", "cwe": "CWE-89", "sink_file": "a/Dao.java", "sink_line": 12,
         "source": "req.getParameter(id)", "hops": ["A:1", "B:2"], "verdict": "confirmed",
         "required_privilege": "none", "entry": "GET /x"},
        {"cwe": "CWE-89", "sink_file": "a/Dao.java", "sink_line": 12, "verdict": "likely"},  # dup
        {"cwe": "CWE-22", "sink_file": "b.ts", "sink_line": "7", "verdict": "likely"},
        {"cwe": "CWE-639", "sink_file": "c.php", "sink_line": 3, "verdict": "confirmed",
         "required_privilege": "admin"},
        {"cwe": "CWE-89", "sink_file": "setup/x.php", "sink_line": 3, "verdict": "confirmed",
         "required_privilege": "operator_or_cli"},
        {"cwe": "CWE-78", "sink_file": "d.ts", "sink_line": 3, "verdict": "false_positive"},
        {"cwe": "CWE-9999", "sink_file": "e.ts", "sink_line": None, "verdict": "confirmed"},
    ]
    out = to_deepaudit_findings(raw)
    assert [f["file_path"] for f in out] == ["a/Dao.java", "b.ts", "c.php", "setup/x.php", "e.ts"]
    sqli, trav, idor, cli, other = out
    assert sqli["vulnerability_type"] == "sql_injection" and sqli["severity"] == "high"
    assert "1. A:1" in sqli["description"] and "Entry: GET /x" in sqli["description"]
    assert "verdict" not in sqli and "is_verified" not in sqli  # static verdict is not verification
    assert trav["severity"] == "medium" and trav["line_start"] == 7  # likely -> one level lower
    assert idor["severity"] == "medium" and cli["severity"] == "low"
    assert other["vulnerability_type"] == "other" and other["line_start"] is None


def test_audit_scope_with_mode():
    from app.api.v1.endpoints.agent_tasks import AgentTaskCreate, _audit_scope_with_mode

    assert _audit_scope_with_mode(None, "agent") is None
    assert _audit_scope_with_mode({"product": "x"}, "yasa") == {"product": "x", "mode": "yasa"}
    assert AgentTaskCreate(project_id="p").audit_mode == "agent"
    with pytest.raises(ValueError):
        AgentTaskCreate(project_id="p", audit_mode="nope")


async def test_execute_yasa_task_saves_findings(tmp_path, monkeypatch):
    from app.services.yasa_audit import task as ytask

    monkeypatch.setattr(ytask, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(ytask, "check_tools", lambda cfg: [])
    monkeypatch.setattr(ytask, "init_navigation", lambda *a, **k: None)
    seen = {}

    def fake_audit(cfg, root, out, deploy, product, start, deadline):
        seen["workers"], seen["budget"], seen["product"] = cfg.workers, round(deadline - start), product
        return {"recon": {"entries": 3, "resolved": 3}, "review": {"units": 3, "reviewed_units": 2},
                "findings": [{"cwe": "CWE-89", "sink_file": "A.java", "sink_line": 5, "verdict": "confirmed"},
                             {"cwe": "CWE-862", "sink_file": "B.java", "sink_line": 9, "verdict": "likely"}],
                "not_reviewed": ["E3"], "tokens": 150}

    monkeypatch.setattr(ytask, "run_entry_audit", fake_audit)

    class DB:
        async def commit(self):
            pass

        async def refresh(self, obj):
            pass

    events = []

    class Emitter:
        def __getattr__(self, name):
            async def emit(*a, **k):
                events.append(name)
            return emit

    saved = {}

    async def save(db, task_id, findings, project_root=None):
        saved["findings"] = findings
        return len(findings)

    t = SimpleNamespace(id="t1", audit_scope={"mode": "yasa", "product": "public: /login"},
                        timeout_seconds=1200, total_files=10, critical_count=0, high_count=0,
                        medium_count=0, low_count=0)
    llm = SimpleNamespace(provider="openai", base_url="http://llm", api_key="k", model="m",
                          timeout=60, temperature=0.1, max_tokens=4096)
    await ytask.execute_yasa_task(DB(), t, str(tmp_path), llm, Emitter(), lambda: False, save,
                                  lambda f: 42.0)
    assert seen == {"workers": 16, "budget": 1200, "product": "public: /login"}
    assert [f["file_path"] for f in saved["findings"]] == ["A.java", "B.java"]
    assert t.findings_count == 2 and t.tokens_used == 150 and t.status == "completed"
    assert (t.high_count, t.medium_count) == (1, 1) and t.security_score == 42.0
    assert "emit_task_complete" in events and "emit_warning" in events  # E3 not reviewed


def test_count_sources_skips_vendor_dirs(tmp_path):
    from app.services.yasa_audit.task import count_sources

    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    for p in ("src/A.java", "src/b.jsp", "src/c.ts", "src/readme.md", "node_modules/x/i.js"):
        (tmp_path / p).write_text("")
    assert count_sources(tmp_path) == 3


def test_scope_tree_applies_excludes_and_targets(tmp_path):
    from app.services.yasa_audit.task import scope_tree

    src = tmp_path / "p"
    for rel in ("src/A.java", "src/B.java", "node_modules/x/i.js", "app.log", "web/c.jsp"):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text("x")
    assert scope_tree(src, tmp_path / "s0", ["*.min.js"], None) == (src, 0)
    root, dropped = scope_tree(src, tmp_path / "s1", ["node_modules/**", "*.log"], None)
    kept = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert kept == ["src/A.java", "src/B.java", "web/c.jsp"] and dropped == 2
    root, dropped = scope_tree(src, tmp_path / "s2", ["*.log"], ["src/A.java", "./web/c.jsp"])
    kept = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    assert kept == ["src/A.java", "web/c.jsp"] and dropped == 3


def test_benchmark_scoring():
    spec = importlib.util.spec_from_file_location("yasa_bench_eval", BENCH)
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    findings = [
        {"sink_file": "routes/search.ts", "sink_line": 23, "cwe": "CWE-89", "verdict": "confirmed"},
        {"sink_file": "routes/keyServer.ts", "sink_line": 14, "cwe": "CWE-22", "verdict": "likely"},
        {"sink_file": "routes/trackOrder.ts", "sink_line": 18, "cwe": "CWE-89", "verdict": "false_positive"},
        {"sink_file": "routes/vulnCodeFixes.ts", "sink_line": 83, "cwe": "CWE-22", "verdict": "likely"},
    ]
    r = ev.score("juice-mini", findings)
    assert r["recall"] == "1/18"
    assert [n["id"] for n in r["negative_hits"]] == ["JS-N02"]
    assert r["wrongly_rejected"] == ["JS-E01"]
    assert r["unmatched"] == []
    assert json.dumps(r)


def test_run_extractor_reports_lost_entries_on_rewrite(tmp_path):
    _write(tmp_path / "p", {f"c/A{i}.php": "<?php function execute() {}" for i in range(10)})
    tb = Toolbox(AuditConfig(), tmp_path / "p", tmp_path)
    gen = ("import json; print(json.dumps([{'route': '/a%d' % i, 'handler_file': 'c/A%d.php' % i, "
           "'handler': 'execute'} for i in range({n})]))")
    assert "change_from_previous_version" not in json.loads(tb.run_extractor("x", gen.replace("{n}", "10")))
    res = json.loads(tb.run_extractor("x", gen.replace("{n}", "3")))
    ch = res["change_from_previous_version"]
    assert (ch["previous"], ch["now"], ch["removed"], ch["added"]) == (10, 3, 7, 0)
    assert "lost 7 of 10" in res["warning"] and ch["removed_by_directory"] == [["c", 7]]


def test_agent_loop_explains_unparsable_arguments_and_forces_finish(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    class FakeLLM:
        def __init__(self):
            self.seen = []

        def chat(self, messages, tools=None):
            self.seen.append([t["function"]["name"] for t in tools])
            if len(self.seen) == 1:  # a long call cut off mid-JSON
                bad = SimpleNamespace(id="c1", function=SimpleNamespace(name="list_dir", arguments='{"path": "a'))
                return SimpleNamespace(content="", tool_calls=[bad])
            if [t for t in tools if t["function"]["name"] != "finish"]:
                return SimpleNamespace(content="", tool_calls=[_call("list_dir", {})])
            return SimpleNamespace(content="", tool_calls=[_call("finish", {"notes": "two dispatchers"})])

    llm = FakeLLM()
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    res = run_agent(llm, tb, tool_schemas("recon"), "s", "u", budget=2, log_path=tmp_path / "t.jsonl")
    log = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert "not valid JSON" in next(e["content"] for e in log if e.get("role") == "tool")
    assert llm.seen[-1] == ["finish"] and res["finished"] and tb.notes == "two dispatchers"


@needs_rg
def test_recon_pass_that_read_the_code_writes_the_extractor(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    _write(tmp_path, {"api/Posts.java": "class Posts {\n  Mono<ServerResponse> list(ServerRequest r) {\n"
                                        "    return r.queryParam(\"q\");\n  }\n}\n"})
    extractor = ("import json; print(json.dumps([{'route': '/apis/posts', 'handler_file': 'api/Posts.java', "
                 "'handler': 'list', 'exposure': 'authenticated'}]))")
    model = {"authentication": "session", "authorization": "RBAC filter", "permission_mapping": "verb+path",
             "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anonymous < user", "evidence": [{"file": "api/Posts.java", "line": 2,
                                                             "quote": "list(ServerRequest r)"}]}
    script = [("list_dir", {})] * 8 + [                       # the pass only reads (budget 2, +6 grace) ...
              ("run_extractor", {"name": "router", "code": extractor}),  # ... then is offered only the gate's tools
              ("record_access_model", model),
              ("check_coverage", {"request_read_pattern": r"queryParam\("})]
    surface = ScriptedLLM([x for x in script if x[0] != "record_access_model"])
    access = ScriptedLLM([("record_access_model", model), ("finish", {})])
    seen = []
    orig = surface.chat

    def chat(messages, tools=None):
        seen.append(messages[-1]["content"] if messages[-1]["role"] == "user" else messages[1]["content"])
        return orig(messages, tools)

    surface.chat = chat
    monkeypatch.setattr(pipeline, "LLM", ByRole(access=access, surface=surface))
    cfg = _cfg(recon_budget=2)
    m = pipeline.recon(cfg, tmp_path, tmp_path / "recon")
    # finish is refused until an extractor ran, so the pass that read the code writes it (no second pass)
    assert m["passes"] == 1 and m["source"] == "agent" and m["entries"] == 1 and m["resolved"] == 1
    assert any("no extractor has run" in x for x in seen) and m["coverage"] is not None
    assert m["access_model"]["principals"] == "anonymous < user"


def test_recon_finish_gates_and_access_model_evidence(tmp_path):
    _write(tmp_path, {"Sec.java": "class Sec {\n  boolean allowed() { return true; }\n}\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    tb.finish_gates = [(lambda t: t.access_model is None, "record_access_model first")]
    assert tb.finish("x") == "not finished: record_access_model first" and not tb.finished
    base = {"authentication": "a", "authorization": "b", "permission_mapping": "c", "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "d"}
    assert tb.record_access_model(**base).startswith("rejected: evidence is required")
    assert "quote not found" in tb.record_access_model(
        **base, evidence=[{"file": "Sec.java", "line": 2, "quote": "denyAll"}])
    assert tb.record_access_model(**base, evidence=[{"file": "Sec.java", "line": 2, "quote": "allowed()"}]) \
        .startswith("access model recorded")
    assert tb.finish("done").startswith("finished") and tb.finished
    tb2 = Toolbox(AuditConfig(), tmp_path, tmp_path)
    tb2.finish_gates = tb.finish_gates
    tb2.finish("forced", _force=True)
    assert tb2.finished and tb2.notes == "forced"


def test_record_card_requires_anchors_and_counts_fact_citations(tmp_path):
    _write(tmp_path, {"A.java": "a\nb\nc\n"})
    fb = FactBook(tmp_path)
    fb.add("first", [{"file": "A.java", "line": 1, "quote": "a"}], "u0")
    fb.add("second", [{"file": "A.java", "line": 2, "quote": "b"}], "u0")
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path, facts=fb, unit="E1")
    card = {"function": "f", "callers": "c", "authz_verdict": "ok"}
    assert tb.record_card(**card, hypotheses=[{"risk": "sqli", "status": "rejected"}]).startswith("rejected")
    assert tb.record_card(**card, hypotheses=[{"risk": "x", "anchor": "A.java:99", "status": "open"}]) \
        .startswith("rejected")  # line out of range
    assert "have no why" in tb.record_card(**card, hypotheses=[{"risk": "idor", "anchor": "A.java:3",
                                                                 "status": "rejected"}])
    assert "unknown fact ids ignored: ['F7']" in tb.record_card(
        **card, hypotheses=[{"risk": "idor", "anchor": "A.java:3", "status": "open", "why": "who owns the row"}],
        facts_used=["F2", "F7"])
    tb.record_card(**card, hypotheses=[], facts_used=["F2"])
    assert len(tb.cards) == 1  # a later call replaces the card
    block = fb.prompt_block()
    assert block.index("F2: second") < block.index("F1: first")  # most cited first


def test_adaptive_limiter_halves_on_rate_limit_and_grows_back():
    from app.services.yasa_audit.llm import AdaptiveLimiter, _is_rate_limit

    lim = AdaptiveLimiter(ceiling=16, grow_after=2)
    for _ in range(3):
        lim.acquire()
    assert lim.stats()["peak_in_flight"] == 3
    lim.release(rate_limited=True)
    assert lim.limit == 8 and lim.stats()["rate_limited"] == 1
    lim.release()
    lim.release()
    assert lim.limit == 9  # two successes in a row -> +1
    err = type("RateLimitError", (Exception,), {})("slow down")
    assert _is_rate_limit(err) and not _is_rate_limit(ValueError("boom"))

def test_report_finding_requires_fields(tmp_path):
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path, unit="E1")
    assert tb.report_finding().startswith("rejected: missing vuln_type")
    assert "impact" in tb.report_finding(vuln_type="x", cwe="y", sink_file="a", sink_line=1, source="s",
                                         entry="e", required_privilege="none", verdict="likely",
                                         route_evidence={"file": "a", "line": 1, "quote": "q"})
    _write(tmp_path, {"Routes.java": "class Routes {\n  route(GET(\"/x\"), this::get);\n}\n"})
    full = {"vuln_type": "IDOR", "cwe": "CWE-639", "sink_file": "a.java", "sink_line": 3, "source": "id",
            "entry": "GET /x", "required_privilege": "customer", "root_cause": "no owner check",
            "impact": "reads another user's order",
            "route_evidence": {"file": "Routes.java", "line": 2, "quote": 'GET("/x")'}}
    assert tb.report_finding(**full, verdict="false_positive").startswith("rejected: verdict")
    phantom = dict(full, route_evidence={"file": "Routes.java", "line": 2, "quote": 'GET("/y")'})
    assert "route_evidence: quote not found" in tb.report_finding(**phantom, verdict="confirmed")
    assert tb.report_finding(**full, verdict="likely") == "recorded #1" and tb.findings[0]["_unit"] == "E1"


def test_recon_sends_access_model_to_the_surface_agent(tmp_path, monkeypatch):
    import threading

    from app.services.yasa_audit import pipeline

    _write(tmp_path, {"Sec.java": "class Sec {\n  boolean allowed() { return true; }\n}\n"})
    recorded = threading.Event()
    model = {"authentication": "a", "authorization": "b", "permission_mapping": "c", "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anon < admin",
             "evidence": [{"file": "Sec.java", "line": 2, "quote": "allowed()"}]}

    class Access(ScriptedLLM):
        def chat(self, messages, tools=None):
            r = super().chat(messages, tools)
            if self.usage.calls == 2:
                recorded.set()
            return r

    surface_msgs = []

    class Surface(ScriptedLLM):
        def chat(self, messages, tools=None):
            recorded.wait(5)
            time.sleep(0.05)  # let the access agent publish its result
            surface_msgs.append([m["content"] for m in messages if m["role"] == "user"])
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", ByRole(
        access=Access([("record_access_model", model), ("finish", {})]),
        surface=Surface([("list_dir", {}), ("list_dir", {}), ("finish", {"notes": "n"})])))
    m = pipeline.recon(AuditConfig(), tmp_path, tmp_path / "recon")
    assert m["access_model"]["principals"] == "anon < admin" and m["access_agent"]["finished"]
    assert any("access-control model is ready" in u and "anon < admin" in u for msgs in surface_msgs for u in msgs)


def test_generic_handlers_are_reviewed_per_resource():
    from app.services.yasa_audit.pipeline import SPLIT_ROUTES, _resource_key, _units

    assert _resource_key("/apis/g/v1/posts/{name}/status") == "/apis/g/v1/posts"
    assert _resource_key("/V1/carts/:cartId/items") == "/V1/carts"
    entries, n = [], 0
    for res, exp in (("posts", "public"), ("users", "privileged"), ("menus", "privileged")):
        for verb, h in (("GET", "Get"), ("PUT", "Update"), ("DELETE", "Delete")):
            n += 1
            entries.append({"id": f"E{n}", "route": f"/apis/g/v1/{res}/{{name}}", "method": verb,
                            "handler_file": f"x/Extension{h}Handler.java", "handler": "handle",
                            "exposure": exp if verb == "GET" else "privileged"})
    entries += [dict(e, id=f"X{i}", route=e["route"].replace("/g/", f"/g{i}/"))
                for i in range(SPLIT_ROUTES) for e in entries[:3]]  # every generic handler > SPLIT_ROUTES
    entries.append({"id": "S1", "route": "/login", "handler_file": "Login.java", "handler": "login",
                    "exposure": "public"})
    units = _units(entries)
    posts = next(u for u in units if u["entries"][0]["route"] == "/apis/g/v1/posts/{name}")
    assert posts["generic"] and len(posts["entries"]) == 3 and len(posts["handlers"]) == 3
    assert posts["exposure"] == "public"
    users = next(u for u in units if u["entries"][0]["route"] == "/apis/g/v1/users/{name}")
    assert users["exposure"] == "privileged"  # not dragged to public by the posts routes
    assert not next(u for u in units if u["entries"][0]["id"] == "S1")["generic"]


def test_anonymous_handlers_are_told_apart_by_line(tmp_path):
    from app.services.yasa_audit.pipeline import _handler_snippet, _units

    entries = [
        {"id": "E1", "route": "/sync/sync", "handler_file": "app-sync.ts", "handler": "app.post",
         "declared_at": "app-sync.ts:140", "exposure": "authenticated"},
        {"id": "E2", "route": "/sync/user-get-key", "handler_file": "app-sync.ts", "handler": "app.post",
         "handler_line": 205, "exposure": "authenticated"},
        {"id": "E3", "route": "/sync/list", "handler_file": "app-sync.ts", "handler": "listFiles",
         "exposure": "authenticated"},
        {"id": "E4", "route": "/sync/files", "handler_file": "app-sync.ts", "handler": "listFiles",
         "exposure": "authenticated"},
    ]
    units = _units(entries)
    assert sorted(len(u["entries"]) for u in units) == [1, 1, 2]  # named handler still shared
    _write(tmp_path, {"app-sync.ts": "\n".join(f"// {i}" for i in range(1, 300))})
    u = next(u for u in units if u["entries"][0]["id"] == "E2")
    assert _handler_snippet(tmp_path, u, lines=2).startswith("app-sync.ts lines 205-206")
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    assert tb._check_entry({"handler_file": "app-sync.ts", "handler_line": 999}) == "handler_line is outside handler_file"


def test_issue_board_links_findings_by_root_cause(tmp_path):
    from app.services.yasa_audit.runner import to_deepaudit_findings
    from app.services.yasa_audit.toolbox import IssueBoard

    _write(tmp_path, {"r.js": "app.post('/a', h)\napp.post('/b', h)\n// NOTE: intentionally no admin check (wontfix)\n"})
    board = IssueBoard()
    ev = lambda line, q: {"file": "r.js", "line": line, "quote": q}  # noqa: E731
    base = {"vuln_type": "IDOR", "cwe": "CWE-639", "sink_file": "s.js", "sink_line": 9, "source": "id",
            "required_privilege": "customer", "verdict": "likely", "impact": "uses the owner's bank link"}
    t1 = Toolbox(AuditConfig(), tmp_path, tmp_path, unit="E1", issues=board)
    assert t1.report_finding(**base, entry="POST /a", route_evidence=ev(1, "app.post('/a'")).startswith("rejected: root_cause")
    assert t1.report_finding(**base, entry="POST /a", route_evidence=ev(1, "app.post('/a'"),
                             root_cause="optional header skips the ownership check") == "recorded #1 as part of I1"
    t2 = Toolbox(AuditConfig(), tmp_path, tmp_path, unit="E2", issues=board)
    assert t2.report_finding(**base, entry="POST /b", route_evidence=ev(2, "app.post('/b'"), same_as="I1") == \
        "recorded #1 as part of I1"
    assert board.issues[0]["entries"] == ["POST /a", "POST /b"] and "I1 (CWE-639" in board.prompt_block()
    assert "documented_intent: quote not found" in t2.report_finding(
        **base, entry="POST /b", route_evidence=ev(2, "app.post('/b'"), root_cause="x",
        documented_intent=ev(3, "by design"))
    t2.report_finding(**dict(base, sink_line=10), entry="POST /b", route_evidence=ev(2, "app.post('/b'"),
                      root_cause="user list open", documented_intent=ev(3, "intentionally no admin check"))
    out = to_deepaudit_findings(t1.findings + t2.findings)
    assert out[-1]["severity"] == "low" and "Documented as intended" in out[-1]["description"]
    assert "Root cause I1" in out[0]["description"]


def test_agent_loop_appends_live_updates_from_parallel_units(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    news = iter([None, "New from reviewers working in parallel:\n- F7: helper escapes", None, None, None])
    seen = []

    class FakeLLM:
        def chat(self, messages, tools=None):
            seen.append([m["content"] for m in messages if m["role"] == "user"])
            return SimpleNamespace(content="", tool_calls=[_call("list_dir", {})])

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    run_agent(FakeLLM(), tb, tool_schemas("review"), "s", "u", budget=4, log_path=tmp_path / "t.jsonl",
              updates=lambda: next(news, None))
    assert sum("F7: helper escapes" in m for m in seen[-1]) == 1  # appended once, kept in the history
    assert not any("F7" in m for m in seen[0])  # nothing before the first step


def test_fact_and_issue_boards_report_what_others_added(tmp_path):
    from app.services.yasa_audit.toolbox import IssueBoard

    _write(tmp_path, {"A.java": "a\n"})
    fb, board = FactBook(tmp_path), IssueBoard()
    fb.add("mine", [{"file": "A.java", "line": 1, "quote": "a"}], "u1")
    fb.add("theirs", [{"file": "A.java", "line": 1, "quote": "a"}], "u2")
    board.register({"root_cause": "x", "cwe": "CWE-1", "entry": "e", "_unit": "u2"})
    seen_f, seen_i = set(), set()
    assert [f["statement"] for f in fb.since(seen_f, "u1")] == ["theirs"] and fb.since(seen_f, "u1") == []
    assert [i["id"] for i in board.since(seen_i, "u1")] == ["I1"] and board.since(seen_i, "u2") == []


@needs_rg
def test_coverage_record_keeps_the_broadest_check(tmp_path):
    _write(tmp_path, {"a.js": "req.body.x\nreq.query.y\n"})
    tb = Toolbox(_cfg(), tmp_path, tmp_path)
    tb.check_coverage(r"req\.(body|query)")
    res = json.loads(tb.check_coverage(r"req\.body"))
    assert tb.coverage["sites"] == 2 and "fewer read sites" in res["note"]


RESOLVER = """
import json, sys
reqs = json.load(sys.stdin)
out = []
for r in reqs:
    p = r["route"]
    if p.startswith("/admin"):
        out.append({"least_privileged": "privileged", "principals": ["admin"], "rule": "Rbac.java:3"})
    elif p.startswith("/me"):
        out.append({"least_privileged": "authenticated", "principals": ["user"], "rule": "Rbac.java:2"})
    else:
        out.append({"least_privileged": "public", "principals": ["anonymous"], "rule": "Rbac.java:1"})
print(json.dumps(out))
"""


def test_access_resolver_installs_after_samples_and_answers_reviewers(tmp_path):
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    assert tb.who_can_call("GET", "/admin").startswith("error: no resolver")
    assert tb.write_access_resolver(RESOLVER, [{"route": "/a"}]).startswith("rejected: give at least 3")
    bad = "import json,sys; json.load(sys.stdin); print(json.dumps([]))"
    assert "one per request" in tb.write_access_resolver(bad, [{"route": "/a"}, {"route": "/me"}, {"route": "/admin"}])
    assert tb.resolver_code is None
    msg = tb.write_access_resolver(RESOLVER, [{"route": "/a"}, {"route": "/me/x"}, {"method": "POST", "route": "/admin/u"}])
    assert msg.startswith("resolver installed") and "POST /admin/u -> privileged ['admin']" in msg
    assert json.loads(tb.who_can_call("GET", "/me/orders"))["least_privileged"] == "authenticated"
    assert (tmp_path / "resolver.py").read_text() == RESOLVER


def test_resolver_disagreement_keeps_declared_until_settled(tmp_path):
    from app.services.yasa_audit.pipeline import _apply_resolver

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    es = [{"route": "/admin/users", "exposure": "authenticated"},   # the two readings disagree
          {"route": "/me/orders", "exposure": "unknown"},            # surface agent did not know
          {"route": "/posts", "exposure": "public"}]
    out = _apply_resolver(tb, es, RESOLVER, tmp_path)
    assert {k: v for k, v in out.items() if not k.startswith("_")} == \
        {"installed": True, "entries": 3, "disagreements": 1, "unknown": 0}
    assert list(out["_groups"]) == [("authenticated", "privileged", "Rbac.java:3")]
    # not reconciled: a resolver that misreads routes must not relabel the surface
    assert es[0]["exposure"] == "authenticated" and es[0]["exposure_declared"] == "authenticated"
    assert es[0]["who_can_call"]["least_privileged"] == "privileged"
    assert es[1]["exposure"] == "authenticated" and "exposure_declared" not in es[1]
    assert es[2]["who_can_call"]["rule"] == "Rbac.java:1"
    assert _apply_resolver(tb, es, RESOLVER, tmp_path)["disagreements"] == 1  # idempotent
    assert es[0]["exposure"] == "authenticated"


def test_reconcile_decisions_are_applied_per_group():
    from app.services.yasa_audit.pipeline import _apply_decisions

    def e(i, declared, lp):
        return {"id": i, "exposure": declared, "exposure_declared": declared,
                "who_can_call": {"least_privileged": lp, "principals": [], "rule": "r"}}

    es = [e("E1", "privileged", "authenticated"), e("E2", "privileged", "public"),
          e("E3", "authenticated", "public"), e("E4", "public", "privileged")]
    out = _apply_decisions(es, {"G1": ["E1"], "G2": ["E2"], "G3": ["E3"]},
                           {"G1": {"verdict": "resolver_wrong", "reason": "misses #[RequiresAdmin] a.php:3"},
                            "G2": {"verdict": "declared_wrong", "reason": "b.php:9"},
                            "G3": {"verdict": "inconsistent_code", "reason": "c.php:2 vs d.php:5"}})
    assert out == {"resolver_wrong": 1, "declared_wrong": 1, "inconsistent_code": 1, "undecided": 1}
    assert es[0]["exposure"] == "privileged" and "exposure_declared" not in es[0]  # declared stands
    assert es[0]["who_can_call"]["least_privileged"] == "unknown"  # the wrong answer is not shown
    assert es[1]["exposure"] == "public" and "exposure_declared" not in es[1]
    assert es[2]["exposure"] == "public" and es[2]["access_inconsistency"] == "c.php:2 vs d.php:5"
    assert es[3]["exposure"] == "public" and es[3]["exposure_declared"] == "public"  # undecided: declared


def test_reconcile_lets_the_access_agent_fix_its_resolver(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    proj = tmp_path / "p"
    _write(proj, {"web/Admin.php": "<?php\nclass Admin {\n  function execute() { require_admin(); }\n}\n",
                  "web/Home.php": "<?php\nclass Home {\n  function execute() { echo $_GET['q']; }\n}\n"})
    extractor = ("import json\nprint(json.dumps([{'route': '/admin', 'handler_file': 'web/Admin.php', "
                 "'handler': 'execute', 'exposure': 'privileged'}, {'route': '/home', 'handler_file': "
                 "'web/Home.php', 'handler': 'execute', 'exposure': 'public'}]))")
    gate_only = ("import json,sys; r=json.load(sys.stdin); print(json.dumps([{'least_privileged': 'public', "
                 "'rule': 'no gate'} for _ in r]))")
    reads_handler = ("import json,sys,os; r=json.load(sys.stdin); print(json.dumps([{'least_privileged': "
                     "'privileged' if 'require_admin' in open(os.path.join(sys.argv[1], q['handler_file']))"
                     ".read() else 'public', 'rule': 'handler check'} if q.get('handler_file') else "
                     "{'least_privileged': 'unknown'} for q in r]))")
    scripts = {
        "access": [("record_access_model", {"authentication": "session", "authorization": "in handlers",
                                            "permission_mapping": "require_admin()", "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anyone, admin",
                                            "evidence": [{"file": "web/Admin.php", "line": 3,
                                                          "quote": "require_admin()"}]}),
                   ("write_access_resolver", {"code": gate_only, "samples": [{"route": "/a"}, {"route": "/b"},
                                                                             {"route": "/c"}]}),
                   ("finish", {"notes": "gate only"})],
        "recon": [("run_extractor", {"name": "web", "code": extractor}),
                  ("check_coverage", {"request_read_pattern": r"\$_GET"}),
                  ("finish", {"notes": "web/*.php"})],
        "reconcile": [("read_file", {"path": "web/Admin.php"}),
                      ("finish", {"notes": "too early"}),  # refused: G1 not settled
                      ("settle", {"decisions": [{"group": "G9", "verdict": "resolver_wrong",
                                                 "reason": "x"}]}),  # no such group
                      ("settle", {"decisions": [{"group": "G1", "verdict": "resolver_wrong",
                                                 "reason": "web/Admin.php:3 require_admin() in the handler"}]}),
                      ("write_access_resolver", {"code": reads_handler, "samples": [
                          {"route": "/admin", "handler_file": "web/Admin.php"},
                          {"route": "/home", "handler_file": "web/Home.php"}, {"route": "/x"}]}),
                      ("finish", {"notes": "resolver missed the check in the handler: fixed"})],
    }
    users = []

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and len(messages) == 2:
                user = messages[1]["content"]
                users.append(user)
                key = ("reconcile" if "independently of you" in user else
                       _role(messages[0]["content"]))
                self.script = _script(scripts, key)
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: Router([]))
    m = pipeline.recon(_cfg(), proj, tmp_path / "out", deadline=time.time() + 900)
    msg = next(u for u in users if "independently of you" in u)
    assert "G1: 1 entries, declared privileged, resolver public (rule: no gate)" in msg
    assert "/admin -> web/Admin.php execute" in msg and gate_only in msg  # samples and current code
    rc = m["reconcile"]
    assert rc["before"] == {"disagreements": 1, "unknown": 0} and rc["resolver_changed"] and rc["finished"]
    assert "fixed" in rc["notes"] and rc["groups"]["G1"]["verdict"] == "resolver_wrong"
    assert m["resolver"]["disagreements"] == 0 and rc["applied"] == {}  # the fixed resolver agrees
    es = json.loads((tmp_path / "out" / "entries.json").read_text())
    assert {e["route"]: e["exposure"] for e in es} == {"/admin": "privileged", "/home": "public"}
    assert not any(e.get("exposure_declared") for e in es)
    assert (tmp_path / "out" / "resolver.py").read_text() == reads_handler


def test_who_can_call_passes_the_entry_handler_to_the_resolver(tmp_path):
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    tb.resolver_code = ("import json,sys; r=json.load(sys.stdin); print(json.dumps([{'least_privileged': "
                        "'public', 'rule': q.get('handler_file', '-') + ':' + str(q.get('handler_line', ''))} "
                        "for q in r]))")
    tb.known_entries = {("POST", "/x"): {"route": "/x", "handler_file": "a.php", "handler_line": 7,
                                        "exposure": "public", "id": "E1"}}
    assert json.loads(tb.who_can_call("post", "/x"))["rule"] == "a.php:7"
    assert json.loads(tb.who_can_call("GET", "/y"))["rule"] == "-:"


def test_extractor_regression_is_pointed_out_once(tmp_path):
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    many = "import json\nprint(json.dumps([{'route': '/r%d' % i, 'handler_file': 'x'} for i in range(30)]))"
    few = "import json\nprint(json.dumps([{'route': '/r0', 'handler_file': 'x'}]))"
    shrunk = lambda: [m for m in tb.extractor_regressions() if "earlier version" in m]  # noqa: E731
    tb.run_extractor("api", many)
    assert shrunk() == []
    tb.run_extractor("api", few)
    assert shrunk() == ["api now yields 1 entries, an earlier version yielded 30"]
    assert shrunk() == []  # a smaller surface can be right: shown once
    tb.finish_gates = [(lambda t: True, lambda t: "dynamic message")]
    assert tb.finish("x") == "not finished: dynamic message"


def test_coverage_says_when_the_pattern_misses_most_handlers(tmp_path):
    files = {f"c/H{i}.php": f"<?php\nfunction a{i}() {{ $this->request->get('x'); }}\n" for i in range(12)}
    files["c/H0.php"] += "$_GET['y'];\n"
    _write(tmp_path, files)
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    tb.manual = [{"route": f"/h{i}", "handler_file": f"c/H{i}.php", "handler": f"a{i}"} for i in range(12)]
    res = json.loads(tb.check_coverage(r"\$_GET"))
    assert res["handler_files_matched"] == 1 and res["handler_files"] == 12 and "says little" in res["note"]
    res = json.loads(tb.check_coverage(r"request->get"))
    assert res["handler_files_matched"] == 12 and "note" not in res


def test_probe_output_is_not_surface_and_probe_extractors_are_flagged(tmp_path):
    _write(tmp_path, {"r/a.ts": "router.get('/a', h)\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    out = tb.run_probe("import os,sys; print(sorted(os.listdir(os.path.join(sys.argv[1], 'r'))))")
    assert "a.ts" in out and tb.entries() == []
    tb.run_extractor("dbg", "import json; print(json.dumps([{'route': 'files: 3', 'handler_file': 'r/a.ts', "
                            "'handler': 'nope'}, {'route': 'x', 'handler_file': 'r/a.ts', 'handler': 'nope2'}]))")
    assert tb.extractor_regressions() == ["dbg: 2 of 2 entries do not resolve to code (fix it, or "
                                          "drop_extractor if it was a probe)"]
    assert tb.extractor_regressions() == []  # pointed out once
    assert tb.drop_extractor("dbg") == "dropped dbg; total entries now 0"
    assert tb.drop_extractor("dbg").startswith("error")


def test_settle_takes_a_batch():
    tb = Toolbox(AuditConfig(), Path("."), Path("/tmp"))
    tb.reconcile_groups = {"G1": ["E1"], "G2": ["E2"], "G3": ["E3"]}
    out = tb.settle([{"group": "G1", "verdict": "resolver_wrong", "reason": "a:1"},
                     {"group": "G2", "verdict": "maybe"}, {"group": "G7", "verdict": "declared_wrong"}])
    assert out == ("G2: verdict must be one of resolver_wrong, declared_wrong, inconsistent_code; unknown group "
                   "'G7'; decided: 1; undecided: G2, G3")
    assert tb.settle({"group": "G2", "verdict": "declared_wrong", "reason": "b:2"}).endswith("undecided: G3")


def test_one_entry_per_request_and_overlaps_are_pointed_out(tmp_path):
    _write(tmp_path, {"r/a.ts": "function real() {}\n", "w/b.ts": "function other() {}\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    tb.run_extractor("probe", "import json; print(json.dumps([{'route': '/cb', 'method': 'GET', "
                              "'handler_file': 'r/a.ts', 'handler': 'missing'}]))")
    tb.run_extractor("good", "import json; print(json.dumps([{'route': '/cb', 'method': 'GET', "
                             "'handler_file': 'r/a.ts', 'handler': 'real'}, {'route': '/s', 'method': 'GET', "
                             "'handler_file': 'r/a.ts', 'handler': 'real'}]))")
    tb.run_extractor("worker", "import json; print(json.dumps([{'route': '/s', 'method': 'GET', "
                               "'handler_file': 'w/b.ts', 'handler': 'other'}]))")
    es = tb.entries()
    assert sorted((e["route"], e["handler"]) for e in es) == [("/cb", "real"), ("/s", "other"), ("/s", "real")]
    msgs = [m for m in tb.extractor_regressions() if "different handlers" in m]
    assert len(msgs) == 1 and msgs[0].startswith("2 requests are mapped to different handlers")


def test_units_merge_entries_that_share_a_request():
    from app.services.yasa_audit.pipeline import _units

    es = [{"id": "E1", "method": "GET", "route": "/cb", "handler_file": "routes/a.ts", "handler": "h",
           "exposure": "public"},
          {"id": "E2", "method": "GET", "route": "/cb", "handler_file": "controllers/a.ts", "handler": "done",
           "exposure": "public"},
          {"id": "E3", "method": "POST", "route": "/cb/x", "handler_file": "controllers/a.ts", "handler": "done",
           "exposure": "public"},
          {"id": "E4", "method": "GET", "route": "/other", "handler_file": "controllers/b.ts", "handler": "b",
           "exposure": "public"}]
    units = _units(es)
    assert sorted(sorted(e["id"] for e in u["entries"]) for u in units) == [["E1", "E2", "E3"], ["E4"]]


def test_ladder_orders_units_within_a_level_and_is_shown(tmp_path):
    from app.services.yasa_audit.pipeline import _rank_principals, _units
    from app.services.yasa_audit.prompts import access_model_text

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path)
    _write(tmp_path, {"a.js": "x\n"})
    assert tb.record_access_model(authentication="session", authorization="grants", permission_mapping="doc.method",
                                  shared_protections="none", principals="visitor < contributor < editor < owner",
                                  ladder=["Visitor", "Contributor", "Editor", "Super Editor", "Owner"],
                                  evidence=[{"file": "a.js", "line": 1, "quote": "x"}]) \
        .startswith("access model recorded")
    assert "ladder (least to most privileged): Visitor < Contributor < Editor < Super Editor < Owner" in \
        access_model_text(tb.access_model)

    def e(i, route, principals):
        return {"id": i, "method": "GET", "route": route, "handler_file": f"{i}.js", "handler": "h",
                "exposure": "privileged", "resolved": True,
                "who_can_call": {"least_privileged": "privileged", "principals": principals, "rule": "r"}}

    es = [e("E1", "/a/settings", ["Owner"]), e("E2", "/a/tags", ["Super Editor", "Owner"]),
          e("E3", "/a/posts", ["any staff user (Contributor and above)", "Owner"]), e("E4", "/a/x", ["robot"])]
    _rank_principals(es, tb.access_model["ladder"])
    assert [x.get("least_principal") for x in es] == ["Owner", "Super Editor", "Contributor", None]
    assert [u["entries"][0]["id"] for u in _units(es)] == ["E3", "E2", "E1", "E4"]


def test_reconcile_shows_new_groups_after_the_resolver_changes(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    proj = tmp_path / "p"
    _write(proj, {"web/Admin.php": "<?php\nfunction execute() { require_admin(); }\n",
                  "web/Home.php": "<?php\nfunction execute() { echo 1; }\n"})
    extractor = ("import json\nprint(json.dumps([{'route': '/admin', 'handler_file': 'web/Admin.php', "
                 "'handler': 'execute', 'exposure': 'privileged'}, {'route': '/home', 'handler_file': "
                 "'web/Home.php', 'handler': 'execute', 'exposure': 'public'}]))")
    public_all = ("import json,sys; r=json.load(sys.stdin); print(json.dumps([{'least_privileged': 'public', "
                  "'rule': 'no gate'} for _ in r]))")
    admin_all = ("import json,sys; r=json.load(sys.stdin); print(json.dumps([{'least_privileged': 'privileged', "
                 "'rule': 'everything admin'} for _ in r]))")
    seen = []
    scripts = {
        "access": [("record_access_model", {"authentication": "s", "authorization": "a", "permission_mapping": "p",
                                            "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anyone, admin", "evidence": [
                                                {"file": "web/Admin.php", "line": 2, "quote": "require_admin()"}]}),
                   ("write_access_resolver", {"code": public_all, "samples": [{"route": "/a"}, {"route": "/b"},
                                                                              {"route": "/c"}]}),
                   ("finish", {"notes": "x"})],
        "recon": [("run_extractor", {"name": "web", "code": extractor}),
                  ("check_coverage", {"request_read_pattern": "echo"}), ("finish", {"notes": "web"})],
        "reconcile": [("settle", {"decisions": [{"group": "G1", "verdict": "resolver_wrong", "reason": "Admin:2"}]}),
                      ("write_access_resolver", {"code": admin_all, "samples": [{"route": "/admin"},
                                                                               {"route": "/home"}, {"route": "/x"}]}),
                      ("finish", {"notes": "too early"}),  # refused: the new group G2 is undecided
                      ("settle", {"decisions": [{"group": "G2", "verdict": "resolver_wrong", "reason": "Home:2"}]}),
                      ("finish", {"notes": "done"})],
    }

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and len(messages) == 2:
                user = messages[1]["content"]
                key = ("reconcile" if "independently of you" in user else
                       _role(messages[0]["content"]))
                self.script = _script(scripts, key)
            seen.extend(m.get("content") or "" for m in messages if m.get("role") == "tool")
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: Router([]))
    m = pipeline.recon(_cfg(), proj, tmp_path / "out", deadline=time.time() + 900)
    assert any("Settle these too" in t and "- G2: 1 entries, declared public, resolver privileged" in t for t in seen)
    rc = m["reconcile"]
    assert {g: v.get("verdict") for g, v in rc["groups"].items()} == {"G1": "resolver_wrong", "G2": "resolver_wrong"}
    es = {e["route"]: e for e in json.loads((tmp_path / "out" / "entries.json").read_text())}
    assert es["/home"]["exposure"] == "public" and es["/admin"]["exposure"] == "privileged"
    assert rc["applied"] == {"resolver_wrong": 1}  # /home; /admin now agrees with the new resolver


def test_access_model_carries_shared_protections_and_cards_quote_the_registration(tmp_path):
    from app.services.yasa_audit.pipeline import _declared_code
    from app.services.yasa_audit.prompts import access_model_text

    _write(tmp_path, {"routes.js": "const r = express.Router();\nr.get('/posts', auth, posts.browse);\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    tb.record_access_model(authentication="a", authorization="b", permission_mapping="c", principals="d", ladder=["a", "b"],
                           shared_protections="ids validated globally (validators/all.ts:27)",
                           evidence=[{"file": "routes.js", "line": 2, "quote": "r.get('/posts'"}])
    assert "- shared protections: ids validated globally (validators/all.ts:27)" in access_model_text(tb.access_model)
    assert _declared_code(tmp_path, {"declared_at": "routes.js:2"}) == \
        {"declared_code": "r.get('/posts', auth, posts.browse);"}
    assert _declared_code(tmp_path, {"declared_at": "routes.js:9"}) == {}
    assert _declared_code(tmp_path, {"declared_at": "nofile.js:1"}) == {}


def test_evidence_quotes_may_span_a_multi_line_registration_and_long_root_causes_are_cut(tmp_path):
    from app.services.yasa_audit.toolbox import verify_evidence

    _write(tmp_path, {"routes.js": "\n" * 19 + "  // Webmentions\n  router.post(\n    '/receive',\n"
                                    "    bodyParser.urlencoded({ extended: true, limit: '64kb' }),\n"
                                    "    http(api.mentions.receive),\n  );\n  return router;\n"})
    quote = ("router.post(\n    '/receive',\n    bodyParser.urlencoded({ extended: true, limit: '64kb' }),\n"
             "    http(api.mentions.receive),\n  );")
    assert verify_evidence(tmp_path, [{"file": "routes.js", "line": 21, "quote": quote}]) is None
    assert verify_evidence(tmp_path, [{"file": "routes.js", "line": 21, "quote": "router.get("}]) is not None
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out", unit="E1")
    long_rc = "The receiver passes the attacker's URL to the client " + "and more words " * 30
    out = tb.report_finding(vuln_type="SSRF", cwe="CWE-918", sink_file="routes.js", sink_line=22, source="url",
                            entry="POST /receive", required_privilege="public", verdict="likely",
                            impact="server-side request", root_cause=long_rc,
                            route_evidence={"file": "routes.js", "line": 21, "quote": quote})
    assert out == "recorded #1"
    rc = tb.findings[0]["root_cause"]
    assert len(rc) <= 240 and rc.endswith("…") and rc.startswith("The receiver passes")


def test_budget_end_offers_the_tools_a_closed_gate_needs(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent
    from app.services.yasa_audit.toolbox import tool_schemas

    _write(tmp_path, {"Sec.java": "class Sec {\n  boolean allowed() { return true; }\n}\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out", unit="access")
    tb.finish_gates = [(lambda t: t.access_model is None, "record_access_model first", ["record_access_model"])]
    seen_tools, prompts = [], []

    class LLM(ScriptedLLM):
        def chat(self, messages, tools=None):
            seen_tools.append(sorted(t["function"]["name"] for t in tools or []))
            prompts.append(messages[-1].get("content") or "")
            return super().chat(messages, tools)

    model = {"authentication": "a", "authorization": "b", "permission_mapping": "c", "ladder": ["anonymous", "admin"], "shared_protections": "none", "principals": "anon < admin",
             "evidence": [{"file": "Sec.java", "line": 2, "quote": "allowed()"}]}
    llm = LLM([("list_dir", {"path": "."})] * 8 + [("record_access_model", model)])
    res = run_agent(llm, tb, tool_schemas("access"), "sys", "go", 2, tmp_path / "log.jsonl")
    assert any("Still required before you can finish: record_access_model first" in p for p in prompts)
    assert seen_tools[-2] == ["record_access_model"]  # the closed gate's tool only
    assert "Tool budget used up. Before finishing" in prompts[-2]
    assert tb.access_model is not None and res["finished"]  # then the finish-only turn


def test_access_notes_reach_reviewers_when_no_model_was_recorded():
    from app.services.yasa_audit.prompts import access_model_text

    text = access_model_text({"unverified_notes": "ACCESS MODEL: session cookie; canThis(...) in pipeline"})
    assert text.startswith("(the access agent ran out of budget") and "canThis(...)" in text


def test_access_model_requires_ladder_and_shared_protections(tmp_path):
    _write(tmp_path, {"a.js": "x\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    base = {"authentication": "a", "authorization": "b", "permission_mapping": "c", "principals": "d",
            "evidence": [{"file": "a.js", "line": 1, "quote": "x"}]}
    assert tb.record_access_model(**base) == "rejected: missing shared_protections, ladder"
    assert tb.record_access_model(**base, shared_protections="s", ladder="anon < admin") == "rejected: missing ladder"
    assert tb.record_access_model(**base, shared_protections="s", ladder=["anon", "admin"]) \
        .startswith("access model recorded")



def test_refutation_check_moves_refuted_findings_out_and_marks_the_rest(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline
    from app.services.yasa_audit.runner import to_deepaudit_findings
    from app.services.yasa_audit.verify import verify

    _write(tmp_path, {"api/posts.js": "function destroy(id) {\n  if (!isOwner(id)) throw new Forbidden();\n"
                                      "  db.delete(id);\n}\n"})
    review = tmp_path / "out" / "review"
    review.mkdir(parents=True)
    base = {"vuln_type": "IDOR", "cwe": "CWE-639", "sink_file": "api/posts.js", "sink_line": 3, "source": "id",
            "required_privilege": "authenticated", "verdict": "likely", "impact": "deletes others' posts"}
    findings = [dict(base, entry="DELETE /posts/:id", issue="I1", root_cause="no owner check"),
                dict(base, entry="DELETE /posts", issue="I1", root_cause="no owner check"),
                dict(base, entry="GET /x", issue="I2", root_cause="other", required_privilege="public"),
                dict(base, entry="GET /y", issue="I3", root_cause="third")]
    (review / "findings.json").write_text(json.dumps({"findings": findings, "not_reviewed": []}))
    seen = []
    plan = {"I1": ("conclude", {"verdict": "refuted", "reason": "destroy checks ownership first",
                                "path": [{"stage": "permission", "file": "api/posts.js", "line": 2,
                                          "quote": "if (!isOwner(id))", "effect": "stops"}]}),
            "I2": ("conclude", {"verdict": "upheld", "reason": "nothing stops it"}),  # refused: no evidence
            "I3": ("conclude", {"verdict": "uncertain", "reason": "did not reach the model"})}

    class Checker(ScriptedLLM):
        def chat(self, messages, tools=None):
            if not self.script and len(messages) == 2:
                iid = messages[1]["content"].split()[2]
                seen.append(iid)
                self.script = [plan[iid]]
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: Checker([]))
    m = verify(_cfg(workers=1), tmp_path, review, deadline=time.time() + 300)
    assert seen == ["I2", "I1", "I3"]  # public first, then the most repeated
    assert m["verdicts"] == {"uncertain": 2, "refuted": 1} and m["findings_refuted"] == 2
    data = json.loads((review / "findings.json").read_text())
    assert [f["entry"] for f in data["refuted"]] == ["DELETE /posts/:id", "DELETE /posts"]
    assert data["refuted"][0]["verification"]["path"][0]["quote"] == "if (!isOwner(id))"
    assert {f["issue"]: f["verification"]["verdict"] for f in data["findings"]} == {"I2": "uncertain",
                                                                                  "I3": "uncertain"}
    out = to_deepaudit_findings(data["findings"])
    assert "NOT verified by the refutation check" in out[0]["description"] and out[0]["confidence"] < 0.6



def test_conclude_requires_the_stages_it_claims(tmp_path):
    _write(tmp_path, {"a.js": "validate(body)\ncan(user, 'edit')\ndb.update(body)\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")

    def st(stage, line, quote, effect="passes"):
        return {"stage": stage, "file": "a.js", "line": line, "quote": quote, "effect": effect}

    assert tb.conclude("upheld", "x", [st("operation", 3, "db.update(body)")]).startswith(
        "rejected: upheld needs the code of each stage the request passes, quoted: missing input_validation, "
        "permission")
    assert tb.conclude("upheld", "x", [st("permission", 2, "can(user, 'edit')", "stops")]).startswith(
        "rejected: a stage you quoted stops")
    assert tb.conclude("refuted", "x", [st("permission", 2, "can(user, 'edit')")]).startswith(
        "rejected: refuted needs the stage")
    assert tb.conclude("upheld", "x", [st("input_validation", 1, "validate(body)"), st("permission", 2, "nope"),
                                       st("operation", 3, "db.update(body)")]).startswith("rejected: path: quote")
    assert tb.conclude("upheld", "x", [st("input_validation", 1, "validate(body)"),
                                       st("permission", 2, "can(user, 'edit')"),
                                       st("operation", 3, "db.update(body)")]) == "concluded: upheld"


def test_a_reply_cut_by_the_output_limit_is_named(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent
    from app.services.yasa_audit.toolbox import tool_schemas

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    prompts = []

    class Cut(ScriptedLLM):
        cfg = AuditConfig()
        last_finish_reason = None

        def chat(self, messages, tools=None):
            prompts.append(messages[-1].get("content") or "")
            if self.usage.calls == 0:
                self.usage.calls += 1
                self.last_finish_reason = "length"
                return SimpleNamespace(content="", tool_calls=None)
            self.last_finish_reason = "tool_calls"
            return super().chat(messages, tools)

    run_agent(Cut([]), tb, tool_schemas("review"), "sys", "go", 5, tmp_path / "log.jsonl")
    assert "cut off by the output limit" in prompts[1] and "parses the registration code" in prompts[1]


def test_recon_follows_up_on_dispatchers_left_unenumerated(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline

    proj = tmp_path / "p"
    _write(proj, {"web/Home.php": "<?php\nfunction home() { echo $_GET['q']; }\n",
                  "api/Users.php": "<?php\nfunction users() { echo $_GET['id']; }\n",
                  "hook/Push.php": "<?php\nfunction push() { echo $_POST['ref']; }\n"})
    web = ("import json\nprint(json.dumps([{'route': '/home', 'handler_file': 'web/Home.php', 'handler': 'home', "
           "'exposure': 'public'}]))")
    api = ("import json\nprint(json.dumps([{'route': '/api/users', 'handler_file': 'api/Users.php', "
           "'handler': 'users', 'exposure': 'public'}]))")
    hook = ("import json\nprint(json.dumps([{'route': '/hook/push', 'handler_file': 'hook/Push.php', "
            "'handler': 'push', 'exposure': 'public'}]))")
    users = []
    scripts = {
        "access": [("record_access_model", {"authentication": "none", "authorization": "none",
                                            "permission_mapping": "none", "principals": "anyone",
                                            "ladder": ["anyone"], "shared_protections": "none",
                                            "evidence": [{"file": "web/Home.php", "line": 2,
                                                          "quote": "function home()"}]}),
                   ("finish", {"notes": "open"})],
        "recon": [("run_extractor", {"name": "web", "code": web}),
                  ("check_coverage", {"request_read_pattern": r"\$_GET"}),
                  ("finish", {"notes": "web pages and a JSON API", "unenumerated": ["API: api/*.php functions", "hooks: hook/*.php"]})],
        "API": [("run_extractor", {"name": "api", "code": api}),
                ("finish", {"notes": "the JSON API is enumerated"})],
        "hooks": [("run_extractor", {"name": "web", "code": hook}),  # a taken name: kept apart on merge
                  ("finish", {"notes": "hooks enumerated"})],
    }

    class Router(ScriptedLLM):
        def chat(self, messages, tools=None):
            # first call: a reminder (the access model is ready) may already follow the user message
            if not self.script and not self.usage.calls:
                user = messages[1]["content"]
                users.append(user)
                key = (("API" if "- API:" in user else "hooks") if "ONE dispatcher they left out" in user else
                       _role(messages[0]["content"]))
                self.script = _script(scripts, key)
            return super().chat(messages, tools)

    monkeypatch.setattr(pipeline, "LLM", lambda cfg: Router([]))
    now = time.time()
    m = pipeline.recon(_cfg(), proj, tmp_path / "out", deadline=now + 900, hard_deadline=now + 1800)
    follow = [u for u in users if "ONE dispatcher they left out" in u]
    assert len(follow) == 2 and all("extractors web" in u for u in follow)  # one fresh agent per dispatcher
    assert any("- API: api/*.php functions" in u for u in follow)
    assert m["entries"] == 3 and m["passes"] == 2
    assert "JSON API is enumerated" in m["notes"] and "hooks enumerated" in m["notes"]
    assert set(m["extractors"]) == {"web", "api", "web-f1"}


def test_extractor_nudge_fires_on_time_as_well_as_steps(tmp_path):
    from app.services.yasa_audit import pipeline
    from app.services.yasa_audit.toolbox import Toolbox

    tb = Toolbox(_cfg(), tmp_path, tmp_path)
    now = time.time()
    assert not pipeline._past_half(now, now + 600, 60)(3, tb)  # early, few steps
    assert pipeline._past_half(now - 400, now + 200, 60)(3, tb)  # past half of the time window
    assert pipeline._past_half(now, now + 600, 60)(30, tb)  # half of the steps
    tb.extractors["x"] = {"entries": [], "run": 1}
    assert not pipeline._past_half(now - 400, now + 200, 60)(30, tb)  # an extractor ran: no nudge


def test_limiter_cuts_once_per_burst_and_recovers():
    from app.services.yasa_audit.llm import AdaptiveLimiter

    lim = AdaptiveLimiter(16)
    for _ in range(5):  # five requests rejected together: one cut, not four
        lim.acquire()
    for _ in range(5):
        lim.release(rate_limited=True)
    assert lim.limit == 8
    for _ in range(8):  # a low cap grows after as many successes as the cap
        lim.acquire()
        lim.release()
    assert lim.limit == 9


def test_access_model_records_designed_powers_and_shows_them(tmp_path):
    from app.services.yasa_audit.prompts import access_model_text

    _write(tmp_path, {"docs/scopes.md": "crons: may edit and run scheduled commands\nenvs: task data only\n"})
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    base = {"authentication": "token", "authorization": "scopes", "permission_mapping": "ns -> scope",
            "principals": "apps", "shared_protections": "joi", "ladder": ["anonymous", "app", "admin"],
            "evidence": [{"file": "docs/scopes.md", "line": 1, "quote": "crons: may edit"}]}
    assert "without powers" in tb.record_access_model(**base)
    assert tb.record_access_model(**base, powers=[{"principal": "app:crons"}]) == \
        "rejected: powers: each row needs principal and power"
    assert "quote not found" in tb.record_access_model(**base, powers=[
        {"principal": "app:envs", "power": "data", "evidence": {"file": "docs/scopes.md", "line": 2, "quote": "runs"}}])
    assert tb.record_access_model(**base, powers=[
        {"principal": "app:crons", "power": "edits and runs scheduled commands (code execution by design)",
         "evidence": {"file": "docs/scopes.md", "line": 1, "quote": "crons: may edit and run"}},
        {"principal": "app:envs", "power": "writes task data; must not control the task runner",
         "evidence": {"file": "docs/scopes.md", "line": 2, "quote": "envs: task data only"}},
        {"principal": "team_admin", "power": "manages one team", "held_for_one_object": True}]) == \
        "access model recorded"
    assert tb.access_model["scoped_roles"] == ["team_admin"]
    text = access_model_text(tb.access_model)
    assert "designed powers" in text and "app:envs: writes task data; must not control the task runner" in text
    assert "team_admin (held for one object" in text and "docs/scopes.md:1" in text


def test_a_designed_capability_leaves_the_report_as_by_design(tmp_path, monkeypatch):
    from app.services.yasa_audit import pipeline
    from app.services.yasa_audit.verify import verify

    _write(tmp_path, {"api/crons.js": "function create(cmd) {\n  exec(cmd);\n}\n",
                      "docs/scopes.md": "crons: may edit and run scheduled commands\n"})
    review = tmp_path / "out" / "review"
    review.mkdir(parents=True)
    f = {"vuln_type": "RCE", "cwe": "CWE-78", "sink_file": "api/crons.js", "sink_line": 2, "source": "cmd",
         "required_privilege": "authenticated", "verdict": "confirmed", "impact": "an app runs commands",
         "entry": "POST /open/crons", "issue": "I1", "root_cause": "commands run as given"}
    (review / "findings.json").write_text(json.dumps({"findings": [f], "not_reviewed": []}))
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "x")
    assert tb.conclude("by_design", "crons runs commands").startswith("rejected: by_design needs power")
    grant = {"principal": "app:crons", "file": "docs/scopes.md", "line": 1, "quote": "may edit and run"}
    monkeypatch.setattr(pipeline, "LLM", lambda cfg: ScriptedLLM([
        ("conclude", {"verdict": "by_design", "reason": "the crons scope is meant to run commands", "power": grant})]))
    m = verify(_cfg(workers=1), tmp_path, review, deadline=time.time() + 300)
    assert m["verdicts"] == {"by_design": 1} and m["findings_by_design"] == 1 and m["findings_kept"] == 0
    data = json.loads((review / "findings.json").read_text())
    assert data["findings"] == [] and data["by_design"][0]["verification"]["power"]["principal"] == "app:crons"


def test_an_empty_reply_cut_by_the_output_limit_is_asked_again_with_a_wider_allowance():
    from app.services.yasa_audit.llm import LLM

    cfg = AuditConfig(llm_base_url="http://localhost:1/v1", llm_api_key="k", llm_model="m", llm_max_tokens=1000,
                      llm_max_tokens_ceiling=3000)
    llm = LLM(cfg)
    asked = []

    def create(**kw):
        asked.append(kw["max_tokens"])
        empty = len(asked) < 3
        msg = SimpleNamespace(content="" if empty else "ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="length" if empty else "stop")],
                               usage=None)

    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert llm.chat([{"role": "user", "content": "x"}]).content == "ok"
    assert asked == [1000, 2000, 3000] and llm.usage.widened == 2
    asked.clear()
    llm.cfg.llm_max_tokens_ceiling = 1000  # nothing wider to try: the empty reply goes back to the loop
    assert llm.chat([{"role": "user", "content": "x"}]).content == "" and asked == [1000]


def test_a_unit_whose_model_keeps_replying_with_nothing_is_counted(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent
    from app.services.yasa_audit.toolbox import tool_schemas

    class Silent(ScriptedLLM):
        cfg = AuditConfig()
        last_finish_reason = "length"

        def chat(self, messages, tools=None):
            self.usage.calls += 1
            return SimpleNamespace(content="", tool_calls=None)

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path / "out")
    res = run_agent(Silent([]), tb, tool_schemas("review"), "sys", "go", 5, tmp_path / "log.jsonl")
    assert res["ended_silent"] and not res["finished"]
    rows = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text().splitlines()]
    assert rows[0]["finish_reason"] == "length"

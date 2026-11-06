"""Unit tests for app.services.yasa_audit (no LLM, no YASA binary needed)."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.services.yasa_audit.config import AuditConfig
from app.services.yasa_audit.jsp2java import class_name, convert
from app.services.yasa_audit.pipeline import detect_lang, is_constant_call
from app.services.yasa_audit.toolbox import Toolbox, parse_sarif, tool_schemas

BENCH = Path(__file__).resolve().parents[1] / "benchmarks" / "yasa_audit" / "eval.py"


@pytest.mark.parametrize(
    "code,pat,expected",
    [
        ("res.sendFile(path.resolve('frontend/dist/frontend/index.html'))", r"res\.sendFile\(", True),
        ("res.sendFile(path.resolve('ftp/', file))", r"res\.sendFile\(", False),
        ("const answer = eval(expression).toString()", r"\beval\s*\(", False),
        ("yaml.load(fs.readFileSync('./swagger.yml', 'utf8'))", r"yaml\.load\(", True),
        ('<td><%=resultSet.getString("name") %></td>', r"<%=", False),
        ("st.executeUpdate(sql);", r"\.execute(Query|Update)?\s*\(", False),
        ('st.executeQuery("select count(*) from doc_info");', r"\.execute(Query|Update)?\s*\(", True),
        ("models.sequelize.query(`SELECT * FROM U WHERE e = '${req.body.email}'`)",
         r"sequelize\.query\(", False),
    ],
)
def test_constant_call_prefilter(code, pat, expected):
    assert is_constant_call(code, pat) is expected


def test_jsp2java_preserves_lines():
    jsp = (
        '<%@ page import="java.sql.*" %>\n'
        "<html>\n"
        "<%\n"
        'String name=request.getParameter("uname");\n'
        "%>\n"
        "<p><%= name %></p>\n"
    )
    java = convert(jsp, class_name("del-ptnt"))
    lines = java.splitlines()
    assert "public class Jsp_del_ptnt extends HttpServlet" in lines[0]
    assert "import java.sql.*;" in lines[0]
    assert 'request.getParameter("uname")' in lines[3]  # JSP line 4 == Java line 4
    assert "out.print(name);" in lines[5]  # JSP line 6 == Java line 6


def _sarif(uri_hops, sink_uri, line):
    hops = [{"location": {"physicalLocation": {"artifactLocation": {"uri": u},
             "region": {"startLine": ln, "snippet": {"text": f"x\n  {ln}:  {tag}:  code",
                                                     "affectedNodeName": n}}}}}
            for u, ln, tag, n in uri_hops]
    return {"message": {"text": "t"}, "entrypoint": {"filePath": "/a", "functionName": "f"},
            "sinkInfo": {"sinkAttribute": ["Sql"]},
            "codeFlows": [{"threadFlows": [{"locations": hops}]}],
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": sink_uri},
                                                "region": {"startLine": line}}}]}


def test_parse_sarif_groups_by_sink_and_maps_jsp():
    jsp_map = {"jsp/Jsp_success.java": "WebContent/success.jsp"}

    def norm(u):
        u = u.replace("file://", "").replace("/tmp/src/", "").lstrip("/")
        return jsp_map.get(u, u)

    data = {"runs": [{"results": [
        _sarif([("file:///jsp/Jsp_success.java", 13, "SOURCE", "getParameter(pwd)"),
                ("file:///jsp/Jsp_success.java", 25, "SINK", "st.executeUpdate")],
               "/tmp/src/jsp/Jsp_success.java", 25),
        _sarif([("file:///jsp/Jsp_success.java", 14, "SOURCE", "getParameter(country)")],
               "/tmp/src/jsp/Jsp_success.java", 25),
    ]}]}
    by_sink = parse_sarif(data, norm)
    assert list(by_sink) == ["WebContent/success.jsp:25"]
    item = by_sink["WebContent/success.jsp:25"]
    assert len(item["sources"]) == 2
    assert item["trace"][0].startswith("WebContent/success.jsp:13 SOURCE")


def test_toolbox_confines_paths(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "a.ts").write_text("x\ny\n")
    (tmp_path / "proj_evil").mkdir()
    (tmp_path / "proj_evil" / "secret.txt").write_text("s")
    tb = Toolbox(AuditConfig(), tmp_path / "proj", tmp_path / "out", enable_yasa=False)
    assert "a.ts lines 1-2" in tb.read_file("a.ts")
    with pytest.raises(ValueError):
        tb.read_file("../proj_evil/secret.txt")  # sibling dir with the same prefix
    (tmp_path / "proj" / "link").symlink_to(tmp_path / "proj_evil")
    with pytest.raises(ValueError):
        tb.read_file("link/secret.txt")


def test_report_finding_requires_engine_ref_when_yasa_enabled(tmp_path):
    tb = Toolbox(AuditConfig(), tmp_path, tmp_path, enable_yasa=True)
    tb.registry["R1-F1"] = {"sink": "a.ts:3"}
    assert tb.report_finding(verdict="confirmed", yasa_ref="R9-F9", sink_file="a.ts").startswith("rejected")
    assert tb.report_finding(verdict="confirmed", yasa_ref="R1-F1", sink_file="a.ts") == "recorded #1"
    assert tb.report_finding(verdict="false_positive", sink_file="b.ts") == "recorded #2"


def test_tool_schemas_stage_specific():
    names = {t["function"]["name"] for t in tool_schemas(enable_yasa=True, with_report=False)}
    assert "yasa_run" in names and "report_finding" not in names
    names = {t["function"]["name"] for t in tool_schemas(enable_yasa=False)}
    assert "yasa_run" not in names and "report_finding" in names


def test_detect_lang(tmp_path):
    (tmp_path / "a.jsp").write_text("")
    (tmp_path / "B.java").write_text("")
    (tmp_path / "x.ts").write_text("")
    assert detect_lang(tmp_path) == "java"


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
    assert r["unmatched"] == []  # vulnCodeFixes is ambiguous, not counted
    assert json.dumps(r)


EXPRESS_BOOT = """import express from 'express'
import * as security from './lib/insecurity'
import { retrieveBasket } from './routes/basket'
import dataErasure from './routes/dataErasure'
import * as address from './routes/address'
const app = express()
app.use(security.updateAuthenticatedUsers())
app.use('/rest/basket', security.isAuthorized(), security.appendUserId())
app.use('/ftp', serveIndex('ftp', { icons: true }))
app.get('/rest/basket/:id', utils.asyncHandler(retrieveBasket()))
app.get('/api/Addresss/:id', security.appendUserId(), utils.asyncHandler(address.getAddressById()))
app.use('/dataerasure', dataErasure)
"""


def test_express_entries_effective_guards(tmp_path):
    from app.services.yasa_audit.entrypoints import express_entries

    (tmp_path / "server.ts").write_text(EXPRESS_BOOT)
    routes = {r["route"]: r for r in express_entries(tmp_path)}
    assert set(routes) == {"/ftp", "/rest/basket/:id", "/api/Addresss/:id", "/dataerasure"}
    basket = routes["/rest/basket/:id"]
    assert basket["file"] == "routes/basket.ts"
    assert basket["guards"] == ["security.updateAuthenticatedUsers", "security.isAuthorized",
                                "security.appendUserId"]  # inherited from the /rest/basket prefix
    assert routes["/api/Addresss/:id"]["guards"] == ["security.updateAuthenticatedUsers",
                                                     "security.appendUserId"]
    assert routes["/dataerasure"]["file"] == "routes/dataErasure.ts"  # bare identifier handler
    assert routes["/ftp"]["file"] == "server.ts" and "directory listing" in routes["/ftp"]["handler"]


def test_java_entries(tmp_path):
    from app.services.yasa_audit.entrypoints import java_entries

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Login.java").write_text('@WebServlet(urlPatterns="/Plogin")\nclass Login {}\n')
    (tmp_path / "WebContent").mkdir()
    (tmp_path / "WebContent" / "delptnt.jsp").write_text("<% %>")
    got = {(e["route"], e["file"]) for e in java_entries(tmp_path)}
    assert got == {("/Plogin", "src/Login.java"), ("/delptnt.jsp", "WebContent/delptnt.jsp")}


def test_schedule_respects_deadline_and_order():
    import time as _t

    from app.services.yasa_audit.pipeline import MIN_UNIT_S, _schedule

    seen = []
    results, skipped = _schedule(["a", "b", "c"], lambda i, u: seen.append(u) or {"findings": [u]},
                                 workers=1, deadline=None)
    assert seen == ["a", "b", "c"] and skipped == []
    results, skipped = _schedule(["a", "b"], lambda i, u: {"findings": [u]}, workers=2,
                                 deadline=_t.time() + MIN_UNIT_S / 2)
    assert results == [] and sorted(skipped) == ["a", "b"]


def test_candidate_rank_prefers_engine_then_severe_classes():
    from app.services.yasa_audit.pipeline import _cand_rank

    assert _cand_rank({"origin": "engine:R1-F1"}) == 0
    assert _cand_rank({"origin": "residual:a.ts:1", "suspected_classes": ["CWE-89"]}) == 1
    assert _cand_rank({"origin": "residual:a.ts:2", "suspected_classes": ["CWE-79"]}) == 3


def test_agent_loop_stops_after_deadline(tmp_path):
    import time as _t
    from types import SimpleNamespace

    from app.services.yasa_audit.agent_loop import run_agent

    class FakeLLM:
        def chat(self, messages, tools=None):
            call = SimpleNamespace(id="c1", function=SimpleNamespace(name="grep", arguments='{"pattern": "x"}'))
            return SimpleNamespace(content="", tool_calls=[call])

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path, enable_yasa=False)
    res = run_agent(FakeLLM(), tb, tool_schemas(enable_yasa=False), "sys", "user", budget=50,
                    log_path=tmp_path / "t.jsonl", deadline=_t.time() - 120)
    assert res["timed_out"] and res["steps"] == 0


SPRING_CTRL = """package x;
@Slf4j
@RestController
@RequestMapping("/user")
public class UserInfoController {

    /**
     * list users
     */
    @GetMapping("/list")
    public ResultDTO<List<User>> list(@RequestParam(required = false) String name) {
        return null;
    }

    @PostMapping("/query")
    @ApiPermission(name = "User-Query", requiredPermission = Permission.SU)
    public ResultDTO<List<User>> query(@RequestBody Query q) {
        return null;
    }
}
"""

SPRING_CFG = """public class WebConfig implements WebMvcConfigurer {
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authInterceptor)
                .addPathPatterns("/**")
                .excludePathPatterns("/css/**");
    }
}
"""


def test_spring_entries_and_global_guards(tmp_path):
    from app.services.yasa_audit.entrypoints import java_global_guards, spring_entries

    (tmp_path / "UserInfoController.java").write_text(SPRING_CTRL)
    (tmp_path / "WebConfig.java").write_text(SPRING_CFG)
    routes = {e["route"]: e for e in spring_entries(tmp_path)}
    assert set(routes) == {"/user/list", "/user/query"}
    assert routes["/user/list"]["guards"] == [] and routes["/user/list"]["handler"] == "list"
    assert routes["/user/query"]["guards"][0].startswith("@ApiPermission")
    assert routes["/user/query"]["method"] == "POST"
    guards = java_global_guards(tmp_path)
    assert len(guards) == 1 and 'addPathPatterns("/**")' in guards[0]


def test_agent_loop_sends_reminder_once(tmp_path):
    from types import SimpleNamespace

    from app.services.yasa_audit.agent_loop import run_agent

    seen_msgs = []

    class FakeLLM:
        def chat(self, messages, tools=None):
            seen_msgs.append([m["content"] for m in messages if m["role"] == "user"])
            call = SimpleNamespace(id="c", function=SimpleNamespace(name="grep", arguments='{"pattern": "x"}'))
            return SimpleNamespace(content="", tool_calls=[call])

    tb = Toolbox(AuditConfig(), tmp_path, tmp_path, enable_yasa=False)
    run_agent(FakeLLM(), tb, tool_schemas(enable_yasa=False), "sys", "user", budget=6,
              log_path=tmp_path / "t.jsonl", reminders=[(lambda steps, t: steps >= 2, "RUN THE ENGINE")])
    assert sum(m.count("RUN THE ENGINE") for m in seen_msgs[-1:]) == 1
    assert not any("RUN THE ENGINE" in m for m in seen_msgs[1])  # not before step 2


# ---------------------------------------------------------------- DeepAudit task integration


def test_to_deepaudit_findings_maps_and_filters():
    from app.services.yasa_audit.runner import to_deepaudit_findings

    raw = [
        {"vuln_type": "SQL injection", "cwe": "CWE-89", "sink_file": "a/Dao.java", "sink_line": 12,
         "source": "req.getParameter(id)", "hops": ["A:1", "B:2"], "verdict": "confirmed",
         "yasa_ref": "R1-F0"},
        {"cwe": "CWE-89", "sink_file": "a/Dao.java", "sink_line": 12, "verdict": "likely"},  # dup
        {"cwe": "CWE-22", "sink_file": "b.ts", "sink_line": "7", "verdict": "likely"},
        {"cwe": "CWE-78", "sink_file": "c.ts", "sink_line": 3, "verdict": "false_positive"},
        {"cwe": "CWE-9999", "sink_file": "d.ts", "sink_line": None, "verdict": "confirmed"},
    ]
    out = to_deepaudit_findings(raw, "dataflow")
    assert [f["file_path"] for f in out] == ["a/Dao.java", "b.ts", "d.ts"]
    sqli, trav, other = out
    assert sqli["vulnerability_type"] == "sql_injection" and sqli["severity"] == "high"
    assert "R1-F0" in sqli["description"] and "1. A:1" in sqli["description"]
    assert "verdict" not in sqli and "is_verified" not in sqli  # triage verdict is not verification
    assert trav["severity"] == "medium" and trav["line_start"] == 7  # likely -> one level lower
    assert other["vulnerability_type"] == "other" and other["line_start"] is None


def test_split_workers_and_stop_flag():
    from app.services.yasa_audit.runner import split_workers

    cfg = AuditConfig(workers=6, should_stop=lambda: True)
    df, az = split_workers(cfg)
    assert (df.workers, az.workers) == (4, 2) and df.stopped() and az.stopped()
    assert not AuditConfig().stopped()


def test_agent_loop_stops_when_cancelled(tmp_path):
    from app.services.yasa_audit.agent_loop import run_agent

    class FakeLLM:
        def chat(self, messages, tools=None):  # pragma: no cover - must not be called
            raise AssertionError("LLM called after cancel")

    tb = Toolbox(AuditConfig(should_stop=lambda: True), tmp_path, tmp_path, enable_yasa=False)
    res = run_agent(FakeLLM(), tb, tool_schemas(enable_yasa=False), "s", "u", budget=5,
                    log_path=tmp_path / "t.jsonl")
    assert res["steps"] == 0 and not res["finished"]


def test_schedule_skips_when_stopped():
    from app.services.yasa_audit.pipeline import _schedule

    results, skipped = _schedule([1, 2, 3], lambda i, u: {"u": u}, 2, None, stop=lambda: True)
    assert results == [] and skipped == [1, 2, 3]


def test_audit_scope_with_mode():
    from app.api.v1.endpoints.agent_tasks import AgentTaskCreate, _audit_scope_with_mode

    assert _audit_scope_with_mode(None, "agent") is None
    assert _audit_scope_with_mode({"product": "x"}, "yasa") == {"product": "x", "mode": "yasa"}
    assert AgentTaskCreate(project_id="p").audit_mode == "agent"
    with pytest.raises(ValueError):
        AgentTaskCreate(project_id="p", audit_mode="nope")


async def test_execute_yasa_task_saves_findings(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from app.services.yasa_audit import task as ytask

    monkeypatch.setattr(ytask, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(ytask, "check_tools", lambda cfg: [])
    monkeypatch.setattr(ytask, "init_navigation", lambda cfg, root, timeout: None)
    seen = {}

    def fake_df(cfg, root, out, deploy, start, deadline):
        seen["df_workers"], seen["budget"] = cfg.workers, round(deadline - start)
        return {"build": {"yasa_runs": 1}, "triage": {"engine_candidates": 2, "units": 3},
                "findings": [{"cwe": "CWE-89", "sink_file": "A.java", "sink_line": 5,
                              "verdict": "confirmed"}], "not_reviewed": [], "tokens": 100}

    def fake_az(cfg, root, out, deploy, product, deadline):
        seen["product"] = product
        return {"authz": {"entries": 4}, "findings": [
            {"cwe": "CWE-862", "sink_file": "B.java", "sink_line": 9, "verdict": "likely"}],
            "not_reviewed": ["C.java"], "tokens": 50}

    monkeypatch.setattr(ytask, "run_dataflow", fake_df)
    monkeypatch.setattr(ytask, "run_authz", fake_az)

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
    assert seen == {"df_workers": 4, "budget": 1200, "product": "public: /login"}
    assert [f["file_path"] for f in saved["findings"]] == ["A.java", "B.java"]
    assert t.findings_count == 2 and t.tokens_used == 150 and t.status == "completed"
    assert (t.high_count, t.medium_count) == (1, 1) and t.security_score == 42.0
    assert "emit_task_complete" in events and "emit_warning" in events  # C.java not reviewed


def test_count_sources_skips_vendor_dirs(tmp_path):
    from app.services.yasa_audit.task import count_sources

    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    for p in ("src/A.java", "src/b.jsp", "src/c.ts", "src/readme.md", "node_modules/x/i.js"):
        (tmp_path / p).write_text("")
    assert count_sources(tmp_path) == 3

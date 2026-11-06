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
    assert r["recall"] == "1/17"
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

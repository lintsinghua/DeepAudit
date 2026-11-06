"""Server-side templates must be scanned and indexed (JSP/ASP.NET/ERB/EJS/... hold request handling)."""

import pytest

from app.core.file_types import SERVER_TEMPLATE_EXTENSIONS
from app.services.rag import indexer
from app.services.rag.splitter import CodeSplitter
from app.services.scanner import is_text_file


@pytest.mark.parametrize("name", ["WebContent/delptnt.jsp", "Views/Home/Index.cshtml",
                                  "views/profile.ejs", "templates/page.twig", "app/views/show.erb"])
def test_scanner_accepts_server_templates(name):
    assert is_text_file(name)


def test_indexer_and_endpoint_lists_include_templates():
    from app.api.v1.endpoints import scan

    for ext in SERVER_TEMPLATE_EXTENSIONS:
        assert ext in indexer.TEXT_EXTENSIONS
        assert ext in scan.TEXT_EXTENSIONS


def test_splitter_chunks_jsp_as_text():
    jsp = "\n".join(
        ["<%@ page import=\"java.sql.*\" %>", "<%", "String name=request.getParameter(\"uname\");",
         "String sql = \"delete from patients_info where name=\"+name;", "st.executeUpdate(sql);", "%>"]
        + ["<p>row</p>"] * 40
    )
    chunks = CodeSplitter().split_file(jsp, "WebContent/delptnt.jsp")
    assert chunks
    assert any("executeUpdate" in c.content for c in chunks)
    assert chunks[0].line_start == 1

"""
Tests for ReportGenerator._escape_html and _process_issues
"""

import html
from html.parser import HTMLParser
from unittest.mock import patch
import pytest

from app.services.report_generator import ReportGenerator


def test_task_pdf_renders_untrusted_values_as_text_and_only_fetches_its_logo():
    from weasyprint import HTML

    class ReportText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.text = []

        def handle_data(self, data):
            self.text.append(data)

    project, branch, issue = "R&D <project>", "feature/<branch>", "A < B & C"
    with patch("app.services.report_generator.HTML", wraps=HTML) as render:
        pdf = ReportGenerator.generate_task_report(
            {"branch_name": branch}, [{"title": issue}], project
        )
    assert pdf.startswith(b"%PDF-")
    args = render.call_args.kwargs
    parser = ReportText()
    parser.feed(args["string"])
    assert f"项目: {project} | 分支: {branch}" in parser.text
    assert f"1. {issue}" in parser.text
    for url in ("file:///example.png", "https://example.invalid/logo.png"):
        with pytest.raises(ValueError):
            args["url_fetcher"](url)


class TestEscapeHtml:
    """Tests for ReportGenerator._escape_html"""

    def test_escape_html_with_none_returns_none(self):
        assert ReportGenerator._escape_html(None) is None

    def test_escape_html_escapes_special_characters(self):
        result = ReportGenerator._escape_html("<script>alert('xss')</script> & \"quoted\"")
        assert result == html.escape("<script>alert('xss')</script> & \"quoted\"")
        # Verify key characters are escaped
        assert "&lt;" in result
        assert "&gt;" in result
        assert "&amp;" in result

    def test_escape_html_with_normal_text(self):
        text = "Hello world, no special chars here."
        assert ReportGenerator._escape_html(text) == text


class TestProcessIssues:
    """Tests for ReportGenerator._process_issues"""

    def test_sorts_by_severity_critical_first(self):
        issues = [
            {"title": "Low issue", "severity": "low"},
            {"title": "Critical issue", "severity": "critical"},
            {"title": "High issue", "severity": "high"},
            {"title": "Medium issue", "severity": "medium"},
        ]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["severity"] == "critical"
        assert result[1]["severity"] == "high"
        assert result[2]["severity"] == "medium"
        assert result[3]["severity"] == "low"

    def test_maps_severity_labels(self):
        issues = [
            {"title": "A", "severity": "critical"},
            {"title": "B", "severity": "high"},
            {"title": "C", "severity": "medium"},
            {"title": "D", "severity": "low"},
        ]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["severity_label"] == "CRITICAL"
        assert result[1]["severity_label"] == "HIGH"
        assert result[2]["severity_label"] == "MEDIUM"
        assert result[3]["severity_label"] == "LOW"

    def test_normalizes_line_number_to_line(self):
        issues = [{"title": "T", "severity": "low", "line_number": 42}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["line"] == 42

    def test_normalizes_code_field_to_code_snippet(self):
        issues = [{"title": "T", "severity": "low", "code": "print('hello')"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["code_snippet"] == "print(&#x27;hello&#x27;)"

    def test_normalizes_context_field_to_code_snippet(self):
        issues = [{"title": "T", "severity": "low", "context": "eval(user_input)"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["code_snippet"] == "eval(user_input)"

    def test_handles_list_code(self):
        issues = [{"title": "T", "severity": "low", "code": ["line1", "line2", "line3"]}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["code_snippet"] == "line1\nline2\nline3"

    def test_escapes_html_in_description(self):
        issues = [{"title": "T", "severity": "low", "description": "<b>bold</b> & stuff"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["description"] == html.escape("<b>bold</b> & stuff")

    def test_handles_none_description_uses_title(self):
        issues = [{"title": "My Title", "severity": "low", "description": None}]
        result = ReportGenerator._process_issues(issues)
        # When description is None, it falls back to title
        # The title is also escaped, so description gets the title value
        assert result[0]["description"] == html.escape("My Title")

    def test_handles_none_string_description_uses_title(self):
        issues = [{"title": "Fallback Title", "severity": "low", "description": "None"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["description"] == html.escape("Fallback Title")

    def test_handles_none_and_none_string_suggestion(self):
        issues = [
            {"title": "T", "severity": "low", "suggestion": None},
            {"title": "T2", "severity": "low", "suggestion": "None"},
        ]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["suggestion"] is None
        assert result[1]["suggestion"] is None

    def test_escapes_html_in_title_and_file_path(self):
        issues = [{"title": "<script>alert(1)</script>", "severity": "low", "file_path": "/path/<to>/file.py"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["title"] == html.escape("<script>alert(1)</script>")
        assert result[0]["file_path"] == html.escape("/path/<to>/file.py")

    def test_with_empty_list(self):
        result = ReportGenerator._process_issues([])
        assert result == []

    def test_default_severity_is_low_when_missing(self):
        issues = [{"title": "No severity field"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["severity"] == "low"
        assert result[0]["severity_label"] == "LOW"

    def test_unknown_severity_gets_unknown_label(self):
        issues = [{"title": "T", "severity": "extreme"}]
        result = ReportGenerator._process_issues(issues)
        assert result[0]["severity_label"] == "UNKNOWN"

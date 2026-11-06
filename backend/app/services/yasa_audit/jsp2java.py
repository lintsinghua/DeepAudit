"""Convert JSP scriptlets into analyzable Java classes, one class per JSP.

YASA does not parse JSP. Each JSP becomes `class Jsp_<name> extends HttpServlet` whose
`_jspService` method contains the scriptlet code, with `<%= expr %>` turned into
`out.print(expr);`. Line numbers are preserved (JSP line N == Java line N) so engine
findings can be mapped back to the original file.
"""

from __future__ import annotations

import re

IMPORT_RE = re.compile(r'<%@\s*page\s+import\s*=\s*"([^"]+)"\s*%>')
TOKEN_RE = re.compile(r"(<%--.*?--%>|<%@.*?%>|<%=.*?%>|<%!.*?%>|<%.*?%>)", re.S)


def _blank(text: str) -> str:
    """Keep only the newlines so that line numbers stay aligned."""
    return "\n" * text.count("\n")


def class_name(stem: str) -> str:
    return "Jsp_" + "".join(c if c.isalnum() else "_" for c in stem)


def convert(jsp_text: str, cls: str) -> str:
    imports: list[str] = []
    for m in IMPORT_RE.finditer(jsp_text):
        imports += [i.strip() for i in m.group(1).split(",") if i.strip()]

    body: list[str] = []
    for part in TOKEN_RE.split(jsp_text):
        if not part:
            continue
        if part.startswith("<%--") or part.startswith("<%@") or part.startswith("<%!"):
            body.append(_blank(part))
        elif part.startswith("<%="):
            body.append(f"out.print({part[3:-2].strip()});" + _blank(part))
        elif part.startswith("<%"):
            body.append(part[2:-2])
        else:  # template HTML
            body.append(_blank(part))

    # The header occupies exactly one line, so JSP line N is Java line N.
    header = (
        "package jsp; import javax.servlet.http.*; import javax.servlet.jsp.*; "
        + " ".join(f"import {i};" for i in imports)
        + f" public class {cls} extends HttpServlet {{ "
        "protected void _jspService(HttpServletRequest request, HttpServletResponse response) "
        "throws Exception { HttpSession session = request.getSession(); JspWriter out = null; "
    )
    return header + "".join(body) + "\n}}\n"

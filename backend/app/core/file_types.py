"""File type constants shared by the scanner, the scan endpoint and the RAG indexer."""

# Server-side templates that contain executable code (scriptlets, expressions, helpers).
# In JSP/ASP.NET/ERB/EJS apps much of the request handling and output lives in these files,
# so skipping them hides both injection sinks and access-control logic from analysis.
SERVER_TEMPLATE_EXTENSIONS = (
    ".jsp", ".jspx", ".jspf",          # Java Server Pages
    ".asp", ".aspx", ".ascx", ".cshtml", ".vbhtml",  # ASP / ASP.NET / Razor
    ".erb",                            # Ruby
    ".ejs", ".hbs", ".pug", ".jade",   # Node.js
    ".twig",                           # PHP
    ".vm", ".ftl",                     # Java (Velocity, FreeMarker)
)

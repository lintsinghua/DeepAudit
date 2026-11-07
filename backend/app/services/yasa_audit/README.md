# yasa_audit: agent-built YASA rules + bounded triage

A command-line audit pipeline for data-flow vulnerabilities (injection, code/template execution, path
traversal, SSRF, XXE, deserialization, XSS, open redirect) and access control (missing authentication,
missing object-level authorization, exposed files). It is independent of the existing
Orchestrator/agents and is not wired into the web UI yet.

## How it works

1. **build**: an agent orients in the project (framework, bootstrap file, wrappers, unparsable code such as
   JSP), writes one YASA `ruleConfig`, runs the engine and fixes configuration problems it can see in the
   scan counters. Limits: 25 tool calls, 2 engine runs. It does not triage.
2. **triage**: every engine finding becomes a candidate. A deterministic sink inventory (L0 patterns + wrapper
   sinks named in the builder's rules, minus calls whose arguments are all constants) adds *residual*
   candidates the engine did not report. Candidates are grouped by file; each group is reviewed in a fresh,
   bounded LLM context (10 tool calls, +4 per extra candidate, cap 24) and every candidate gets a verdict.
3. **authz** (separate command): a deterministic entry inventory (servlets and JSPs; Express routes with the
   guards that actually apply, from global, prefix and inline middleware) is reviewed in batches of three
   handler files, each batch seeing the full route table for peer comparison. `--product` declares which
   routes are public by design and the roles; without it most false positives are "public by design" pages.
   No RAG index is used: reviewers given a semantic-search tool called it 0-1 times per run.

Knowledge given to the agents lives in `kb/`: `l0_spec.md` (sources, sinks, class-specific sanitizers),
`yasa_reference.md` (official engine reference), `yasa_playbook.md` (engine know-how; each item verified,
see `backend/benchmarks/yasa_audit/README.md`).

## Entry discovery and large projects

Entries come from the indexes `yasamcp init` already builds, not from per-language code (`discovery.py`):

1. **codegraph routes**: codegraph's framework resolvers (Spring, Laravel, Drupal, Django, Flask, FastAPI,
   Express, NestJS, Go, Rails, ASP.NET, ...) write `route` nodes; the handler is the function named on the
   registration line among the route's call/reference edges.
2. **yasa-mcp `api`**: interface / RPC implementations.
3. **URL-addressable scripts** (PHP, JSP): if most files share a direct-access guard
   (`if (!defined('X')) die`, as in SugarCRM/SuiteCRM, WordPress, CodeIgniter, Joomla), the entries are the
   files that define X; otherwise files with top-level code that read request input and that no other file
   includes. JSP pages outside WEB-INF.
4. The regex extractors (`entrypoints.py`) only add guard annotations and fill gaps.

Each entry is annotated with `dispatcher` (request data selects the code: dynamic include, `new $x`,
`call_user_func`, getattr, reflection) and `web_server_denied` (a deny rule from `.htaccess`, `web.config`,
server configs, or rule templates written by installer code). Dispatchers are reviewed first and the
reviewer resolves the dispatch convention once.

Large projects: codegraph indexes SuiteCRM (760k LOC PHP) in 37 s, while YASA's call graph took more than
15 min. Stages start when codegraph's index is complete; YASA's call graph keeps building in the background
and is stopped at the end; until it exists, the navigation tools (find_function, find_callers, call_graph,
search_symbol) answer from codegraph. Triage orders sinks by class, then by whether codegraph links their
file to an entry.

## Setup

```bash
bash backend/scripts/setup_yasa.sh        # native YASA + official yasa-mcp bundle into ~/.yasamcp
export LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=...   # CLI only; OpenAI-compatible with tool calling
```

Supported platforms: Linux x86_64, macOS ARM64 (Apple Silicon) and macOS x86_64 (Intel).
The installer preserves the official MCP bundle's `lib/` directory, verifies its release checksum,
and reuses an existing installation on subsequent runs. No Docker or Rosetta is needed on macOS.
Legacy source virtualenv installations are still discovered; use `YASA_REF=<tag/branch>` to install
from source and set `YASAMCP_BIN` to the path printed by the installer.

With the default location nothing else is needed. For another location run the script with
`YASAMCP_HOME=/opt/yasamcp` and start the CLI or backend with the same variable; `YASA_BIN`, `YASAMCP_BIN`,
`YASA_RG_BIN` and `YASAMCP_TOOLS_DIR` override single tools.

## Usage

```bash
cd backend
uv run python -m app.services.yasa_audit init  /path/to/project                 # navigation cache (once per version)
uv run python -m app.services.yasa_audit run   /path/to/project --out out/ \
       --deploy "Linux container, Node 22"                               # build + triage
uv run python -m app.services.yasa_audit trace /path/to/project --out out-a/    # baseline: agent tracing only
uv run python -m app.services.yasa_audit authz /path/to/project --out out-z/ \
       --product "Roles: user, admin. Public by design: /login, /search"  # access control
```

Outputs: `out/build/yasa-*/` (rule configs, SARIF), `out/build/yasa_registry.json` (engine findings by id),
`out/triage/findings.json` (verdicts with file:line hops), `out/metrics.json` (tokens, wall time),
and a `transcript.jsonl` per agent.

`--deploy` matters: whether a path check can be bypassed with a backslash depends on the OS, for example.

## In DeepAudit (task system + web UI)

The new-audit dialog has a third mode, **YASA 混合审计**, with an optional product-context field. It
creates a normal agent task (`POST /api/v1/agent-tasks/` with `audit_mode: "yasa"`); the mode and the
optional `product` / `deploy` / `stages` / `workers` settings are kept in `audit_scope`, so no DB migration
is needed. `task.py` then runs, within `timeout_seconds` (default 1800):

0. the task's exclude patterns and target files are applied (kept files copied to `<run dir>/src` when
   anything is left out)
1. `yasa-mcp init` (navigation cache; on failure the run continues with grep/read only)
2. dataflow (build + triage) and access control (authz) side by side, workers split about 2:1
3. findings saved through `_save_findings`, so the task page, finding status workflow and reports work as
   for agent tasks. Triage verdicts become confidence (confirmed 0.85, likely 0.6, one severity lower), not
   `is_verified`: nothing is executed.

Navigation initialization has its own timeout (up to 600 seconds within the audit budget). On timeout,
the entire navigation process group is stopped, including native engine children. Its stdout/stderr
are retained in the scoped project's `.yasa/navigation-init.log`; a timeout means degraded navigation,
not successful indexing of the whole project.

LLM settings come from the user's DeepAudit LLM config (then the environment); the provider must be
OpenAI-compatible with tool calling. Cancelling the task stops agent loops and pending units. Run
directories (rules, SARIF, transcripts, `not_reviewed`) go to `$YASA_AUDIT_RUNS_DIR/<task id>`
(default `/tmp/deepaudit-yasa-runs`). The backend finds the tools installed by `setup_yasa.sh` (see Setup);
these variables are read from the process environment, not from `backend/.env`.

## Measured (deepseek-flash, 2026-11-05/06)

| Target | Recall | Negatives hit | Tokens | Wall time |
| --- | --- | --- | --- | --- |
| HMS (Java Servlet + JSP, 1.9k LOC) | 13/13 | 0 | 0.71 M | 3.3 min |
| Juice Shop backend (TypeScript, 10k LOC) | 14/17 | 2 | 1.67 M | 9.5 min |
| HMS, access control (`authz --product ...`) | 8/8 | 1 (+4 low-impact pages that violate the declared policy) | 0.43 M | 2.2 min |

Details, baselines and the experiments behind the design are in `backend/benchmarks/yasa_audit/README.md`.

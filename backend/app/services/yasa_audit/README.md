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

## Entry discovery: an agent-authored model, not per-framework code

The attack surface is found by a **recon stage** (`pipeline.recon`), not by a growing pile of
per-framework extractors. The principle: tools give evidence, the agent builds a declarative model of
how *this* project routes requests, and a deterministic executor expands and validates it.

- `routing.py` is project- and framework-agnostic. It runs a **recipe** the agent writes: a `family`
  (`config-xml` for routes declared in XML config such as OFBiz `controller.xml`, Spring/Struts XML,
  web.xml; or `annotation` for `@*Mapping`/`@Path`), the file glob, and how to read the route uri, the
  `security`/auth, the handler, and the view. `expand()` applies it across the whole project; `resolve()`
  binds every route's handler to real code via codegraph, following an optional
  request -> service -> implementation hop (a `services` recipe section). No framework name appears in it.
- The recon agent (`prompts.RECON`, `toolbox.try_recipe`) reads a real config file, writes a recipe,
  runs `try_recipe`, and refines it against the coverage counters (routes / resolved / public) until the
  surface is captured. Its `entries.json` is shared by build, triage and authz (`load_entries`).
- `discovery.py` (codegraph route nodes, the `script`/`direct-access-guard` rule, `entrypoints.py`
  regex extractors, dispatcher/`web_server_denied` annotations) is now the **fallback** used when the
  agent finds less than the heuristics, and the source of the reachable-file set for engine scoping.

The resolved model also **drives the engine**: `auto_engine_plan` emits YASA entrypoints from the
model's handlers (Java `packageName`+`functionName`, scripts by `filePath`), so config-wired handlers
reach taint analysis instead of only the framework-collected ones.

Example: Apache OFBiz (3,166 `request-map`s in 17 `controller.xml`; codegraph finds 0 routes, the
heuristics 47 wrong ones). The agent writes a `config-xml` recipe with a `servicedef` services hop and
gets 3,284 entries, 987 resolved to code, 59 public -- with no OFBiz-specific code in the pipeline.

Each entry may be annotated with `dispatcher` (request data selects the code) and `web_server_denied`
(a deny rule from `.htaccess`, server configs, or installer code). Dispatchers are reviewed first.

Engine input (`engine_scope.py`): the discovered entries also drive the taint engine. For PHP, and for any
project above 1,500 source files, the builder's engine runs use a line-preserving shadow copy that contains
only the files codegraph links to the entries. PHP entry scripts are wrapped as
`YasaEntry<N>_<k>Service::run()` (top-level classes stay at file level), and the project's own `*Service`
classes are renamed to `*Servic_`. The reason: YASA's PHP checker self-collects `*Service` methods, and it
ignores ruleConfig entrypoints (the analyzer never runs the list the checker builds). SuiteCRM: 647 of 4,654
files, 71 entrypoints, 2.5 min, 14 findings with the stock PHP rules. DVWA: 83 entrypoints, 59 findings, 9 s.

Automatic first engine run: the build stage runs the engine once before the agent, with the default
sources/sinks of the language (`kb/rule_defaults`, from YASA's example configs) and entrypoints derived from
discovery: for JS/TS the function that registers each route (codegraph: smallest function around the
registration line), for the other languages the engine's own collection. It gets at most half of the build
window; the agent starts from its findings (R1-*) and refines the rules. Engine runs with less than two
minutes left are refused instead of timing out.

Scope: whole packages (nearest manifest) of the entries when they total at most 2,500 files, plus files
codegraph links to the entries; UI packages (React/Vue/... without a server framework) and tests are
excluded, as are client-side routes and test routes in discovery. Every stage reads a snapshot of
codegraph's index (WAL file, still open by the background init) and treats index errors as "no ordering
information", never as a stage failure.

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

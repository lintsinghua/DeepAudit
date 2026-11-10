# yasa_audit: entry-first audit, with sensitive operations and identity design

Three stages under one wall-clock budget (default 30 minutes):

1. **recon** — agents map the attack surface, the access-control model and what is worth protecting
   (sensitive operations, identity subsystems).
2. **review** — every entry point, every sensitive operation outside a handler and every identity
   subsystem is reviewed in its own fresh context.
3. **verify** — every reported root cause gets a sceptical agent that tries to refute it, or shows that
   what it gives is within a principal's designed power (`by_design`).

There is no per-framework code, no routing DSL and no sink list. Project knowledge lives in what the
agents write (extractor programs, entry cards, verified facts), and correctness comes from checks that
do not depend on the framework.

## recon

The agent starts from the directory layout, codegraph's route evidence and the navigation tools
(functions, callers, call graph, symbol search; answered from codegraph's index by `graph.py`). It works out where requests come in and how the dispatch chooses the code to run,
for every dispatcher the project has (pages, REST, GraphQL, admin area, ...).

It then writes a small **extractor program** per dispatcher and runs it with `run_extractor`. The
program applies the mapping it found (code, config, naming conventions, schemas, DI bindings — whatever
this project uses) to the whole tree and prints entries:

```json
{"route": "/V1/carts/:cartId", "method": "GET", "handler_file": "app/.../CartRepository.php",
 "handler": "get", "kind": "rest", "auth": "resource Magento_Cart::manage",
 "exposure": "privileged", "declared_at": "app/.../etc/webapi.xml:40"}
```

Three checks are returned to the agent after each run, and it fixes the extractor when one fails:

| Check | What it catches |
| --- | --- |
| handler resolves to a file that contains the handler | interfaces, wrong paths, name-only guesses |
| random samples the agent must read back | a mapping that is plausible but wrong |
| `check_coverage`: code that reads request data, not reachable from any entry | dispatchers or areas not covered yet |

If the agent produces nothing usable, codegraph's own routes are used so the review can start.
Output: `recon/entries.json`, `recon/recon.json` (counts, coverage, the agent's notes on each
dispatcher), `recon/extractors/*.py`.

## Sensitive operations and identity subsystems (`assets.py`)

Starting only from entries misses three kinds of flaw. The first is code that no route reaches
directly: render pipelines, hooks, and extension points with no caller in the repository. The second is
a value that is sanitized at the entry and transformed again by another component. The third is the
design of a module, such as how a login binds an external identity, which no single route shows. A
third recon agent, running in parallel with the other two, maps the other end of the flow.

**Operations.** The classes are fixed, describe effects rather than frameworks, and never change per
project:

| Class | What the operation does |
| --- | --- |
| `credential_or_privilege_write` | sets or changes an account's credentials, tokens, role, groups or permissions |
| `act_on_other_account` | acts on someone else's account: sets its password, issues it an invitation, reset link, key or session, rotates its key, changes its role, deletes it |
| `bulk_field_assignment` | copies request fields onto a stored object without naming each one (mass assignment) |
| `object_by_request_id` | loads, changes or deletes an object chosen by an id, key or path from the request |
| `personal_data_output` | puts email, IP, phone, password hash, token, ... where someone other than the owner reads it |
| `query_construction` | builds a database or search query from text or structures containing request or stored data |
| `code_or_command_execution` | runs code or commands not fixed in the program text (shell, eval, dynamic include, template compile, deserialization, XXE) |
| `outbound_request` | makes the server fetch a URL or connect to a host |
| `raw_markup_output` | writes data into HTML or an attribute without the project's escaping |
| `file_write` | writes, moves, extracts or deletes a file |
| `state_change_in_read_path` | changes persistent state on a path meant only to read (GET, permission callback, renderer) |
| `secret_generation_or_check` | creates or checks a secret value: tokens, codes, signed links, webhook signatures, keys |

The classes do not limit what is found. Entry units still trace every class of vulnerability forward
from the request. The operation classes choose where review also starts backward: these are the
operations whose flaws entry review misses most often. That happens when the data was stored earlier by
another request, when the code is reached through hooks or extension points, or when the check is
missing in one sibling of many.

How *this* project performs each class is found from evidence, not from a rule list:

- the sensitive fields of its data model;
- the guards the project applies itself (a permission or ownership check, an escaping call, an
  allowlist), which show what it treats as sensitive;
- the helpers that codegraph navigation leads to.

The agent writes each form as a declarative **recipe**:

```json
{"name": "role-write", "op_class": "credential_or_privilege_write", "pattern": "->role\\s*=",
 "guard": "requireAdmin\\(|->can\\(", "why": "users.role, set by Users::actionSave (app/Users.php:5)"}
```

`run_recipe` expands a recipe over the whole project (tests and vendored code left out). It places
every site in codegraph's call graph, following calls through interfaces and parent methods; calls from
tests and vendored code are not counted, and module-level code counts as a caller. The scope is set by
reachability, not by the agent: a recipe's `glob` says where the agent looked, and matches outside it in
code the entries can reach (libraries and provider adapters the application calls) are added to the map
and reported as `reachable_outside_glob`. Reachability follows calls, instantiations and references, and a
type reached brings its methods. Product code that no other file names statically is either dead or loaded
by name at run time (a provider registry, a lazy import, a plugin directory), which the index cannot tell
apart, so it counts as reachable too. So does product code in a language the index does not parse (shell
scripts a task runner sources, templates): nothing is known about what runs it, so a glob cannot leave it
out, and the agent is told up front which such files exist. The executor returns counters the agent
refines the recipe on, just as it refines an extractor on coverage:

| Counter | Meaning |
| --- | --- |
| `handler` | the site is in an entry's handler |
| `entry` | an enumerated entry reaches the site through calls |
| `no_callers` | nothing in the repository calls the site: a framework hook, an extension point, a public API, or dead code |
| `internal` | something calls the site, but no enumerated entry reaches it |
| `unindexed` | the file is in a language the index does not parse: who runs it is unknown, and its unit asks the reviewer to find out |
| `guarded` / `unguarded` | whether the guard pattern appears in the operation's function before it, or in a caller within three calls |

The agent can finish only when each class has a recipe or has been declared absent (`class_absent`,
with what it searched).

For `act_on_other_account` the guard is the project's own comparison of the caller's authority with the
target account's (a set of target roles a manager may act on, a rank comparison). Every invitation,
password reset, key rotation or deletion on someone's behalf that lacks it becomes a difference unit,
shown next to the siblings that have it.

**Identity subsystems.** The same agent records registration, login, recovery, SSO, tokens, account
linking, invitations, MFA, sessions and user management with `record_identity`. Each subsystem carries
its route patterns, files, models and settings (defaults with `file:line`). Subsystems are recorded one
per call (a later record with the same name replaces it), so no call is cut by the output limit.

Once the entries are final, the recipes are expanded again against them, and the subsystems are joined
to their entries and sites. Output: `recon/assets.json`.

## review

Entries that run the same handler form one unit; units are ordered public → unknown → authenticated →
privileged. Each unit gets the entry, similar entries for comparison (peers), the handler's code and the
verified facts so far. The reviewer:

1. understands the scenario: what it does, who can call it, inputs, data touched, values it stores;
2. judges access control (missing authentication / authorization, object-level authorization);
3. lists the risks plausible for *this* function (it stores a file, fetches a URL, builds a query,
   renders data, loads an object by id, ...);
4. traces each risk with the navigation tools to a confirmed path or a rejection with evidence;
5. records a card, reports findings (with `required_privilege`), and shares facts.

**Paths cross storage.** A flaw is a path from a value someone controls to an operation that trusts it,
and a path has two kinds of edge: a call, and a value written to storage and read back later (a database
field, a file, a setting, an environment or cache key, a queue). The call graph ends at storage, so the
reviewers are given the other edge: a value is as trusted as whoever can write it, not as the place it
is read from.
- Backward, a trace that arrives at stored data continues at its writers. `who_reaches(pattern)` takes
  the pattern of the code that writes the value and returns the writers by function, the entries that
  reach each through calls and their least privileged caller. It is to storage what `find_callers` is to
  a call, and it is the recipe executor of the asset map, so it works on any text the project has
  (scripts, templates and declarative files included).
- Forward, when a request value is stored, what its readers do with it decides what the write must
  check: the reviewer finds the readers and judges the check against the most demanding one.

What a reviewer establishes about a stored value (who can write it, where it is used as code, a path, a
query or markup) is shared as a fact. This one rule covers second-order injection, stored markup,
templates or expressions kept in the database, and settings or environment values that a runner executes.

Facts are accepted only when each quote is found at the cited file:line, so later reviewers can rely on
them instead of re-deriving the same framework behaviour. The system prompt is identical for every unit
(facts and the entry go in the user message), which keeps the provider's prefix cache effective.

There is no re-review stage.

### Three kinds of unit

| Kind | Unit | Starts from | Question |
| --- | --- | --- | --- |
| entry | entries sharing one handler | the route, forward | is this entry vulnerable? |
| operation | a function performing sensitive operations outside every handler | the operation, backward | can anyone make it happen with values they control? |
| design | one identity subsystem (at most `design_units_max`) | routes, models and settings together | does the design hold? |

- **Operation units.** A site inside a handler is not a unit of its own: it is listed in that entry's
  unit ("sensitive operations in this handler", with a guarded sibling next to an unguarded site), so
  the code is reviewed once. Every other site is
  grouped by function. The reviewer works backward through the entries listed and through paths the
  index cannot see (hooks, events, render pipelines, jobs). It is shown sibling sites of the same recipe
  where the project's guard is on the way: a check the siblings make and this path does not is the
  most likely flaw. When nothing calls the code, the threat model is a plugin or integration written
  the way the project's documentation shows. Units are ordered by the exposure of the entries that
  reach them, with unguarded and caller-less sites first. An operation unit is skipped, its result
  shared, when an entry reviewer read the whole function or anchored a hypothesis at the operation.
- **Contract units.** A function that `HUB_ENTRIES` (20) or more entries reach is shared infrastructure
  (a database helper, an HTTP wrapper). Tracing its paths backward has no end, so its unit reviews its
  contract instead: what callers must guarantee for the operation to be safe and whether the function
  enforces it. The contract is recorded as a fact, which every entry reviewer then sees.
- **Design units.** The reviewer answers a fixed checklist with `record_design` and cannot finish until
  every item is answered:
  - identity binding;
  - claiming of existing records (inactive, guest, pending);
  - token lifecycle (expiry, single use, hashing, constant-time comparison, revocation);
  - defaults;
  - privilege ceiling: for each principal the subsystem manages, whether it can grant or reach more than
    its designed power (see below).

  Each answer has a status:
  - `sound`, `flaw` and `owner_decision` need quoted evidence;
  - `unclear` and `not_applicable` do not.

  A flaw that has been traced to its harm is also reported as a finding, with its preconditions in the
  impact. A subsystem with more than 40 entries is reviewed in parts that share its models and settings,
  unless its routes match more than a third of all entries: then it is a mechanism most requests pass
  (a session or token gate), reviewed once from its files, models and settings.
- **Follow-up units.** A review often ends with a conclusion it could not finish. In a design unit that is
  a flaw it did not trace to a finding, or an answer that depends on a function it did not read
  (`to_verify`); at most three per design unit. In an entry or operation unit it is a hypothesis left
  `open`: the first one per unit, once per anchor for the whole run, since parallel units often reach the
  same code. Each gets a fresh reviewer, with the earlier reasoning, that reads the code and either
  reports the finding or records what stops it. Follow-ups run as soon as the unit that raised them ends;
  a design follow-up's outcome is written next to its answer in the worksheet (`follow_up`).
- **Rejections need reasons.** A card is refused while a hypothesis that is not confirmed has no `why`:
  a rejection names the code that stops it, an open hypothesis what is left to read.

The schedule puts design units first, because they are few and nothing else covers them. Entry units
follow, and operation units take every `operation_every`-th slot, so neither kind waits for the other to
be used up. All units share facts, root causes and what the entry reviewers have covered. Each finding
carries `unit_kind`.

Exposure is about who can obtain a role, not what it is called; impact is about what a principal is
meant to do. The access agent records, besides the ladder, each principal's **designed power**: one row
per role, permission or scope that grants something different (each scope of a scoped token, which a
ladder cannot order), read from the project's own statements (documentation, comments, the restrictions
and security fixes it adds), with evidence. A row says whether the role is held for one object (team,
organization or project admin, owner). An ordinary user can hold such a role, so an entry only such a
role can call is reviewed as `authenticated`, not `privileged`. Reviewers and the refutation check judge
what an attacker obtains against the designed power of the least privileged principal that can take the
path: a scope meant to edit scheduled commands running a command is designed (`by_design`), a data-only
scope controlling what runs is an escalation.

Tool calls are forgiving: arguments a tool does not declare are dropped and named in the result, and
missing required ones are asked for, instead of the call failing. A reasoning model's hidden reasoning
counts against the output limit; when it uses all of it and nothing visible comes back, the same request
is sent again with twice the allowance (up to `LLM_MAX_TOKENS_CEILING`, default 32768) instead of being
lost. Units that still end that way are counted (`units_ended_silent`).

Output:
- `review/findings.json`:
  - `findings`;
  - `open_leads`;
  - `design_worksheet`: per subsystem, every checklist item with its status, answer and evidence. This is
    what a human reviews for defaults and design trade-offs.
  - `not_reviewed`, `not_reviewed_operations` and `not_reviewed_design`, when the budget runs out;
  - after verify, `refuted` and `by_design`: findings taken out, each with the check's reasoning (for
    `by_design`, the principal and where the project grants the power).
- `review/cards.json`, `review/facts.json`.
- `metrics.json`: units of each kind, tokens, cached tokens, reasoning tokens, wall time.

## Usage

```bash
bash backend/scripts/setup_yasa.sh        # codegraph + ripgrep into ~/.yasamcp/tools
export LLM_BASE_URL=... LLM_API_KEY=... LLM_MODEL=...   # OpenAI-compatible with tool calling
export LLM_STRONG_MODEL=...          # optional: used for recon/access/reconcile/verify (review = LLM_MODEL)
cd backend
uv run python -m app.services.yasa_audit init  /path/to/project            # codegraph index
uv run python -m app.services.yasa_audit recon /path/to/project --out out/ # surface only
uv run python -m app.services.yasa_audit run   /path/to/project --out out/ \
       --recon-runs 2 --strong-model deepseek/deepseek-v4-pro \
       --deploy "Linux, nginx, PHP 8.3" \
       --product "Roles: guest, customer, admin. Public by design: catalog, login. CLI input is trusted."
```

`run` reuses `out/recon/entries.json` when it exists. `--recon-runs N` (or `recon_runs` in config)
runs recon N times and unions the entries — a single run sees only part of a large surface — stopping
early when a run grows the union by less than `recon_converge_threshold` (5%); `recon.json` then carries
a `converge` block with the per-run growth and a capture-recapture estimate of the full surface. The
deciding stages (recon, access model, reconcile, refutation check) run on `--strong-model` when set,
while per-entry review stays on the cheaper `LLM_MODEL`; the resolved model per stage is in `metrics.json`. In DeepAudit, the "YASA" task mode runs the same
`run` after the navigation index is ready; `product` and `deploy` come from the task's `audit_scope`.

## Not in this version

Automatic YASA taint rules (sources, sinks, sanitizers) and engine runs. The earlier rule-building,
residual-sink and grouped-triage pipeline is in git history (before `feat/entry-first-review`).

## Code index

`codegraph` (tree-sitter, many languages) indexes the project in seconds to a minute: calls,
inheritance, containment and the routes of common frameworks. `graph.py` answers the navigation tools
from it with read-only SQL. Calls to an interface or abstract method are followed to the
implementations, callers of an implementation include calls through its interface, and a call on
`this` / `self` / `super` / `parent` is resolved in the caller's own class hierarchy (a parent named by
its short name is taken from the file's imports). Calls whose receiver type is not visible statically
may still be missing or attributed to a same-named function, so agents treat the index as navigation
and the code as the evidence.

The YASA engine's index is no longer built: on PHP it resolved 3% of the calls codegraph resolves
(inherited methods were missing), on TypeScript it produced nothing after ten minutes, and on Java it
was not better than codegraph plus the implementation step above, while costing 1-10 minutes per run.

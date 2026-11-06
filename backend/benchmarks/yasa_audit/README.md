# yasa_audit benchmark

Ground truth, scorer and target preparation for `app/services/yasa_audit`, plus the record of the
experiments (2026-11-05/06) that shaped its design.

## Targets

```bash
bash backend/benchmarks/yasa_audit/prepare_targets.sh /tmp/targets   # juice, juice-mini, hms
```

| Target | Code | Data-flow vulns | Negatives |
| --- | --- | --- | --- |
| `hms` | projectworlds Hospital-Management-System, Java Servlet + JSP, ~1.9k LOC | 13 | 4 |
| `juice` | OWASP Juice Shop backend at `717f5efa`, TypeScript/Express, ~10k LOC | 17 | 6 |
| `juice-mini` | 21 Juice route files (unchanged) + trimmed `juice-mini/server.ts`, ~6.5k LOC | 17 | 4 |

Ground truth is in `groundtruth/` and mirrored in `eval.py`. HMS was reviewed by hand in full. Juice uses
the project's own `vuln-code-snippet` annotations plus hand-verified server-side injections. Seven items
were first reported by a tool and then verified by hand (marked "added"); negatives are sites that look
dangerous but are safe (e.g. a `'/'` check before a single-segment `sendFile`, `Number()` before `$where`).
Access-control findings (HMS has 7) are not scored yet.

```bash
python backend/benchmarks/yasa_audit/eval.py --project hms out/triage/findings.json
```

## Results

Model: deepseek-flash (temperature 0.1), YASA 0.2.30. "A" = one agent traces source -> sink itself;
"B" = one agent writes YASA rules, runs the engine and triages, all in one conversation; "C" = this package
(build stage, then grouped triage + residual sinks).

| Target | Mode | Recall | Negatives hit | Tokens | Wall |
| --- | --- | --- | --- | --- | --- |
| hms | A (2 runs) | 13/13, 11/13 | 0 | 0.74 M, 0.96 M | 3 min |
| hms | C | 13/13 | 0 | 0.62 M (prototype), 0.71 M (this package) | 3 min |
| juice-mini | A | 13/17 | 3 | 1.08 M | 4 min |
| juice-mini | B with playbook | 0/17 | - | 0.63 M | 10 min |
| juice-mini | C | 14/17 | 2 | 1.17 M | 8 min |
| juice | A (2 runs) | 9/17, 12/17 | 0 | 1.42 M, 3.53 M | 3, 5.4 min |
| juice | engine only, default entrypoints, no triage | 11/17 | 3 | 0 | 16 min |
| juice | C | 14/17 | 2 | 1.67 M | 9.5 min |

Findings that shaped the design:

- Engine and agent tracing are complementary: the engine found the NoSQL `$where` injection and the
  null-byte bypass that both A runs missed; A found the XXE behind a project wrapper, pug template injection
  and zip slip that the engine rules did not cover. C combines both.
- B fails structurally: one long conversation that iterates rules and triages dozens of findings degraded
  (the model returned empty replies after the 4th engine output) and reported nothing. The same rules,
  triaged in small fresh contexts (C), gave the best recall. Hence the separate build stage.
- Rule quality depended mostly on engine know-how, not on the sink list (see the playbook log below). With
  the playbook the builder configured the engine correctly on its first run.
- Engine cost is set by the entrypoint strategy, not project size (975 s -> 88 s on the same code).
- Small contexts are cheaper: grouping candidates by file cut triage tokens on HMS from 1.58 M to 0.62 M.
- Remaining false positives are sanitizer judgements: single-segment path checks (fixed by passing
  `--deploy`) and a `Number()` conversion the triage ignored.

Open: the 1 M tokens per 10k LOC target is not met yet (residual sinks dominate triage cost).

## Access control and RAG (2026-11-06)

Ground truth: `groundtruth/authz.yaml` (HMS 8 items, juice-mini 5 items; entry level). The juice-mini
`server.ts` carries the original auth middleware and directory listings for this purpose.

| Target | Condition | Recall | Extra reports | Tokens | Semantic-search calls |
| --- | --- | --- | --- | --- | --- |
| hms | authz stage, no RAG | 8/8 | 3 | 0.45 M | - |
| hms | authz stage + semantic search (DeepAudit RAG) | 8/8 | 5 | 0.46 M | 0 |
| hms | authz stage, no RAG, with `--product` | 8/8 | 5 (no public-by-design FPs) | 0.43 M | - |
| juice-mini | authz stage, no RAG | 4/5 | 5 | 0.56 M | - |
| juice-mini | authz stage + semantic search | 5/5 | 3 | 0.62 M | 1 |

- A full-repo RAG index is not needed by this pipeline: with the deterministic route table in the prompt,
  reviewers almost never used semantic search, and the recall difference (4/5 vs 5/5) came from one judgement
  on `/ftp` (rejected as "public by design" in one run, reported in the other), not from retrieval.
- Building the index is cheap (DeepAudit RAG: ~31 s and ~70k embedding tokens for 6.5k LOC), but DeepAudit's
  indexer skipped `.jsp` files, so HMS business logic was invisible to it until `.jsp` was added.
- Without product context the main false positives are public-by-design pages (login, registration). With
  `--product` they disappear; what remains are pages that violate the declared policy but expose no data,
  which should be ranked by severity rather than dropped.

## Playbook verification log

Each item in `app/services/yasa_audit/kb/yasa_playbook.md` refers to one of these runs.

| Id | Claim | How it was verified |
| --- | --- | --- |
| V1 | YASA does not parse JSP; preprocessing to Java recovers the flows | HMS: Java-only scan found 2 servlet SQLi; with `jsp2java` 9 SQLi sinks incl. 7 in JSPs |
| V2 | Java checker only self-collects `main()`/Spring; servlets need explicit sources | HMS: entryPointCount 9, markedSourceCount 0; adding `getParameter` return-value source -> findings |
| V3 | `getAttribute` as second-order source reaches session-based SQLi | HMS: adds `updateprofile.jsp:53` and `apn-his.jsp:105` |
| V4 | Express checker needs listed entrypoints; `js_input` finds inline, factory-returned and exported handlers; `--analyzer` changes nothing; dotted member sinks match | 37-line synthetic Express app, both checkers x with/without `--analyzer` (identical counters) |
| V5 | Factory-returned handlers are only analyzed when the route-registering file is scanned | Juice `routes/` only: markedSourceCount 29, findingCount 0; with `server.ts`: findings |
| V6 | `ONLY_CUSTOM` + bootstrap file (file-level) entrypoint gives the same findings much faster; a bootstrap function does not | Juice full: default 321 entrypoints 975 s; file-level `/server.ts` 88 s, same 13 sinks; `start`/`configureApp` 0 findings |
| V7 | Generic response/log sinks inflate matchedSinkCount | Juice: default JS rule config matched 1336 sinks |

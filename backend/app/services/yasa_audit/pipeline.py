"""Entry-first audit: route reconnaissance, then one review per entry point.

recon  : an agent works out how requests reach code in THIS project (directory layout, codegraph's route
         evidence, navigation tools), writes extractor programs that enumerate every entry, and checks
         them (handlers resolve to code, sampled entries read correctly, request-reading code is reachable
         from some entry). Output: entries.json.
         In parallel, an agent maps what is worth protecting (assets.py): recipes for a fixed set of classes of
         sensitive operation, expanded over the project and placed in the call graph, and the identity
         subsystems. Output: assets.json.
review : three kinds of unit, each in a fresh context, sharing verified facts and root causes:
         - entry: entries sharing one handler; what it does, who can call it, its access-control verdict,
           risks plausible for that function, each traced to a confirmed path or rejected;
         - operation: a function performing sensitive operations outside any handler, reviewed backward
           to every path that reaches it (entries, hooks, render pipelines) or, with no caller in the
           repository, as an extension point used the way the project documents it;
         - design: one identity subsystem against a fixed checklist; answers form a design worksheet.
"""

from __future__ import annotations

import collections
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

from . import assets as assets_map
from .agent_loop import run_agent
from .config import AuditConfig
from .discovery import codegraph_db, codegraph_routes, snapshot_codegraph
from .llm import LLM, limiter_for
from .prompts import access_model_text, access_prompt, assets_prompt, recon_prompt, review_prompt
from .toolbox import EXPOSURES, FactBook, IssueBoard, Toolbox, tool_schemas

MIN_UNIT_S = 60  # do not start a unit with less time left than this
SKIP_PARTS = {"node_modules", ".git", ".yasa", ".codegraph", "vendor", "venv", ".venv", "__pycache__"}
EXPOSURE_RANK = {"public": 0, "unknown": 1, "authenticated": 2, "privileged": 3}
PEERS_MAX = 12


def _schedule(units: list, work, workers: int, deadline: float | None,
              stop=None) -> tuple[list[dict], list]:
    """Run work(i, unit) for units in order on `workers` threads. Units that would start with less than
    MIN_UNIT_S left before the deadline are skipped and returned separately. A result may carry
    "followups": units that settle what that unit left open; they run next, ahead of the units not
    started yet, because a conclusion half-verified is worth more than one more unit started."""
    pending: collections.deque = collections.deque(enumerate(units))
    results: list[tuple[int, dict]] = []
    skipped: list = []
    cond = threading.Condition()
    state = {"active": 0, "next": len(units)}

    def guarded(i: int, unit: object) -> dict | None:
        if (stop and stop()) or (deadline is not None and time.time() > deadline - MIN_UNIT_S):
            skipped.append(unit)
            return None
        try:
            return work(i, unit)
        except Exception as e:  # keep the batch going
            return {"findings": [], "cards": [], "prompt_tokens": 0, "completion_tokens": 0,
                    "cached_tokens": 0, "steps": 0, "error": f"{type(e).__name__}: {e}",
                    **({"kind": unit.get("kind", "entry")} if isinstance(unit, dict) else {})}

    def worker() -> None:
        while True:
            with cond:
                while not pending and state["active"]:
                    cond.wait()
                if not pending:
                    cond.notify_all()
                    return
                i, unit = pending.popleft()
                state["active"] += 1
            r = guarded(i, unit)
            with cond:
                state["active"] -= 1
                if r is not None:
                    for follow in reversed(r.pop("followups", None) or []):
                        pending.appendleft((state["next"], follow))
                        state["next"] += 1
                    results.append((i, r))
                cond.notify_all()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [r for _, r in sorted(results, key=lambda x: x[0])], skipped


def _metrics(llm: LLM, extra: dict) -> dict:
    u = llm.usage
    return {"prompt_tokens": u.prompt, "completion_tokens": u.completion, "cached_tokens": u.cached,
            "reasoning_tokens": u.reasoning, "llm_calls": u.calls, **extra}


def _ext_counts(root: Path) -> list[tuple[str, int]]:
    c: collections.Counter = collections.Counter()
    for _d, ds, fs in os.walk(root):
        ds[:] = [x for x in ds if x not in SKIP_PARTS and not x.startswith(".")]
        c.update(os.path.splitext(f)[1] or f for f in fs)
    return c.most_common(15)


# ----------------------------------------------------------------- recon

def _access_agent(cfg: AuditConfig, root: Path, out: Path, deploy: str, product: str,
                  deadline: float | None, user: str, holder: dict) -> None:
    """Works out the project-wide access-control model; publishes it in holder['model']."""
    tb = Toolbox(cfg, root, out, unit="access")
    tb.finish_gates = [(lambda t: t.access_model is None,
                        "record_access_model first (how requests are authenticated and authorized)",
                        ["record_access_model"])]
    llm = LLM(cfg, stage="access")

    def missing(t: Toolbox) -> list[str]:
        return [x for x, done in (("record_access_model", t.access_model is not None),
                                  ("write_access_resolver", t.resolver_code is not None)) if not done]

    # Reading the security chain can take the whole budget; at two thirds, say what is still owed.
    owed = (lambda steps, t: steps >= cfg.access_budget * 2 // 3 and bool(missing(t)),
            lambda t: "Two thirds of your budget is used. Still to do: " + ", ".join(missing(t))
                      + " (a resolver may answer unknown for what you could not work out).")
    try:
        holder["res"] = run_agent(llm, tb, tool_schemas("access"), access_prompt(cfg.access_budget, deploy, product),
                                  user, cfg.access_budget, out / "transcript-access.jsonl", deadline=deadline,
                                  reminders=[owed])
    except Exception as e:  # the surface agent and the review still run without a model
        holder["error"] = f"{type(e).__name__}: {e}"
    model = tb.access_model
    if model is None and (tb.notes or "").strip():  # still better than nothing for the reviewers
        model = {"unverified_notes": tb.notes[:4000]}
    holder["model"], holder["llm"], holder["resolver"], holder["tb"] = model, llm, tb.resolver_code, tb
    holder["done"].set()


def _classes_left(t: Toolbox) -> list[str]:
    done = {r["op_class"] for r in t.recipes.values()} | set(t.absent)
    return [c for c in assets_map.OP_CLASSES if c not in done]


def _assets_agent(cfg: AuditConfig, root: Path, out: Path, deploy: str, product: str, deadline: float | None,
                  user: str, entries_now, holder: dict) -> None:
    """Maps the sensitive operations (recipes) and the identity subsystems; the map is built from them
    once the entries are final."""
    tb = Toolbox(cfg, root, out, unit="assets")
    tb.entries_source = entries_now
    tb.finish_gates = [(lambda t: bool(_classes_left(t)),
                        lambda t: "run a recipe, or class_absent, for: " + ", ".join(_classes_left(t)),
                        ["run_recipe", "class_absent"]),
                       (lambda t: t.identity is None,
                        "record_identity (an empty list if the project creates no identities)", ["record_identity"])]
    try:  # what the index cannot see into is part of the map too: say so before the agent picks globs
        unseen = assets_map.unparsed_summary(root, tb.call_index())
    except Exception:
        unseen = ""
    user = f"{user}\n\n{unseen}" if unseen else user
    llm, t0 = LLM(cfg, stage="recon"), time.time()
    no_recipe = (lambda steps, t: not t.recipes and (steps >= cfg.assets_budget // 2 or (
                     deadline is not None and time.time() >= t0 + (deadline - t0) / 2)),
                 "Half of your time or tool budget is used and no recipe has run. Write recipes now for the "
                 "operations you have seen, run them, then refine.")
    try:
        holder["res"] = run_agent(llm, tb, tool_schemas("assets"), assets_prompt(cfg.assets_budget, deploy, product),
                                  user, cfg.assets_budget, out / "transcript-assets.jsonl", deadline=deadline,
                                  reminders=[no_recipe])
    except Exception as e:  # the review still runs, from the entries only
        holder["error"] = f"{type(e).__name__}: {e}"
    holder["tb"], holder["llm"] = tb, llm


def _build_assets(holder: dict, entries: list[dict], out: Path) -> dict:
    """recon/assets.json from the agent's recipes, expanded against the final entries."""
    tb: Toolbox | None = holder.get("tb")
    if tb is None:
        return {"error": holder.get("error") or "the assets agent did not finish in time"}
    tb.entries_source = None
    try:
        data = assets_map.build(tb, dict(tb.recipes), tb.identity, dict(tb.absent), entries)
    except Exception as e:  # a map that cannot be built must not cost the recon
        return {"error": f"{type(e).__name__}: {e}"}
    assets_map.dump(data, out / "assets.json")
    res = holder.get("res") or {}
    return {**data["summary"], "steps": res.get("steps"), "finished": res.get("finished"),
            **({"error": holder["error"]} if holder.get("error") else {})}


def _apply_resolver(tb: Toolbox, entries: list[dict], code: str | None, out: Path) -> dict:
    """Run the access agent's who-can-call program on every entry and compare it with the exposure the
    surface agent declared: two independent readings of the access rules. The declared exposure stands
    (a resolver that misreads one request shape would otherwise relabel hundreds of entries) until the
    reconcile pass decides the disagreements; both stay visible to reviewers."""
    if not code or not entries:
        return {"installed": bool(code)}
    (out / "resolver.py").write_text(code)
    res = tb.resolve_access(entries, code)
    if isinstance(res, str):
        return {"installed": True, "error": res[:500]}
    groups: dict[tuple, list[dict]] = {}
    unknown: dict[str, list[dict]] = {}
    for e, r in zip(entries, res, strict=True):
        if e.get("exposure_declared"):  # a previous application: start again from the declared exposure
            e["exposure"] = e.pop("exposure_declared")
        e["who_can_call"] = r
        declared = e.get("exposure") or "unknown"
        lp = r["least_privileged"]
        if lp == "unknown":
            unknown.setdefault(str(e.get("kind") or _route_key(e.get("route", ""), 1)), []).append(e)
        elif declared == "unknown":
            if lp in EXPOSURES:
                e["exposure"] = lp
        elif lp != declared:
            e["exposure_declared"] = declared
            groups.setdefault((declared, lp, r["rule"][:100]), []).append(e)
    return {"installed": True, "entries": len(entries),
            "disagreements": sum(len(v) for v in groups.values()),
            "unknown": sum(len(v) for v in unknown.values()), "_groups": groups, "_unknown": unknown}


def _declared_code(root: Path, e: dict) -> dict:
    """The code at the entry's declared_at (the registration), quoted for the reviewer."""
    where = str(e.get("declared_at") or "")
    file, _, line = where.rpartition(":")
    if not file or not line.isdigit() or int(line) < 1:
        return {}
    try:
        with (root / file).open(errors="ignore") as fh:
            for i, text in enumerate(fh, 1):
                if i == int(line):
                    return {"declared_code": text.strip()[:200]} if text.strip() else {}
    except OSError:
        pass
    return {}


def _rank_principals(entries: list[dict], ladder: list[str] | None) -> None:
    """Place each entry on the project's principal ladder: the least privileged principal the resolver
    names for it (a ladder name matches a principal equal to it or containing it; the longest wins)."""
    if not ladder:
        return
    names = [(i, n.lower()) for i, n in enumerate(ladder)]
    for e in entries:
        ranks = []
        for p in (e.get("who_can_call") or {}).get("principals") or []:
            hits = [(len(n), i) for i, n in names if n == p.lower() or n in p.lower()]
            if hits:
                ranks.append(max(hits)[1])
        if ranks:
            e["principal_rank"] = min(ranks)
            e["least_principal"] = ladder[min(ranks)]
        else:
            e.pop("principal_rank", None)
            e.pop("least_principal", None)


def _scoped_exposure(entries: list[dict], scoped_roles: list[str] | None) -> int:
    """An entry that an object-scoped role (team or organization admin, project owner) can call is open
    to ordinary users: any of them can hold such a role for some object, by creating it or being made its
    admin. Entries the resolver answers with such a role are reviewed as authenticated, not privileged.
    Returns how many entries this lowered."""
    names: Final = [n.lower() for n in scoped_roles or [] if n]
    lowered = 0
    for e in entries:
        principals = [str(p).lower() for p in (e.get("who_can_call") or {}).get("principals") or []]
        role = next((r for r in names for p in principals if r == p or r in p), None)
        if role is not None and e.get("exposure") == "privileged":
            e["exposure"], e["exposure_scoped_role"] = "authenticated", role
            lowered += 1
    return lowered


def _apply_decisions(entries: list[dict], groups: dict[str, list[str]], decisions: dict[str, dict]) -> dict:
    """Apply the access agent's per-group verdicts to the entries that still disagree."""
    verdict_of = {eid: decisions[g] for g, ids in groups.items() if g in decisions for eid in ids}
    c: collections.Counter = collections.Counter()
    for e in entries:
        if not e.get("exposure_declared"):
            continue
        d = verdict_of.get(e.get("id"))
        lp = e["who_can_call"]["least_privileged"]
        if d is None:
            c["undecided"] += 1
        elif d["verdict"] == "resolver_wrong":  # the declared exposure stands; the wrong answer goes
            e.pop("exposure_declared")
            e["who_can_call"] = {"least_privileged": "unknown", "principals": [],
                                 "rule": "resolver wrong for this entry: " + d["reason"][:150]}
            c["resolver_wrong"] += 1
        elif d["verdict"] == "declared_wrong" and lp in EXPOSURES:
            e["exposure"] = lp
            e.pop("exposure_declared")
            c["declared_wrong"] += 1
        else:  # inconsistent code: keep both, review it as the more exposed one
            if lp in EXPOSURES:
                e["exposure"] = min(e["exposure"], lp, key=lambda x: EXPOSURE_RANK.get(x, 1))
            e["access_inconsistency"] = d["reason"]
            c["inconsistent_code"] += 1
    return dict(c)


def _req_key(e: dict) -> tuple:
    return (e.get("method", "ANY"), e.get("route"), str(e.get("handler_file")))


def _sample(e: dict) -> str:
    where = f"{e.get('handler_file')}:{e.get('handler_line') or ''}".rstrip(":")
    return f"{e.get('method', '')} {e.get('route', '')} -> {where} {e.get('handler', '')}".strip()


def _group_rows(groups: list[tuple[str, tuple, list[dict]]]) -> list[str]:
    rows = []
    for gid, (declared, lp, rule), es in groups:
        rows.append(f"- {gid}: {len(es)} entries, declared {declared}, resolver {lp} (rule: {rule})")
        rows += [f"    {_sample(e)}" for e in es[:3]]
    return rows


def _unknown_rows(applied: dict) -> list[str]:
    rows = []
    for kind, es in sorted(applied["_unknown"].items(), key=lambda kv: -len(kv[1]))[:6]:
        rows.append(f"- {len(es)} entries of kind/prefix {kind!r}: resolver unknown")
        rows += [f"    {_sample(e)}  request fields: "
                 + json.dumps({k: e.get(k) for k in ("method", "route", *Toolbox.RESOLVER_FIELDS) if e.get(k)},
                              ensure_ascii=False) for e in es[:2]]
    return rows


def _new_groups(applied: dict, groups: dict[str, list[str]], decided: set[str], limit: int = 12
                ) -> list[tuple[str, tuple, list[dict]]]:
    """Number the disagreements no decided group covers as new groups (ids continue), replacing the
    undecided ones: after the resolver changed, those describe answers it no longer gives."""
    covered = {eid for g, ids in groups.items() if g in decided for eid in ids}
    for g in [g for g in groups if g not in decided]:
        del groups[g]
    n = max((int(g[1:]) for g in groups if g[1:].isdigit()), default=0)
    out = []
    for key, es in sorted(applied["_groups"].items(), key=lambda kv: -len(kv[1])):
        es = [e for e in es if e.get("id") not in covered]
        if es and len(out) < limit:
            n += 1
            groups[f"G{n}"] = [e["id"] for e in es if e.get("id")]
            out.append((f"G{n}", key, es))
    return out


def _reconcile_message(entries: list[dict], applied: dict, code: str, model: dict | None
                       ) -> tuple[str, dict[str, list[str]]]:
    ids: dict[str, list[str]] = {}
    rows = _group_rows(_new_groups(applied, ids, set())) + _unknown_rows(applied)
    msg = (f"The surface agent enumerated {len(entries)} entries and declared each one's exposure, "
           f"independently of you. Your resolver disagrees on {applied['disagreements']} of them and answers "
           f"unknown for {applied['unknown']}. The groups:\n" + "\n".join(rows) +
           "\n\nFirst settle every group G<n>, all in one settle call, after reading the handler of a sample "
           "or two where you are not sure:\n"
           "- resolver_wrong (it misses a check, misreads a request shape, ...): the declared exposure stands;\n"
           "- declared_wrong: the resolver is right;\n"
           "- inconsistent_code: both follow real code that disagrees (a likely access-control bug).\n"
           "Then, with the rest of your budget, fix the resolver where it is wrong or answers unknown and install "
           "it with write_access_resolver (samples from these groups); it is run on every entry again and the "
           "disagreements left are shown to you as new groups to settle. Then finish.\n\n"
           + (access_model_text(model) + "\n\n" if model else "") + "Your current resolver:\n" + code)
    return msg, ids


def _reconcile(cfg: AuditConfig, out: Path, entries: list[dict], holder: dict, applied: dict,
               deadline: float | None, deploy: str = "", product: str = "") -> dict:
    """The access agent settles its disagreements with the surface agent (a fresh, short context)."""
    tb: Toolbox = holder["tb"]
    msg, tb.reconcile_groups = _reconcile_message(entries, applied, tb.resolver_code or "", holder.get("model"))
    tb.decisions = {}
    tb.finished = False

    def regroup() -> str:
        applied2 = _apply_resolver(tb, entries, tb.resolver_code, out)
        if "_groups" not in applied2:
            return f"(could not run it on the entries: {applied2.get('error', '')})"
        new = _new_groups(applied2, tb.reconcile_groups, set(tb.decisions))
        head = (f"On all {len(entries)} entries: {applied2['disagreements']} disagreements with the declared "
                f"exposure, {applied2['unknown']} unknown.")
        if not new:
            return head + " No new group to settle."
        return head + " Settle these too (in one settle call):\n" + "\n".join(_group_rows(new))

    tb.on_resolver_installed = regroup
    tb.finish_gates = [(lambda t: any(g not in t.decisions for g in t.reconcile_groups),
                        lambda t: "settle every group first; undecided: "
                                  + ", ".join(g for g in t.reconcile_groups if g not in t.decisions),
                        ["settle"])]
    llm = LLM(cfg, stage="reconcile")
    settle_now = (lambda steps, t: steps >= cfg.reconcile_budget // 2 and any(g not in t.decisions
                                                                               for g in t.reconcile_groups),
                  lambda t: "Half of your budget is used: settle the undecided groups now, in one call: "
                            + ", ".join(g for g in t.reconcile_groups if g not in t.decisions))
    res = run_agent(llm, tb, tool_schemas("access"), access_prompt(cfg.reconcile_budget, deploy, product), msg,
                    cfg.reconcile_budget, out / "transcript-reconcile.jsonl", deadline=deadline,
                    reminders=[settle_now])
    tb.on_resolver_installed = None
    changed = tb.resolver_code != holder.get("resolver")
    holder["resolver"] = tb.resolver_code
    return {"steps": res.get("steps"), "finished": res.get("finished"), "resolver_changed": changed,
            "groups": {g: {"entries": len(ids), **tb.decisions.get(g, {})}
                       for g, ids in tb.reconcile_groups.items()}, "notes": (tb.notes or "")[:2000],
            "_ids": tb.reconcile_groups, "_decisions": tb.decisions}


RECONCILE_S = 240  # wall-clock slice of the reconcile pass, outside the agents' recon share
RECON_EXTENSION = 0.10  # share of the remaining budget follow-up recon passes may add


def _past_half(t0: float, until: float | None, budget: int):
    """Reminder condition: half of the step budget or of the wall-clock window is used and no extractor
    has run. Agents read file after file and are cut by the deadline before writing anything."""
    def cond(steps: int, t: Toolbox) -> bool:
        late = until is not None and time.time() >= t0 + (until - t0) / 2
        return (steps >= budget // 2 or late) and not t.extractors and not t.manual
    return cond


def _followup(cfg: AuditConfig, root: Path, out: Path, tb: Toolbox, left: list[str], deploy: str,
              product: str, until: float | None, holder: dict, llm: LLM, rnd: int) -> list[str]:
    """Enumerate each unenumerated dispatcher in its own fresh context, in parallel; merge the extractors
    into tb. Returns the dispatchers the agents report as still left (new ones they came across)."""
    budget = max(12, cfg.recon_budget // 3)
    model = holder.get("model")
    taken = sorted(tb.extractors)

    def one(i: int, disp: str):
        sub, sub_llm, t0 = Toolbox(cfg, root, out, unit="recon"), LLM(cfg, stage="recon"), time.time()
        msg = (f"Earlier passes enumerated {len(tb.entries())} entries with the extractors "
               f"{', '.join(taken) or '(none)'}. Enumerate ONE dispatcher they left out:\n- {disp}\n\n"
               f"Notes of the earlier passes:\n{tb.notes}\n\n"
               "Read only what this dispatcher needs, write one extractor for it (a new name, not one of the "
               "above), run it with run_extractor, fix what the checks report, then finish; list in "
               "unenumerated any other dispatcher you came across that none of these covers.")
        if model is not None:
            msg += "\n\nAccess-control model (set each entry's exposure from it):\n" + access_model_text(model)
        try:
            run_agent(sub_llm, sub, tool_schemas("recon"), recon_prompt(budget, deploy, product), msg, budget,
                      out / f"transcript-f{rnd}-{i + 1}.jsonl", deadline=until,
                      reminders=[(_past_half(t0, until, budget),
                                  "Half of your time or tool budget is used and no extractor has run. Stop "
                                  "reading: write the extractor for this dispatcher now and run it, then refine.")])
        except Exception:  # one dispatcher failing must not lose the others
            pass
        return sub, sub_llm

    with ThreadPoolExecutor(max_workers=max(1, min(len(left), 6))) as ex:
        subs = list(ex.map(lambda a: one(*a), enumerate(left[:6])))
    still: list[str] = []
    notes = []
    for sub, sub_llm in subs:
        for k in ("prompt", "completion", "cached", "reasoning", "calls"):
            setattr(llm.usage, k, getattr(llm.usage, k) + getattr(sub_llm.usage, k))
        for name, ex in sorted(sub.extractors.items(), key=lambda kv: kv[1].get("run", 0)):
            final = name if name not in tb.extractors else f"{name}-f{rnd}"
            tb._runs = getattr(tb, "_runs", 0) + 1
            tb.extractors[final] = {**ex, "run": tb._runs}
            tb.extractor_best[final] = max(tb.extractor_best.get(final, 0), len(ex["entries"]))
        tb.manual += sub.manual
        still += sub.unenumerated
        if sub.notes:
            notes.append(sub.notes)
    if notes:
        tb.notes = (tb.notes + "\n\n" + "\n\n".join(notes)).strip()
    return still


def recon(cfg: AuditConfig, root: Path, out: Path, deploy: str = "", product: str = "",
          deadline: float | None = None, hard_deadline: float | None = None) -> dict:
    """Two agents in parallel: one maps the attack surface (entries.json), one the access-control model.
    The model is sent to the surface agent as soon as it is recorded, for the entries' exposure."""
    out.mkdir(parents=True, exist_ok=True)
    t_recon = time.time()
    try:
        snapshot_codegraph(root, out)
    except Exception:
        pass
    tb = Toolbox(cfg, root, out, unit="recon")
    user = (f"Files by extension (vendored and VCS directories left out): {_ext_counts(root)}\n\n"
            f"Top-level layout:\n{tb.list_dir('.', 2)}\n\n"
            f"codegraph route evidence:\n{tb.codegraph_routes(limit=25)}")
    holder: dict = {"model": None, "done": threading.Event()}
    access = threading.Thread(target=_access_agent, daemon=True,
                              args=(cfg, root, out, deploy, product, deadline, user, holder))
    access.start()
    assets_holder: dict = {}
    assets_thread = threading.Thread(target=_assets_agent, daemon=True,
                                     args=(cfg, root, out, deploy, product, deadline, user, tb.entries,
                                           assets_holder))
    assets_thread.start()

    regressions: list[str] = []

    def regressed(t: Toolbox) -> bool:
        regressions[:] = t.extractor_regressions()
        return bool(regressions)

    tb.finish_gates = [(lambda t: not t.extractors and not t.manual,
                        "no extractor has run. Your context already holds what the dispatchers need (a fresh "
                        "pass would have to read it all again): write an extractor for the dispatcher you "
                        "understand best, run it with run_extractor, and list the others in unenumerated",
                        ["run_extractor"]),
                       (lambda t: (t.extractors or t.manual) and t.coverage is None,
                        "run check_coverage once with a pattern for how this project reads request data",
                        ["check_coverage"]),
                       (regressed, lambda t: "; ".join(regressions) + ". Fix the regression and run the extractor "
                        "again, or finish again if the smaller result is the right one.")]
    llm = LLM(cfg, stage="recon")
    no_extractor_yet = (_past_half(t_recon, deadline, cfg.recon_budget),
                        "Half of your time or tool budget is used and no extractor has run. Stop reading: write an "
                        "extractor for the dispatcher you understand best and run it now, then refine.")
    model_ready = (lambda steps, t: holder["done"].is_set() and holder["model"] is not None,
                   lambda t: "The access-control model is ready. Use it to set each entry's exposure (the "
                             "least privileged principal that can call it); re-run extractors if needed:\n"
                             + access_model_text(holder["model"]))
    res = run_agent(llm, tb, tool_schemas("recon"), recon_prompt(cfg.recon_budget, deploy, product), user,
                    cfg.recon_budget, out / "transcript.jsonl", deadline=deadline,
                    reminders=[no_extractor_yet, model_ready])
    passes = 1
    # Understood the dispatch but enumerated nothing: a second, fresh context that starts from the agent's
    # own notes and only has to turn them into extractors.
    if not tb.entries() and tb.notes and (deadline is None or time.time() < deadline - 120):
        budget2 = max(10, cfg.recon_budget // 2)
        tb.finished = False
        res2 = run_agent(
            llm, tb, tool_schemas("recon"), recon_prompt(budget2, deploy, product),
            "An earlier pass worked out how requests reach code but did not enumerate any entries. Its "
            f"notes:\n{tb.notes}\n\nWrite one extractor per dispatcher described there, run each with "
            "run_extractor, fix what the checks report, then call finish with the notes (updated).",
            budget2, out / "transcript-2.jsonl", deadline=deadline,
            reminders=[model_ready] if holder["model"] is None else [])
        res = {k: (res.get(k, 0) + res2.get(k, 0)) if isinstance(res2.get(k), (int, float)) and k != "finished"
               else res2.get(k) for k in res2}
        passes = 2
    hard = hard_deadline or deadline
    # The reconcile pass runs on the entries enumerated so far, while the follow-up passes run: both take
    # minutes, and every minute before the review starts is a minute less of review.
    early: dict = {}
    snap = [dict(e) for e in tb.entries()]  # taken here: the follow-up passes add to tb meanwhile

    def reconcile_early() -> None:
        holder["done"].wait(timeout=None if deadline is None else max(0.0, deadline + 60 - time.time()))
        for i, e in enumerate(snap):
            e["id"] = f"E{i + 1}"
        applied = _apply_resolver(tb, snap, holder.get("resolver"), out)
        if not (applied.get("disagreements") or applied.get("unknown")) or holder.get("tb") is None \
                or (hard is not None and time.time() >= hard - 3 * RECONCILE_S):
            return
        early["before"] = {k: applied.get(k) for k in ("disagreements", "unknown")}
        try:
            rec = _reconcile(cfg, out, snap, holder, applied, time.time() + RECONCILE_S, deploy, product)
            by_id = {e["id"]: _req_key(e) for e in snap}
            rec["_keys"] = {g: [by_id[i] for i in ids if i in by_id] for g, ids in rec.pop("_ids").items()}
            early["rec"] = rec
        except Exception as e:  # keep the unreconciled answers (declared exposure stands)
            early["rec"] = {"error": f"{type(e).__name__}: {e}"}

    rec_thread = threading.Thread(target=reconcile_early, daemon=True)
    rec_thread.start()
    # Dispatchers the agent found but left unenumerated: follow-up passes, one fresh agent per dispatcher,
    # all in parallel (dispatchers are independent, and one context reading all of them runs out of time
    # before it writes anything). A missing dispatcher hides a whole part of the surface, so these may run
    # past the recon share by up to RECON_EXTENSION of the remaining budget.
    extend_to = deadline if hard_deadline is None or deadline is None else \
        min(hard_deadline, deadline + RECON_EXTENSION * (hard_deadline - t_recon))
    rounds = 0
    while tb.unenumerated and rounds < 2 and (extend_to is None or time.time() < extend_to - 120):
        left, n_before = tb.unenumerated, len(tb.entries())
        tb.unenumerated = []
        rounds += 1
        found = _followup(cfg, root, out, tb, left, deploy, product, extend_to, holder, llm, rounds)
        passes += 1
        tb.unenumerated = [x for x in found if x not in left]  # a dispatcher it still could not do is not retried
        if len(tb.entries()) == n_before:  # no progress: stop rather than loop
            break
    rec_thread.join(timeout=None if hard is None else max(0.0, min(hard, time.time() + RECONCILE_S + 90)
                                                           - time.time()))
    entries = tb.entries()
    source = "agent"
    if not entries:  # the agent produced nothing usable: keep codegraph's routes so review can start
        db = codegraph_db(root)
        entries = [{"route": r["route"], "method": r["method"], "handler_file": r["file"],
                    "handler": r.get("handler", ""), "exposure": "unknown", "origin": "codegraph"}
                   for r in (codegraph_routes(db, root) if db else [])]
        source = "codegraph-fallback"
    for i, e in enumerate(entries):
        e["id"] = f"E{i + 1}"
        e["resolved"] = tb._check_entry(e) is None
    resolver = _apply_resolver(tb, entries, holder.get("resolver"), out)
    reconcile = early.get("rec")
    if reconcile is not None and "_keys" in reconcile:
        id_of = {_req_key(e): e["id"] for e in entries}
        groups = {g: [id_of[k] for k in keys if k in id_of] for g, keys in reconcile.pop("_keys").items()}
        reconcile["applied"] = _apply_decisions(entries, groups, reconcile.pop("_decisions"))
    if reconcile is not None:
        reconcile["before"] = early.get("before")
    scoped_lowered: Final = _scoped_exposure(entries, (holder.get("model") or {}).get("scoped_roles"))
    _rank_principals(entries, (holder.get("model") or {}).get("ladder"))
    resolver = {k: v for k, v in resolver.items() if not k.startswith("_")}
    (out / "entries.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False))
    assets_thread.join(timeout=None if hard is None else max(0.0, min(hard, (deadline or hard) + 90) - time.time()))
    assets_m = _build_assets(assets_holder, entries, out)
    by_exp = collections.Counter(e["exposure"] for e in entries)
    m = _metrics(llm, {"stage": "recon", "source": source, "entries": len(entries),
                       "resolved": sum(e["resolved"] for e in entries), "by_exposure": dict(by_exp),
                       "extractors": {k: len(v["entries"]) for k, v in tb.extractors.items()},
                       "manual_entries": len(tb.manual), "coverage": tb.coverage, "notes": tb.notes,
                       "access_model": holder["model"], "access_error": holder.get("error"),
                       "resolver": resolver, "reconcile": reconcile, "assets": assets_m,
                       "scoped_role_entries": scoped_lowered,
                       "passes": passes, **res})
    for h, name in ((holder, "access_agent"), (assets_holder, "assets_agent")):  # every agent's tokens count
        if h.get("llm") is None:
            continue
        a = _metrics(h["llm"], h.get("res") or {})
        for k in ("prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens", "llm_calls"):
            m[k] = m.get(k, 0) + a.get(k, 0)
        m[name] = {k: a.get(k) for k in ("steps", "wall_s", "tool_counts", "finished", "prompt_tokens", "llm_calls")}
    (out / "recon.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    return m


# ----------------------------------------------------------------- review

SPLIT_ROUTES = 8  # a handler serving more routes than this is generic: review it per resource


def _resource_key(route: str) -> str:
    """The route without its parameters and trailing id-like segments: /apis/g/v1/posts/{name}/x -> /apis/g/v1/posts."""
    parts = [p for p in re.split(r"[/?]", route or "") if p]
    while parts and (parts[-1].startswith(("{", ":", "<", "*")) or "{" in parts[-1]):
        parts.pop()
    keep = []
    for p in parts:
        if p.startswith(("{", ":", "<", "*")):
            break
        keep.append(p)
    return "/" + "/".join(keep)


def _handler_id(e: dict) -> tuple:
    """What identifies the code an entry runs: file, name and first line. A name alone does not identify
    anonymous code (callbacks, lambdas, closures: every route of a file may be 'app.post'), so the
    handler_line, or else the registration line in the same file, is part of the identity."""
    hf, h = e.get("handler_file") or "", e.get("handler") or ""
    line = e.get("handler_line") or 0
    if not line and e.get("declared_at"):
        f, _, ln = str(e["declared_at"]).rpartition(":")
        if f.lstrip("./") == hf and ln.isdigit():
            line = int(ln)
    return (hf, h, int(line or 0), "" if hf else e.get("route"))


def _units(entries: list[dict]) -> list[dict]:
    """One unit per handler (several routes can run the same code), most exposed first.

    A generic handler (one function serving many resources, e.g. a CRUD dispatcher) is split into one
    unit per resource: access control and object ownership differ per resource, and one context cannot
    judge dozens of them.
    """
    # One code path is reviewed once: entries that share a handler or a request (the same method and route
    # described by two extractors, e.g. once at the route file and once at the controller) are one unit.
    parent = list(range(len(entries)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first: dict[tuple, int] = {}
    for i, e in enumerate(entries):
        for key in (("h", *_handler_id(e)), ("r", e.get("method", "ANY"), e.get("route"))):
            if key in first:
                parent[find(i)] = find(first[key])
            else:
                first[key] = i
    by_handler: dict[tuple, list[dict]] = {}
    for i, e in enumerate(entries):
        root = entries[find(i)]
        by_handler.setdefault(_handler_id(root), []).append(e)
    groups: list[tuple[str, str, list[dict], bool]] = []
    by_res: dict[str, list[dict]] = {}  # routes of generic handlers, by resource (all their verbs together)
    for (hf, h, _line, _), es in by_handler.items():
        if len(es) > SPLIT_ROUTES:
            for e in es:
                by_res.setdefault(_resource_key(e.get("route", "")), []).append(e)
        else:
            groups.append((hf, h, es, False))
    for es in by_res.values():
        groups.append((es[0].get("handler_file") or "", es[0].get("handler") or "", es, True))
    units = []
    for hf, h, es, generic in groups:
        exp = min((e.get("exposure", "unknown") for e in es), key=lambda x: EXPOSURE_RANK.get(x, 1))
        units.append({"handler_file": hf, "handler": h, "handler_line": _handler_id(es[0])[2] or None,
                      "exposure": exp, "entries": es, "generic": generic,
                      "handlers": sorted({f"{e.get('handler_file')}::{e.get('handler')}" for e in es}),
                      "resolved": all(e.get("resolved", True) for e in es)})
    # within a level: entries where the two readings of the access rules disagree first
    # within a level: lower on the project's principal ladder first, then entries where the two readings
    # of the access rules disagree
    units.sort(key=lambda u: (EXPOSURE_RANK.get(u["exposure"], 1), not u["resolved"],
                              min((e.get("principal_rank", 99) for e in u["entries"]), default=99),
                              not any(e.get("exposure_declared") for e in u["entries"]),
                              u["entries"][0].get("route", "")))
    return units


def _route_key(route: str, n: int = 2) -> str:
    return "/".join([p for p in re.split(r"[/?]", route or "") if p][:n])


def _peers(unit: dict, entries: list[dict]) -> list[str]:
    """Similar entries for access-control comparison: same route prefix, then same handler directory."""
    keys = {_route_key(e.get("route", "")) for e in unit["entries"]}
    hdir = os.path.dirname(unit["handler_file"])
    own = {id(e) for e in unit["entries"]}
    near = [e for e in entries if id(e) not in own and _route_key(e.get("route", "")) in keys]
    near += [e for e in entries if id(e) not in own and e not in near and hdir
             and os.path.dirname(e.get("handler_file") or "") == hdir]
    return [f"{e.get('method', 'ANY')} {e.get('route')} -> {e.get('handler_file')}::{e.get('handler', '')} "
            f"auth={e.get('auth', '?')} exposure={e.get('exposure')}" for e in near[:PEERS_MAX]]


def _handler_snippet(root: Path, unit: dict, lines: int = 70) -> str:
    """The handler's code, so the reviewer starts reading the right place."""
    f = root / unit["handler_file"] if unit["handler_file"] else None
    if f is None or not f.is_file():
        return ""
    text = f.read_text(errors="ignore").splitlines()
    name = re.escape((unit["handler"] or "").split("::")[-1].split(".")[-1])
    start = 0
    if unit.get("handler_line"):
        start = max(0, min(len(text) - 1, int(unit["handler_line"]) - 1))
    elif name:
        rx = re.compile(rf"(function|def|func|fn|sub)\s+&?{name}\b|\b{name}\s*[:=]\s*(async\s*)?(function|\()"
                        rf"|\b(public|private|protected|static|async)\b[^;=]*\b{name}\s*\(")
        start = next((i for i, ln in enumerate(text) if rx.search(ln)), 0)
    body = "\n".join(f"{i + 1:5d}| {text[i]}" for i in range(start, min(len(text), start + lines)))
    return f"{unit['handler_file']} lines {start + 1}-{min(len(text), start + lines)} of {len(text)}:\n{body}"


class _Shared:
    """What every review unit of a run shares: boards other units write to, prompts, and lookups."""

    def __init__(self, cfg: AuditConfig, root: Path, entries: list[dict], deploy: str, product: str,
                 surface_notes: str, access_model: dict | None, resolver: str | None, assets: dict,
                 deadline: float | None):
        self.entries, self.resolver, self.deadline = entries, resolver, deadline
        self.facts, self.issues, self.coverage = FactBook(root), IssueBoard(), assets_map.Coverage()
        self.leads = assets_map.LeadBoard()
        self.reach = assets_map.Reach(root, entries)
        self.systems = {k: review_prompt(cfg.review_budget if k != "design" else cfg.design_budget, deploy,
                                         product, surface_notes, access_model, k)
                        for k in ("entry", "operation", "design", "lead")}
        self.known = {(str(e.get("method") or "GET").upper(), str(e.get("route"))): e for e in entries}
        self.recipes = {r["name"]: r for r in assets.get("recipes") or []}
        self.guarded: dict[str, list[dict]] = collections.defaultdict(list)  # recipe -> sites with its guard
        for site in assets.get("sites") or []:
            if site.get("guard_at"):
                self.guarded[site.get("guard_recipe") or site["recipe"]].append(site)


def _entry_brief(root: Path, unit: dict, entries: list[dict], guarded: dict[str, list[dict]]) -> str:
    entry_view = {"routes": [{**{k: e.get(k) for k in ("id", "method", "route", "kind", "auth", "exposure",
                                                        "least_principal", "exposure_declared", "who_can_call",
                                                        "declared_at") if e.get(k)},
                              **_declared_code(root, e)} for e in unit["entries"][:20]],
                  "more_routes": max(0, len(unit["entries"]) - 20),
                  "handler_file": unit["handler_file"], "handler": unit["handler"]}
    if unit.get("generic"):
        entry_view["handlers"] = unit["handlers"][:10]
        entry_view["note"] = ("these handlers are shared by many resources; review them for the resource of "
                              "these routes only (its access rules, ownership and stored data)")
    peers = _peers(unit, entries)
    return "\n\n".join(x for x in (
        "Entry to review:\n" + json.dumps(entry_view, ensure_ascii=False),
        ("Similar entries (peers):\n" + "\n".join(peers)) if peers else "",
        assets_map.handler_operations(unit, guarded)) if x)


def _unit_view(root: Path, unit: dict, sh: _Shared) -> tuple[str, str, str]:
    """(id for facts and issues, the unit's description, the code to start reading)."""
    kind = unit.get("kind", "entry")
    if kind == "operation":
        first = unit["sites"][0]
        siblings = [x for site in unit["sites"] for x in sh.guarded.get(site["recipe"], [])
                    if x["file"] != unit["handler_file"]]
        start = max(unit["span"][0], first["line"] - 30)
        code = _handler_snippet(root, {"handler_file": unit["handler_file"], "handler": "", "handler_line": start})
        return (f"op:{assets_map.site_key(first)}", assets_map.operation_brief(unit, siblings, sh.recipes), code)
    if kind == "design":
        return f"design:{unit['handler']}", assets_map.design_brief(unit), ""
    if kind == "lead":
        return f"lead:{unit['handler']}", assets_map.lead_brief(unit), ""
    return (",".join(e["id"] for e in unit["entries"][:5]), _entry_brief(root, unit, sh.entries, sh.guarded),
            _handler_snippet(root, unit))


_SNIPPET_SPAN: Final = re.compile(r"^(\S+) lines (\d+)-(\d+) of ")


def _review_unit(cfg: AuditConfig, root: Path, out: Path, unit: dict, sh: _Shared) -> dict:
    kind = unit.get("kind", "entry")
    if kind == "operation" and sh.coverage.covered(unit):
        # an entry's reviewer read this function in full or traced the operation: its card and findings
        # are shared
        return {"kind": kind, "covered": True, "findings": [], "cards": [], "prompt_tokens": 0,
                "completion_tokens": 0, "cached_tokens": 0, "steps": 0}
    out.mkdir(parents=True, exist_ok=True)
    uid, brief, code = _unit_view(root, unit, sh)
    tb = Toolbox(cfg, root, out, facts=sh.facts, unit=uid, issues=sh.issues)
    tb.resolver_code, tb.known_entries, tb.coverage = sh.resolver, sh.known, sh.coverage
    tb.reach = sh.reach
    if kind == "entry":  # what an entry reviewer reads counts as reviewed for the operations in it
        tb.records_reads = True
        if (shown := _SNIPPET_SPAN.match(code)) is not None:
            sh.coverage.read(uid, shown.group(1), int(shown.group(2)), int(shown.group(3)))
    budget = cfg.review_budget
    if kind == "design":
        budget = cfg.design_budget
        left = lambda t: [k for k in assets_map.IDENTITY_CHECKLIST if k not in t.design]  # noqa: E731
        tb.finish_gates = [(lambda t: bool(left(t)), lambda t: "answer with record_design: " + ", ".join(left(t)),
                            ["record_design"])]
    llm = LLM(cfg, stage="review")
    user = "\n\n".join(x for x in (brief, sh.facts.prompt_block(), sh.issues.prompt_block(), code) if x)
    seen_facts = {f["id"] for f in sh.facts.facts}
    seen_issues = {i["id"] for i in sh.issues.issues}

    def updates() -> str | None:
        """What other units verified or reported since this one started (units run in parallel)."""
        rows = [f"- {f['id']}: {f['statement']}" for f in sh.facts.since(seen_facts, uid)]
        rows += [f"- {i['id']} ({i['cwe']}, {i['where']}): {i['root_cause']} -> use same_as={i['id']} if this "
                 "unit has the same root cause" for i in sh.issues.since(seen_issues, uid)]
        return ("New from reviewers working in parallel:\n" + "\n".join(rows)) if rows else None

    res = run_agent(llm, tb, tool_schemas("design" if kind == "design" else "review"), sh.systems[kind], user,
                    budget, out / "transcript.jsonl", deadline=sh.deadline, updates=updates)
    ids = [e["id"] for e in unit["entries"]]
    where = f"identity:{unit['handler']}" if kind == "design" or (kind == "lead" and "answer" in unit) else \
        f"lead:{unit['handler']}" if kind == "lead" else f"{unit['handler_file']}::{unit['handler']}"
    for x in tb.findings + tb.cards:
        x["entries"], x["handler"], x["unit_kind"] = ids, where, kind
    out_extra: dict = {}
    if kind == "design":
        g = unit["subsystem"]
        answers = [tb.design[k] for k in assets_map.IDENTITY_CHECKLIST if k in tb.design]
        out_extra["design"] = [{"subsystem": g["name"], "unit": unit["handler"], "kind": g["kind"], "entries": ids,
                                "files": g["files"], "settings": g["settings"], "complete": not left(tb),
                                "items": answers}]
        out_extra["followups"] = assets_map.follow_ups(unit, answers, reported=bool(tb.findings))
    if kind in ("entry", "operation"):  # what this review left open is settled next, in a fresh context
        out_extra["followups"] = sh.leads.follow_ups(unit, tb.cards)
    if kind == "lead" and "answer" in unit:
        out_extra["lead_of"] = {"unit": unit["handler"].rsplit(": ", 1)[0], "item": unit["answer"]["item"],
                                "findings": len(tb.findings),
                                "conclusion": next((str(c.get("function") or "")[:300] for c in tb.cards), "")}
    return {"kind": kind, "findings": tb.findings, "cards": tb.cards, **out_extra, **_metrics(llm, res)}


def _exposure_check(cards: list[dict], entries: list[dict]) -> dict:
    """How often the reviewers, having read the handler, agree with recon's exposure and the resolver."""
    by_id = {e["id"]: e for e in entries}
    c: collections.Counter = collections.Counter()
    for card in cards:
        if card.get("unit_kind", "entry") != "entry":  # an operation's callers are other paths
            continue
        seen = card.get("least_privileged_caller")
        es = [by_id[i] for i in card.get("entries", []) if i in by_id]
        if seen not in (*EXPOSURES, "denied") or not es:
            continue
        e = es[0]
        c["cards"] += 1
        c["recon_agrees"] += (e.get("exposure_declared") or e.get("exposure")) == seen
        if e.get("who_can_call"):
            c["resolver_answered"] += 1
            c["resolver_agrees"] += e["who_can_call"]["least_privileged"] == seen
    return dict(c)


def review(cfg: AuditConfig, root: Path, out: Path, entries: list[dict], deploy: str = "", product: str = "",
           surface_notes: str = "", deadline: float | None = None, access_model: dict | None = None,
           resolver: str | None = None, assets: dict | None = None) -> dict:
    """Review every unit: identity design units first (few, and nothing else covers them), then entry
    units with operation units interleaved; a follow-up for what a unit left open (a design conclusion,
    an open hypothesis) runs as soon as that unit ends."""
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    assets = assets or {}
    units = [{**u, "kind": "entry"} for u in _units(entries)]
    sites = assets.get("sites") or []
    ops = assets_map.operation_units(sites, entries, units, EXPOSURE_RANK)
    designs = assets_map.design_units(assets.get("identity") or [], entries, sites, cfg.design_units_max)
    order = designs + assets_map.interleave(units, ops, cfg.operation_every)
    sh = _Shared(cfg, root, entries, deploy, product, surface_notes, access_model, resolver, assets, deadline)
    results, skipped = _schedule(order, lambda i, u: _review_unit(cfg, root, out / f"unit-{i:04d}", u, sh),
                                 cfg.workers, deadline, cfg.stopped)
    findings = [f for r in results for f in r["findings"]]
    cards = [c for r in results for c in r["cards"]]
    worksheet = [d for r in results for d in r.get("design") or []]
    for r in results:  # what the follow-up of each open worksheet item concluded
        lead = r.get("lead_of")
        for d in worksheet if lead else ():
            for item in d["items"]:
                if d["unit"] == lead["unit"] and item["item"] == lead["item"]:
                    item["follow_up"] = {"findings": lead["findings"], "conclusion": lead["conclusion"]}
    left = collections.defaultdict(list)
    for u in skipped:
        left[u.get("kind", "entry")].append(u)
    not_reviewed = [e["id"] for u in left["entry"] for e in u["entries"]]
    # Suspicions a reviewer could not verify within its budget: kept apart from findings, for follow-up.
    open_leads = [{"entries": c.get("entries"), "handler": c.get("handler"), "lead": str(lead)[:500]}
                  for c in cards for lead in (c.get("open_leads") or []) if str(lead).strip()]
    (out / "findings.json").write_text(json.dumps({
        "findings": findings, "open_leads": open_leads, "design_worksheet": worksheet,
        "not_reviewed": not_reviewed,
        "not_reviewed_operations": [assets_map.site_key(x) for u in left["operation"] for x in u["sites"]],
        "not_reviewed_design": [u["handler"] for u in left["design"]]}, indent=1, ensure_ascii=False))
    (out / "cards.json").write_text(json.dumps(cards, indent=1, ensure_ascii=False))
    (out / "facts.json").write_text(json.dumps(sh.facts.facts, indent=1, ensure_ascii=False))
    (out / "issues.json").write_text(json.dumps(sh.issues.issues, indent=1, ensure_ascii=False))
    s = lambda k: sum(r.get(k, 0) for r in results)  # noqa: E731
    kinds = collections.Counter(r.get("kind", "entry") for r in results if not r.get("covered"))
    m = {"stage": "review", "entries": len(entries), "units": len(units), "reviewed_units": kinds["entry"],
         "skipped_units": len(left["entry"]), "not_reviewed_entries": len(not_reviewed),
         "operation_units": len(ops), "reviewed_operation_units": kinds["operation"],
         "operation_units_covered_by_entry_review": sum(1 for r in results if r.get("covered")),
         "design_units": len(designs), "reviewed_design_units": kinds["design"],
         "follow_up_units": kinds["lead"],
         "hub_operation_units": sum(1 for u in ops if u.get("hub")),
         "design_items": dict(collections.Counter(i["status"] for d in worksheet for i in d["items"])),
         "prompt_tokens": s("prompt_tokens"), "completion_tokens": s("completion_tokens"),
         "cached_tokens": s("cached_tokens"), "reasoning_tokens": s("reasoning_tokens"), "steps": s("steps"),
         "errors": sum(1 for r in results if r.get("error")), "facts": len(sh.facts.facts),
         # units that stopped because the model kept replying with nothing (its reasoning used the whole
         # output allowance even after LLM.chat widened it), and requests sent again with a wider one
         "units_ended_silent": dict(collections.Counter(r.get("kind", "entry") for r in results
                                                         if r.get("ended_silent"))),
         "output_widened": s("widened"),
         "cards": len(cards), "n_findings": len(findings), "root_causes": len(sh.issues.issues),
         "findings_by_unit_kind": dict(collections.Counter(f.get("unit_kind") for f in findings)),
         "authz_verdicts": dict(collections.Counter(c.get("authz_verdict") for c in cards)),
         "exposure_check": _exposure_check(cards, entries),
         "workers": cfg.workers, "llm_limiter": limiter_for(cfg).stats(),
         "wall_s": round(time.time() - t0, 1)}
    (out / "metrics.json").write_text(json.dumps(m, indent=1))
    return m


# ----------------------------------------------------------------- both

_ANON_NAMES = {"", "closure", "anonymous", "lambda", "function", "fn", "handler", "callback", "default"}


def _entry_key(e: dict) -> tuple:
    """What makes entries of two independent recon runs the same door: the code it runs and the request
    that reaches it. Runs spell the same thing differently (a qualified or bare handler name, the line of
    the docblock or of the function, 'GET/POST' or 'GET|POST'), so the key keeps only what does not vary:
    the file, the bare function name and the route. The line stays only for anonymous handlers, where it
    is the identity."""
    hf = str(e.get("handler_file") or "").lstrip("./")
    name = re.sub(r"\(.*$", "", re.split(r"::|->|\\|\.|#|@", str(e.get("handler") or ""))[-1]).strip().lower()
    anon = name in _ANON_NAMES or not re.fullmatch(r"[a-z_$][\w$]*", name)
    return ((hf, name, _handler_id(e)[2] if anon else 0), _resource_key(e.get("route", "")))


def _merge_run(merged: dict, entries: list[dict]) -> set:
    """Adds one run's entries to the union; returns the run's keys as matched to the union. A named handler
    that occurs once in the run and once in the union is the same door even if the two runs spelled its
    route differently."""
    code_count = collections.Counter(_entry_key(e)[0] for e in entries)
    union_by_code: dict[tuple, list[tuple]] = {}
    for k in merged:
        union_by_code.setdefault(k[0], []).append(k)
    keys = set()
    for e in entries:
        k = _entry_key(e)
        if k not in merged:
            alt = union_by_code.get(k[0], [])
            if k[0][1] and not k[0][2] and code_count[k[0]] == 1 and len(alt) == 1:
                k = alt[0]
        if k not in merged or (e.get("resolved") and not merged[k].get("resolved")):
            merged[k] = e
        keys.add(k)
    return keys


def _model_score(rec: dict) -> tuple:
    """How complete a recon's access model is, to choose which run's model and resolver lead the merge."""
    am = rec.get("access_model") or {}
    return (bool((rec.get("resolver") or {}).get("installed")), bool(am.get("ladder")),
            bool(am.get("shared_protections")), len(json.dumps(am)), rec.get("entries", 0))


def converge_recon(cfg: AuditConfig, root: Path, out: Path, deploy: str = "", product: str = "",
                   deadline: float | None = None, hard_deadline: float | None = None) -> dict:
    """Run recon several times (each a fresh context) and union the entries they enumerate: a single
    run sees only part of a large surface and the misses are what the review never gets to see. Stops
    adding runs once one grows the union by less than recon_converge_threshold, or the budget runs low.
    The access model and resolver are taken from the most complete run and re-applied to the whole
    union, so exposure, who_can_call and least_principal are consistent across it."""
    runs = max(1, cfg.recon_runs)
    if runs == 1:
        return recon(cfg, root, out, deploy, product, deadline, hard_deadline)
    hard = hard_deadline or deadline
    share = cfg.recon_share if deadline is None else (deadline - time.time()) / max(1, runs)
    merged: dict[tuple, dict] = {}
    recs: list[dict] = []
    growth: list[dict] = []
    run_keys: list[set] = []
    for i in range(runs):
        sub = out if i == 0 else out.parent / f"{out.name}-{i + 1}"
        r_deadline = None if deadline is None else time.time() + share
        rec = recon(cfg, root, sub, deploy, product, r_deadline, hard_deadline=hard)
        recs.append(rec)
        before = len(merged)
        run_keys.append(_merge_run(merged, json.loads((sub / "entries.json").read_text())))
        added = len(merged) - before
        growth.append({"run": i + 1, "run_entries": rec.get("entries", 0), "union": len(merged), "added": added})
        if i and added <= cfg.recon_converge_threshold * before:
            break  # converged: the last run barely grew the union
        if hard is not None and time.time() > hard - 2 * share:
            break  # not enough budget left for another full run

    entries = list(merged.values())
    primary = max(range(len(recs)), key=lambda i: _model_score(recs[i]))
    pdir = out if primary == 0 else out.parent / f"{out.name}-{primary + 1}"
    model = recs[primary].get("access_model")
    rf = pdir / "resolver.py"
    resolver_code = rf.read_text() if rf.exists() else None

    # re-number, re-check, and re-apply the chosen resolver to the full union
    tb = Toolbox(cfg, root, out, unit="merge")
    for i, e in enumerate(entries):
        e["id"] = f"E{i + 1}"
        e["resolved"] = tb._check_entry(e) is None
        e.pop("exposure_declared", None)
    resolver = _apply_resolver(tb, entries, resolver_code, out) if resolver_code else {}
    _rank_principals(entries, (model or {}).get("ladder"))
    resolver = {k: v for k, v in resolver.items() if not k.startswith("_")}
    if resolver_code:
        (out / "resolver.py").write_text(resolver_code)
    (out / "entries.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False))

    # capture-recapture: from the overlap of the two largest runs, estimate the true surface size (keys
    # as matched while merging; out/entries.json now holds the union, not the first run)
    estimate = None
    if len(run_keys) >= 2:
        a, b = sorted(run_keys, key=len, reverse=True)[:2]
        inter = len(a & b)
        estimate = round(len(a) * len(b) / inter) if inter else None

    m = dict(recs[primary])
    tok = lambda k: sum(r.get(k, 0) or 0 for r in recs)  # noqa: E731
    m.update({"entries": len(entries), "by_exposure": dict(collections.Counter(e["exposure"] for e in entries)),
              "resolved": sum(e["resolved"] for e in entries), "resolver": resolver,
              "converge": {"runs": len(recs), "growth": growth, "union": len(entries),
                           "primary_run": primary + 1, "estimated_surface": estimate},
              "prompt_tokens": tok("prompt_tokens"), "completion_tokens": tok("completion_tokens"),
              "cached_tokens": tok("cached_tokens"), "llm_calls": tok("llm_calls")})
    (out / "recon.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    return m


def run(cfg: AuditConfig, root: Path, out: Path, deploy: str = "", product: str = "",
        start: float | None = None, deadline: float | None = None) -> dict:
    """recon (reused when out/recon/entries.json exists, with its assets.json when there is one), review,
    then the refutation check of every reported root cause, within one wall-clock budget (the check keeps
    verify_share of it)."""
    start = start or time.time()
    deadline = deadline or start + cfg.time_budget_s
    ef = out / "recon" / "entries.json"
    if ef.exists():
        rec = json.loads((out / "recon" / "recon.json").read_text()) if (out / "recon" / "recon.json").exists() else {}
        rec.setdefault("reused", True)
    else:
        rec = converge_recon(cfg, root, out / "recon", deploy, product,
                             start + cfg.recon_share * (deadline - start), hard_deadline=deadline)
    entries = json.loads(ef.read_text())
    rf = out / "recon" / "resolver.py"
    resolver = rf.read_text() if rf.exists() else None
    af = out / "recon" / "assets.json"
    assets = json.loads(af.read_text()) if af.exists() else None
    review_deadline = deadline - cfg.verify_share * (deadline - start)
    rv = review(cfg, root, out / "review", entries, deploy, product, rec.get("notes") or "", review_deadline,
                rec.get("access_model"), resolver, assets)
    from .verify import verify  # verify imports this module
    vf = verify(cfg, root, out / "review", deploy, product, rec.get("access_model"), resolver, deadline)
    tok = lambda m, k: (m or {}).get(k, 0) or 0  # noqa: E731
    m = {"recon": rec, "review": rv, "verify": vf,
         "models": {s: cfg.model_for(s) for s in ("recon", "access", "reconcile", "review", "verify")},
         "total_tokens": sum(tok(x, "prompt_tokens") + tok(x, "completion_tokens") for x in (rec, rv, vf)),
         "total_cached_tokens": sum(tok(x, "cached_tokens") for x in (rec, rv, vf)),
         "total_wall_s": round(time.time() - start, 1), "time_budget_s": round(deadline - start)}
    (out / "metrics.json").write_text(json.dumps(m, indent=1, ensure_ascii=False))
    return m

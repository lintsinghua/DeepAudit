"""A minimal tool-calling loop with a hard step budget and transcript logging."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from .llm import LLM, parse_args
from .toolbox import Toolbox


def _compact(messages: list[dict], keep_last: int = 14, limit_chars: int = 160_000) -> None:
    """Shorten old tool outputs once the transcript gets large."""
    if sum(len(m.get("content") or "") for m in messages) < limit_chars:
        return
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    for i in tool_idx[:-keep_last]:
        c = messages[i]["content"]
        if len(c) > 400:
            messages[i]["content"] = c[:400] + "\n...[older tool output elided]"


# (condition(steps, toolbox), message or message(toolbox)); sent once, the first time the condition holds
Reminder = tuple[Callable[[int, Toolbox], bool], "str | Callable[[Toolbox], str]"]


def _invoke(tb: Toolbox, spec: dict, args: dict) -> str:
    """Call a tool with the arguments its schema declares. Arguments it does not declare are dropped and
    named in the result, and missing required ones are asked for, instead of the whole call failing on a
    TypeError: a model that adds a field it invented should still get its call run."""
    name: Final = spec["name"]
    params: Final = spec.get("parameters") or {}
    declared: Final = set(params.get("properties") or {})
    extra: Final = sorted(str(k) for k in args if k not in declared)
    missing: Final = [k for k in params.get("required") or [] if k not in args]
    if missing:
        return f"error: {name} needs {', '.join(missing)}; send the call again with them"
    try:
        result = str(getattr(tb, name)(**{k: v for k, v in args.items() if k in declared}))
    except Exception as e:  # tool errors go back to the model
        result = f"error: {type(e).__name__}: {e}"
    return result + (f"\n(ignored argument(s) this tool does not have: {', '.join(extra)})" if extra else "")


def _unmet(tb: Toolbox) -> list[tuple[str, list[str]]]:
    """Finish gates still closed: (message, names of the tools that satisfy it, if the gate names any)."""
    out = []
    for cond, msg, *rest in tb.finish_gates:
        if cond(tb):
            out.append((msg(tb) if callable(msg) else msg, list(rest[0]) if rest else []))
    return out


def run_agent(llm: LLM, tb: Toolbox, tools: list[dict], system: str, user: str, budget: int,
              log_path: Path, deadline: float | None = None,
              reminders: list[Reminder] | None = None,
              updates: Callable[[], str | None] | None = None) -> dict:
    """Run until finish, the step budget, or the wall-clock deadline (epoch seconds).

    Near the deadline the agent is told to report and finish; 60 s after it the loop stops.
    `reminders` are (condition(steps, toolbox), message) pairs; each message is sent once, the first
    time its condition holds. `updates()` is called before every model call; text it returns (e.g. facts
    other agents verified meanwhile) is appended as a message, so parallel agents share what they learn.
    """
    pending = list(reminders or [])
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    steps = nudges = 0
    warned = time_warned = timed_out = ended_silent = False
    counts: dict[str, int] = {}
    specs: Final = {t["function"]["name"]: t["function"] for t in tools}
    with open(log_path, "w") as log:
        while steps < budget + 6 and not tb.finished:
            _compact(messages)
            if tb.cfg.stopped():
                break
            now = time.time()
            if deadline is not None and now > deadline + 60:
                timed_out = True
                break
            if deadline is not None and not time_warned and now > deadline - 30:
                messages.append({"role": "user", "content": "Time budget reached. Report what you "
                                 "have concluded now, then call finish."})
                time_warned = warned = True
            if updates is not None and steps and (news := updates()):
                messages.append({"role": "user", "content": news})
            for rem in [r for r in pending if r[0](steps, tb)]:
                messages.append({"role": "user", "content": rem[1](tb) if callable(rem[1]) else rem[1]})
                pending.remove(rem)
            if not warned and steps >= budget - 3:
                owed = _unmet(tb)
                messages.append({"role": "user", "content": "Budget nearly used. "
                                 + (f"Still required before you can finish: {'; '.join(m for m, _ in owed)}. "
                                    if owed else "")
                                 + "Record only what you verified; what you could not verify goes into your "
                                 "notes or open leads, not into conclusions. Then call finish."})
                warned = True
            msg = llm.chat(messages, tools=tools)
            entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls]
            messages.append(entry)
            reason = getattr(llm, "last_finish_reason", None)
            log.write(json.dumps({"t": round(time.time() - t0, 1), **entry,
                                  **({"finish_reason": reason} if not msg.tool_calls else {})},
                                 ensure_ascii=False) + "\n")
            if not msg.tool_calls:
                nudges += 1
                if nudges > 3:
                    ended_silent = not msg.content
                    break
                if reason == "length":
                    # Cut by the output limit even at the widest allowance LLM.chat tries: hidden reasoning
                    # used it all, or a tool call was too long and the provider dropped it. Either way the
                    # same reply again fails the same way: ask for one short step.
                    messages.append({"role": "user", "content": "Your last reply was cut off by the output "
                                     "limit before anything usable came out (long hidden reasoning, or a tool "
                                     "call too long to complete), so nothing ran. Do not plan everything at "
                                     "once: make the single next tool call now, and keep it short: e.g. a "
                                     "program that parses the registration code instead of listing entries "
                                     "by hand, or several smaller calls."})
                else:
                    messages.append({"role": "user", "content": "Continue with tools; call finish when done."})
                continue
            for tc in msg.tool_calls:
                steps += 1
                name = tc.function.name
                counts[name] = counts.get(name, 0) + 1
                args = parse_args(tc.function.arguments)
                if name not in specs or getattr(tb, name, None) is None:
                    result = f"error: unknown tool {name}"
                elif "_unparsed" in args:
                    result = (f"error: the arguments of {name} were not valid JSON "
                              f"({len(tc.function.arguments or '')} chars; probably cut off by the output "
                              "limit). Send a shorter call, e.g. split a long program into several, or one "
                              "item per call.")
                else:
                    args = {k: v for k, v in args.items() if not str(k).startswith("_")}  # private params
                    result = _invoke(tb, specs[name], args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                log.write(json.dumps({"t": round(time.time() - t0, 1), "role": "tool", "name": name,
                                      "args": args, "content": str(result)[:3000]},
                                     ensure_ascii=False) + "\n")
        # Out of steps with a required deliverable missing (a finish gate that names the tools that
        # satisfy it): a few last turns offering only those tools, built from what the agent read.
        def open_time() -> bool:
            return not timed_out and not tb.cfg.stopped() and (deadline is None or time.time() < deadline + 60)

        for _ in range(3):
            owed = [(m, names) for m, names in _unmet(tb) if names]
            if tb.finished or not owed or not open_time():
                break
            names = {n for _, ns in owed for n in ns}
            final = [t for t in tools if t["function"]["name"] in names]
            messages.append({"role": "user", "content": "Tool budget used up. Before finishing, from what "
                             f"you have read: {'; '.join(m for m, _ in owed)}."})
            try:
                msg = llm.chat(messages, tools=final)
            except Exception:
                break
            entry = {"role": "assistant", "content": msg.content or ""}
            calls = [tc for tc in (msg.tool_calls or []) if tc.function.name in names]
            if calls:
                entry["tool_calls"] = [{"id": tc.id, "type": "function", "function": {
                    "name": tc.function.name, "arguments": tc.function.arguments}} for tc in calls]
            messages.append(entry)
            for tc in calls:
                args = {k: v for k, v in parse_args(tc.function.arguments).items() if not str(k).startswith("_")}
                result = _invoke(tb, specs[tc.function.name], args)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                log.write(json.dumps({"t": round(time.time() - t0, 1), "role": "tool", "name": tc.function.name,
                                      "args": args, "content": str(result)[:3000]}, ensure_ascii=False) + "\n")
            if not calls:
                break
        # Out of steps without finishing: one last turn that can only call finish, so the agent's
        # conclusions (notes) are not lost. Not after a cancel or a timeout.
        finish_only = [t for t in tools if t["function"]["name"] == "finish"]
        if not tb.finished and finish_only and open_time():
            messages.append({"role": "user", "content": "Tool budget used up. Call finish now; put "
                             "everything you concluded into its notes."})
            try:
                msg = llm.chat(messages, tools=finish_only)
            except Exception:
                msg = None
            for tc in (msg.tool_calls or []) if msg else []:
                if tc.function.name == "finish":
                    args = parse_args(tc.function.arguments)
                    tb.finish(**{k: v for k, v in args.items() if k in ("notes", "unenumerated")}, _force=True)
                    log.write(json.dumps({"t": round(time.time() - t0, 1), "role": "tool", "name": "finish",
                                          "args": args, "content": "forced finish"}, ensure_ascii=False) + "\n")
                    break
    return {"steps": steps, "wall_s": round(time.time() - t0, 1), "tool_counts": counts,
            "finished": tb.finished, "timed_out": timed_out, "ended_silent": ended_silent,
            "widened": getattr(getattr(llm, "usage", None), "widened", 0)}

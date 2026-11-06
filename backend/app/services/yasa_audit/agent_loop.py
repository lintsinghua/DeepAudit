"""A minimal tool-calling loop with a hard step budget and transcript logging."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

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


Reminder = tuple[Callable[[int, Toolbox], bool], str]


def run_agent(llm: LLM, tb: Toolbox, tools: list[dict], system: str, user: str, budget: int,
              log_path: Path, deadline: float | None = None,
              reminders: list[Reminder] | None = None) -> dict:
    """Run until finish, the step budget, or the wall-clock deadline (epoch seconds).

    Near the deadline the agent is told to report and finish; 60 s after it the loop stops.
    `reminders` are (condition(steps, toolbox), message) pairs; each message is sent once, the first
    time its condition holds.
    """
    pending = list(reminders or [])
    messages: list[dict] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    steps = nudges = 0
    warned = time_warned = timed_out = False
    counts: dict[str, int] = {}
    allowed = {t["function"]["name"] for t in tools}
    with open(log_path, "w") as log:
        while steps < budget + 6 and not tb.finished:
            _compact(messages)
            now = time.time()
            if deadline is not None and now > deadline + 60:
                timed_out = True
                break
            if deadline is not None and not time_warned and now > deadline - 30:
                messages.append({"role": "user", "content": "Time budget reached. Report what you "
                                 "have concluded now, then call finish."})
                time_warned = warned = True
            for rem in [r for r in pending if r[0](steps, tb)]:
                messages.append({"role": "user", "content": rem[1]})
                pending.remove(rem)
            if not warned and steps >= budget - 3:
                messages.append({"role": "user", "content": "Budget nearly used. Report what you "
                                 "have concluded, then call finish."})
                warned = True
            msg = llm.chat(messages, tools=tools)
            entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls]
            messages.append(entry)
            log.write(json.dumps({"t": round(time.time() - t0, 1), **entry}, ensure_ascii=False) + "\n")
            if not msg.tool_calls:
                nudges += 1
                if nudges > 3:
                    break
                messages.append({"role": "user", "content": "Continue with tools; call finish when done."})
                continue
            for tc in msg.tool_calls:
                steps += 1
                name = tc.function.name
                counts[name] = counts.get(name, 0) + 1
                args = parse_args(tc.function.arguments)
                fn = getattr(tb, name, None) if name in allowed else None
                try:
                    result = fn(**args) if fn and "_unparsed" not in args else f"error: bad call {name}"
                except Exception as e:  # tool errors go back to the model
                    result = f"error: {type(e).__name__}: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
                log.write(json.dumps({"t": round(time.time() - t0, 1), "role": "tool", "name": name,
                                      "args": args, "content": str(result)[:3000]},
                                     ensure_ascii=False) + "\n")
    return {"steps": steps, "wall_s": round(time.time() - t0, 1), "tool_counts": counts,
            "finished": tb.finished, "timed_out": timed_out}

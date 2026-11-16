"""Thin OpenAI-compatible chat client with retries, token accounting and adaptive concurrency."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import AuditConfig


@dataclass
class Usage:
    prompt: int = 0
    completion: int = 0
    cached: int = 0  # prompt tokens served from the provider's prefix cache (billed lower)
    reasoning: int = 0  # completion tokens spent on hidden reasoning
    calls: int = 0
    widened: int = 0  # requests sent again with a larger output allowance (see LLM.chat)
    seconds: float = 0.0

    def add(self, usage: Any, secs: float) -> None:
        self.calls += 1
        self.seconds += secs
        if usage:
            self.prompt += getattr(usage, "prompt_tokens", 0) or 0
            self.completion += getattr(usage, "completion_tokens", 0) or 0
            ptd = getattr(usage, "prompt_tokens_details", None)
            ctd = getattr(usage, "completion_tokens_details", None)
            self.cached += (getattr(ptd, "cached_tokens", 0) or 0) if ptd else 0
            self.reasoning += (getattr(ctd, "reasoning_tokens", 0) or 0) if ctd else 0


class AdaptiveLimiter:
    """Caps concurrent requests to one endpoint. Halves the cap when the provider rate-limits (once per
    burst: the requests in flight when the provider pushes back all fail together, and counting each one
    took the cap from 16 to 4 for the rest of a run), raises it by one after as many successes in a row as
    the cap (at most `grow_after`, at least 4), between 1 and `ceiling`.

    Many review units can run at once (most of a unit's time is spent outside LLM calls, in tools);
    the limiter keeps the number of requests in flight at what the provider accepts.
    """

    def __init__(self, ceiling: int, start: int | None = None, grow_after: int = 20, burst_s: float = 10.0):
        self.ceiling = max(1, ceiling)
        self.limit = max(1, min(self.ceiling, start or self.ceiling))
        self.grow_after = grow_after
        self.in_flight = 0
        self.ok_streak = 0
        self.throttled = 0
        self.peak = 0
        self.burst_s = burst_s
        self.last_cut = 0.0
        self.last_error = ""  # the provider's last rate-limit message (RPM, TPM or concurrency: they differ)
        self._cv = threading.Condition()

    def acquire(self) -> None:
        with self._cv:
            while self.in_flight >= self.limit:
                self._cv.wait()
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)

    def release(self, rate_limited: bool = False, error: str = "") -> None:
        with self._cv:
            if error:
                self.last_error = error[:300]
            self.in_flight -= 1
            if rate_limited:
                self.throttled += 1
                self.ok_streak = 0
                now = time.monotonic()
                if now - self.last_cut >= self.burst_s:  # one cut per burst of rejections
                    self.limit = max(1, self.limit // 2)
                    self.last_cut = now
            else:
                self.ok_streak += 1
                if self.ok_streak >= min(self.grow_after, max(4, self.limit)) and self.limit < self.ceiling:
                    self.limit += 1
                    self.ok_streak = 0
            self._cv.notify_all()

    def stats(self) -> dict:
        with self._cv:
            return {"limit": self.limit, "ceiling": self.ceiling, "peak_in_flight": self.peak,
                    "rate_limited": self.throttled, "last_rate_limit_error": self.last_error}


_LIMITERS: dict[tuple, AdaptiveLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter_for(cfg: AuditConfig) -> AdaptiveLimiter:
    """One limiter per endpoint and model for the whole process (all stages and units share it)."""
    key = (cfg.llm_base_url, cfg.llm_model)
    with _LIMITERS_LOCK:
        lim = _LIMITERS.get(key)
        if lim is None or lim.ceiling != max(1, cfg.llm_concurrency):
            lim = _LIMITERS[key] = AdaptiveLimiter(cfg.llm_concurrency)
        return lim


def _is_rate_limit(e: Exception) -> bool:
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    return status == 429 or type(e).__name__ == "RateLimitError" or "rate limit" in str(e).lower()


@dataclass
class LLM:
    cfg: AuditConfig
    usage: Usage = field(default_factory=Usage)
    last_finish_reason: str | None = None  # 'length' when the reply was cut by the output limit

    def __post_init__(self) -> None:
        from openai import OpenAI  # transitive dependency of litellm

        self.cfg.require_llm()
        self.client = OpenAI(
            base_url=self.cfg.llm_base_url,
            api_key=self.cfg.llm_api_key,
            timeout=self.cfg.llm_timeout_s,
            max_retries=0,  # retries are ours, so rate limits reach the limiter
        )
        self.limiter = limiter_for(self.cfg)

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        """One completion. A reasoning model's hidden reasoning counts against max_tokens: when it uses
        the whole allowance nothing visible comes back (no text, no tool call, finish_reason 'length').
        Asking again in words repeats the same reasoning and fails the same way, so the same request is
        sent again with twice the allowance, up to llm_max_tokens_ceiling."""
        last_err: Exception | None = None
        err = ""
        max_tokens = self.cfg.llm_max_tokens
        attempt = 0
        while attempt < 6:
            t0 = time.time()
            kw: dict[str, Any] = {
                "model": self.cfg.llm_model,
                "messages": messages,
                "temperature": self.cfg.llm_temperature,
                "max_tokens": max_tokens,
            }
            if tools:
                kw["tools"] = tools
                kw["tool_choice"] = "auto"
            self.limiter.acquire()
            limited = False
            try:
                resp = self.client.chat.completions.create(**kw)
                self.usage.add(resp.usage, time.time() - t0)
                self.last_finish_reason = getattr(resp.choices[0], "finish_reason", None)
                msg = resp.choices[0].message
                if (self.last_finish_reason == "length" and not msg.content and not msg.tool_calls
                        and max_tokens < self.cfg.llm_max_tokens_ceiling):
                    max_tokens = min(self.cfg.llm_max_tokens_ceiling, max_tokens * 2)
                    self.usage.widened += 1
                    continue
                return msg
            except Exception as e:  # network / rate limit: back off and retry
                last_err = e
                limited = _is_rate_limit(e)
                err = str(e) if limited else ""
            finally:
                self.limiter.release(rate_limited=limited, error=err)
            attempt += 1
            time.sleep(min(30, (5 if limited else 2) * attempt))
        raise RuntimeError(f"LLM call failed after retries: {last_err}")


def parse_args(raw: str | None) -> dict:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {"_unparsed": raw}
    except json.JSONDecodeError:
        return {"_unparsed": raw}

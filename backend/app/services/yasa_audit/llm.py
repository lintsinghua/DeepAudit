"""Thin OpenAI-compatible chat client with retries and token accounting."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .config import AuditConfig


@dataclass
class Usage:
    prompt: int = 0
    completion: int = 0
    calls: int = 0
    seconds: float = 0.0

    def add(self, usage: Any, secs: float) -> None:
        self.calls += 1
        self.seconds += secs
        if usage:
            self.prompt += getattr(usage, "prompt_tokens", 0) or 0
            self.completion += getattr(usage, "completion_tokens", 0) or 0


@dataclass
class LLM:
    cfg: AuditConfig
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        from openai import OpenAI  # transitive dependency of litellm

        self.cfg.require_llm()
        self.client = OpenAI(
            base_url=self.cfg.llm_base_url,
            api_key=self.cfg.llm_api_key,
            timeout=self.cfg.llm_timeout_s,
        )

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Any:
        last_err: Exception | None = None
        for attempt in range(4):
            t0 = time.time()
            try:
                kw: dict[str, Any] = {
                    "model": self.cfg.llm_model,
                    "messages": messages,
                    "temperature": self.cfg.llm_temperature,
                    "max_tokens": self.cfg.llm_max_tokens,
                }
                if tools:
                    kw["tools"] = tools
                    kw["tool_choice"] = "auto"
                resp = self.client.chat.completions.create(**kw)
                self.usage.add(resp.usage, time.time() - t0)
                return resp.choices[0].message
            except Exception as e:  # network / rate limit: back off and retry
                last_err = e
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after retries: {last_err}")


def parse_args(raw: str | None) -> dict:
    try:
        val = json.loads(raw or "{}")
        return val if isinstance(val, dict) else {"_unparsed": raw}
    except json.JSONDecodeError:
        return {"_unparsed": raw}

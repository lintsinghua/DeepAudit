"""Runtime configuration for the YASA hybrid audit pipeline.

LLM settings reuse DeepAudit's environment variables (LLM_API_KEY, LLM_MODEL, LLM_BASE_URL,
LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT). Tool locations default to the layout created by
backend/scripts/setup_yasa.sh and can be overridden with YASA_RG_BIN / YASA_CODEGRAPH_BIN.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Where setup_yasa.sh installs the native tools (codegraph, ripgrep). YASAMCP_HOME is the older name.
DEFAULT_HOME = Path(os.environ.get("YASA_HOME") or os.environ.get("YASAMCP_HOME") or Path.home() / ".yasamcp")


def platform_directory() -> str:
    """Directory names of the native tool bundle."""
    system, machine = platform.system(), platform.machine()
    return {
        ("Darwin", "arm64"): "darwin-aarch64",
        ("Darwin", "aarch64"): "darwin-aarch64",
        ("Darwin", "x86_64"): "darwin-x86-64",
        ("Linux", "x86_64"): "linux-x86-64",
    }.get((system, machine), f"{system.lower()}-{machine.lower()}")


DEFAULT_TOOLS = DEFAULT_HOME / "tools" / platform_directory()


@dataclass
class AuditConfig:
    # LLM (OpenAI-compatible chat completions with tool calling)
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    llm_temperature: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.1"))
    )
    llm_max_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS", "8192")))
    # A reply that hidden reasoning cut off before anything visible is asked again with twice the
    # allowance, up to this
    llm_max_tokens_ceiling: int = field(
        default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS_CEILING", "32768")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.environ.get("LLM_TIMEOUT", "150")))

    # Tools: codegraph indexes the code (calls, inheritance, routes), ripgrep searches it
    rg_bin: str = field(
        default_factory=lambda: os.environ.get("YASA_RG_BIN", str(DEFAULT_TOOLS / "ripgrep" / "rg"))
    )
    codegraph_bin: str = field(default_factory=lambda: os.environ.get(
        "YASA_CODEGRAPH_BIN", str(DEFAULT_TOOLS / "codegraph" / "bin" / "codegraph")))

    # Budgets. Wall time is the hard constraint: one audit should finish within time_budget_s.
    time_budget_s: int = 1800
    recon_share: float = 0.25  # route reconnaissance may use this share of the budget
    recon_budget: int = 60  # tool calls of the surface agent
    access_budget: int = 40  # tool calls of the access-control agent (runs in parallel with it)
    review_budget: int = 24  # tool calls per entry review
    verify_budget: int = 24  # tool calls of the refutation check per root cause
    verify_share: float = 0.12  # share of the wall-clock budget kept for the refutation check
    reconcile_budget: int = 20  # tool calls of the access agent to settle disagreements with the surface
    assets_budget: int = 40  # tool calls of the sensitive-asset agent (runs in parallel with the surface agent)
    design_budget: int = 36  # tool calls per identity design-review unit
    design_units_max: int = 10  # identity design units (a large subsystem counts once per part), at most
    operation_every: int = 3  # every n-th review slot goes to an operation unit while both kinds are left
    workers: int = 16  # review units in parallel (a unit spends most of its time in tools, not the LLM)
    # LLM requests in flight at most; halved automatically when the provider rate-limits
    llm_concurrency: int = field(default_factory=lambda: int(os.environ.get("LLM_CONCURRENCY", "16")))

    # Cooperative cancellation: agent loops and the unit scheduler stop when this returns True.
    should_stop: Callable[[], bool] | None = field(default=None, repr=False, compare=False)

    def stopped(self) -> bool:
        return bool(self.should_stop and self.should_stop())

    def require_llm(self) -> None:
        missing = [
            n
            for n, v in (
                ("LLM_BASE_URL", self.llm_base_url),
                ("LLM_API_KEY", self.llm_api_key),
                ("LLM_MODEL", self.llm_model),
            )
            if not v
        ]
        if missing:
            raise SystemExit(f"missing environment variables: {', '.join(missing)}")

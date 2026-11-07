"""Runtime configuration for the YASA hybrid audit pipeline.

LLM settings reuse DeepAudit's environment variables (LLM_API_KEY, LLM_MODEL, LLM_BASE_URL,
LLM_TEMPERATURE, LLM_MAX_TOKENS, LLM_TIMEOUT). Tool locations default to the layout created by
backend/scripts/setup_yasa.sh and can be overridden with YASA_* variables.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOME = Path(os.environ.get("YASAMCP_HOME", Path.home() / ".yasamcp"))


def platform_directory() -> str:
    """Use the same native-tool directory names as upstream yasa-mcp."""
    system, machine = platform.system(), platform.machine()
    return {
        ("Darwin", "arm64"): "darwin-aarch64",
        ("Darwin", "aarch64"): "darwin-aarch64",
        ("Darwin", "x86_64"): "darwin-x86-64",
        ("Linux", "x86_64"): "linux-x86-64",
    }.get((system, machine), f"{system.lower()}-{machine.lower()}")


DEFAULT_TOOLS = DEFAULT_HOME / "tools" / platform_directory()


def _default_yasamcp() -> str:
    """Official release bundle, legacy source virtualenv, then PATH."""
    native_bin = DEFAULT_HOME / "mcp" / platform_directory() / "yasamcp"
    if native_bin.is_file() and os.access(native_bin, os.X_OK):
        return str(native_bin)
    venv_bin = DEFAULT_HOME / "venv" / "bin" / "yasa-mcp"
    return str(venv_bin) if venv_bin.exists() else "yasa-mcp"


@dataclass
class AuditConfig:
    # LLM (OpenAI-compatible chat completions with tool calling)
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", ""))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    llm_temperature: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.1"))
    )
    llm_max_tokens: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_TOKENS", "4096")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.environ.get("LLM_TIMEOUT", "150")))

    # Tools
    yasa_bin: str = field(
        default_factory=lambda: os.environ.get("YASA_BIN", str(DEFAULT_TOOLS / "yasa" / "yasa"))
    )
    yasamcp_bin: str = field(default_factory=lambda: os.environ.get("YASAMCP_BIN", _default_yasamcp()))
    yasamcp_tools_dir: str = field(
        default_factory=lambda: os.environ.get("YASAMCP_TOOLS_DIR", str(DEFAULT_HOME / "tools"))
    )
    rg_bin: str = field(
        default_factory=lambda: os.environ.get("YASA_RG_BIN", str(DEFAULT_TOOLS / "ripgrep" / "rg"))
    )

    # Budgets. Wall time is the hard constraint: one audit should finish within time_budget_s.
    time_budget_s: int = 1800
    build_share: float = 0.35  # build stage (incl. engine runs) may use this share of the budget
    yasa_timeout_s: int = 600
    builder_max_yasa_runs: int = 2
    builder_budget: int = 25
    triage_budget: int = 10
    triage_group_budget_cap: int = 24
    trace_budget: int = 80
    workers: int = 6

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

"""
Agent Configuration Module

Centralized configuration management for the Agent audit framework.
All configuration values can be overridden via environment variables with AGENT_ prefix.
"""

import os
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class LogLevel(str, Enum):
    """Logging levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AgentConfig(BaseSettings):
    """
    Centralized configuration for the Agent audit framework.

    All settings can be overridden via environment variables with AGENT_ prefix.
    Example: AGENT_LLM_MAX_RETRIES=5
    """

    # ============ LLM Settings ============
    llm_max_retries: int = Field(
        default=3,
        description="Maximum number of retries for LLM calls"
    )
    llm_retry_base_delay: float = Field(
        default=1.0,
        description="Base delay in seconds for LLM retry backoff"
    )
    llm_retry_max_delay: float = Field(
        default=60.0,
        description="Maximum delay in seconds for LLM retry backoff"
    )
    llm_timeout_seconds: int = Field(
        default=120,
        description="Timeout in seconds for LLM requests"
    )
    llm_max_tokens_per_call: int = Field(
        default=4096,
        description="Maximum tokens per LLM call"
    )
    llm_temperature: float = Field(
        default=0.1,
        description="Default temperature for LLM calls"
    )
    llm_stream_enabled: bool = Field(
        default=True,
        description="Enable streaming for LLM responses"
    )

    # ============ Agent Iteration Limits ============
    orchestrator_max_iterations: int = Field(
        default=20,
        description="Maximum iterations for orchestrator agent"
    )
    recon_max_iterations: int = Field(
        default=15,
        description="Maximum iterations for reconnaissance agent"
    )
    analysis_max_iterations: int = Field(
        default=30,
        description="Maximum iterations for analysis agent"
    )
    verification_max_iterations: int = Field(
        default=15,
        description="Maximum iterations for verification agent"
    )

    # ============ Agent Timeouts ============
    orchestrator_timeout_seconds: int = Field(
        default=1800,
        description="Timeout in seconds for orchestrator (30 minutes)"
    )
    sub_agent_timeout_seconds: int = Field(
        default=600,
        description="Timeout in seconds for sub-agents (10 minutes)"
    )

    # ============ Tool Settings ============
    tool_timeout_seconds: int = Field(
        default=60,
        description="Default timeout for tool execution"
    )
    tool_max_retries: int = Field(
        default=2,
        description="Maximum retries for tool execution"
    )

    # External Tool Toggles
    semgrep_enabled: bool = Field(
        default=True,
        description="Enable Semgrep scanner"
    )
    bandit_enabled: bool = Field(
        default=True,
        description="Enable Bandit scanner"
    )
    gitleaks_enabled: bool = Field(
        default=True,
        description="Enable Gitleaks scanner"
    )
    npm_audit_enabled: bool = Field(
        default=True,
        description="Enable npm audit"
    )
    safety_enabled: bool = Field(
        default=True,
        description="Enable Safety (Python) scanner"
    )
    osv_scanner_enabled: bool = Field(
        default=True,
        description="Enable OSV scanner"
    )
    # Kunlun-M (MIT License - https://github.com/LoRexxar/Kunlun-M)
    kunlun_enabled: bool = Field(
        default=True,
        description="Enable Kunlun-M static code analyzer"
    )

    # External Tool Timeouts
    semgrep_timeout_seconds: int = Field(
        default=120,
        description="Timeout for Semgrep scanner"
    )
    bandit_timeout_seconds: int = Field(
        default=60,
        description="Timeout for Bandit scanner"
    )
    gitleaks_timeout_seconds: int = Field(
        default=60,
        description="Timeout for Gitleaks scanner"
    )
    kunlun_timeout_seconds: int = Field(
        default=600,
        description="Timeout for Kunlun-M scanner (10 minutes for deep analysis)"
    )

    # ============ Rate Limiting ============
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable rate limiting for tools"
    )
    external_tool_rate_per_second: float = Field(
        default=0.2,
        description="Rate limit for external tools (calls per second)"
    )
    external_tool_burst: int = Field(
        default=3,
        description="Burst limit for external tools"
    )
    llm_rate_per_minute: int = Field(
        default=60,
        description="Rate limit for LLM calls per minute"
    )

    # ============ Circuit Breaker ============
    circuit_breaker_enabled: bool = Field(
        default=True,
        description="Enable circuit breaker pattern"
    )
    circuit_failure_threshold: int = Field(
        default=5,
        description="Number of failures before circuit opens"
    )
    circuit_recovery_timeout_seconds: float = Field(
        default=30.0,
        description="Time to wait before attempting recovery"
    )
    circuit_half_open_max_calls: int = Field(
        default=3,
        description="Max calls in half-open state before closing"
    )

    # ============ Resource Limits ============
    max_file_size_bytes: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Maximum file size to analyze"
    )
    max_files_per_scan: int = Field(
        default=1000,
        description="Maximum files to scan per task"
    )
    max_findings_per_agent: int = Field(
        default=100,
        description="Maximum findings per agent before stopping"
    )
    max_total_findings: int = Field(
        default=500,
        description="Maximum total findings per task"
    )
    max_context_messages: int = Field(
        default=50,
        description="Maximum messages in agent context"
    )
    max_tool_output_length: int = Field(
        default=50000,
        description="Maximum length of tool output"
    )

    # ============ Checkpoint & Persistence ============
    checkpoint_enabled: bool = Field(
        default=True,
        description="Enable automatic checkpointing"
    )
    checkpoint_interval_iterations: int = Field(
        default=5,
        description="Create checkpoint every N iterations"
    )
    checkpoint_on_tool_complete: bool = Field(
        default=False,
        description="Create checkpoint after each tool completion"
    )
    checkpoint_on_phase_complete: bool = Field(
        default=True,
        description="Create checkpoint after each phase"
    )
    max_checkpoints_per_task: int = Field(
        default=50,
        description="Maximum checkpoints to keep per task"
    )

    # ============ Logging & Telemetry ============
    log_level: LogLevel = Field(
        default=LogLevel.INFO,
        description="Logging level"
    )
    structured_logging_enabled: bool = Field(
        default=True,
        description="Enable structured JSON logging"
    )
    telemetry_enabled: bool = Field(
        default=True,
        description="Enable telemetry tracing"
    )
    log_llm_prompts: bool = Field(
        default=False,
        description="Log full LLM prompts (may contain sensitive data)"
    )
    log_llm_responses: bool = Field(
        default=False,
        description="Log full LLM responses"
    )
    log_tool_inputs: bool = Field(
        default=True,
        description="Log tool input parameters"
    )
    log_tool_outputs: bool = Field(
        default=False,
        description="Log full tool outputs"
    )

    # ============ Event Streaming ============
    sse_heartbeat_interval_seconds: int = Field(
        default=30,
        description="SSE heartbeat interval"
    )
    event_queue_max_size: int = Field(
        default=1000,
        description="Maximum events in queue"
    )
    event_batch_size: int = Field(
        default=10,
        description="Events to batch for persistence"
    )

    # ============ Security ============
    allowed_file_extensions: Set[str] = Field(
        default={
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".php",
            ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".rs", ".scala",
            ".vue", ".svelte", ".html", ".css", ".scss", ".sass", ".less",
            ".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".conf",
            ".sql", ".graphql", ".proto", ".sh", ".bash", ".zsh", ".ps1",
            ".md", ".txt", ".rst", ".env.example", ".gitignore",
        },
        description="Allowed file extensions for analysis"
    )
    blocked_directories: Set[str] = Field(
        default={
            "node_modules", "__pycache__", ".git", ".svn", ".hg",
            "venv", ".venv", "env", ".env", "virtualenv",
            "dist", "build", "target", "out", "bin", "obj",
            ".idea", ".vscode", ".vs", ".pytest_cache", ".mypy_cache",
            "coverage", ".coverage", "htmlcov", ".tox", ".nox",
        },
        description="Directories to exclude from scanning"
    )
    max_path_depth: int = Field(
        default=20,
        description="Maximum directory depth to scan"
    )

    # ============ Knowledge & RAG ============
    rag_enabled: bool = Field(
        default=True,
        description="Enable RAG-based knowledge retrieval"
    )
    rag_top_k: int = Field(
        default=5,
        description="Number of RAG results to retrieve"
    )
    knowledge_modules_enabled: bool = Field(
        default=True,
        description="Enable knowledge module injection"
    )

    # ============ Graceful Degradation ============
    fallback_enabled: bool = Field(
        default=True,
        description="Enable fallback strategies on failure"
    )
    continue_on_tool_failure: bool = Field(
        default=True,
        description="Continue execution if a tool fails"
    )
    continue_on_partial_results: bool = Field(
        default=True,
        description="Continue with partial results on timeout"
    )

    class Config:
        env_prefix = "AGENT_"
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


@dataclass
class ToolConfig:
    """Configuration for a specific tool"""
    name: str
    enabled: bool = True
    timeout_seconds: int = 60
    max_retries: int = 2
    rate_limit_per_second: Optional[float] = None
    fallback_tool: Optional[str] = None
    circuit_breaker_enabled: bool = True


@dataclass
class AgentTypeConfig:
    """Configuration for a specific agent type"""
    agent_type: str
    max_iterations: int
    timeout_seconds: int
    tools: List[str] = field(default_factory=list)
    knowledge_modules: List[str] = field(default_factory=list)


# ============ Configuration Factory ============

@lru_cache()
def get_agent_config() -> AgentConfig:
    """
    Get the singleton agent configuration instance.

    Configuration is loaded once and cached. To reload configuration,
    call get_agent_config.cache_clear() first.
    """
    return AgentConfig()


def get_tool_config(tool_name: str) -> ToolConfig:
    """Get configuration for a specific tool"""
    config = get_agent_config()

    # Tool-specific configurations
    tool_configs: Dict[str, ToolConfig] = {
        "semgrep_scan": ToolConfig(
            name="semgrep_scan",
            enabled=config.semgrep_enabled,
            timeout_seconds=config.semgrep_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
            fallback_tool="pattern_match",
        ),
        "bandit_scan": ToolConfig(
            name="bandit_scan",
            enabled=config.bandit_enabled,
            timeout_seconds=config.bandit_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
            fallback_tool="pattern_match",
        ),
        "gitleaks_scan": ToolConfig(
            name="gitleaks_scan",
            enabled=config.gitleaks_enabled,
            timeout_seconds=config.gitleaks_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
        ),
        "npm_audit": ToolConfig(
            name="npm_audit",
            enabled=config.npm_audit_enabled,
            timeout_seconds=config.tool_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
        ),
        "safety_check": ToolConfig(
            name="safety_check",
            enabled=config.safety_enabled,
            timeout_seconds=config.tool_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
        ),
        "osv_scanner": ToolConfig(
            name="osv_scanner",
            enabled=config.osv_scanner_enabled,
            timeout_seconds=config.tool_timeout_seconds,
            rate_limit_per_second=config.external_tool_rate_per_second,
        ),
    }

    return tool_configs.get(
        tool_name,
        ToolConfig(
            name=tool_name,
            timeout_seconds=config.tool_timeout_seconds,
            max_retries=config.tool_max_retries,
        )
    )


def get_agent_type_config(agent_type: str) -> AgentTypeConfig:
    """Get configuration for a specific agent type"""
    config = get_agent_config()

    agent_configs = {
        "orchestrator": AgentTypeConfig(
            agent_type="orchestrator",
            max_iterations=config.orchestrator_max_iterations,
            timeout_seconds=config.orchestrator_timeout_seconds,
            tools=["think", "reflect", "dispatch_agent", "finish"],
        ),
        "recon": AgentTypeConfig(
            agent_type="recon",
            max_iterations=config.recon_max_iterations,
            timeout_seconds=config.sub_agent_timeout_seconds,
            tools=["list_files", "read_file", "search_code"],
            knowledge_modules=["project_analysis"],
        ),
        "analysis": AgentTypeConfig(
            agent_type="analysis",
            max_iterations=config.analysis_max_iterations,
            timeout_seconds=config.sub_agent_timeout_seconds,
            tools=[
                "smart_scan", "pattern_match", "dataflow_analysis",
                "read_file", "search_code", "semgrep_scan", "bandit_scan"
            ],
            knowledge_modules=["sql_injection", "xss", "command_injection"],
        ),
        "verification": AgentTypeConfig(
            agent_type="verification",
            max_iterations=config.verification_max_iterations,
            timeout_seconds=config.sub_agent_timeout_seconds,
            tools=[
                "validate_vulnerability",
                "dataflow_analysis",
            ],
            knowledge_modules=["vulnerability_verification"],
        ),
    }

    return agent_configs.get(
        agent_type,
        AgentTypeConfig(
            agent_type=agent_type,
            max_iterations=config.analysis_max_iterations,
            timeout_seconds=config.sub_agent_timeout_seconds,
        )
    )


# ============ Configuration Validation ============

def validate_config() -> List[str]:
    """
    Validate current configuration and return list of warnings.

    Returns:
        List of warning messages for potentially problematic settings.
    """
    config = get_agent_config()
    warnings = []

    # Check for potentially problematic settings
    if config.llm_max_retries > 5:
        warnings.append(
            f"llm_max_retries={config.llm_max_retries} is high, "
            "may cause long delays on persistent failures"
        )

    if config.orchestrator_max_iterations > 50:
        warnings.append(
            f"orchestrator_max_iterations={config.orchestrator_max_iterations} "
            "is very high, may lead to excessive LLM costs"
        )

    if config.max_file_size_bytes > 50 * 1024 * 1024:
        warnings.append(
            f"max_file_size_bytes={config.max_file_size_bytes} is very large, "
            "may cause memory issues"
        )

    if not config.circuit_breaker_enabled:
        warnings.append(
            "circuit_breaker_enabled=False may cause cascading failures"
        )

    if not config.checkpoint_enabled:
        warnings.append(
            "checkpoint_enabled=False means state cannot be recovered on failure"
        )

    if config.log_llm_prompts or config.log_llm_responses:
        warnings.append(
            "LLM prompt/response logging enabled - may log sensitive data"
        )

    return warnings


# ============ Environment-Specific Presets ============

def apply_development_preset():
    """Apply development-friendly settings"""
    os.environ.setdefault("AGENT_LOG_LEVEL", "DEBUG")
    os.environ.setdefault("AGENT_LOG_LLM_PROMPTS", "true")
    os.environ.setdefault("AGENT_LOG_TOOL_OUTPUTS", "true")
    os.environ.setdefault("AGENT_CHECKPOINT_INTERVAL_ITERATIONS", "1")
    get_agent_config.cache_clear()


def apply_production_preset():
    """Apply production-safe settings"""
    os.environ.setdefault("AGENT_LOG_LEVEL", "INFO")
    os.environ.setdefault("AGENT_LOG_LLM_PROMPTS", "false")
    os.environ.setdefault("AGENT_LOG_LLM_RESPONSES", "false")
    os.environ.setdefault("AGENT_CIRCUIT_BREAKER_ENABLED", "true")
    os.environ.setdefault("AGENT_CHECKPOINT_ENABLED", "true")
    get_agent_config.cache_clear()


def apply_testing_preset():
    """Apply testing settings with shorter timeouts"""
    os.environ.setdefault("AGENT_LLM_TIMEOUT_SECONDS", "30")
    os.environ.setdefault("AGENT_TOOL_TIMEOUT_SECONDS", "10")
    os.environ.setdefault("AGENT_ORCHESTRATOR_MAX_ITERATIONS", "5")
    os.environ.setdefault("AGENT_ANALYSIS_MAX_ITERATIONS", "10")
    os.environ.setdefault("AGENT_CIRCUIT_BREAKER_ENABLED", "false")
    get_agent_config.cache_clear()

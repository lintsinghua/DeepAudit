"""
Agent Error Hierarchy

Production-grade error handling system for the Agent audit framework.
Provides structured error types with recovery strategies and metadata.
"""

from enum import Enum
from typing import Any, Dict, Optional, Type, List
from dataclasses import dataclass, field
from datetime import datetime


class ErrorSeverity(str, Enum):
    """Error severity levels for monitoring and alerting"""
    LOW = "low"           # Minor issues, can be ignored
    MEDIUM = "medium"     # Notable issues, may affect results
    HIGH = "high"         # Significant issues, likely affects results
    CRITICAL = "critical" # Severe issues, operation cannot continue


class RecoveryStrategy(str, Enum):
    """Strategies for recovering from errors"""
    RETRY = "retry"                     # Retry the same operation
    RETRY_WITH_BACKOFF = "retry_backoff" # Retry with exponential backoff
    SKIP = "skip"                       # Skip this operation, continue
    FALLBACK = "fallback"               # Use fallback approach
    ABORT = "abort"                     # Abort the operation
    MANUAL = "manual"                   # Requires manual intervention


@dataclass
class ErrorContext:
    """Context information for debugging errors"""
    correlation_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    task_id: Optional[str] = None
    iteration: Optional[int] = None
    tool_name: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    additional_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task_id": self.task_id,
            "iteration": self.iteration,
            "tool_name": self.tool_name,
            "timestamp": self.timestamp,
            **self.additional_data
        }


class AgentError(Exception):
    """
    Base exception for all agent-related errors.

    Attributes:
        error_code: Unique error code for identification
        message: Human-readable error message
        recoverable: Whether the error can be recovered from
        recovery_strategy: Suggested recovery approach
        retry_after: Suggested wait time before retry (seconds)
        severity: Error severity level
        context: Additional context for debugging
    """
    error_code: str = "AGENT_ERROR"
    recoverable: bool = False
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.ABORT
    retry_after: Optional[int] = None
    severity: ErrorSeverity = ErrorSeverity.HIGH

    def __init__(
        self,
        message: str,
        *,
        error_code: Optional[str] = None,
        recoverable: Optional[bool] = None,
        recovery_strategy: Optional[RecoveryStrategy] = None,
        retry_after: Optional[int] = None,
        severity: Optional[ErrorSeverity] = None,
        context: Optional[ErrorContext] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message

        # Allow instance-level overrides of class defaults
        if error_code is not None:
            self.error_code = error_code
        if recoverable is not None:
            self.recoverable = recoverable
        if recovery_strategy is not None:
            self.recovery_strategy = recovery_strategy
        if retry_after is not None:
            self.retry_after = retry_after
        if severity is not None:
            self.severity = severity

        self.context = context or ErrorContext()
        self.cause = cause

    def with_context(self, **kwargs) -> "AgentError":
        """Add context information to the error"""
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)
            else:
                self.context.additional_data[key] = value
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "recoverable": self.recoverable,
            "recovery_strategy": self.recovery_strategy.value,
            "retry_after": self.retry_after,
            "severity": self.severity.value,
            "context": self.context.to_dict(),
            "cause": str(self.cause) if self.cause else None,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.error_code}, message={self.message!r})"


# ============ LLM Errors ============

class LLMError(AgentError):
    """Base class for LLM-related errors"""
    error_code = "LLM_ERROR"
    severity = ErrorSeverity.HIGH


class LLMRateLimitError(LLMError):
    """
    Rate limit exceeded from LLM provider.

    Recoverable by waiting and retrying.
    """
    error_code = "LLM_RATE_LIMIT"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    retry_after = 60  # Default wait 60 seconds
    severity = ErrorSeverity.MEDIUM


class LLMTimeoutError(LLMError):
    """
    LLM request timed out.

    Recoverable by retrying, possibly with shorter context.
    """
    error_code = "LLM_TIMEOUT"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    retry_after = 5
    severity = ErrorSeverity.MEDIUM


class LLMConnectionError(LLMError):
    """
    Failed to connect to LLM service.

    Recoverable by retrying with backoff.
    """
    error_code = "LLM_CONNECTION"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    retry_after = 10
    severity = ErrorSeverity.HIGH


class LLMAuthenticationError(LLMError):
    """
    Authentication failed with LLM provider.

    Not recoverable - requires configuration fix.
    """
    error_code = "LLM_AUTH"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.CRITICAL


class LLMContentFilterError(LLMError):
    """
    Content was filtered by LLM provider's safety systems.

    Not automatically recoverable - may need prompt adjustment.
    """
    error_code = "LLM_CONTENT_FILTER"
    recoverable = False
    recovery_strategy = RecoveryStrategy.SKIP
    severity = ErrorSeverity.MEDIUM


class LLMContextLengthError(LLMError):
    """
    Context length exceeded LLM's maximum.

    Recoverable by reducing context size.
    """
    error_code = "LLM_CONTEXT_LENGTH"
    recoverable = True
    recovery_strategy = RecoveryStrategy.FALLBACK
    severity = ErrorSeverity.MEDIUM


class LLMInvalidResponseError(LLMError):
    """
    LLM returned an invalid or unparseable response.

    Recoverable by retrying with clearer instructions.
    """
    error_code = "LLM_INVALID_RESPONSE"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY
    retry_after = 1
    severity = ErrorSeverity.MEDIUM


class LLMQuotaExceededError(LLMError):
    """
    Account quota/budget exceeded.

    Not recoverable without budget increase.
    """
    error_code = "LLM_QUOTA_EXCEEDED"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.CRITICAL


# ============ Tool Errors ============

class ToolError(AgentError):
    """Base class for tool execution errors"""
    error_code = "TOOL_ERROR"
    severity = ErrorSeverity.MEDIUM


class ToolExecutionError(ToolError):
    """
    Tool execution failed.

    May be recoverable depending on the specific tool.
    """
    error_code = "TOOL_EXECUTION"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY
    retry_after = 2


class ToolTimeoutError(ToolError):
    """
    Tool execution timed out.

    Recoverable by retrying or using fallback tool.
    """
    error_code = "TOOL_TIMEOUT"
    recoverable = True
    recovery_strategy = RecoveryStrategy.FALLBACK
    retry_after = 5


class ToolNotFoundError(ToolError):
    """
    Requested tool does not exist.

    Not recoverable - likely a configuration or prompt issue.
    """
    error_code = "TOOL_NOT_FOUND"
    recoverable = False
    recovery_strategy = RecoveryStrategy.SKIP
    severity = ErrorSeverity.HIGH


class ToolInputValidationError(ToolError):
    """
    Tool input validation failed.

    Recoverable by adjusting input parameters.
    """
    error_code = "TOOL_INPUT_INVALID"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY
    severity = ErrorSeverity.LOW


class ToolPermissionError(ToolError):
    """
    Insufficient permissions for tool operation.

    Not automatically recoverable.
    """
    error_code = "TOOL_PERMISSION"
    recoverable = False
    recovery_strategy = RecoveryStrategy.SKIP
    severity = ErrorSeverity.HIGH


class ToolResourceError(ToolError):
    """
    Tool required resource is unavailable.

    May be recoverable by waiting.
    """
    error_code = "TOOL_RESOURCE"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    retry_after = 10


class ExternalToolError(ToolError):
    """
    External tool (semgrep, bandit, etc.) failed.

    Recoverable using fallback scanning method.
    """
    error_code = "EXTERNAL_TOOL_ERROR"
    recoverable = True
    recovery_strategy = RecoveryStrategy.FALLBACK


# ============ Agent Lifecycle Errors ============

class AgentLifecycleError(AgentError):
    """Base class for agent lifecycle errors"""
    error_code = "AGENT_LIFECYCLE"


class AgentCancelledError(AgentLifecycleError):
    """
    Agent execution was cancelled by user or system.

    Not recoverable - intentional termination.
    """
    error_code = "AGENT_CANCELLED"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.LOW


class AgentTimeoutError(AgentLifecycleError):
    """
    Agent exceeded maximum execution time.

    Not recoverable in current run.
    """
    error_code = "AGENT_TIMEOUT"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.MEDIUM


class AgentIterationLimitError(AgentLifecycleError):
    """
    Agent exceeded maximum iteration count.

    Not recoverable in current run.
    """
    error_code = "AGENT_ITERATION_LIMIT"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.MEDIUM


class AgentInitializationError(AgentLifecycleError):
    """
    Agent failed to initialize properly.

    May be recoverable by fixing configuration.
    """
    error_code = "AGENT_INIT"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.HIGH


# ============ State Errors ============

class StateError(AgentError):
    """Base class for state-related errors"""
    error_code = "STATE_ERROR"


class StateRecoveryError(StateError):
    """
    Failed to recover agent state from checkpoint.

    Not automatically recoverable.
    """
    error_code = "STATE_RECOVERY"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.HIGH


class StatePersistenceError(StateError):
    """
    Failed to persist agent state.

    Recoverable by retrying.
    """
    error_code = "STATE_PERSISTENCE"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY
    severity = ErrorSeverity.MEDIUM


class InvalidStateTransitionError(StateError):
    """
    Invalid state transition attempted.

    Indicates a bug in state machine logic.
    """
    error_code = "STATE_INVALID_TRANSITION"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.HIGH


# ============ Communication Errors ============

class CommunicationError(AgentError):
    """Base class for inter-agent communication errors"""
    error_code = "COMMUNICATION_ERROR"


class MessageDeliveryError(CommunicationError):
    """
    Failed to deliver message between agents.

    Recoverable by retrying.
    """
    error_code = "MESSAGE_DELIVERY"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY
    retry_after = 1


class AgentNotFoundError(CommunicationError):
    """
    Target agent not found in registry.

    Not recoverable - likely a timing or configuration issue.
    """
    error_code = "AGENT_NOT_FOUND"
    recoverable = False
    recovery_strategy = RecoveryStrategy.SKIP
    severity = ErrorSeverity.HIGH


# ============ Resource Errors ============

class ResourceError(AgentError):
    """Base class for resource-related errors"""
    error_code = "RESOURCE_ERROR"


class CircuitOpenError(ResourceError):
    """
    Circuit breaker is open, service unavailable.

    Recoverable after circuit recovery timeout.
    """
    error_code = "CIRCUIT_OPEN"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    severity = ErrorSeverity.MEDIUM

    def __init__(self, service_name: str, **kwargs):
        message = f"Circuit breaker open for service: {service_name}"
        super().__init__(message, **kwargs)
        self.service_name = service_name


class RateLimitExceededError(ResourceError):
    """
    Internal rate limit exceeded.

    Recoverable by waiting.
    """
    error_code = "RATE_LIMIT"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    severity = ErrorSeverity.LOW


class ResourceExhaustedError(ResourceError):
    """
    Resource (memory, connections, etc.) exhausted.

    May need cleanup before retry.
    """
    error_code = "RESOURCE_EXHAUSTED"
    recoverable = True
    recovery_strategy = RecoveryStrategy.RETRY_WITH_BACKOFF
    retry_after = 30
    severity = ErrorSeverity.HIGH


# ============ Validation Errors ============

class ValidationError(AgentError):
    """Base class for validation errors"""
    error_code = "VALIDATION_ERROR"
    severity = ErrorSeverity.LOW


class InputValidationError(ValidationError):
    """
    Input data validation failed.

    Not automatically recoverable - requires input correction.
    """
    error_code = "INPUT_VALIDATION"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT


class PathTraversalError(ValidationError):
    """
    Path traversal attack detected.

    Not recoverable - security violation.
    """
    error_code = "PATH_TRAVERSAL"
    recoverable = False
    recovery_strategy = RecoveryStrategy.ABORT
    severity = ErrorSeverity.CRITICAL


class FileSizeExceededError(ValidationError):
    """
    File size exceeded maximum limit.

    Not recoverable with current file.
    """
    error_code = "FILE_SIZE_EXCEEDED"
    recoverable = False
    recovery_strategy = RecoveryStrategy.SKIP
    severity = ErrorSeverity.LOW


# ============ Error Registry ============

class ErrorRegistry:
    """
    Registry for mapping error codes to error classes.
    Useful for deserializing errors from logs or API responses.
    """
    _registry: Dict[str, Type[AgentError]] = {}

    @classmethod
    def register(cls, error_class: Type[AgentError]) -> Type[AgentError]:
        """Register an error class by its error code"""
        cls._registry[error_class.error_code] = error_class
        return error_class

    @classmethod
    def get(cls, error_code: str) -> Optional[Type[AgentError]]:
        """Get error class by error code"""
        return cls._registry.get(error_code)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentError:
        """Create error instance from dictionary"""
        error_code = data.get("error_code", "AGENT_ERROR")
        error_class = cls.get(error_code) or AgentError

        context = ErrorContext(**data.get("context", {}))

        return error_class(
            message=data.get("message", "Unknown error"),
            context=context,
        )


# Register all error classes
for error_class in [
    AgentError, LLMError, LLMRateLimitError, LLMTimeoutError, LLMConnectionError,
    LLMAuthenticationError, LLMContentFilterError, LLMContextLengthError,
    LLMInvalidResponseError, LLMQuotaExceededError, ToolError, ToolExecutionError,
    ToolTimeoutError, ToolNotFoundError, ToolInputValidationError, ToolPermissionError,
    ToolResourceError, ExternalToolError, AgentLifecycleError, AgentCancelledError,
    AgentTimeoutError, AgentIterationLimitError, AgentInitializationError,
    StateError, StateRecoveryError, StatePersistenceError, InvalidStateTransitionError,
    CommunicationError, MessageDeliveryError, AgentNotFoundError, ResourceError,
    CircuitOpenError, RateLimitExceededError, ResourceExhaustedError,
    ValidationError, InputValidationError, PathTraversalError, FileSizeExceededError,
]:
    ErrorRegistry.register(error_class)


# ============ Helper Functions ============

def is_recoverable(error: Exception) -> bool:
    """Check if an error is recoverable"""
    if isinstance(error, AgentError):
        return error.recoverable
    return False


def get_retry_after(error: Exception) -> Optional[int]:
    """Get suggested retry delay for an error"""
    if isinstance(error, AgentError):
        return error.retry_after
    return None


def get_recovery_strategy(error: Exception) -> RecoveryStrategy:
    """Get recovery strategy for an error"""
    if isinstance(error, AgentError):
        return error.recovery_strategy
    return RecoveryStrategy.ABORT


def wrap_exception(
    error: Exception,
    error_class: Type[AgentError] = AgentError,
    message: Optional[str] = None,
    **context_kwargs
) -> AgentError:
    """Wrap a generic exception in an AgentError"""
    if isinstance(error, AgentError):
        return error.with_context(**context_kwargs)

    wrapped = error_class(
        message=message or str(error),
        cause=error,
    )
    return wrapped.with_context(**context_kwargs)

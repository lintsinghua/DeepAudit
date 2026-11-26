"""
Input Validation Module

Security-focused input validation for the Agent framework.
Prevents path traversal, validates inputs, and enforces limits.
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.project_paths import resolve_project_path

from .errors import (
    InputValidationError,
    PathTraversalError,
    FileSizeExceededError,
)


# ============ Validation Constants ============

# Dangerous patterns that should never appear in file paths
DANGEROUS_PATH_PATTERNS = [
    r'\.\.',           # Parent directory traversal
    r'\.\./',
    r'\.\.\\',
    r'/\.\.',
    r'\\\.\.',
    r'^/',             # Absolute path (Unix)
    r'^[A-Za-z]:',     # Absolute path (Windows)
    r'~',              # Home directory expansion
    r'\$',             # Environment variable
    r'%',              # Windows environment variable
]

# File extensions that should never be read
BLOCKED_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib',  # Executables
    '.bin', '.dat',                    # Binary data
    '.key', '.pem', '.p12', '.pfx',   # Private keys
    '.env',                            # Environment files (use .env.example)
}

# Maximum sizes
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_MAX_PATH_LENGTH = 500
DEFAULT_MAX_CONTENT_LENGTH = 100000


# ============ Path Validation ============

def validate_path(
    path: str,
    project_root: str,
    allow_absolute: bool = False,
) -> str:
    """
    Validate and normalize a file path.

    Args:
        path: Path to validate
        project_root: Project root directory
        allow_absolute: Whether to allow absolute paths

    Returns:
        Normalized absolute path

    Raises:
        PathTraversalError: If path traversal is detected
        InputValidationError: If path is invalid
    """
    if not path or not path.strip():
        raise InputValidationError("Path cannot be empty")

    path = path.strip()

    # Check for dangerous patterns
    for pattern in DANGEROUS_PATH_PATTERNS:
        if re.search(pattern, path):
            raise PathTraversalError(f"Dangerous path pattern detected: {path}")

    if os.path.isabs(path) and not allow_absolute:
        raise PathTraversalError(f"Absolute paths not allowed: {path}")
    try:
        return resolve_project_path(project_root, path)
    except ValueError as exc:
        raise PathTraversalError(f"Invalid project path: {path}") from exc



def validate_file_extension(
    path: str,
    allowed_extensions: Optional[Set[str]] = None,
    blocked_extensions: Optional[Set[str]] = None,
) -> None:
    """
    Validate file extension.

    Args:
        path: File path
        allowed_extensions: Set of allowed extensions (if None, all allowed)
        blocked_extensions: Set of blocked extensions

    Raises:
        InputValidationError: If extension is not allowed
    """
    ext = os.path.splitext(path)[1].lower()

    blocked = blocked_extensions or BLOCKED_EXTENSIONS
    if ext in blocked:
        raise InputValidationError(f"File extension not allowed: {ext}")

    if allowed_extensions is not None and ext not in allowed_extensions:
        raise InputValidationError(f"File extension not in allowed list: {ext}")


def validate_file_size(
    path: str,
    max_size: int = DEFAULT_MAX_FILE_SIZE,
) -> int:
    """
    Validate file size.

    Args:
        path: File path
        max_size: Maximum allowed size in bytes

    Returns:
        File size in bytes

    Raises:
        FileSizeExceededError: If file exceeds max size
    """
    try:
        size = os.path.getsize(path)
        if size > max_size:
            raise FileSizeExceededError(
                f"File size {size} exceeds maximum {max_size}: {path}"
            )
        return size
    except OSError as e:
        raise InputValidationError(f"Cannot check file size: {e}")


# ============ Input Schemas ============

class AgentTaskInput(BaseModel):
    """Validated input for creating an agent task"""
    task: str = Field(..., min_length=1, max_length=10000)
    project_root: str = Field(..., min_length=1, max_length=500)
    max_iterations: int = Field(default=20, ge=1, le=100)
    timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    target_vulnerabilities: List[str] = Field(default_factory=list)
    exclude_patterns: List[str] = Field(default_factory=list)
    target_files: List[str] = Field(default_factory=list)

    @field_validator('task')
    @classmethod
    def task_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Task cannot be empty or whitespace')
        return v.strip()

    @field_validator('project_root')
    @classmethod
    def project_root_exists(cls, v: str) -> str:
        if not os.path.isdir(v):
            raise ValueError(f'Project root does not exist: {v}')
        return os.path.abspath(v)

    @field_validator('target_vulnerabilities')
    @classmethod
    def validate_vulnerabilities(cls, v: List[str]) -> List[str]:
        valid_types = {
            'sql_injection', 'xss', 'command_injection', 'path_traversal',
            'ssrf', 'xxe', 'deserialization', 'auth_bypass', 'idor',
            'csrf', 'open_redirect', 'race_condition', 'crypto',
        }
        for vuln in v:
            if vuln.lower() not in valid_types:
                raise ValueError(f'Unknown vulnerability type: {vuln}')
        return [vuln.lower() for vuln in v]


class ToolInput(BaseModel):
    """Base class for tool inputs"""
    pass


class FileReadInput(ToolInput):
    """Validated input for file read operations"""
    file_path: str = Field(..., min_length=1, max_length=500)
    start_line: Optional[int] = Field(default=None, ge=1)
    end_line: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode='after')
    def validate_line_range(self) -> 'FileReadInput':
        if self.start_line and self.end_line:
            if self.start_line > self.end_line:
                raise ValueError('start_line must be <= end_line')
        return self


class FileSearchInput(ToolInput):
    """Validated input for file search operations"""
    pattern: str = Field(..., min_length=1, max_length=1000)
    path: str = Field(default=".", max_length=500)
    max_results: int = Field(default=100, ge=1, le=1000)
    include_context: bool = Field(default=True)
    context_lines: int = Field(default=3, ge=0, le=10)

    @field_validator('pattern')
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        # Try to compile as regex to validate
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f'Invalid regex pattern: {e}')
        return v


class CodeAnalysisInput(ToolInput):
    """Validated input for code analysis operations"""
    file_path: str = Field(..., min_length=1, max_length=500)
    analysis_type: str = Field(default="full")
    include_ast: bool = Field(default=False)

    @field_validator('analysis_type')
    @classmethod
    def validate_analysis_type(cls, v: str) -> str:
        valid_types = {'full', 'quick', 'security', 'dataflow'}
        if v.lower() not in valid_types:
            raise ValueError(f'Invalid analysis type: {v}')
        return v.lower()


class PatternMatchInput(ToolInput):
    """Validated input for pattern matching operations"""
    patterns: List[str] = Field(..., min_items=1, max_items=50)
    target_path: str = Field(default=".", max_length=500)
    file_extensions: List[str] = Field(default_factory=list)
    max_files: int = Field(default=500, ge=1, le=2000)


class ExternalToolInput(ToolInput):
    """Validated input for external tool operations"""
    tool_name: str = Field(..., min_length=1, max_length=50)
    target_path: str = Field(..., max_length=500)
    options: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = Field(default=60, ge=5, le=300)

    @field_validator('tool_name')
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        valid_tools = {
            'semgrep', 'bandit', 'gitleaks', 'npm_audit',
            'safety', 'osv_scanner', 'trufflehog'
        }
        if v.lower() not in valid_tools:
            raise ValueError(f'Unknown external tool: {v}')
        return v.lower()


# ============ Validation Helpers ============

class ToolInputValidator:
    """Validates tool inputs before execution"""

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)

    def validate_file_path(self, path: str) -> str:
        """Validate and normalize a file path"""
        return validate_path(path, self.project_root)

    def validate_file_for_read(
        self,
        path: str,
        max_size: int = DEFAULT_MAX_FILE_SIZE,
        allowed_extensions: Optional[Set[str]] = None,
    ) -> str:
        """Validate a file for reading"""
        abs_path = self.validate_file_path(path)

        if not os.path.isfile(abs_path):
            raise InputValidationError(f"File does not exist: {path}")

        validate_file_extension(abs_path, allowed_extensions)
        validate_file_size(abs_path, max_size)

        return abs_path

    def validate_directory(self, path: str) -> str:
        """Validate a directory path"""
        abs_path = self.validate_file_path(path)

        if not os.path.isdir(abs_path):
            raise InputValidationError(f"Directory does not exist: {path}")

        return abs_path

    def validate_output_path(self, path: str) -> str:
        """Validate a path for writing output"""
        abs_path = self.validate_file_path(path)

        # Ensure parent directory exists
        parent = os.path.dirname(abs_path)
        if not os.path.isdir(parent):
            raise InputValidationError(f"Parent directory does not exist: {parent}")

        return abs_path


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """Sanitize a string value"""
    if not isinstance(value, str):
        value = str(value)

    # Remove null bytes and control characters
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)

    # Truncate to max length
    if len(value) > max_length:
        value = value[:max_length] + "..."

    return value


def sanitize_dict(data: Dict[str, Any], max_depth: int = 5) -> Dict[str, Any]:
    """Recursively sanitize a dictionary"""
    if max_depth <= 0:
        return {"_truncated": True}

    result = {}
    for key, value in data.items():
        key = sanitize_string(str(key), 100)

        if isinstance(value, str):
            result[key] = sanitize_string(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value, max_depth - 1)
        elif isinstance(value, list):
            result[key] = [
                sanitize_dict(v, max_depth - 1) if isinstance(v, dict)
                else sanitize_string(str(v)) if isinstance(v, str)
                else v
                for v in value[:100]  # Limit list items
            ]
        else:
            result[key] = value

    return result

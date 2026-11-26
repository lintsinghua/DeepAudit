"""Tests for agent input validation: path traversal, extension blocking, sanitization."""
import os
import tempfile
import pytest

from app.services.agent.core.validation import (
    validate_path,
    validate_file_extension,
    sanitize_string,
    sanitize_dict,
    ToolInputValidator,
    FileReadInput,
    FileSearchInput,
    CodeAnalysisInput,
    ExternalToolInput,
)
from app.services.agent.core.errors import PathTraversalError, InputValidationError


class TestValidatePath:
    def test_simple_relative(self, temp_dir):
        result = validate_path("src/main.py", temp_dir)
        assert result.endswith("src/main.py")

    def test_traversal_attack(self, temp_dir):
        with pytest.raises(PathTraversalError):
            validate_path("../../etc/passwd", temp_dir)

    def test_absolute_path_blocked(self, temp_dir):
        with pytest.raises(PathTraversalError):
            validate_path("/etc/passwd", temp_dir)

    def test_home_expansion_blocked(self, temp_dir):
        with pytest.raises(PathTraversalError):
            validate_path("~/evil", temp_dir)

    def test_empty_path_raises(self, temp_dir):
        with pytest.raises(InputValidationError):
            validate_path("", temp_dir)

    def test_whitespace_path_raises(self, temp_dir):
        with pytest.raises(InputValidationError):
            validate_path("   ", temp_dir)

    def test_dollar_sign_blocked(self, temp_dir):
        with pytest.raises(PathTraversalError):
            validate_path("$HOME/evil", temp_dir)


class TestValidateFileExtension:
    def test_blocked_extension_exe(self):
        with pytest.raises(InputValidationError):
            validate_file_extension("program.exe")

    def test_blocked_extension_env(self):
        with pytest.raises(InputValidationError):
            validate_file_extension("config.env")

    def test_allowed_extension(self):
        # Should not raise
        validate_file_extension("main.py")

    def test_restricted_allowed_set(self):
        with pytest.raises(InputValidationError):
            validate_file_extension("main.rb", allowed_extensions={".py", ".js"})

    def test_in_restricted_set(self):
        # Should not raise
        validate_file_extension("main.py", allowed_extensions={".py", ".js"})


class TestSanitizeString:
    def test_removes_control_chars(self):
        result = sanitize_string("hello\x00world\x08")
        assert "\x00" not in result
        assert "\x08" not in result

    def test_truncation(self):
        long_string = "a" * 2000
        result = sanitize_string(long_string, max_length=100)
        assert len(result) == 103  # 100 + "..."
        assert result.endswith("...")

    def test_short_string_unchanged(self):
        assert sanitize_string("hello") == "hello"

    def test_non_string_converted(self):
        result = sanitize_string(42)
        assert result == "42"


class TestSanitizeDict:
    def test_simple_dict(self):
        data = {"key": "value"}
        result = sanitize_dict(data)
        assert result == {"key": "value"}

    def test_nested_dict(self):
        data = {"a": {"b": "c"}}
        result = sanitize_dict(data)
        assert result["a"]["b"] == "c"

    def test_max_depth_truncation(self):
        data = {"a": {"b": {"c": {"d": {"e": "deep"}}}}}
        result = sanitize_dict(data, max_depth=0)
        assert result == {"_truncated": True}

    def test_list_truncation(self):
        data = {"items": list(range(200))}
        result = sanitize_dict(data)
        assert len(result["items"]) == 100  # capped at 100

    def test_string_values_sanitized(self):
        data = {"key": "hello\x00world"}
        result = sanitize_dict(data)
        assert "\x00" not in result["key"]


class TestPydanticInputModels:
    def test_file_read_input_valid(self):
        inp = FileReadInput(file_path="/some/file.py")
        assert inp.file_path == "/some/file.py"

    def test_file_read_input_line_range_invalid(self):
        with pytest.raises(Exception):
            FileReadInput(file_path="test.py", start_line=10, end_line=5)

    def test_file_search_input_valid(self):
        inp = FileSearchInput(pattern="cursor.execute")
        assert inp.pattern == "cursor.execute"

    def test_file_search_input_invalid_regex(self):
        with pytest.raises(Exception):
            FileSearchInput(pattern="[invalid")

    def test_code_analysis_input_valid(self):
        inp = CodeAnalysisInput(file_path="test.py", analysis_type="security")
        assert inp.analysis_type == "security"

    def test_code_analysis_input_invalid_type(self):
        with pytest.raises(Exception):
            CodeAnalysisInput(file_path="test.py", analysis_type="invalid")

    def test_external_tool_input_valid(self):
        inp = ExternalToolInput(tool_name="semgrep", target_path="/code")
        assert inp.tool_name == "semgrep"

    def test_external_tool_input_unknown_tool(self):
        with pytest.raises(Exception):
            ExternalToolInput(tool_name="nonexistent_tool", target_path="/code")


class TestToolInputValidator:
    def test_validate_file_path(self, temp_dir):
        validator = ToolInputValidator(temp_dir)
        # Create a file
        file_path = os.path.join(temp_dir, "test.py")
        with open(file_path, "w") as f:
            f.write("print('hello')")

        result = validator.validate_file_path("test.py")
        assert result == os.path.realpath(os.path.join(temp_dir, "test.py"))

    def test_validate_file_for_read(self, temp_dir):
        validator = ToolInputValidator(temp_dir)
        file_path = os.path.join(temp_dir, "test.py")
        with open(file_path, "w") as f:
            f.write("code")

        result = validator.validate_file_for_read("test.py")
        assert os.path.isfile(result)

    def test_validate_file_not_found(self, temp_dir):
        validator = ToolInputValidator(temp_dir)
        with pytest.raises(InputValidationError):
            validator.validate_file_for_read("nonexistent.py")

    def test_validate_directory(self, temp_dir):
        validator = ToolInputValidator(temp_dir)
        result = validator.validate_directory(".")
        assert os.path.isdir(result)

    def test_validate_directory_not_found(self, temp_dir):
        validator = ToolInputValidator(temp_dir)
        with pytest.raises(InputValidationError):
            validator.validate_directory("nonexistent_dir")

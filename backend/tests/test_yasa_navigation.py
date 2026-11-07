"""A slow native child must not survive navigation initialization's timeout."""
import os
import subprocess
import sys

import pytest

from app.services.yasa_audit.config import AuditConfig
from app.services.yasa_audit.runner import init_navigation


def _cli(tmp_path, body):
    path = tmp_path / "mock-mcp"
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)
    return AuditConfig(yasamcp_bin=str(path))


def test_navigation_timeout_stops_native_child(tmp_path):
    cfg = _cli(tmp_path, '''import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path(__file__).with_suffix('.child').write_text(str(child.pid))
print('native child started', flush=True)
time.sleep(60)
''')
    child_pid = None
    try:
        with pytest.raises(RuntimeError, match="navigation process group stopped"):
            init_navigation(cfg, tmp_path, timeout_s=1)
        child_pid = int((tmp_path / "mock-mcp.child").read_text())
        state = subprocess.run(["ps", "-p", str(child_pid), "-o", "stat="],
                               capture_output=True, text=True).stdout.strip()
        assert not state or state.startswith("Z"), state
        assert "native child started" in (tmp_path / ".yasa/navigation-init.log").read_text()
    finally:
        marker = tmp_path / "mock-mcp.child"
        if child_pid is None and marker.exists():
            child_pid = int(marker.read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, 9)
            except ProcessLookupError:
                pass


def test_navigation_success_preserves_diagnostics(tmp_path):
    cfg = _cli(tmp_path, "import sys\nprint('cache ready')\nprint('diagnostic', file=sys.stderr)\n")
    init_navigation(cfg, tmp_path, timeout_s=5)
    log = (tmp_path / ".yasa/navigation-init.log").read_text()
    assert "cache ready" in log and "diagnostic" in log


def test_navigation_failure_reports_diagnostic_path(tmp_path):
    cfg = _cli(tmp_path, "print('parser failed')\nraise SystemExit(3)\n")
    with pytest.raises(RuntimeError, match="exited with code 3; log:"):
        init_navigation(cfg, tmp_path, timeout_s=5)
    assert "parser failed" in (tmp_path / ".yasa/navigation-init.log").read_text()

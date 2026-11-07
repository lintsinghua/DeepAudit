"""Platform resolution and offline installer regression tests."""
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.services.yasa_audit import config


@pytest.mark.parametrize("system,machine,expected", [
    ("Darwin", "arm64", "darwin-aarch64"),
    ("Darwin", "aarch64", "darwin-aarch64"),
    ("Darwin", "x86_64", "darwin-x86-64"),
    ("Linux", "x86_64", "linux-x86-64"),
])
def test_native_tool_paths(monkeypatch, tmp_path, system, machine, expected):
    monkeypatch.setattr(config.platform, "system", lambda: system)
    monkeypatch.setattr(config.platform, "machine", lambda: machine)
    assert config.platform_directory() == expected
    monkeypatch.setattr(config, "DEFAULT_HOME", tmp_path)
    monkeypatch.setattr(config, "DEFAULT_TOOLS", tmp_path / "tools" / expected)
    for name in ("YASA_BIN", "YASAMCP_BIN", "YASA_RG_BIN", "YASAMCP_TOOLS_DIR"):
        monkeypatch.delenv(name, raising=False)
    mcp = tmp_path / "mcp" / expected / "yasamcp"
    mcp.parent.mkdir(parents=True)
    mcp.write_text("#!/bin/sh\nexit 0\n")
    mcp.chmod(0o755)
    cfg = config.AuditConfig()
    assert cfg.yasa_bin == str(tmp_path / "tools" / expected / "yasa/yasa")
    assert cfg.rg_bin == str(tmp_path / "tools" / expected / "ripgrep/rg")
    assert cfg.yasamcp_bin == str(mcp)
    assert cfg.yasamcp_tools_dir == str(tmp_path / "tools")
    monkeypatch.setenv("YASA_BIN", "/custom/yasa")
    monkeypatch.setenv("YASAMCP_BIN", "/custom/yasa-mcp")
    monkeypatch.setenv("YASA_RG_BIN", "/custom/rg")
    monkeypatch.setenv("YASAMCP_TOOLS_DIR", "/custom/tools")
    cfg = config.AuditConfig()
    assert (cfg.yasa_bin, cfg.yasamcp_bin, cfg.rg_bin, cfg.yasamcp_tools_dir) == (
        "/custom/yasa", "/custom/yasa-mcp", "/custom/rg", "/custom/tools")


def test_legacy_source_virtualenv(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEFAULT_HOME", tmp_path)
    mcp = tmp_path / "venv/bin/yasa-mcp"
    mcp.parent.mkdir(parents=True)
    mcp.touch()
    assert config._default_yasamcp() == str(mcp)


def _executable(path, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


@pytest.fixture
def installer(tmp_path):
    """Fake only uname and downloads; exercise real extraction, checksum and validation."""
    bindir = tmp_path / "bin"
    _executable(bindir / "uname", '#!/bin/sh\ncase "$1" in -s) echo "$TEST_OS";; -m) echo "$TEST_ARCH";; esac\n')
    _executable(bindir / "curl", f'''#!{sys.executable}
import os, pathlib, shutil, sys
args=sys.argv[1:]
url=args[-1]
dest=args[args.index('-o')+1]
with open(os.environ['DOWNLOAD_LOG'], 'a') as log: log.write(url+'\\n')
shutil.copyfile(pathlib.Path(os.environ['FIXTURES']) / url.rsplit('/',1)[-1], dest)
''')
    env = os.environ.copy()
    env.update(PATH=f"{bindir}:{env['PATH']}", PYTHON=sys.executable,
               YASAMCP_HOME=str(tmp_path / "install"), FIXTURES=str(tmp_path / "fixtures"),
               DOWNLOAD_LOG=str(tmp_path / "downloads.txt"), YASAMCP_VERSION="yasamcp-v1.0.3")
    env.pop("YASA_REF", None)
    script = Path(__file__).resolve().parents[1] / "scripts/setup_yasa.sh"
    return script, env, tmp_path


@pytest.mark.parametrize("system,machine,plat", [
    ("Darwin", "arm64", "darwin-aarch64"),
    ("Darwin", "aarch64", "darwin-aarch64"),
    ("Darwin", "x86_64", "darwin-x86-64"),
    ("Linux", "x86_64", "linux-x86-64"),
])
def test_installer_platform_and_reuse(installer, system, machine, plat):
    script, env, root = installer
    fixtures = Path(env["FIXTURES"])
    fixtures.mkdir()
    with zipfile.ZipFile(fixtures / f"{plat}.zip", "w") as archive:
        for rel in ("yasa/yasa", "ripgrep/rg", "scc/scc"):
            archive.writestr(f"{plat}/{rel}", "#!/bin/sh\nexit 0\n")
    bundle = root / f"yasamcp-{plat}"
    _executable(bundle / "yasamcp", "#!/bin/sh\nexit 0\n")
    (bundle / "lib").mkdir()
    (bundle / "lib/resource.txt").write_text("bundled resource")
    mcp_archive = fixtures / f"yasamcp-{plat}.tar.gz"
    with tarfile.open(mcp_archive, "w:gz") as archive:
        archive.add(bundle, arcname=bundle.name)
    digest = hashlib.sha256(mcp_archive.read_bytes()).hexdigest()
    (fixtures / "sha256sum.txt").write_text(f"{digest}  releases/{mcp_archive.name}\n")
    env.update(TEST_OS=system, TEST_ARCH=machine)
    first = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    home = Path(env["YASAMCP_HOME"])
    assert (home / "mcp" / plat / "lib/resource.txt").is_file()
    assert json.loads((home / "config.json").read_text())["binary_path"] == str(home / "tools")
    downloads = Path(env["DOWNLOAD_LOG"]).read_text()
    assert f"/{plat}.zip" in downloads and f"yasamcp-{plat}.tar.gz" in downloads
    second = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert second.returncode == 0, second.stdout + second.stderr
    assert Path(env["DOWNLOAD_LOG"]).read_text() == downloads
    # A tampered release must not replace the installed bundle.
    (home / "mcp" / plat / "version.txt").unlink()
    (fixtures / "sha256sum.txt").write_text(f"{'0' * 64}  releases/{mcp_archive.name}\n")
    invalid = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert invalid.returncode != 0
    assert "SHA256 verification failed" in invalid.stderr
    assert (home / "mcp" / plat / "lib/resource.txt").read_text() == "bundled resource"


def test_unsupported_installer_platform(installer):
    script, env, root = installer
    env.update(TEST_OS="Linux", TEST_ARCH="aarch64")
    result = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and "unsupported platform" in result.stderr
    assert not Path(env["DOWNLOAD_LOG"]).exists()
    assert not Path(env["YASAMCP_HOME"]).exists()

#!/usr/bin/env bash
# Install the YASA engine binaries and the yasa-mcp CLI used by app/services/yasa_audit.
#
#   bash backend/scripts/setup_yasa.sh            # installs into ~/.yasamcp
#   YASAMCP_HOME=/opt/yasamcp bash backend/scripts/setup_yasa.sh
#
# Supports Linux x86_64, macOS Apple Silicon and macOS Intel.
# By default use the official yasa-mcp onedir release (including its lib/ resources).
# Set YASA_REF to install from source in an isolated virtualenv instead.
set -euo pipefail

HOME_DIR="${YASAMCP_HOME:-$HOME/.yasamcp}"
YASAMCP_VERSION="${YASAMCP_VERSION:-yasamcp-v1.0.3}"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) PLAT="linux-x86-64" ;;
  Darwin-arm64|Darwin-aarch64) PLAT="darwin-aarch64" ;;
  Darwin-x86_64) PLAT="darwin-x86-64" ;;
  *) echo "unsupported platform: $(uname -s)-$(uname -m) (supported: Linux x86_64, macOS ARM64/x86_64)" >&2; exit 1 ;;
esac
PY="${PYTHON:-python3}"
TOOLS="$HOME_DIR/tools"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$TOOLS"

if [ ! -x "$TOOLS/$PLAT/yasa/yasa" ]; then
  echo "downloading YASA native engines..."
  curl -fsSL --retry 2 -o "$WORK/engines.zip" "https://yasa.oss-cn-beijing.aliyuncs.com/$PLAT.zip"
  unzip -q "$WORK/engines.zip" -d "$WORK/engines"
  rm -rf "$TOOLS/$PLAT"
  mv "$WORK/engines/$PLAT" "$TOOLS/$PLAT"
  find "$TOOLS/$PLAT" -type f \( -name yasa -o -name rg -o -name scc -o -name codegraph -o -path '*/yasa/deps/*' \) -exec chmod u+x {} +
fi
"$PY" - "$HOME_DIR/config.json" "$TOOLS" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"binary_path": sys.argv[2]}))
PY

if [ -n "${YASA_REF:-}" ]; then
  echo "installing yasa-mcp from source ($YASA_REF)..."
  git clone --depth 1 --branch "$YASA_REF" https://github.com/antgroup/YASA-Engine.git "$WORK/yasa-src"
  [ -x "$HOME_DIR/venv/bin/python" ] || "$PY" -m venv "$HOME_DIR/venv"
  "$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
  "$HOME_DIR/venv/bin/python" -m pip install --quiet "$WORK/yasa-src/yasamcp"
  PKG_DIR="$("$HOME_DIR/venv/bin/python" -c 'import yasa_mcp, os; print(os.path.dirname(yasa_mcp.__file__))')"
  ( cd "$WORK/yasa-src/yasamcp/src/yasa_mcp" &&
    find . -type f ! -name '*.py' ! -path '*/__pycache__/*' -exec sh -c \
      'mkdir -p "$1/$(dirname "$2")" && cp "$2" "$1/$2"' _ "$PKG_DIR" {} \; )
  MCP_BIN="$HOME_DIR/venv/bin/yasa-mcp"
else
  MCP_DIR="$HOME_DIR/mcp/$PLAT"
  MCP_BIN="$MCP_DIR/yasamcp"
  if [ ! -x "$MCP_BIN" ] || [ "$(cat "$MCP_DIR/version.txt" 2>/dev/null || true)" != "$YASAMCP_VERSION" ]; then
    ARCHIVE="yasamcp-$PLAT.tar.gz"
    RELEASE="https://github.com/antgroup/YASA-Engine/releases/download/$YASAMCP_VERSION"
    echo "downloading yasa-mcp $YASAMCP_VERSION ($PLAT)..."
    curl -fsSL --retry 2 -o "$WORK/$ARCHIVE" "$RELEASE/$ARCHIVE"
    curl -fsSL --retry 2 -o "$WORK/sha256sum.txt" "$RELEASE/sha256sum.txt"
    "$PY" - "$WORK/$ARCHIVE" "$WORK/sha256sum.txt" <<'PY'
import hashlib, sys
from pathlib import Path
archive, sums = map(Path, sys.argv[1:])
expected = next((line.split()[0] for line in sums.read_text().splitlines()
                 if len(line.split()) == 2 and Path(line.split()[1]).name == archive.name), None)
with archive.open('rb') as source:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b''):
        digest.update(chunk)
if expected is None or digest.hexdigest() != expected:
    raise SystemExit('yasa-mcp SHA256 verification failed')
PY
    tar -xzf "$WORK/$ARCHIVE" -C "$WORK"
    test -f "$WORK/yasamcp-$PLAT/yasamcp"
    test -d "$WORK/yasamcp-$PLAT/lib"
    mkdir -p "$HOME_DIR/mcp"
    rm -rf "$MCP_DIR"
    mv "$WORK/yasamcp-$PLAT" "$MCP_DIR"
    chmod u+x "$MCP_BIN"
    echo "$YASAMCP_VERSION" > "$MCP_DIR/version.txt"
  fi
fi


"$TOOLS/$PLAT/yasa/yasa" --version >/dev/null 2>&1 || "$TOOLS/$PLAT/yasa/yasa" --help >/dev/null 2>&1 \
  || { echo "YASA engine does not start" >&2; exit 1; }
"$TOOLS/$PLAT/ripgrep/rg" --version >/dev/null || { echo "ripgrep does not start" >&2; exit 1; }
"$MCP_BIN" --help >/dev/null || { echo "yasa-mcp does not start" >&2; exit 1; }

echo
echo "done: $HOME_DIR ($PLAT)"
if [ -n "${YASA_REF:-}" ]; then
  echo "source install: start the backend with YASAMCP_BIN=$MCP_BIN"
fi
if [ "$HOME_DIR" != "$HOME/.yasamcp" ]; then
  echo "non-default location: start the backend with YASAMCP_HOME=$HOME_DIR"
fi

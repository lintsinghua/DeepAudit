#!/usr/bin/env bash
# Install the YASA engine binaries and the yasa-mcp CLI used by app/services/yasa_audit.
#
#   bash backend/scripts/setup_yasa.sh            # installs into ~/.yasamcp
#   YASAMCP_HOME=/opt/yasamcp bash backend/scripts/setup_yasa.sh
#
# Linux x86_64 only (the platforms YASA publishes binaries for are linux-x64 and macOS).
# yasa-mcp goes into its own virtualenv ($YASAMCP_HOME/venv), so system Python is left untouched.
# With the default location no environment variables are needed: app.services.yasa_audit finds
# everything under ~/.yasamcp.
# yasa-mcp is installed from source because its pip package currently omits non-Python resources
# (repository/mapper/**/*.sql, tools/ast_grep/rules/**); without them `func` and `search` fail
# with KeyError. This script copies those files into the installed package.
set -euo pipefail

HOME_DIR="${YASAMCP_HOME:-$HOME/.yasamcp}"
YASA_REF="${YASA_REF:-main}"
PLAT="linux-x86-64"
TOOLS="$HOME_DIR/tools"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[ "$(uname -s)-$(uname -m)" = "Linux-x86_64" ] || { echo "only Linux x86_64 is supported" >&2; exit 1; }
mkdir -p "$TOOLS"

if [ ! -x "$TOOLS/$PLAT/yasa/yasa" ]; then
  echo "downloading YASA native engines..."
  curl -fsSL -o "$WORK/engines.zip" "https://yasa.oss-cn-beijing.aliyuncs.com/$PLAT.zip"
  unzip -q "$WORK/engines.zip" -d "$WORK/engines"
  rm -rf "$TOOLS/$PLAT"
  mv "$WORK/engines/$PLAT" "$TOOLS/$PLAT"
  chmod +x "$TOOLS/$PLAT/yasa/yasa" "$TOOLS/$PLAT/yasa/deps/"* "$TOOLS/$PLAT/ripgrep/rg" "$TOOLS/$PLAT/scc/scc" || true
fi
echo "{\"binary_path\": \"$TOOLS\"}" > "$HOME_DIR/config.json"

echo "installing yasa-mcp from source ($YASA_REF)..."
git clone --depth 1 --branch "$YASA_REF" https://github.com/antgroup/YASA-Engine.git "$WORK/yasa-src"
PY="${PYTHON:-python3}"
[ -x "$HOME_DIR/venv/bin/python" ] || "$PY" -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/python" -m pip install --quiet --upgrade pip
"$HOME_DIR/venv/bin/python" -m pip install --quiet "$WORK/yasa-src/yasamcp"
PKG_DIR="$("$HOME_DIR/venv/bin/python" -c 'import yasa_mcp, os; print(os.path.dirname(yasa_mcp.__file__))')"
( cd "$WORK/yasa-src/yasamcp/src/yasa_mcp" &&
  find . -type f ! -name '*.py' ! -path '*/__pycache__/*' -exec sh -c \
    'mkdir -p "$1/$(dirname "$2")" && cp "$2" "$1/$2"' _ "$PKG_DIR" {} \; )


"$TOOLS/$PLAT/yasa/yasa" --version >/dev/null 2>&1 || "$TOOLS/$PLAT/yasa/yasa" --help >/dev/null 2>&1 \
  || { echo "YASA engine does not start" >&2; exit 1; }
"$HOME_DIR/venv/bin/yasa-mcp" --help >/dev/null || { echo "yasa-mcp does not start" >&2; exit 1; }

echo
echo "done: $HOME_DIR"
if [ "$HOME_DIR" != "$HOME/.yasamcp" ]; then
  echo "non-default location: start the backend with YASAMCP_HOME=$HOME_DIR"
fi

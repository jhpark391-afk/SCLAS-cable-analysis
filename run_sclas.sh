#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

if [ -x "$WORKSPACE_DIR/90_env/venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/venv/bin/python"
elif [ -x "$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python"
else
    echo "No SCLAS virtualenv Python found under $WORKSPACE_DIR/90_env" >&2
    exit 1
fi

exec "$PYTHON" "$PROJECT_DIR/code/sclas_remote_gui.py"

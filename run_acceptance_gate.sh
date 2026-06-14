#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

if [ -x "$WORKSPACE_DIR/90_env/venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/venv/bin/python"
elif [ -x "$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    echo "ERROR: Python was not found." >&2
    exit 1
fi

"$PYTHON" "$PROJECT_DIR/code/sclas_acceptance_gate.py" --save-report --save-markdown

echo
echo "Acceptance gate report saved in the latest job folder."

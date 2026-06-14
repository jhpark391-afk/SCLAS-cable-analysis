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

echo "[1/4] Running SCLAS self-check"
"$PYTHON" "$PROJECT_DIR/code/sclas_self_check.py"

echo
echo "[2/4] Saving acceptance gate report"
"$PYTHON" "$PROJECT_DIR/code/sclas_acceptance_gate.py" --save-report --save-markdown

echo
echo "[3/4] Saving handoff snapshot"
"$PYTHON" "$PROJECT_DIR/code/sclas_handoff_snapshot.py" --save-report --save-markdown

echo
echo "[4/4] Saving next Codex prompt"
"$PYTHON" "$PROJECT_DIR/code/sclas_next_prompt.py" --save

echo
echo "Validation suite complete."
echo "Generated local reports are intentionally ignored by git."

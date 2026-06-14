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

"$PYTHON" "$PROJECT_DIR/code/sclas_validation_suite.py" --save-report --save-markdown

echo
echo "Validation suite complete."
echo "Generated local reports are intentionally ignored by git:"
echo "  $PROJECT_DIR/validation_suite_report.json"
echo "  $PROJECT_DIR/validation_suite_report.md"

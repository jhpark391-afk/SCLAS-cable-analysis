#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x "../90_env/venv/bin/python" ]; then
  PYTHON_BIN="../90_env/venv/bin/python"
fi

"$PYTHON_BIN" code/sclas_session_brief.py --save-report --save-markdown "$@"

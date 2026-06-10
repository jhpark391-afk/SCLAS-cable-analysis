#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSPACE_DIR="$(cd "$PROJECT_DIR/.." && pwd)"

if [ -x "$WORKSPACE_DIR/90_env/venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/venv/bin/python"
    PYQT_SITE="$WORKSPACE_DIR/90_env/venv/lib/python3.12/site-packages/PyQt5"
elif [ -x "$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python" ]; then
    PYTHON="$WORKSPACE_DIR/90_env/SCLAS_test_venv/bin/python"
    PYQT_SITE="$WORKSPACE_DIR/90_env/SCLAS_test_venv/lib/python3.12/site-packages/PyQt5"
else
    echo "No SCLAS virtualenv Python found under $WORKSPACE_DIR/90_env" >&2
    exit 1
fi

export QT_PLUGIN_PATH="$PYQT_SITE/Qt5/plugins"
export QT_QPA_PLATFORM_PLUGIN_PATH="$PYQT_SITE/Qt5/plugins/platforms"

exec "$PYTHON" "$PROJECT_DIR/code/sclas_remote_gui.py"

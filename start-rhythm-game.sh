#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_NAME="Raspberry-PI-Rythm-game-implementation"

if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    REPO_DIR=$SCRIPT_DIR
else
    REPO_DIR="$SCRIPT_DIR/$REPO_NAME"
fi

if [ ! -f "$REPO_DIR/pyproject.toml" ]; then
    echo "error: rhythm game repository not found at $REPO_DIR" >&2
    exit 1
fi

VENV_DIR="$REPO_DIR/.venv"
COMMAND="$VENV_DIR/bin/pi2-rhythm"
CONFIG_FILE="$REPO_DIR/config.toml"

# A nonempty config beside an externally installed helper script is the cabinet
# override. Missing/empty overrides fall back to the tracked stock config.
if [ "$SCRIPT_DIR" != "$REPO_DIR" ] && [ -s "$SCRIPT_DIR/config.toml" ]; then
    CONFIG_FILE="$SCRIPT_DIR/config.toml"
fi

if [ ! -s "$CONFIG_FILE" ]; then
    echo "error: no nonempty config; run the updater to restore the stock config" >&2
    exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv --system-site-packages "$VENV_DIR"
fi

if [ ! -x "$COMMAND" ]; then
    echo "Installing rhythm game into the virtual environment..."
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR" --no-deps
fi

cd "$REPO_DIR"
exec "$COMMAND" --config "$CONFIG_FILE" --kiosk "$@"

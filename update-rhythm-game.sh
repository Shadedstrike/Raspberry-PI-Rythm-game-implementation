#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_NAME="Raspberry-PI-Rythm-game-implementation"

# The script lives in the repository in git, but is intended to be moved to
# the repository's parent directory on the Pi.
if [ -d "$SCRIPT_DIR/.git" ]; then
    REPO_DIR=$SCRIPT_DIR
else
    REPO_DIR="$SCRIPT_DIR/$REPO_NAME"
fi

CONFIG_FILE="$REPO_DIR/config.toml"

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "error: git repository not found at $REPO_DIR" >&2
    exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "error: config file not found at $CONFIG_FILE" >&2
    exit 1
fi

TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rhythm-game-update.XXXXXX")
SAVED_CONFIG="$TEMP_DIR/config.toml"
RESTORE_NEEDED=true

restore_config() {
    if [ "$RESTORE_NEEDED" = true ] && [ -f "$SAVED_CONFIG" ]; then
        mv -f -- "$SAVED_CONFIG" "$CONFIG_FILE"
    fi
    rmdir "$TEMP_DIR" 2>/dev/null || true
}

trap restore_config EXIT HUP INT TERM

cp -p -- "$CONFIG_FILE" "$SAVED_CONFIG"

# Remove the cabinet-specific tracked edit so it cannot block the pull. The
# saved copy is restored whether the pull succeeds or fails.
git -C "$REPO_DIR" restore --source=HEAD -- config.toml
git -C "$REPO_DIR" pull --ff-only

mv -f -- "$SAVED_CONFIG" "$CONFIG_FILE"
RESTORE_NEEDED=false
rmdir "$TEMP_DIR"

VENV_DIR="$REPO_DIR/.venv"
if [ -x "$VENV_DIR/bin/pip" ]; then
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR" --no-deps
fi

echo "Updated $REPO_DIR and restored config.toml"
echo "Revision: $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "Launcher: $VENV_DIR/bin/pi2-rhythm"

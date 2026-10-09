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

TEMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rhythm-game-update.XXXXXX")
SAVED_CONFIG="$TEMP_DIR/config.toml"
RESTORE_NEEDED=true
HAVE_SAVED_CONFIG=false

restore_config() {
    if [ "$RESTORE_NEEDED" = true ] && [ "$HAVE_SAVED_CONFIG" = true ] && [ -s "$SAVED_CONFIG" ]; then
        mv -f -- "$SAVED_CONFIG" "$CONFIG_FILE"
    fi
    rmdir "$TEMP_DIR" 2>/dev/null || true
}

trap restore_config EXIT HUP INT TERM

# Preserve a cabinet-specific repository config only when it contains data.
# A missing/zero-byte file must never replace the tracked stock configuration.
if [ -s "$CONFIG_FILE" ]; then
    cp -p -- "$CONFIG_FILE" "$SAVED_CONFIG"
    HAVE_SAVED_CONFIG=true
fi

# Fetch first, then recover the stock configuration directly from the remote
# tree. This works even when the local file was deleted, truncated, or the local
# HEAD predates config.toml. Fast-forward only after the damaged path is clean.
git -C "$REPO_DIR" fetch origin main
git -C "$REPO_DIR" restore --source=origin/main -- config.toml
git -C "$REPO_DIR" merge --ff-only origin/main

if [ "$HAVE_SAVED_CONFIG" = true ]; then
    mv -f -- "$SAVED_CONFIG" "$CONFIG_FILE"
    CONFIG_RESULT="restored nonempty cabinet config"
else
    CONFIG_RESULT="using stock config (cabinet config was missing or empty)"
fi
RESTORE_NEEDED=false
rmdir "$TEMP_DIR"

VENV_DIR="$REPO_DIR/.venv"
if [ -x "$VENV_DIR/bin/pip" ]; then
    "$VENV_DIR/bin/pip" install -e "$REPO_DIR" --no-deps
fi

echo "Updated $REPO_DIR; $CONFIG_RESULT"
echo "Revision: $(git -C "$REPO_DIR" rev-parse --short HEAD)"
echo "Launcher: $VENV_DIR/bin/pi2-rhythm"

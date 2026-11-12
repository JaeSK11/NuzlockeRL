#!/usr/bin/env bash
# Create the venv and build PyNDS from source (the pip wheel can't read memory).
# Usage: scripts/setup_env.sh [VENV_DIR]   (default ~/venvs/nuzlockerl)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${1:-$HOME/venvs/nuzlockerl}"
PYNDS_COMMIT=5a40a52

python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -r "$ROOT/requirements.txt"
mkdir -p "$ROOT/repos"
if [ ! -d "$ROOT/repos/PyNDS" ]; then
  git clone -q https://github.com/unexploredtest/PyNDS.git "$ROOT/repos/PyNDS"
fi
cd "$ROOT/repos/PyNDS"
git fetch -q --unshallow 2>/dev/null || true
git checkout -q "$PYNDS_COMMIT"
git submodule update --init --recursive
# A fixed DS clock (NOODS_RTC_EPOCH, set by src/gen4.py), so runs don't depend on the host's time
PATCH="$ROOT/patches/noods-fixed-rtc.patch"
if ! git -C externals/NooDS apply --reverse --check "$PATCH" 2>/dev/null; then
  git -C externals/NooDS apply "$PATCH"
fi
PATH="$VENV/bin:$PATH" "$VENV/bin/pip" install --no-build-isolation .
echo "OK: $VENV  (needs system libportaudio2 for 'import pynds')"

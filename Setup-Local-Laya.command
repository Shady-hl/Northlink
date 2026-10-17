#!/bin/zsh
set -e
cd "$(dirname "$0")"
export PIP_CACHE_DIR="$PWD/.pip-cache"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_INPUT=1
print 'Online setup: install app dependencies and optional Laya model. No paid API is used.'
if [[ ! -x .venv/bin/python ]]; then
  NORTHLINK_SETUP_PYTHON=""
  for candidate in python3.14 python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,12))'; then
      NORTHLINK_SETUP_PYTHON="$(command -v "$candidate")"
      break
    fi
  done
  if [[ -z "$NORTHLINK_SETUP_PYTHON" ]]; then
    print 'Install Python 3.12 or newer, then run this setup again.'
    read -r '?Press Return to close.'
    exit 1
  fi
  "$NORTHLINK_SETUP_PYTHON" -m venv .venv
fi
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -r requirements.txt
if [[ ! -x .venv-laya/bin/python ]]; then
  .venv/bin/python -m venv .venv-laya
fi
.venv-laya/bin/python -m ensurepip --upgrade
.venv-laya/bin/python -m pip install -r requirements-laya.txt
.venv-laya/bin/python scripts/prepare_laya.py
print 'Ready. Double-click Start-Northlink.command. Setup needs internet; normal classification does not.'
read -r '?Press Return to close.'

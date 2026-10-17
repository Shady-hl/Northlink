#!/bin/zsh
set -e
cd "$(dirname "$0")"
PYTHON=".venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  print 'Prepare this laptop while online first; see README.md for installation steps.'
  read -r '?Press Return to close.'
  exit 1
fi
export NORTHLINK_DB="${NORTHLINK_DB:-$PWD/data/northlink.db}"
print 'Northlink refined: http://localhost:8528'
print 'Keep this window running. Press Ctrl+C to stop.'
exec "$PYTHON" -m streamlit run app.py --server.port 8528 "$@"

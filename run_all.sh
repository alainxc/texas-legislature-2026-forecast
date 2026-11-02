#!/usr/bin/env bash
# One-command pipeline: fetch -> baseline -> forecast -> backtest -> site -> zip.
# Usage: ./run_all.sh [--as-of YYYY-MM-DD] [--skip-fetch]
set -euo pipefail
cd "$(dirname "$0")"
ASOF=""; SKIP=0
while [ $# -gt 0 ]; do case "$1" in --as-of) ASOF="--as-of $2"; shift 2;; --skip-fetch) SKIP=1; shift;; *) echo "unknown arg $1"; exit 1;; esac; done
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; fi
PY=".venv/bin/python"
if [ "$SKIP" = 0 ]; then
  for f in pipeline/fetch/fetch_*.py; do echo "== $f"; $PY "$f" || echo "!! $f failed; continuing with cached data"; done
fi
echo "== geometry";  (cd pipeline && ../$PY build_geo.py)
echo "== baseline";  (cd pipeline && ../$PY baseline.py >/dev/null)
echo "== forecast";  (cd pipeline && ../$PY forecast.py $ASOF | grep -v '^NOTE' || true)
echo "== backtest";  (cd pipeline && ../$PY backtest.py | grep -v '^NOTE' | cut -c1-200 || true)
echo "== site";      (cd pipeline && ../$PY build_site.py)
echo "== zip";       ./make_zip.sh

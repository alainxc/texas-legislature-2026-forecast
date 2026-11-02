#!/usr/bin/env bash
# Zip the built site into the repository root as site-YYYYMMDD-HHMM.zip (the deploy workflow
# publishes whichever site-*.zip in the root was committed most recently). Older zips are kept
# only if KEEP_OLD_ZIPS=1; by default they are removed so the repo stays small.
set -euo pipefail
cd "$(dirname "$0")"
[ -f site/index.html ] || { echo "site/ not built; run ./run_all.sh first"; exit 1; }
name="site-$(date +%Y%m%d-%H%M).zip"
[ "${KEEP_OLD_ZIPS:-0}" = 1 ] || rm -f site-*.zip
(cd site && zip -q -r "../$name" . -x '.DS_Store')
echo "wrote $name ($(du -h "$name" | cut -f1))"

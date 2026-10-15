#!/usr/bin/env bash
# D077 reproduction: fetch the published branch and run targeted + full 506 suite.
set -u
BR=feature/test-nested-scan-order
DIR=$(mktemp -d)
git clone -q --branch "$BR" --single-branch https://github.com/Dolesh-avkalan/drive-tool.git "$DIR"
cd "$DIR"
echo "head: $(git rev-parse HEAD)"
echo "tree: $(git rev-parse HEAD^{tree})"
echo "blob: $(git rev-parse HEAD:tests/test_partial_scan_review_fixes.py)"
for PY in python3.11 python3.12; do
  echo "=== $PY targeted ==="; $PY -m unittest tests.test_partial_scan_review_fixes -v 2>&1 | tail -3
  echo "=== $PY full ===";     $PY -m unittest discover -s tests 2>&1 | tail -3
done
rm -rf "$DIR"

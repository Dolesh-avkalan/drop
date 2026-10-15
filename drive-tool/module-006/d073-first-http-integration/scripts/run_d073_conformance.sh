#!/usr/bin/env bash
# D073 reproduction: fetch the integration branch and run the combined conformance.
set -u
BR=feature/module-006b-http-integration
DIR=$(mktemp -d)
git clone -q --branch "$BR" --single-branch https://github.com/Dolesh-avkalan/drive-tool.git "$DIR"
cd "$DIR"
echo "head: $(git rev-parse HEAD)"
echo "tree: $(git rev-parse HEAD^{tree})"
echo "adapter blob: $(git rev-parse HEAD:drive_tool/http_adapter.py)"
echo "test blob:    $(git rev-parse HEAD:tests/test_http_adapter.py)"
for PY in python3.11 python3.12; do
  echo "=== $PY focused ==="; $PY -m unittest tests.test_http_adapter 2>&1 | tail -4
  echo "=== $PY full ===";    $PY -m unittest discover -s tests   2>&1 | tail -4
done
rm -rf "$DIR"

#!/usr/bin/env bash
# D076 reproduction: targeted oldfail (base cc9c994e) vs newpass (branch), both interpreters.
set -u
BR=feature/module-006b-http-save-test
T=SaveUncertaintyTests.test_post_lease_save_failure_is_uncertain
for REF in cc9c994e64a52793949b58699f707c53f47c4369 "$BR"; do
  DIR=$(mktemp -d)
  git clone -q https://github.com/Dolesh-avkalan/drive-tool.git "$DIR"
  ( cd "$DIR" && git checkout -q "$REF" && echo "=== $REF ===" && git rev-parse HEAD \
    && for PY in python3.11 python3.12; do echo "--- $PY ---"; $PY -m unittest tests.test_http_adapter.$T 2>&1 | tail -3; done )
  rm -rf "$DIR"
done

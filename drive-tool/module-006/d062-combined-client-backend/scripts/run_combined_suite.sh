#!/usr/bin/env bash
# D062 — run the full combined suite / probes / mutations against the published
# integrated bytes on Python 3.11 and 3.12.
#
# Usage: run_combined_suite.sh <path-to-published-tree> <outdir>
set -u
TREE="${1:?published tree path required}"
OUT="${2:?output dir required}"
mkdir -p "$OUT/logs"
cd "$TREE" || exit 2

MODS=$(ls tests/test_*.py | sed 's#/#.#; s#\.py$##' | tr '\n' ' ')

for PY in python3.11 python3.12; do
  echo "== full combined suite ($PY) =="
  PYTHONPATH=. "$PY" -m unittest -v $MODS > "$OUT/logs/suite_full_$PY.txt" 2>&1
  echo "exit=$?"
  PYTHONPATH=. "$PY" -m unittest -v tests.test_file_service > "$OUT/logs/suite_focused_$PY.txt" 2>&1
  echo "focused exit=$?"
done

SCRIPTS="$(dirname "$0")"
for PY in python3.11 python3.12; do
  echo "== probes ($PY) =="
  PYTHONPATH="$TREE" "$PY" "$SCRIPTS/reproduce_probes.py" > "$OUT/logs/probes_$PY.txt" 2>&1
  echo "exit=$?"
done

echo "== mutations =="
python3.12 "$SCRIPTS/reproduce_mutations.py" --cand "$TREE" \
  --out "$OUT/logs/mutations.txt" --pythons python3.11,python3.12
echo "exit=$?"

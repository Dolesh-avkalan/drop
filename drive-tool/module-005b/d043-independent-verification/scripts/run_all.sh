#!/bin/sh
# D043 independent verification runner (reviewer: Sarvam).
# Reproduces the full-suite runs, the independent probe and the builder
# mutation runner against candidate head 121faf848b2f33f80721239fc7716adba7a9ba62.
#
# Environment used: Debian GNU/Linux 12 (bookworm), x86_64, non-root uid 1000,
# kernel 4.19.0-gvisor. Interpreters: Python 3.11.2 and 3.12.13.
# No strace/ltrace is present on this kernel, so syscall observation is done
# through the adapter's own OS seams (which delegate to the real os calls).
#
# CAND must point at a checkout of the candidate head (the builder's runner
# hardcodes SRC_REPO=/scratch/repos/drive-tool, so place the candidate there).
set -eu

CAND="${1:-/scratch/repos/drive-tool}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "== candidate: $CAND =="
sha256sum "$CAND/drive_tool/local.py"

echo "== full committed suite =="
( cd "$CAND" && python3.11 -m unittest discover -s tests -v )
( cd "$CAND" && python3.12 -m unittest discover -s tests -v )

echo "== independent adversarial probe =="
python3.11 "$HERE/scripts/d043_independent_probe.py" "$CAND"
python3.12 "$HERE/scripts/d043_independent_probe.py" "$CAND"

echo "== builder mutation runner (published, unmodified) =="
python3.12 "$HERE/scripts/mutation_runner.py" python3.12
python3.11 "$HERE/scripts/mutation_runner.py" python3.11

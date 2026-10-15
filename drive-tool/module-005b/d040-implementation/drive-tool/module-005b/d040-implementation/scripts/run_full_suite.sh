#!/bin/sh
# MODULE-005B full committed-suite runner (documents the exact commands used).
#
# Environment: Debian GNU/Linux 12 (bookworm), x86_64, non-root uid 1000.
# Interpreter A: Python 3.11.2   Interpreter B: Python 3.12.13.
# Run from the drive-tool repository root, on branch
# feature/module-005b-range-read (head 121faf848b2f33f80721239fc7716adba7a9ba62).
#
# Expected result: 351 tests, OK, exit 0 on each interpreter, zero skips.
set -eu

python3.11 --version
python3.12 --version

python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v

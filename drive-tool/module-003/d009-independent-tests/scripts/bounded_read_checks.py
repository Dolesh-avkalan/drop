#!/usr/bin/env python3
"""d009 independent bounded-read checks (asserting).

Provenance: written independently for d009; does not reuse any d007 script.

Checks, against the revised adapter (PYTHONPATH=<checkout>):
  1. below-limit   : file size M-10 -> exact bytes returned
  2. exact-limit   : file size M     -> exact bytes returned
  3. above-limit   : file size M+1   -> ReadLimitExceededError from fstat
  4. grow-during-read : file starts at M, grows past M via the _os_read seam
                        -> ReadLimitExceededError (fstat cannot be bypassed)
  5. under-report-stat : _os_fstat lies that the (really M+500) file is tiny
                        -> ReadLimitExceededError at read time (cap is M+1)

Exit 0 iff all five behave as specified.
"""
from __future__ import annotations

import os
import shutil
import stat as statmod
import sys
import tempfile

from drive_tool.local import LocalAdapter, ReadLimitExceededError
from drive_tool.storage import FileRef

M = 1000
failures: list[str] = []


def _mkroot(base):
    root = os.path.join(base, "root")
    os.mkdir(root)
    return root


def _write(path, n, byte=b"A"):
    with open(path, "wb") as fh:
        fh.write(byte * n)


def _check(name, cond, detail=""):
    if cond:
        print(f"PASS {name} {detail}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


def main() -> int:
    print(f"python {sys.version.split()[0]} | d009 bounded-read checks | max_read_bytes={M}")
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_bounded_"))
    try:
        root = _mkroot(base)
        _write(os.path.join(root, "below.bin"), M - 10)
        _write(os.path.join(root, "exact.bin"), M)
        _write(os.path.join(root, "above.bin"), M + 1)

        with LocalAdapter("src", root, max_read_bytes=M) as ad:
            r = ad.read_bytes(FileRef("src", "p/below.bin"))
            _check("below-limit", r == b"A" * (M - 10), f"(len={len(r)})")
            r = ad.read_bytes(FileRef("src", "p/exact.bin"))
            _check("exact-limit", r == b"A" * M, f"(len={len(r)})")
            try:
                ad.read_bytes(FileRef("src", "p/above.bin"))
                _check("above-limit", False, "(no error raised)")
            except ReadLimitExceededError as exc:
                _check("above-limit", True, f"({type(exc).__name__})")

        # 4. deterministic growth during read
        grow_root = os.path.join(base, "grow")
        os.mkdir(grow_root)
        grow_path = os.path.join(grow_root, "g.bin")
        _write(grow_path, M)
        ad = LocalAdapter("src", grow_root, max_read_bytes=M)
        real_read = ad._os_read
        state = {"grown": False}

        def read_hook(fd, length):
            if not state["grown"]:
                state["grown"] = True
                with open(grow_path, "ab") as fh:  # file grows after fstat
                    fh.write(b"B" * M)
            return real_read(fd, length)

        ad._os_read = read_hook
        try:
            ad.read_bytes(FileRef("src", "p/g.bin"))
            _check("grow-during-read", False, "(no error; growth bypassed the cap)")
        except ReadLimitExceededError as exc:
            _check("grow-during-read", True, f"({type(exc).__name__})")
        finally:
            ad._os_read = real_read
            ad.close()

        # 5. fstat under-reports the real (larger) file size
        lie_root = os.path.join(base, "lie")
        os.mkdir(lie_root)
        lie_path = os.path.join(lie_root, "l.bin")
        _write(lie_path, M + 500)
        ad = LocalAdapter("src", lie_root, max_read_bytes=M)
        real_fstat = ad._os_fstat

        def fstat_hook(fd):
            st = real_fstat(fd)
            if statmod.S_ISREG(st.st_mode) and st.st_size > M:
                vals = list(st)
                vals[6] = 10  # st_size index
                return os.stat_result(vals)
            return st

        ad._os_fstat = fstat_hook
        try:
            ad.read_bytes(FileRef("src", "p/l.bin"))
            _check("under-report-stat", False, "(no error; cap bypassed)")
        except ReadLimitExceededError as exc:
            _check("under-report-stat", True, f"({type(exc).__name__})")
        finally:
            ad._os_fstat = real_fstat
            ad.close()

        print()
        if failures:
            print(f"RESULT: FAIL - {failures}")
            return 1
        print("RESULT: PASS - all bounded-read checks behaved as specified")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Independent failure-path descriptor-cleanup probe (uses /proc/self/fd).

Complements the suite's own fd tests by hammering mixed success/failure paths
and asserting the live descriptor count returns to baseline. Read-only review
probe: creates throwaway fixtures only.

Run:  python3.11 fd_probe.py   /   python3.12 fd_probe.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.environ.get("DRIVE_TOOL_ROOT", "/scratch/work/dt-checkout"))

from drive_tool.local import (  # noqa: E402
    LocalAdapter,
    ReadLimitExceededError,
    UnsafePathError,
)
from drive_tool.storage import FileRef, NotFoundError, ROOT_ID  # noqa: E402


def fdcount() -> int:
    return len(os.listdir("/proc/self/fd"))


def main() -> int:
    if not os.path.isdir("/proc/self/fd"):
        print("TESTS_NOT_RUN: /proc/self/fd unavailable")
        return 2
    base = os.path.realpath(tempfile.mkdtemp(prefix="fd_probe_"))
    root = os.path.join(base, "root")
    outside = os.path.join(base, "outside")
    os.mkdir(root)
    os.mkdir(outside)
    with open(os.path.join(root, "file.txt"), "wb") as fh:
        fh.write(b"hello")
    with open(os.path.join(root, "big.bin"), "wb") as fh:
        fh.write(b"x" * 100)
    sub = os.path.join(root, "a", "b")
    os.makedirs(sub)
    with open(os.path.join(sub, "f.txt"), "wb") as fh:
        fh.write(b"data")
    os.symlink(outside, os.path.join(sub, "sym"))

    baseline = fdcount()
    adapter = LocalAdapter("src", root, max_read_bytes=20)
    after_init = fdcount()

    for _ in range(50):
        adapter.stat(FileRef("src", ROOT_ID))
        adapter.stat(FileRef("src", "p/a/b/f.txt"))
        adapter.list_children(FileRef("src", ROOT_ID))
        adapter.list_children(FileRef("src", "p/a/b"))
        adapter.read_bytes(FileRef("src", "p/a/b/f.txt"))
        try:
            adapter.read_bytes(FileRef("src", "p/a/b/missing.txt"))
        except NotFoundError:
            pass
        try:
            adapter.stat(FileRef("src", "p/a/b/sym/escape"))
        except UnsafePathError:
            pass
        try:
            adapter.read_bytes(FileRef("src", "p/big.bin"))
        except ReadLimitExceededError:
            pass

    during = fdcount()
    adapter.close()
    end = fdcount()

    print(f"baseline={baseline} after_init={after_init} during_50_loops={during} after_close={end}")
    ok = (after_init == baseline + 1) and (during == baseline + 1) and (end == baseline)
    print("RESULT:", "PASS (no leak)" if ok else "FAIL (descriptor count drifted)")
    shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

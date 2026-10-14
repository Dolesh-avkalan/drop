#!/usr/bin/env python3
"""Independent bounded-read edge probe.

Two angles the suite does not cover directly:
  (1) A very large *apparent* size (sparse file) must be rejected by the upfront
      fstat gate WITHOUT calling os.read and without allocating proportional to
      the untrusted size.
  (2) A file that grows after fstat must yield at most max_read_bytes + 1 bytes
      read from the descriptor (independent re-derivation of the suite's seam).

Run:  python3.11 bounded_probe.py   /   python3.12 bounded_probe.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.environ.get("DRIVE_TOOL_ROOT", "/scratch/work/dt-checkout"))

from drive_tool.local import LocalAdapter, ReadLimitExceededError  # noqa: E402
from drive_tool.storage import FileRef  # noqa: E402


def main() -> int:
    # Use tmpfs (/dev/shm) so a large apparent size stays sparse.
    fsroot = "/dev/shm" if os.path.isdir("/dev/shm") else tempfile.gettempdir()
    base = os.path.realpath(tempfile.mkdtemp(prefix="bounded_probe_", dir=fsroot))
    root = os.path.join(base, "root")
    os.mkdir(root)

    # --- (1) large sparse file, apparent size 2 GiB, limit 1 MiB ---
    sparse = os.path.join(root, "huge.bin")
    with open(sparse, "wb") as fh:
        fh.truncate(2 * 1024 * 1024 * 1024)
    apparent = os.stat(sparse).st_size
    blocks = os.stat(sparse).st_blocks

    adapter = LocalAdapter("src", root, max_read_bytes=1024 * 1024)
    read_calls: list[int] = []
    real_read = adapter._os_read

    def counting_read(fd, length):
        read_calls.append(length)
        return real_read(fd, length)

    adapter._os_read = counting_read
    outcome = None
    try:
        adapter.read_bytes(FileRef("src", "p/huge.bin"))
        outcome = "NO ERROR (unexpected)"
    except ReadLimitExceededError as exc:
        outcome = f"ReadLimitExceededError: {exc}"
    print(f"(1) apparent_size={apparent} st_blocks={blocks}")
    print(f"    outcome={outcome}")
    print(f"    os.read calls before rejection={len(read_calls)}")
    adapter.close()

    # --- (2) grow-after-fstat: at most limit + 1 bytes read from descriptor ---
    grow = os.path.join(root, "grow.bin")
    with open(grow, "wb") as fh:
        fh.write(b"0123456789")  # 10 bytes, limit 16
    adapter2 = LocalAdapter("src", root, max_read_bytes=16)
    real_fstat = adapter2._os_fstat
    real_read2 = adapter2._os_read
    total = 0

    def fstat_then_append(fd):
        st = real_fstat(fd)
        with open(grow, "ab") as w:
            w.write(b"X" * 100)
        return st

    def counting_read2(fd, length):
        nonlocal total
        chunk = real_read2(fd, length)
        total += len(chunk)
        return chunk

    adapter2._os_fstat = fstat_then_append
    adapter2._os_read = counting_read2
    outcome2 = None
    try:
        adapter2.read_bytes(FileRef("src", "p/grow.bin"))
        outcome2 = "NO ERROR (unexpected)"
    except ReadLimitExceededError as exc:
        outcome2 = f"ReadLimitExceededError: {exc}"
    print(f"(2) outcome={outcome2}")
    print(f"    bytes read from descriptor={total} (expected max_read_bytes+1 = 17)")
    adapter2.close()

    shutil.rmtree(base, ignore_errors=True)
    ok = (len(read_calls) == 0) and (total == 17)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

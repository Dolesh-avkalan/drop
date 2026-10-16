#!/usr/bin/env python3
"""D119 repro E: semantic mutant against the CORRECTED oracle.

Applies a non-atomic-publish mutant to the product (runtime patch only) and runs
the PATCHED payload's concurrent_ops. The corrected stage must still FAIL
(torn/inconsistent reads) -- proving the lease fix did not blind the oracle and
did not blanket-forgive faults.
"""
import os, sys, time, importlib.util

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
PATCHED = "/scratch/work/d119/harsh_checks_d110.patched.py"
sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location("patched_d110", PATCHED)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

from drive_tool.local_write import LocalWriter

_orig = LocalWriter._os_rename


def nonatomic_rename(self, src, dst, src_dir_fd=None, dst_dir_fd=None):
    sfd = os.open(src, os.O_RDONLY, dir_fd=src_dir_fd)
    data = b""
    while True:
        c = os.read(sfd, 65536)
        if not c:
            break
        data += c
    os.close(sfd)
    dfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644, dir_fd=dst_dir_fd)
    half = len(data) // 2
    os.write(dfd, data[:half])
    time.sleep(0.03)
    os.write(dfd, data[half:])
    os.close(dfd)
    os.unlink(src, dir_fd=src_dir_fd)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    LocalWriter._os_rename = nonatomic_rename
    try:
        caught = 0
        for i in range(n):
            r = P.stage_concurrent_ops(REPO, 120.0)
            if r.get("result") != "PASS":
                caught += 1
            print("  mutant iter %d: result=%s torn=%s problems=%s"
                  % (i, r.get("result"), r.get("torn_count"),
                     (r.get("problems") or [])[:1]))
            sys.stdout.flush()
        print("PATCHED stage caught the non-atomic-publish mutant in %d/%d runs"
              % (caught, n))
    finally:
        LocalWriter._os_rename = _orig


if __name__ == "__main__":
    main()

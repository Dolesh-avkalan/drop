#!/usr/bin/env python3
"""D062 assembly — reproduce the combined client+backend candidate from pinned inputs.

Routine assembly only (no design, no fixes). Retrieves the two pinned source
snapshots via pinned codeload tarballs, overlays exactly the two backend files
onto the accepted client base, and asserts:

  * exactly two additions vs the base (no removals, no modifications);
  * the two added files hash to the expected git blobs.

Pins
----
base  (accepted client/main source base) : cbf60867a0ca6e10206d540aed93f40e24b44a5d
backend (feature/module-006a-file-service-independent) : 14729120c0f32ee5d64c1daf93b27fa1b3270d6b
expected blobs : drive_tool/file_service.py  b7e18c606f45066cd54ec66016e70e797486ef50
                 tests/test_file_service.py  8b5248f9365d8cac6e1331bb4677dea48a1778ff

Usage: python3 assemble_candidate.py [--work DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tarfile

BASE = "cbf60867a0ca6e10206d540aed93f40e24b44a5d"
BACKEND = "14729120c0f32ee5d64c1daf93b27fa1b3270d6b"
OWNER_REPO = "Dolesh-avkalan/drive-tool"
OVERLAY = ["drive_tool/file_service.py", "tests/test_file_service.py"]
EXPECTED_BLOBS = {
    "drive_tool/file_service.py": "b7e18c606f45066cd54ec66016e70e797486ef50",
    "tests/test_file_service.py": "8b5248f9365d8cac6e1331bb4677dea48a1778ff",
}


def gitblob(path: str) -> str:
    data = open(path, "rb").read()
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def sha256(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fetch(sha: str, work: str) -> str:
    tgz = os.path.join(work, f"{sha}.tar.gz")
    if not os.path.exists(tgz):
        url = f"https://codeload.github.com/{OWNER_REPO}/tar.gz/{sha}"
        subprocess.run(["curl", "-sSL", "-o", tgz, url], check=True)
    dest = os.path.join(work, sha)
    if not os.path.isdir(dest):
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(tgz) as tf:
            tf.extractall(dest)
    entries = os.listdir(dest)
    assert len(entries) == 1, entries
    return os.path.join(dest, entries[0])


def walk(root: str) -> dict:
    out = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = sha256(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/scratch/work/d062_assembly")
    args = ap.parse_args()
    os.makedirs(args.work, exist_ok=True)

    base = fetch(BASE, args.work)
    backend = fetch(BACKEND, args.work)

    integ = os.path.join(args.work, "integration")
    if os.path.isdir(integ):
        subprocess.run(["rm", "-rf", integ], check=True)
    subprocess.run(["cp", "-a", base, integ], check=True)
    for rel in OVERLAY:
        subprocess.run(["cp", "-a", os.path.join(backend, rel), os.path.join(integ, rel)], check=True)

    wb, wi = walk(base), walk(integ)
    added = sorted(set(wi) - set(wb))
    removed = sorted(set(wb) - set(wi))
    changed = sorted(r for r in set(wb) & set(wi) if wb[r] != wi[r])

    print("added  :", added)
    print("removed:", removed)
    print("changed:", changed)
    ok = True
    if added != sorted(OVERLAY):
        ok = False
        print("FAIL: additions are not exactly the two overlay files")
    if removed or changed:
        ok = False
        print("FAIL: base source is not unchanged")
    for rel in OVERLAY:
        got = gitblob(os.path.join(integ, rel))
        exp = EXPECTED_BLOBS[rel]
        status = "OK" if got == exp else "FAIL"
        if got != exp:
            ok = False
        print(f"[{status}] {rel} gitblob={got} expected={exp}")

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

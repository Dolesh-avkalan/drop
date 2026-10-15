#!/usr/bin/env python3
"""D062 verification — re-fetch the PUBLISHED branch head and verify its bytes.

Retrieves the published commit (feature/module-006a-service-client-integration)
via pinned codeload, re-derives the blob hashes, and re-computes the diff vs the
accepted client base to confirm exactly two additions and an unchanged base.

Usage: python3 verify_published.py [--commit SHA] [--work DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tarfile

OWNER_REPO = "Dolesh-avkalan/drive-tool"
BASE = "cbf60867a0ca6e10206d540aed93f40e24b44a5d"
PUBLISHED = "67d37b2bba1e2676d12c99eff0559c04df6174c8"
EXPECTED_TREE = "d6b5e87cd37e459bb8c3b1c85f97700dc2225ca7"
OVERLAY = ["drive_tool/file_service.py", "tests/test_file_service.py"]
EXPECTED_BLOBS = {
    "drive_tool/file_service.py": "b7e18c606f45066cd54ec66016e70e797486ef50",
    "tests/test_file_service.py": "8b5248f9365d8cac6e1331bb4677dea48a1778ff",
}


def gitblob(path):
    data = open(path, "rb").read()
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fetch(sha, work):
    tgz = os.path.join(work, f"{sha}.tar.gz")
    if not os.path.exists(tgz):
        subprocess.run(["curl", "-sSL", "-o", tgz,
                        f"https://codeload.github.com/{OWNER_REPO}/tar.gz/{sha}"], check=True)
    dest = os.path.join(work, sha)
    if not os.path.isdir(dest):
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(tgz) as tf:
            tf.extractall(dest)
    entries = os.listdir(dest)
    assert len(entries) == 1, entries
    return os.path.join(dest, entries[0])


def walk(root):
    out = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            out[os.path.relpath(p, root)] = sha256(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default=PUBLISHED)
    ap.add_argument("--work", default="/scratch/work/d062_verify")
    args = ap.parse_args()
    os.makedirs(args.work, exist_ok=True)

    pub = fetch(args.commit, args.work)
    base = fetch(BASE, args.work)

    ok = True
    for rel in OVERLAY:
        got = gitblob(os.path.join(pub, rel))
        exp = EXPECTED_BLOBS[rel]
        if got != exp:
            ok = False
        print(f"[{'OK' if got == exp else 'FAIL'}] {rel} gitblob={got} expected={exp}")

    wb, wp = walk(base), walk(pub)
    added = sorted(set(wp) - set(wb))
    removed = sorted(set(wb) - set(wp))
    changed = sorted(r for r in set(wb) & set(wp) if wb[r] != wp[r])
    print("added  :", added)
    print("removed:", removed)
    print("changed:", changed)
    if added != sorted(OVERLAY) or removed or changed:
        ok = False
    print("published commit:", args.commit)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

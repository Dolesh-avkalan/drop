#!/usr/bin/env python3
"""d009 independent root-rename anchoring check (asserting).

Provenance: written independently for d009.

The adapter retains a root directory descriptor. After construction the root
pathname is renamed away and the ORIGINAL pathname is replaced, first by an
outside symlink, then by a real outside directory. The adapter must keep
resolving against the originally opened directory (the retained fd), never the
replacement. Outside content carries a synthetic sentinel only.

Exit 0 iff reads/listings/stat still reflect the ORIGINAL directory after both
replacements.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from drive_tool.local import LocalAdapter
from drive_tool.storage import FileRef, ROOT_ID

ORIG = b"ORIGINAL_INSIDE_BYTES"
EVIL = b"OUTSIDE_SENTINEL_BYTES_0123456789"
failures: list[str] = []


def _check(name, cond, detail=""):
    if cond:
        print(f"PASS {name} {detail}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


def _mk(base, name, payload):
    d = os.path.join(base, name)
    os.mkdir(d)
    with open(os.path.join(d, "a.txt"), "wb") as fh:
        fh.write(payload)
    return d


def main() -> int:
    print(f"python {sys.version.split()[0]} | d009 root-rename anchoring")
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_anchor_"))
    try:
        root = _mk(base, "root", ORIG)
        outside_link_target = _mk(base, "outside_link", EVIL)
        outside_dir = _mk(base, "outside_dir", EVIL)

        ad = LocalAdapter("src", root)

        # Replacement 1: rename root away, put an outside SYMLINK at old path.
        moved = os.path.join(base, "root__moved")
        os.rename(root, moved)
        os.symlink(outside_link_target, root)
        r = ad.read_bytes(FileRef("src", "p/a.txt"))
        _check("symlink-replacement read", r == ORIG, f"(got {r!r})")
        kids = [m.name for m in ad.list_children(FileRef("src", ROOT_ID))]
        _check("symlink-replacement list", kids == ["a.txt"], f"(got {kids})")
        st = ad.stat(FileRef("src", "p/a.txt"))
        _check("symlink-replacement stat", st.size_bytes == len(ORIG), f"(size={st.size_bytes})")

        # Replacement 2: swap the symlink for a real OUTSIDE DIRECTORY.
        os.unlink(root)
        os.rename(outside_dir, root)
        r = ad.read_bytes(FileRef("src", "p/a.txt"))
        _check("dir-replacement read", r == ORIG, f"(got {r!r})")

        ad.close()

        # Control: a NEW adapter built on the replaced path DOES see outside data.
        ad2 = LocalAdapter("src", root)
        r2 = ad2.read_bytes(FileRef("src", "p/a.txt"))
        _check("control: fresh adapter sees outside", r2 == EVIL, f"(got {r2!r})")
        ad2.close()

        print()
        if failures:
            print(f"RESULT: FAIL - {failures}")
            return 1
        print("RESULT: PASS - retained root fd stays anchored to the original directory")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

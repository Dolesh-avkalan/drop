"""Apply the D070 isolated production charging mutation to a fresh copy.

Mutation: in LocalAdapter._post_yield_storage_error, under-charge by one so the
entry that raised from the metadata/stat seam is treated as uncharged
(ScanFailure(entry_count) -> ScanFailure(entry_count - 1)).

This is applied ONLY to an isolated copy under mutation/. It is never applied
to the candidate branch. It must still compile.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

WORK = "/scratch/work/d070"
SRC = os.path.join(WORK, "repo")
DST = os.path.join(WORK, "mutation", "repo")

OLD = """        if isinstance(exc, ScanFailure):
            return exc
        if entry_count > 0:
            return ScanFailure(entry_count, exc)
        return exc"""

NEW = """        if isinstance(exc, ScanFailure):
            return exc
        if entry_count > 0:
            # D070 MUTATION (isolated copy only; never committed to candidate):
            # under-charge by 1 -- the entry that raised from the metadata/stat
            # seam is treated as uncharged.
            return ScanFailure(entry_count - 1, exc)
        return exc"""


def main():
    shutil.rmtree(os.path.join(WORK, "mutation"), ignore_errors=True)
    os.makedirs(os.path.join(WORK, "mutation"), exist_ok=True)
    shutil.copytree(SRC, DST)
    path = os.path.join(DST, "drive_tool", "local.py")
    src = open(path).read()
    if src.count(OLD) != 1:
        print(f"anchor not unique: {src.count(OLD)}")
        sys.exit(2)
    open(path, "w").write(src.replace(OLD, NEW))
    print("mutation applied to", path)
    # prove it compiles on both interpreters
    for py in ("python3.11", "python3.12"):
        subprocess.run([py, "-m", "py_compile", path], check=True)
        print(f"  {py} py_compile OK")
    subprocess.run(["git", "-C", DST, "diff", "drive_tool/local.py"])
    print("mutation diff written above")


if __name__ == "__main__":
    main()

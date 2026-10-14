#!/usr/bin/env python3
"""d009 independent FIFO / special-entry no-hang check (asserting).

Provenance: written independently for d009.

Opening a FIFO for read normally blocks until a writer appears. The adapter must
reject it without blocking. Because a bug here would HANG the test, the read is
executed in a child process under a wall-clock timeout; a timeout is recorded as
a FAIL (hang), never as success.

Also checks stat('p/fifo') -> UnsupportedEntryError and that list_children omits
the FIFO.

Usage:
  PYTHONPATH=<checkout> python3.11 fifo_timeout.py          # parent/driver
  PYTHONPATH=<checkout> python3.11 fifo_timeout.py child <root>   # child op
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import shutil

TIMEOUT_S = 10


def child_main(root: str) -> int:
    from drive_tool.local import LocalAdapter, UnsupportedEntryError
    from drive_tool.storage import FileRef

    ad = LocalAdapter("src", root)
    try:
        r = ad.read_bytes(FileRef("src", "p/fifo"))
        print(f"CHILD read_bytes returned {len(r)} bytes (should not happen)")
        return 2
    except UnsupportedEntryError as exc:
        print(f"CHILD OK: UnsupportedEntryError: {exc}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"CHILD wrong exception {type(exc).__name__}: {exc}")
        return 3
    finally:
        try:
            ad.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    failures: list[str] = []

    def check(name, cond, detail=""):
        if cond:
            print(f"PASS {name} {detail}")
        else:
            print(f"FAIL {name} {detail}")
            failures.append(name)

    print(f"python {sys.version.split()[0]} | d009 FIFO no-hang check")
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_fifo_"))
    try:
        root = os.path.join(base, "root")
        os.mkdir(root)
        os.mkfifo(os.path.join(root, "fifo"))
        with open(os.path.join(root, "regular.txt"), "wb") as fh:
            fh.write(b"R")

        # Child process with timeout: a hang becomes TimeoutExpired, not success.
        try:
            proc = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "child", root],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
            )
            out = (proc.stdout + proc.stderr).strip()
            print("  child:", out.replace("\n", " | "))
            check("fifo-read-no-hang", proc.returncode == 0,
                  f"(rc={proc.returncode}, within {TIMEOUT_S}s)")
        except subprocess.TimeoutExpired:
            check("fifo-read-no-hang", False, f"(HANG: exceeded {TIMEOUT_S}s)")

        # Direct (non-opening) checks in the parent.
        from drive_tool.local import LocalAdapter, UnsupportedEntryError
        from drive_tool.storage import FileRef, ROOT_ID
        ad = LocalAdapter("src", root)
        try:
            try:
                ad.stat(FileRef("src", "p/fifo"))
                check("fifo-stat", False, "(no error)")
            except UnsupportedEntryError:
                check("fifo-stat", True, "(UnsupportedEntryError)")
            except Exception as exc:  # noqa: BLE001
                check("fifo-stat", False, f"(wrong exception {type(exc).__name__})")
            names = [m.name for m in ad.list_children(FileRef("src", ROOT_ID))]
            check("fifo-omitted-from-listing", names == ["regular.txt"], f"(got {names})")
        finally:
            ad.close()

        print()
        if failures:
            print(f"RESULT: FAIL - {failures}")
            return 1
        print("RESULT: PASS - FIFO rejected without blocking and omitted from listing")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "child":
        raise SystemExit(child_main(sys.argv[2]))
    raise SystemExit(main())

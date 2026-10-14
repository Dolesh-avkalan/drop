#!/usr/bin/env python3
"""d012 fresh operational containment checks (primary, fresh provenance).

Re-runs, with tiny synthetic fixtures and independent code:
  * read/stat/list symlink-swap containment (final + intermediate symlinks)
  * root rename anchoring (root renamed, old path replaced by outside symlink)
  * bounded growth/read (fstat lies small, real file large -> at most max+1)
  * FIFO / special entry rejected without blocking (timeout-bounded subprocess)
  * repeated descriptor counts (no fd leak across many ops)

Usage: python3 d012_operational.py <tree> [--json out.json]
Exit 0 iff every check passes (or all skipped on a correctly rejected kernel).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

TREE = None
JSON_OUT = None
FAILS = []
CHECKS = []


def record(name, ok, detail=""):
    CHECKS.append({"check": name, "ok": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def main():
    global TREE, JSON_OUT
    args = list(sys.argv[1:])
    if "--json" in args:
        i = args.index("--json")
        JSON_OUT = args[i + 1]
        del args[i:i + 2]
    TREE = args[0] if args else "."
    sys.path.insert(0, TREE)

    from drive_tool.local import (
        LocalAdapter, LocalStorageError, UnsafePathError, UnsupportedEntryError,
        ReadLimitExceededError, UnsupportedPlatformError, _no_follow_semantics_available,
    )
    from drive_tool.storage import FileRef, StorageError

    print("=== d012 operational containment checks ===")
    print(f"tree: {os.path.abspath(TREE)}")

    if not _no_follow_semantics_available():
        print("SKIP: adapter unsupported on this kernel (fail-closed) -- operational "
              "checks not meaningful here")
        if JSON_OUT:
            with open(JSON_OUT, "w") as fh:
                json.dump({"tree": TREE, "skipped": "unsupported kernel"}, fh, indent=2)
        return 0

    base = tempfile.mkdtemp(prefix="d012op_")
    base = os.path.realpath(base)
    root = os.path.join(base, "root")
    outside = os.path.join(base, "outside")
    os.makedirs(os.path.join(root, "sub", "deep"))
    os.makedirs(outside)
    with open(os.path.join(root, "file.txt"), "wb") as fh:
        fh.write(b"orig-root-data")
    with open(os.path.join(root, "sub", "f2.txt"), "wb") as fh:
        fh.write(b"sub-data")
    with open(os.path.join(outside, "secret.txt"), "wb") as fh:
        fh.write(b"SECRET")

    try:
        ad = LocalAdapter("s", root)
        R = lambda fid: FileRef("s", fid)  # noqa: E731

        # ---- 1. symlink containment ------------------------------------
        # final symlink -> outside file
        os.symlink(os.path.join(outside, "secret.txt"), os.path.join(root, "flink"))
        for meth in ("stat", "read_bytes"):
            try:
                getattr(ad, meth)(R("p/flink"))
                record(f"final symlink rejected by {meth}", False, "no error raised")
            except UnsafePathError:
                record(f"final symlink rejected by {meth}", True)
            except Exception as exc:  # noqa: BLE001
                record(f"final symlink rejected by {meth}", False, f"{type(exc).__name__}")
        # final symlink -> outside dir, via list_children
        os.symlink(outside, os.path.join(root, "dlink"))
        try:
            ad.list_children(R("p/dlink"))
            record("final dir-symlink rejected by list_children", False, "no error")
        except UnsafePathError:
            record("final dir-symlink rejected by list_children", True)
        except Exception as exc:  # noqa: BLE001
            record("final dir-symlink rejected by list_children", False, type(exc).__name__)
        # intermediate symlink -> outside dir
        try:
            ad.stat(R("p/dlink/secret.txt"))
            record("intermediate symlink rejected by stat", False, "no error")
        except UnsafePathError:
            record("intermediate symlink rejected by stat", True)
        except Exception as exc:  # noqa: BLE001
            record("intermediate symlink rejected by stat", False, type(exc).__name__)
        # listing omits symlinks and specials, never follows them
        names = [m.name for m in ad.list_children(R("root"))]
        record("listing omits symlinks", "flink" not in names and "dlink" not in names,
               f"names={names}")

        # ---- 2. root rename anchoring ----------------------------------
        moved = os.path.join(base, "root_moved")
        os.rename(root, moved)
        os.symlink(outside, root)   # old pathname now points outside
        with open(os.path.join(outside, "file.txt"), "wb") as fh:
            fh.write(b"DECOY-OVERWRITE")
        try:
            got = ad.read_bytes(R("p/file.txt"))
            record("root anchoring: read stays in original dir", got == b"orig-root-data",
                   f"got={got!r}")
        except Exception as exc:  # noqa: BLE001
            record("root anchoring: read stays in original dir", False,
                   f"{type(exc).__name__}: {exc}")
        try:
            names2 = [m.name for m in ad.list_children(R("root"))]
            record("root anchoring: listing stays in original dir",
                   "secret.txt" not in names2 and "file.txt" in names2, f"names={names2}")
        except Exception as exc:  # noqa: BLE001
            record("root anchoring: listing stays in original dir", False,
                   f"{type(exc).__name__}: {exc}")
        ad.close()

        # ---- 3. bounded read / growth ----------------------------------
        br = tempfile.mkdtemp(prefix="d012br_")
        br = os.path.realpath(br)
        f_small = os.path.join(br, "small.bin")
        f_exact = os.path.join(br, "exact.bin")
        f_over = os.path.join(br, "over.bin")
        with open(f_small, "wb") as fh:
            fh.write(b"abc")          # 3
        with open(f_exact, "wb") as fh:
            fh.write(b"abcdefgh")     # 8
        with open(f_over, "wb") as fh:
            fh.write(b"abcdefghi")    # 9
        ad2 = LocalAdapter("s", br, max_read_bytes=8)
        record("bounded read below limit", ad2.read_bytes(R("p/small.bin")) == b"abc")
        record("bounded read exact limit", ad2.read_bytes(R("p/exact.bin")) == b"abcdefgh")
        try:
            ad2.read_bytes(R("p/over.bin"))
            record("bounded read above limit rejected", False, "no error")
        except ReadLimitExceededError:
            record("bounded read above limit rejected", True)
        except Exception as exc:  # noqa: BLE001
            record("bounded read above limit rejected", False, type(exc).__name__)

        # growth after fstat: fstat reports small, real file is 100 bytes
        grow = os.path.join(br, "grow.bin")
        with open(grow, "wb") as fh:
            fh.write(b"x" * 100)
        ad3 = LocalAdapter("s", br, max_read_bytes=10)

        class Lying(LocalAdapter):
            read_bytes_total = 0

            def _os_fstat(self, fd):
                st = os.fstat(fd)
                if stat.S_ISREG(st.st_mode):
                    return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                           st.st_uid, st.st_gid, 5, 0, 0, 0))  # size=5
                return st

            def _os_read(self, fd, length):
                chunk = os.read(fd, length)
                type(self).read_bytes_total += len(chunk)
                return chunk

        ad4 = Lying("s", br, max_read_bytes=10)
        Lying.read_bytes_total = 0
        try:
            ad4.read_bytes(R("p/grow.bin"))
            record("growth-after-fstat rejected", False, "no error raised")
        except ReadLimitExceededError:
            record("growth-after-fstat rejected", True)
        except Exception as exc:  # noqa: BLE001
            record("growth-after-fstat rejected", False, type(exc).__name__)
        record("growth-after-fstat read bounded to max+1", Lying.read_bytes_total <= 11,
               f"bytes read={Lying.read_bytes_total} (limit+1=11)")
        ad4.close(); ad2.close(); ad3.close()

        # ---- 4. FIFO / special entry, non-blocking ---------------------
        fdir = tempfile.mkdtemp(prefix="d012fifo_")
        fdir = os.path.realpath(fdir)
        fifo = os.path.join(fdir, "pipe")
        made_fifo = True
        try:
            os.mkfifo(fifo)
        except OSError as exc:
            made_fifo = False
            record("FIFO fixture created", False, f"mkfifo failed: {exc}")
        if made_fifo:
            child = (
                "import sys; sys.path.insert(0, %r)\n"
                "from drive_tool.local import LocalAdapter, UnsupportedEntryError\n"
                "from drive_tool.storage import FileRef\n"
                "a = LocalAdapter('s', %r)\n"
                "try:\n"
                "    a.read_bytes(FileRef('s','p/pipe'))\n"
                "    print('NO_ERROR')\n"
                "except UnsupportedEntryError:\n"
                "    print('UNSUPPORTED_ENTRY')\n"
                "except Exception as e:\n"
                "    print('OTHER:'+type(e).__name__)\n"
            ) % (TREE, fdir)
            try:
                p = subprocess.run([sys.executable, "-c", child], capture_output=True,
                                   text=True, timeout=15)
                out = p.stdout.strip()
                record("FIFO read rejected without blocking (bounded subprocess)",
                       out == "UNSUPPORTED_ENTRY" and p.returncode == 0,
                       f"out={out!r} rc={p.returncode}")
            except subprocess.TimeoutExpired:
                record("FIFO read rejected without blocking (bounded subprocess)", False,
                       "TIMEOUT: read blocked on FIFO")
            # listing omits the FIFO
            adf = LocalAdapter("s", fdir)
            try:
                names = [m.name for m in adf.list_children(FileRef("s", "root"))]
                record("listing omits FIFO", "pipe" not in names, f"names={names}")
            except Exception as exc:  # noqa: BLE001
                record("listing omits FIFO", False, f"{type(exc).__name__}: {exc}")
            adf.close()

        # ---- 5. repeated descriptor counts -----------------------------
        try:
            fd_dir = "/proc/self/fd"
            before = len(os.listdir(fd_dir))
            ad5 = LocalAdapter("s", br)
            for _ in range(200):
                ad5.stat(R("p/small.bin"))
                ad5.list_children(R("root"))
                ad5.read_bytes(R("p/small.bin"))
                try:
                    ad5.read_bytes(R("p/does-not-exist"))
                except StorageError:
                    pass
            ad5.close()
            after = len(os.listdir(fd_dir))
            record("no fd leak across 200 op cycles", after <= before + 1,
                   f"before={before} after={after}")
        except FileNotFoundError:
            record("no fd leak across 200 op cycles", False, "/proc/self/fd unavailable")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    npass = sum(1 for c in CHECKS if c["ok"])
    print(f"RESULT: {npass} passed, {len(CHECKS) - npass} failed, {len(CHECKS)} total")
    if JSON_OUT:
        with open(JSON_OUT, "w") as fh:
            json.dump({"tree": os.path.abspath(TREE), "checks": CHECKS,
                       "passed": npass, "failed": len(CHECKS) - npass}, fh, indent=2)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())

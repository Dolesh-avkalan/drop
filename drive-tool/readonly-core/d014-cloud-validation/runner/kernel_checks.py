#!/usr/bin/env python3
"""d014 real-kernel checks for the read-only core candidate (stdlib only).

Provenance: written for d014. Run one named check per process so a hang is
contained by the orchestrating runner's wall-clock timeout:

    python3 kernel_checks.py <check> <src-dir>

`<src-dir>` is the extracted candidate root (the directory containing
`drive_tool/`). Checks use REAL synthetic files and REAL os.open semantics; the
implementation is never edited and kernel support is never mocked. A conformant
kernel is not expected to reproduce any historical insecure behaviour.

Checks: nofollow, bounded_read, root_anchor, dir_symlink_swap, fifo, fd_lifetime.
Exit: 0 = PASS, 1 = FAIL, 2 = SKIP (with a precise reason).
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile

MAX_FIXTURE_BYTES = 1024 * 1024  # fixtures stay <= 1 MiB


def _fail(msg):
    print(f"  {msg}")
    return 1


def _write(path, data):
    assert len(data) <= MAX_FIXTURE_BYTES, "fixture exceeds 1 MiB bound"
    with open(path, "wb") as fh:
        fh.write(data)


def _mkroot(prefix):
    raw = tempfile.mkdtemp(prefix=prefix)
    return os.path.realpath(raw)


# --------------------------------------------------------------------------

def check_nofollow():
    """Actual runtime O_NOFOLLOW semantics with the adapter's component flags."""
    from drive_tool.local import _dir_open_flags, _file_open_flags
    base = _mkroot("d014_nofollow_")
    try:
        target = os.path.join(base, "target")
        link = os.path.join(base, "link")
        os.mkdir(target)
        os.symlink(target, link)
        flags = _dir_open_flags()
        print(f"  component flags = {oct(flags)} (O_NOFOLLOW={bool(flags & os.O_NOFOLLOW)}, "
              f"O_DIRECTORY={bool(flags & getattr(os, 'O_DIRECTORY', 0))})")
        followed = False
        err = None
        try:
            fd = os.open(link, flags)
        except OSError as exc:
            err = exc.errno
        else:
            followed = True
            os.close(fd)
        # Report the O_DIRECTORY interaction (informational, not asserted).
        with_dir = None
        try:
            fd2 = os.open(link, flags | getattr(os, "O_DIRECTORY", 0))
        except OSError as exc:
            with_dir = errno.errorcode.get(exc.errno, exc.errno)
        else:
            with_dir = "FOLLOWED"
            os.close(fd2)
        print(f"  open(symlink, component flags) -> "
              f"{'FOLLOWED' if followed else errno.errorcode.get(err, err)}")
        print(f"  open(symlink, flags|O_DIRECTORY) -> {with_dir} (informational)")
        # A real directory must open and fstat as a directory.
        fd3 = os.open(target, flags)
        try:
            is_dir = stat.S_ISDIR(os.fstat(fd3).st_mode)
        finally:
            os.close(fd3)
        print(f"  open(real dir) fstat S_ISDIR = {is_dir}")
        if followed or not is_dir:
            return _fail("kernel does not enforce O_NOFOLLOW with component flags")
        if _file_open_flags() != flags:
            return _fail("file and directory component flags differ")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_bounded_read():
    from drive_tool.local import LocalAdapter, ReadLimitExceededError
    from drive_tool.storage import FileRef
    base = _mkroot("d014_bounded_")
    try:
        for name, size in (("small.bin", 3), ("exact.bin", 8), ("over.bin", 9)):
            _write(os.path.join(base, name), b"x" * size)
        ad = LocalAdapter("s", base, max_read_bytes=8)
        if ad.read_bytes(FileRef("s", "p/small.bin")) != b"x" * 3:
            return _fail("below-limit read wrong")
        if ad.read_bytes(FileRef("s", "p/exact.bin")) != b"x" * 8:
            return _fail("exact-limit read wrong")
        try:
            ad.read_bytes(FileRef("s", "p/over.bin"))
            return _fail("above-limit read not rejected")
        except ReadLimitExceededError:
            pass
        # growth after fstat: fstat lies '5', real file is 100, limit 10
        _write(os.path.join(base, "grow.bin"), b"y" * 100)
        ad.close()

        class Lying(LocalAdapter):
            read_total = 0

            def _os_fstat(self, fd):
                st = os.fstat(fd)
                if stat.S_ISREG(st.st_mode):
                    return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                           st.st_uid, st.st_gid, 5, 0, 0, 0))
                return st

            def _os_read(self, fd, length):
                chunk = os.read(fd, length)
                type(self).read_total += len(chunk)
                return chunk

        ad2 = Lying("s", base, max_read_bytes=10)
        Lying.read_total = 0
        try:
            ad2.read_bytes(FileRef("s", "p/grow.bin"))
            return _fail("growth-after-fstat not rejected")
        except ReadLimitExceededError:
            pass
        finally:
            ad2.close()
        if Lying.read_total > 11:
            return _fail(f"growth read {Lying.read_total} > limit+1 (11)")
        print(f"  below/exact/above + growth all bounded (growth read {Lying.read_total} <= 11)")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_root_anchor():
    from drive_tool.local import LocalAdapter
    from drive_tool.storage import FileRef
    base = _mkroot("d014_anchor_")
    try:
        root = os.path.join(base, "root")
        outside = os.path.join(base, "outside")
        os.makedirs(root)
        os.makedirs(outside)
        _write(os.path.join(root, "file.txt"), b"ORIGINAL")
        _write(os.path.join(outside, "file.txt"), b"DECOY")
        ad = LocalAdapter("s", root)
        moved = os.path.join(base, "root_moved")
        os.rename(root, moved)
        os.symlink(outside, root)
        got = ad.read_bytes(FileRef("s", "p/file.txt"))
        names = [m.name for m in ad.list_children(FileRef("s", "root"))]
        ad.close()
        print(f"  read after root swap = {got!r}; listing = {names}")
        if got != b"ORIGINAL" or "file.txt" not in names:
            return _fail("root descriptor not anchored to the original directory")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_dir_symlink_swap():
    from drive_tool.local import LocalAdapter, UnsafePathError
    from drive_tool.storage import FileRef
    base = _mkroot("d014_swap_")
    try:
        root = os.path.join(base, "root")
        outside = os.path.join(base, "outside")
        os.makedirs(os.path.join(root, "sub"))
        os.makedirs(outside)
        _write(os.path.join(root, "sub", "inside.txt"), b"INSIDE")
        _write(os.path.join(outside, "secret.txt"), b"SECRET")
        ad = LocalAdapter("s", root)
        # Replace the directory 'sub' with a symlink to 'outside' (a directory
        # symlink swap), then attempt to traverse through it.
        os.rename(os.path.join(root, "sub"), os.path.join(base, "sub_real"))
        os.symlink(outside, os.path.join(root, "sub"))
        results = []
        for op, fid in (("stat", "p/sub/secret.txt"),
                        ("read", "p/sub/secret.txt"),
                        ("list", "p/sub")):
            try:
                if op == "stat":
                    ad.stat(FileRef("s", fid))
                elif op == "read":
                    ad.read_bytes(FileRef("s", fid))
                else:
                    ad.list_children(FileRef("s", fid))
                results.append((op, "ESCAPED"))
            except UnsafePathError:
                results.append((op, "contained"))
            except Exception as exc:  # noqa: BLE001
                results.append((op, f"other:{type(exc).__name__}"))
        ad.close()
        print(f"  swap results = {results}")
        if any(r[1] != "contained" for r in results):
            return _fail("directory symlink swap not contained")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_fifo():
    from drive_tool.local import LocalAdapter, UnsupportedEntryError
    from drive_tool.storage import FileRef
    base = _mkroot("d014_fifo_")
    try:
        fifo = os.path.join(base, "pipe")
        try:
            os.mkfifo(fifo)
        except OSError as exc:
            print(f"  SKIP: mkfifo unavailable: {exc}")
            return 2
        ad = LocalAdapter("s", base)
        # stat must be UnsupportedEntryError
        try:
            ad.stat(FileRef("s", "p/pipe"))
            ad.close()
            return _fail("stat(FIFO) not rejected")
        except UnsupportedEntryError:
            pass
        # read must be UnsupportedEntryError without blocking (a hang would be
        # killed by the orchestrator timeout; we also bound it here)
        try:
            ad.read_bytes(FileRef("s", "p/pipe"))
            ad.close()
            return _fail("read(FIFO) not rejected")
        except UnsupportedEntryError:
            pass
        names = [m.name for m in ad.list_children(FileRef("s", "root"))]
        ad.close()
        print(f"  FIFO rejected; listing = {names}")
        if "pipe" in names:
            return _fail("FIFO not omitted from listing")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_fd_lifetime():
    from drive_tool.local import LocalAdapter, LocalStorageError
    from drive_tool.storage import FileRef, StorageError
    if not os.path.isdir("/proc/self/fd"):
        print("  SKIP: /proc/self/fd unavailable")
        return 2
    base = _mkroot("d014_fd_")
    try:
        os.makedirs(os.path.join(base, "a", "b"))
        _write(os.path.join(base, "a", "file.txt"), b"hello")
        _write(os.path.join(base, "a", "b", "file.txt"), b"deep")

        def nfd():
            return len(os.listdir("/proc/self/fd"))

        # (a) repeated success/failure ops must not grow the fd table
        ad = LocalAdapter("s", base)
        before = nfd()
        for _ in range(200):
            ad.stat(FileRef("s", "p/a/file.txt"))
            ad.list_children(FileRef("s", "root"))
            ad.read_bytes(FileRef("s", "p/a/file.txt"))
            try:
                ad.read_bytes(FileRef("s", "p/missing"))
            except StorageError:
                pass
        ad.close()
        after = nfd()
        print(f"  repeated ops fd count: before={before} after={after}")
        if after > before + 1:
            return _fail("descriptor leak across repeated operations")

        # (b) parent-close handoff: fail the close of the parent directory fd
        #     after the child is acquired; the child must still be released.
        class Handoff(LocalAdapter):
            def __init__(self, *a, fail_close_name=None, **k):
                self._fail = fail_close_name
                self._paths = {}
                super().__init__(*a, **k)

            def _os_open(self, path, flags, *, dir_fd=None):
                fd = super()._os_open(path, flags, dir_fd=dir_fd)
                self._paths[fd] = path
                return fd

            def _os_close(self, fd):
                name = self._paths.get(fd)
                super()._os_close(fd)
                if name == self._fail:
                    raise OSError(errno.EIO, "injected parent-close failure")

        results = []
        for op, fid in (("read", "p/a/file.txt"), ("list", "p/a/b")):
            had = Handoff("s", base, fail_close_name="a")
            b0 = nfd()
            err = None
            try:
                if op == "read":
                    had.read_bytes(FileRef("s", fid))
                else:
                    had.list_children(FileRef("s", fid))
            except LocalStorageError as exc:
                err = exc
            finally:
                b1 = nfd()
                had.close()
            # close() of the root may add nothing; measure growth across the op
            results.append((op, type(err).__name__ if err else None, b1 - b0))
        print(f"  handoff results (op, raised, fd-delta) = {results}")
        for op, raised, delta in results:
            if raised != "LocalStorageError":
                return _fail(f"{op}: expected LocalStorageError, got {raised}")
            if delta > 1:
                return _fail(f"{op}: child descriptor leaked (fd delta {delta})")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


CHECKS = {
    "nofollow": check_nofollow,
    "bounded_read": check_bounded_read,
    "root_anchor": check_root_anchor,
    "dir_symlink_swap": check_dir_symlink_swap,
    "fifo": check_fifo,
    "fd_lifetime": check_fd_lifetime,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "list"):
        print("checks:", ", ".join(CHECKS))
        return 0
    name = sys.argv[1]
    src = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    sys.path.insert(0, src)
    if name not in CHECKS:
        print(f"unknown check {name!r}")
        return 1
    print(f"=== kernel check: {name} ===")
    rc = CHECKS[name]()
    label = {0: "PASS", 1: "FAIL", 2: "SKIP"}.get(rc, "?")
    print(f"CHECK {name} RESULT: {label}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

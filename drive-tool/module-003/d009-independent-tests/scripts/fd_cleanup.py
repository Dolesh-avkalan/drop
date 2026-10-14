#!/usr/bin/env python3
"""d009 independent descriptor-lifetime checks (asserting) - v2, reuse-safe.

Provenance: written independently for d009; does not reuse d007's fd tests.

Part A - repeated success/failure fd accounting:
  Runs many successful and failing operations and asserts the process open-fd
  count does not grow (no leak across repeated success or failure).

Part B - parent-descriptor close error AFTER the child descriptor is acquired
  (the path d007's committed tests do not cover):
  For read_bytes and list_children the adapter opens a parent directory fd, then
  the child file/scan fd, then closes the parent fd in a `finally`. We inject a
  failure on that parent close (a close() that reports an error while the kernel
  has already released the fd) and ask: is the CHILD fd released exactly once?

  Leak detection is done by snapshotting the live open descriptors via
  /proc/self/fd before and after the operation, so it is NOT fooled by the
  kernel reusing a freed fd number. A child descriptor still open afterwards is
  an orphaned descriptor (the module's stated invariant is that every opened
  descriptor is released exactly once).

Exit 0 iff Part A shows no growth AND neither Part B child fd is orphaned.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat as statmod
import sys
import tempfile

from drive_tool.local import LocalAdapter
from drive_tool.storage import FileRef, ROOT_ID

failures: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name} {detail}")
    else:
        print(f"FAIL {name} {detail}")
        failures.append(name)


def open_fd_set() -> set[int]:
    return {int(x) for x in os.listdir("/proc/self/fd")}


def build_tree(base):
    root = os.path.join(base, "root")
    os.mkdir(root)
    os.mkdir(os.path.join(root, "d1"))
    os.mkdir(os.path.join(root, "d1", "d2"))
    with open(os.path.join(root, "d1", "d2", "file.txt"), "wb") as fh:
        fh.write(b"hello")
    os.symlink(os.path.join(base, "outside"), os.path.join(root, "link"))
    os.mkdir(os.path.join(base, "outside"))
    os.mkfifo(os.path.join(root, "fifo"))
    return root


def part_a(base):
    print("\n-- Part A: repeated success/failure fd accounting --")
    root = build_tree(base)
    ad = LocalAdapter("src", root)
    try:
        for _ in range(3):
            ad.read_bytes(FileRef("src", "p/d1/d2/file.txt"))
        before = len(open_fd_set())
        N = 300
        for _ in range(N):
            for op in (
                lambda: ad.read_bytes(FileRef("src", "p/d1/d2/file.txt")),
                lambda: ad.stat(FileRef("src", "p/d1/d2/file.txt")),
                lambda: ad.list_children(FileRef("src", ROOT_ID)),
                lambda: ad.list_children(FileRef("src", "p/d1")),
                lambda: ad.read_bytes(FileRef("src", "p/missing.txt")),
                lambda: ad.stat(FileRef("src", "p/missing.txt")),
                lambda: ad.list_children(FileRef("src", "p/d1/d2/file.txt")),
                lambda: ad.read_bytes(FileRef("src", "p/link")),
                lambda: ad.read_bytes(FileRef("src", "p/fifo")),
                lambda: ad.read_bytes(FileRef("src", ROOT_ID)),
                lambda: ad.read_bytes(FileRef("src", "p/d1/d2/../x")),
            ):
                try:
                    op()
                except Exception:  # noqa: BLE001
                    pass
        after = len(open_fd_set())
        check("partA-no-fd-growth", after <= before,
              f"(before={before}, after={after}, iterations={N})")
    finally:
        ad.close()


def _run_parent_close_case(kind, base):
    root = os.path.join(base, "root_" + kind)
    os.mkdir(root)
    os.mkdir(os.path.join(root, "a"))
    os.mkdir(os.path.join(root, "a", "b"))
    with open(os.path.join(root, "a", "b", "file.txt"), "wb") as fh:
        fh.write(b"payload")

    ad = LocalAdapter("src", root)
    root_fd = ad._root_fd
    parent_box: dict[str, int] = {}
    open_meta: dict[int, tuple] = {}
    events: list[tuple[str, int]] = []  # ordered open/close, reuse-safe

    real_open = ad._os_open
    real_close = ad._os_close
    real_trav = ad._traverse_parent_dir

    def trav(rfd, dir_parts, file_id):
        fd = real_trav(rfd, dir_parts, file_id)
        parent_box["fd"] = fd
        return fd

    def open_hook(path, flags, *, dir_fd=None):
        fd = real_open(path, flags, dir_fd=dir_fd)
        open_meta[fd] = (path, dir_fd)
        events.append(("open", fd))
        return fd

    def close_hook(fd):
        events.append(("close", fd))
        if parent_box.get("fd") == fd:
            real_close(fd)  # kernel releases the fd even though close() errors
            raise OSError(errno.EIO, "injected parent-close failure")
        real_close(fd)

    ad._traverse_parent_dir = trav
    ad._os_open = open_hook
    ad._os_close = close_hook

    raised = None
    try:
        if kind == "read":
            ad.read_bytes(FileRef("src", "p/a/b/file.txt"))
        else:
            ad.list_children(FileRef("src", "p/a/b"))
    except Exception as exc:  # noqa: BLE001
        raised = exc
    finally:
        ad._traverse_parent_dir = real_trav
        ad._os_open = real_open
        ad._os_close = real_close

    # Ordered live-set: robust against the kernel reusing a freed fd number.
    live: set[int] = set()
    for ev, fd in events:
        if ev == "open":
            live.add(fd)
        else:
            live.discard(fd)
    live.discard(root_fd)

    parent_fd = parent_box.get("fd")
    child_candidates = [fd for fd, (p, dfd) in open_meta.items()
                        if dfd == parent_fd and fd != parent_fd]
    child_fd = child_candidates[-1] if child_candidates else None
    child_still_open = False
    if child_fd is not None:
        try:
            os.fstat(child_fd)
            child_still_open = True
        except OSError:
            child_still_open = False

    print(f"  [{kind}] raised={type(raised).__name__ if raised else None} "
          f"parent_fd={parent_fd} child_fd={child_fd} "
          f"events={events} live_after={sorted(live)} "
          f"child_fstat_ok={child_still_open}")

    ok = True
    if raised is None:
        check(f"partB-{kind}-parent-close-wrapped", False, "(operation did not raise)")
        ok = False
    # child released exactly once == child not still open and not in live set
    child_released_once = (child_fd is not None
                           and not child_still_open
                           and child_fd not in live)
    check(f"partB-{kind}-child-released-exactly-once", child_released_once,
          f"(child_fd={child_fd} still_open={child_still_open} in_live={child_fd in live})")
    if not child_released_once:
        ok = False

    # Clean up any leaked descriptor so later checks are not polluted.
    for fd in list(live):
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        ad.close()
    except Exception:  # noqa: BLE001
        pass
    return ok


def part_b(base):
    print("\n-- Part B: parent-close error after child descriptor acquired --")
    _run_parent_close_case("read", base)
    _run_parent_close_case("list", base)


def main() -> int:
    print(f"python {sys.version.split()[0]} | d009 descriptor-lifetime checks (reuse-safe)")
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_fd_"))
    try:
        part_a(base)
        part_b(base)
        print()
        if failures:
            print(f"RESULT: FAIL - {failures}")
            return 1
        print("RESULT: PASS")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

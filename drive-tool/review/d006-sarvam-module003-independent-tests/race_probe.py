#!/usr/bin/env python3
"""Deterministic pre-stat/open symlink-swap race probe for LocalAdapter.

Scenario exercised (as required by the review task):
  A component is swapped from a real directory to a symlink pointing at a
  SEPARATE outside fixture, immediately AFTER the adapter's no-follow lstat
  (`_os_stat_nofollow`) and BEFORE its no-follow open (`_os_open`).

The swap is triggered from a wrapper around `LocalAdapter._os_open`: the first
time `_os_open` is called for the component name "sub", the wrapper performs
the rename+symlink swap and then delegates to the real open. Because the
adapter always lstat()s the component immediately before open()ing it, this
hook fires exactly in the stat->open window, deterministically (no timing
luck needed).

Three entry points are exercised: read_bytes (intermediate traversal),
stat (intermediate traversal), and list_children (final directory).

Part A uses the REAL os.open on THIS environment.
Part B additionally emulates (clearly labelled SIMULATED) a kernel that honours
O_NOFOLLOW|O_DIRECTORY, to show what a conformant open would do.

Run:  python3.11 race_probe.py   /   python3.12 race_probe.py
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drive_tool.local import LocalAdapter, UnsafePathError  # noqa: E402
from drive_tool.storage import FileRef, ROOT_ID  # noqa: E402

SAFE = b"SAFE_INSIDE_BYTES"
SENTINEL = b"OUTSIDE_SENTINEL_BYTES_0123456789"


def build(base: str):
    root = os.path.join(base, "root")
    outside = os.path.join(base, "outside")
    os.mkdir(root)
    os.mkdir(outside)
    sub = os.path.join(root, "sub")
    os.mkdir(sub)
    with open(os.path.join(sub, "target.txt"), "wb") as fh:
        fh.write(SAFE)
    with open(os.path.join(outside, "target.txt"), "wb") as fh:
        fh.write(SENTINEL)
    with open(os.path.join(outside, "secret.txt"), "wb") as fh:
        fh.write(b"OUTSIDE_SECRET_ONLY")
    return root, outside, sub


def swap(sub: str, outside: str) -> None:
    moved = sub + "__moved"
    if os.path.islink(sub):
        os.unlink(sub)
    if os.path.exists(moved):
        shutil.rmtree(moved)
    os.rename(sub, moved)
    os.symlink(outside, sub)


def restore(sub: str, outside: str) -> None:
    moved = sub + "__moved"
    if os.path.islink(sub):
        os.unlink(sub)
    if os.path.exists(moved):
        os.rename(moved, sub)


def conformant_open(real_open, path, flags, dir_fd):
    """SIMULATED conformant kernel: O_NOFOLLOW|O_DIRECTORY rejects a symlink."""
    if (flags & os.O_NOFOLLOW) and (flags & os.O_DIRECTORY) and dir_fd is not None:
        try:
            st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(st.st_mode):
                raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)
    return real_open(path, flags, dir_fd=dir_fd)


def run_case(title, fn, simulated: bool) -> None:
    base = os.path.realpath(tempfile.mkdtemp(prefix="race_probe_"))
    root, outside, sub = build(base)
    adapter = LocalAdapter("src", root)
    real_open = adapter._os_open

    def hook(path, flags, *, dir_fd=None):
        if path == "sub":
            swap(sub, outside)
        if simulated:
            return conformant_open(real_open, path, flags, dir_fd)
        return real_open(path, flags, dir_fd=dir_fd)

    adapter._os_open = hook  # instance attribute shadows the bound method
    label = "SIMULATED conformant open" if simulated else "ACTUAL os.open (this env)"
    print(f"  [{label}] {title}")
    try:
        fn(adapter)
    except Exception as exc:  # noqa: BLE001
        print(f"      -> raised {type(exc).__name__}: {exc}")
    finally:
        adapter._os_open = real_open
        try:
            adapter.close()
        except Exception:
            pass
        restore(sub, outside)
        shutil.rmtree(base, ignore_errors=True)


def case_read_bytes(adapter):
    data = adapter.read_bytes(FileRef("src", "p/sub/target.txt"))
    if data == SENTINEL:
        print(f"      -> ESCAPED: read_bytes returned OUTSIDE sentinel bytes {data!r}")
    elif data == SAFE:
        print(f"      -> contained: read_bytes returned inside bytes {data!r}")
    else:
        print(f"      -> unexpected bytes {data!r}")


def case_stat(adapter):
    meta = adapter.stat(FileRef("src", "p/sub/target.txt"))
    if meta.size_bytes == len(SENTINEL):
        print(f"      -> ESCAPED: stat exposed OUTSIDE metadata (size={meta.size_bytes}, "
              f"name={meta.name!r})")
    elif meta.size_bytes == len(SAFE):
        print(f"      -> contained: stat size={meta.size_bytes} (inside file)")
    else:
        print(f"      -> unexpected size {meta.size_bytes}")


def case_list_children(adapter):
    names = [m.name for m in adapter.list_children(FileRef("src", "p/sub"))]
    if "secret.txt" in names:
        print(f"      -> ESCAPED: list_children('p/sub') exposed OUTSIDE entries {names}")
    else:
        print(f"      -> contained: list_children('p/sub') = {names}")


def main() -> int:
    print(f"python {sys.version.split()[0]} | realpath(TMPDIR) base under /tmp")
    for simulated in (False, True):
        run_case("read_bytes('p/sub/target.txt') traversal", case_read_bytes, simulated)
        run_case("stat('p/sub/target.txt') traversal", case_stat, simulated)
        run_case("list_children('p/sub') final directory", case_list_children, simulated)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

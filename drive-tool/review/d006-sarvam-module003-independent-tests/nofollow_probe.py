#!/usr/bin/env python3
"""Tiny raw os.open probe: does O_NOFOLLOW|O_DIRECTORY follow a symlink here?

Self-contained. Creates its own throwaway fixtures, makes no writes outside
the temp dir it creates, and touches no services. Run:

    python3.11 nofollow_probe.py
    python3.12 nofollow_probe.py

It reports the raw open() outcome only. It does NOT attribute the result to a
"filesystem" or "kernel" by name; it records the observed behaviour plus the
mount type that /proc/mounts reports for the directory used, so the reader can
judge.
"""
from __future__ import annotations

import errno
import os
import stat
import sys
import tempfile


def mount_info(path: str):
    """Best-effort mount type for `path` by longest-prefix match on /proc/mounts."""
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    best = None
    try:
        with open("/proc/mounts", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1].replace("\\040", " ")
                if real == mp or mp == "/" or real.startswith(mp.rstrip("/") + "/"):
                    if best is None or len(mp) > len(best[1]):
                        best = (parts[2], mp)
    except OSError as exc:
        return ("<unreadable /proc/mounts>", str(exc))
    return best or ("<no match>", "")


def probe(base: str) -> None:
    """Run the symlink-to-directory no-follow open probe inside `base`."""
    os.makedirs(base, exist_ok=True)
    work = os.path.realpath(tempfile.mkdtemp(prefix="nofollow_probe_", dir=base))
    real_dir = os.path.join(work, "realdir")
    os.mkdir(real_dir)
    os.mkdir(os.path.join(real_dir, "child"))
    link_dir = os.path.join(work, "linkdir")
    os.symlink(real_dir, link_dir)

    fs, mp = mount_info(work)
    print(f"--- probe dir: {work}")
    print(f"    /proc/mounts type for dir: {fs!r} (mountpoint {mp!r})")

    parent_fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY | os.O_NONBLOCK)
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
        print(f"    flags include O_NOFOLLOW: {bool(flags & os.O_NOFOLLOW)}, "
              f"O_DIRECTORY: {bool(flags & os.O_DIRECTORY)}")
        st = os.lstat(link_dir)
        print(f"    lstat('linkdir').islink = {stat.S_ISLNK(st.st_mode)}")

        # (A) the exact combination under test: O_NOFOLLOW | O_DIRECTORY
        try:
            fd = os.open("linkdir", flags, dir_fd=parent_fd)
        except OSError as exc:
            print(f"    (A) open('linkdir', O_NOFOLLOW|O_DIRECTORY) -> "
                  f"raised {errno.errorcode.get(exc.errno, exc.errno)} ({exc.errno})")
        else:
            print(f"    (A) open('linkdir', O_NOFOLLOW|O_DIRECTORY) -> "
                  f"SUCCEEDED fd={fd} (symlink FOLLOWED)")
            try:
                print(f"        readdir(fd) = {sorted(os.listdir(fd))}")
            except OSError as exc:
                print(f"        readdir(fd) failed: {exc}")
            os.close(fd)

        # (B) O_NOFOLLOW WITHOUT O_DIRECTORY, for contrast
        try:
            fd2 = os.open("linkdir", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        except OSError as exc:
            print(f"    (B) open('linkdir', O_NOFOLLOW only) -> "
                  f"raised {errno.errorcode.get(exc.errno, exc.errno)} ({exc.errno})")
        else:
            print(f"    (B) open('linkdir', O_NOFOLLOW only) -> SUCCEEDED fd={fd2}")
            os.close(fd2)
    finally:
        os.close(parent_fd)
        # tidy up
        import shutil
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    print(f"python {sys.version.split()[0]} | os.name={os.name}")
    for base in ("/tmp", "/scratch/work", "/dev/shm"):
        if os.path.isdir(base):
            try:
                probe(base)
            except OSError as exc:
                print(f"--- probe dir {base!r}: setup failed: {exc}")
        else:
            print(f"--- probe dir {base!r}: not present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

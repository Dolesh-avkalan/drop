#!/usr/bin/env python3
"""d009 independent raw-kernel O_NOFOLLOW / O_DIRECTORY semantics probe.

Provenance: written independently for d009. It does NOT import the adapter and
does NOT reuse the d007 `raw_probe.py`. It calls the real `os.open` on the
running kernel for several flag combinations and reports the true errno. No
mocks, no simulation.

Purpose: independently establish whether, on THIS kernel, O_NOFOLLOW alone
rejects a symlink and whether combining it with O_DIRECTORY changes that
behaviour. This is the crux of the d007 correction.

Exit code: 0 if the adapter's exact component flags (O_NOFOLLOW, no
O_DIRECTORY) atomically reject a symlink AND a real directory opens as S_ISDIR;
1 otherwise. Print-only detail goes to stdout regardless.
"""
from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile

O = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
FLAGS_ADAPTER = O | os.O_NOFOLLOW                      # what the revised adapter uses
FLAGS_NOFOLLOW_DIR = O | os.O_NOFOLLOW | os.O_DIRECTORY  # what the old adapter used
FLAGS_DIR_ONLY = O | os.O_DIRECTORY
FLAGS_PLAIN = O

FLAG_SETS = {
    "NOFOLLOW_only": FLAGS_ADAPTER,
    "NOFOLLOW|DIRECTORY": FLAGS_NOFOLLOW_DIR,
    "DIRECTORY_only": FLAGS_DIR_ONLY,
    "plain": FLAGS_PLAIN,
}


def attempt(path: str) -> str:
    try:
        fd = os.open(path, _CUR)
    except OSError as exc:
        return "raised " + errno.errorcode.get(exc.errno, str(exc.errno))
    try:
        st = os.fstat(fd)
        kind = (
            "dir" if stat.S_ISDIR(st.st_mode)
            else "reg" if stat.S_ISREG(st.st_mode)
            else "fifo" if stat.S_ISFIFO(st.st_mode)
            else "lnk" if stat.S_ISLNK(st.st_mode)
            else "other"
        )
        return f"opened mode={oct(st.st_mode)} ({kind})"
    finally:
        os.close(fd)


_CUR = 0  # set per loop


def main() -> int:
    base = tempfile.mkdtemp(prefix="d009_raw_probe_")
    try:
        d = os.path.join(base, "d")
        os.mkdir(d)
        link = os.path.join(base, "link_to_dir")
        os.symlink(d, link)
        broken = os.path.join(base, "broken_link")
        os.symlink(os.path.join(base, "does_not_exist"), broken)
        fifo = os.path.join(base, "fifo")
        os.mkfifo(fifo)
        reg = os.path.join(base, "f.txt")
        with open(reg, "wb") as fh:
            fh.write(b"x")

        targets = [
            ("symlink_to_dir", link),
            ("broken_symlink", broken),
            ("real_dir", d),
            ("root_slash", "/"),
            ("fifo", fifo),
            ("regular_file", reg),
        ]

        print(f"python {os.sys.version.split()[0]} | kernel via os.open (real, no mocks)")
        print(f"flag values: O_NOFOLLOW={os.O_NOFOLLOW} O_DIRECTORY={os.O_DIRECTORY} O_NONBLOCK={os.O_NONBLOCK}")
        global _CUR
        for name, flags in FLAG_SETS.items():
            _CUR = flags
            print(f"\n[flags={name}] O_NOFOLLOW={bool(flags & os.O_NOFOLLOW)} O_DIRECTORY={bool(flags & os.O_DIRECTORY)}")
            for tname, path in targets:
                print(f"  {tname:16s}: {attempt(path)}")

        # Assertions: the adapter's exact flags must reject symlinks and open real dirs.
        _CUR = FLAGS_ADAPTER
        ok = True
        r = attempt(link)
        if not r.startswith("raised ELOOP"):
            print(f"\nASSERT-FAIL: adapter flags followed symlink_to_dir -> {r}")
            ok = False
        else:
            print("\nASSERT-OK: adapter flags (O_NOFOLLOW, no O_DIRECTORY) reject symlink with ELOOP")
        r = attempt(d)
        if "(dir)" not in r:
            print(f"ASSERT-FAIL: adapter flags did not open real dir -> {r}")
            ok = False
        else:
            print("ASSERT-OK: adapter flags open a real directory as S_ISDIR")

        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

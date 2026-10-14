#!/usr/bin/env python3
"""Asserting variant of the d006 pre-stat/open directory-swap race reproducer.

The original d006 ``race_probe.py`` is print-only and always exits 0 - it is a
report, not a pass/fail gate. This script ASSERTS containment instead: for each
entry point it forces a directory component to be swapped for a symlink to an
OUTSIDE fixture immediately before the adapter's atomic component open, and it
fails (non-zero exit) if any entry point exposes outside bytes, outside
metadata, or an outside directory listing, or if it raises anything other than
``UnsafePathError``.

It is self-contained (it imports only the public adapter API), so it runs
unchanged against the OLD commit (where it FAILS) and the REVISED commit (where
it PASSES). No simulation: the real ``os.open`` on the running kernel is used.

Scenarios covered:
  * read_bytes intermediate traversal   (outside sentinel BYTES must not leak)
  * stat intermediate traversal         (outside METADATA must not leak)
  * list_children final directory       (outside LISTING must not leak)
  * root setup / ancestor traversal     (configuration must be rejected)

Run:
  PYTHONPATH=<checkout> python3.11 race_probe_assert.py
  PYTHONPATH=<checkout> python3.12 race_probe_assert.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

from drive_tool.local import LocalAdapter, UnsafePathError
from drive_tool.storage import FileRef, ROOT_ID

SAFE = b"SAFE_INSIDE_BYTES"
SENTINEL = b"OUTSIDE_SENTINEL_BYTES_0123456789"

failures: list[str] = []


def _build(base: str):
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


def _swap(sub: str, outside: str) -> None:
    moved = sub + "__moved"
    if os.path.islink(sub):
        os.unlink(sub)
    if os.path.exists(moved):
        shutil.rmtree(moved)
    os.rename(sub, moved)
    os.symlink(outside, sub)


def _run_case(name: str, fn, *, component: str = "sub") -> None:
    base = os.path.realpath(tempfile.mkdtemp(prefix="race_probe_assert_"))
    root, outside, sub = _build(base)
    adapter = LocalAdapter("src", root)
    real_open = adapter._os_open
    state = {"done": False}

    def hook(path: str, flags: int, *, dir_fd: int | None = None) -> int:
        if path == component and not state["done"]:
            state["done"] = True
            _swap(sub, outside)
        return real_open(path, flags, dir_fd=dir_fd)

    adapter._os_open = hook  # instance attribute shadows the bound method
    try:
        try:
            result = fn(adapter)
        except UnsafePathError as exc:
            print(f"PASS {name}: contained (UnsafePathError: {exc})")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: unexpected {type(exc).__name__}: {exc}")
            failures.append(name)
            return
        print(f"FAIL {name}: ESCAPED - operation returned {result!r}")
        failures.append(name)
    finally:
        adapter._os_open = real_open
        try:
            adapter.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(base, ignore_errors=True)


def _case_root_ancestor() -> None:
    base = os.path.realpath(tempfile.mkdtemp(prefix="race_probe_anc_"))
    try:
        anc = os.path.join(base, "anc")
        os.mkdir(anc)
        inner = os.path.join(anc, "inner")
        os.mkdir(inner)
        outside = os.path.join(base, "outside")
        os.mkdir(outside)
        with open(os.path.join(outside, "leak.txt"), "wb") as fh:
            fh.write(SENTINEL)

        state = {"done": False}
        real_open = os.open

        def hook(self_, path: str, flags: int, *, dir_fd: int | None = None) -> int:
            if path == "anc" and not state["done"]:
                state["done"] = True
                os.rename(anc, os.path.join(base, "anc__moved"))
                os.symlink(outside, anc)
            return real_open(path, flags, dir_fd=dir_fd)

        LocalAdapter._os_open = hook
        try:
            LocalAdapter("src", inner)
        except UnsafePathError as exc:
            print(f"PASS root-ancestor swap: contained (UnsafePathError: {exc})")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL root-ancestor swap: unexpected {type(exc).__name__}: {exc}")
            failures.append("root-ancestor")
            return
        finally:
            LocalAdapter._os_open = real_open
        print("FAIL root-ancestor swap: ESCAPED - adapter was constructed")
        failures.append("root-ancestor")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    print(f"python {sys.version.split()[0]} | real kernel os.open | asserting reproducer")
    _run_case(
        "read_bytes('p/sub/target.txt') traversal",
        lambda a: a.read_bytes(FileRef("src", "p/sub/target.txt")),
    )
    _run_case(
        "stat('p/sub/target.txt') traversal",
        lambda a: a.stat(FileRef("src", "p/sub/target.txt")),
    )
    _run_case(
        "list_children('p/sub') final directory",
        lambda a: a.list_children(FileRef("src", "p/sub")),
    )
    _case_root_ancestor()
    print()
    if failures:
        print(f"RESULT: FAIL - {len(failures)} containment failure(s): {failures}")
        return 1
    print("RESULT: PASS - all entry points contained the directory swap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""d009 independent directory-swap containment probe (asserting, real kernel).

Provenance: written independently for d009. It imports only the public adapter
API plus the adapter's own `_os_open` seam; it does NOT reuse d007's
`race_probe_assert.py`. The swap is triggered by a hook that wraps the seam and
then calls the REAL `os.open`, so the open that matters executes on the running
kernel - nothing about the open is mocked.

For each entry point a directory component is renamed away and replaced by a
symlink to an OUTSIDE fixture immediately BEFORE that component's open (i.e.
after any pre-stat the old adapter performs). The probe ASSERTS containment:

  PASS  -> the operation raised UnsafePathError (outside content not exposed)
  FAIL  -> the operation returned outside bytes/metadata/listing, or raised a
           different exception, or (root case) the adapter was constructed
           against the outside directory.

Exit code 0 iff every case is contained; 1 otherwise.

Run against any checkout:
  PYTHONPATH=<checkout> python3.11 containment_assert.py
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


def _swap_to_symlink(dirpath: str, outside: str) -> None:
    moved = dirpath + "__moved"
    if os.path.islink(dirpath):
        os.unlink(dirpath)
    if os.path.exists(moved):
        shutil.rmtree(moved)
    os.rename(dirpath, moved)
    os.symlink(outside, dirpath)


def _run_instance_case(name: str, op, *, component: str) -> None:
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_cont_"))
    root, outside, sub = _build(base)
    adapter = LocalAdapter("src", root)
    real_open = adapter._os_open
    state = {"done": False}

    def hook(path, flags, *, dir_fd=None):
        if path == component and not state["done"]:
            state["done"] = True
            _swap_to_symlink(sub, outside)
        return real_open(path, flags, dir_fd=dir_fd)

    adapter._os_open = hook
    try:
        try:
            result = op(adapter)
        except UnsafePathError as exc:
            print(f"PASS {name}: contained (UnsafePathError: {exc})")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: wrong exception {type(exc).__name__}: {exc}")
            failures.append(name)
            return
        print(f"FAIL {name}: ESCAPED -> returned {result!r}")
        failures.append(name)
    finally:
        adapter._os_open = real_open
        try:
            adapter.close()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(base, ignore_errors=True)


def _run_root_case() -> None:
    """Root/ancestor traversal swapped immediately before the ancestor open."""
    name = "root-ancestor-swap"
    base = os.path.realpath(tempfile.mkdtemp(prefix="d009_cont_root_"))
    try:
        anc = os.path.join(base, "anc")
        os.mkdir(anc)
        inner = os.path.join(anc, "inner")
        os.mkdir(inner)
        outside = os.path.join(base, "outside")
        os.mkdir(outside)
        # Mirror the inner dir under outside so a followed symlink anchors OUTSIDE.
        os.mkdir(os.path.join(outside, "inner"))
        with open(os.path.join(outside, "inner", "leak.txt"), "wb") as fh:
            fh.write(SENTINEL)

        state = {"done": False}
        real_open = LocalAdapter._os_open

        def hook(self_, path, flags, *, dir_fd=None):
            if path == "anc" and not state["done"]:
                state["done"] = True
                os.rename(anc, os.path.join(base, "anc__moved"))
                os.symlink(outside, anc)
            return real_open(self_, path, flags, dir_fd=dir_fd)

        LocalAdapter._os_open = hook
        try:
            adapter = LocalAdapter("src", inner)
        except UnsafePathError as exc:
            print(f"PASS {name}: contained (UnsafePathError: {exc})")
            return
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: wrong exception {type(exc).__name__}: {exc}")
            failures.append(name)
            return
        finally:
            LocalAdapter._os_open = real_open
        # Constructed: did it anchor outside?
        try:
            leaked = adapter.read_bytes(FileRef("src", "p/leak.txt"))
        except Exception as exc:  # noqa: BLE001
            leaked = f"<read error {type(exc).__name__}: {exc}>"
        finally:
            try:
                adapter.close()
            except Exception:  # noqa: BLE001
                pass
        if leaked == SENTINEL:
            print(f"FAIL {name}: ESCAPED - anchored OUTSIDE, read sentinel {leaked!r}")
        else:
            print(f"FAIL {name}: adapter constructed against outside (read -> {leaked!r})")
        failures.append(name)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def main() -> int:
    print(f"python {sys.version.split()[0]} | real kernel os.open | d009 containment probe")
    _run_instance_case(
        "read_bytes(p/sub/target.txt) traversal",
        lambda a: a.read_bytes(FileRef("src", "p/sub/target.txt")),
        component="sub",
    )
    _run_instance_case(
        "stat(p/sub/target.txt) traversal",
        lambda a: a.stat(FileRef("src", "p/sub/target.txt")),
        component="sub",
    )
    _run_instance_case(
        "list_children(p/sub) final dir open",
        lambda a: a.list_children(FileRef("src", "p/sub")),
        component="sub",
    )
    _run_root_case()
    print()
    if failures:
        print(f"RESULT: FAIL - {len(failures)} containment failure(s): {failures}")
        return 1
    print("RESULT: PASS - all entry points contained the directory swap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""d012 fresh independent ownership check (primary, fresh provenance).

This is written from scratch for d012; it is NOT the d010/d009 test code.

Design
------
The adapter exposes low-level OS seams (``_os_open``, ``_os_close``,
``_os_fstat``, ``_os_stat_nofollow``, ``_os_scandir``, ``_os_read``).  We
subclass ``LocalAdapter`` and override those seams so that every descriptor
returned by ``_os_open`` is replaced by a *virtual* descriptor id (a unique,
never-reused integer) mapped to the real OS fd.

Why virtual ids instead of tracking real fd integers: the kernel reuses fd
numbers, so an integer is NOT a lifetime identity.  A virtual id is allocated
per *acquisition* and is never reused, so:

  * "closed exactly once" is exact -- a second close of a virtual id is a
    double-close, detectable with no reuse ambiguity;
  * "no retry of an ambiguous close" is exact -- we can count close attempts
    per acquisition.

Close-error injection models real Linux semantics:

  * ``after_real``  -- perform the real ``close`` (the fd IS released), then
    report an error (the common Linux case).
  * ``ambiguous``   -- report an error WITHOUT releasing the fd (the fd may or
    may not be released; the module must not retry and must not claim release).

Usage:  python3 d012_ownership_check.py <tree-with-drive_tool> [--json out.json]
Exit 0 iff every scenario passes.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import tempfile

TREE = None
JSON_OUT = None


# --------------------------------------------------------------------------
# instrumentation
# --------------------------------------------------------------------------

class Ledger:
    def __init__(self) -> None:
        self.next_vfd = 1_000_000
        self.vfd_to_real: dict[int, int] = {}
        self.label: dict[int, str] = {}
        self.open_seq: list[int] = []
        self.close_attempts: dict[int, int] = {}
        self.released: set[int] = set()          # vfds actually released via real close
        self.close_order: list[int] = []
        self.double_close: list[int] = []
        self.close_without_open: list[int] = []
        # injection
        self.fail_close_paths: dict[str, str] = {}   # path label -> mode
        self.fail_read = False
        self.fail_scandir = False
        self.ambiguous_left_open: list[int] = []     # real fds we deliberately left open

    def alloc(self, real_fd: int, path: str) -> int:
        v = self.next_vfd
        self.next_vfd += 1
        self.vfd_to_real[v] = real_fd
        self.label[v] = path
        self.open_seq.append(v)
        return v

    def translate(self, vfd: int) -> int:
        if vfd in self.vfd_to_real:
            return self.vfd_to_real[vfd]
        return vfd  # shouldn't happen; surface loudly via downstream EBADF


def make_adapter_class(local_mod):
    LocalAdapter = local_mod.LocalAdapter

    class InstrumentedAdapter(LocalAdapter):  # type: ignore[misc]
        def __init__(self, *args, ledger=None, **kwargs):
            self._led = ledger if ledger is not None else Ledger()
            super().__init__(*args, **kwargs)

        # -- seams ---------------------------------------------------------
        def _os_open(self, path, flags, *, dir_fd=None):
            led = self._led
            rfd = None if dir_fd is None else led.translate(dir_fd)
            real = os.open(path, flags, dir_fd=rfd)
            return led.alloc(real, path)

        def _os_close(self, fd):
            led = self._led
            if fd not in led.vfd_to_real:
                # closing something never opened, or already closed -> double close
                led.double_close.append(fd)
                raise OSError(errno.EBADF, "close of unowned/already-closed descriptor")
            led.close_attempts[fd] = led.close_attempts.get(fd, 0) + 1
            led.close_order.append(fd)
            mode = led.fail_close_paths.get(led.label.get(fd, ""), None)
            if mode == "ambiguous":
                # report uncertainty, do NOT release the real fd
                led.ambiguous_left_open.append(led.vfd_to_real[fd])
                raise OSError(errno.EIO, "injected ambiguous close failure")
            real = led.vfd_to_real.pop(fd)
            os.close(real)
            led.released.add(fd)
            if mode == "after_real":
                raise OSError(errno.EIO, "injected close failure after real close")

        def _os_fstat(self, fd):
            return os.fstat(self._led.translate(fd))

        def _os_stat_nofollow(self, path, *, dir_fd):
            return os.stat(path, dir_fd=self._led.translate(dir_fd), follow_symlinks=False)

        def _os_scandir(self, fd):
            if self._led.fail_scandir:
                raise OSError(errno.EIO, "injected scandir failure")
            return os.scandir(self._led.translate(fd))

        def _os_read(self, fd, length):
            if self._led.fail_read:
                raise OSError(errno.EIO, "injected read failure")
            return os.read(self._led.translate(fd), length)

    return InstrumentedAdapter


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def build_fixture(tmp):
    root = os.path.join(tmp, "root")
    os.makedirs(os.path.join(root, "a", "b", "c"))
    with open(os.path.join(root, "a", "file.txt"), "wb") as fh:
        fh.write(b"hello")
    with open(os.path.join(root, "a", "b", "file.txt"), "wb") as fh:
        fh.write(b"deep")
    return root


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------

class Failure(Exception):
    pass


def parts_of(file_id):
    assert file_id.startswith("p/")
    return tuple(file_id[2:].split("/"))


def run_scenario(InstrumentedAdapter, FileRef, LocalStorageError, RootError, *,
                 op, target, fail_paths=None, primary=None, ambiguous_path=None,
                 child_expected=True, label=""):
    """Return dict with observed facts; raise Failure on assertion violation."""
    tmp = tempfile.mkdtemp(prefix="d012own_")
    try:
        root = build_fixture(tmp)
        led = Ledger()
        fail_paths = dict(fail_paths or {})
        if ambiguous_path:
            fail_paths[ambiguous_path] = "ambiguous"
        led.fail_close_paths = fail_paths
        led.fail_read = (primary == "read")
        led.fail_scandir = (primary == "scandir")

        adapter = InstrumentedAdapter("src", root, ledger=led)
        root_vfd = adapter._root_fd
        baseline = len(led.open_seq)

        parts = parts_of(target)
        parent_label = parts[-2] if len(parts) >= 2 else None
        child_label = parts[-1]

        ref = FileRef("src", target)
        raised = None
        try:
            if op == "read":
                adapter.read_bytes(ref)
            elif op == "list":
                adapter.list_children(ref)
            else:
                raise AssertionError(op)
        except BaseException as exc:  # noqa: BLE001
            raised = exc

        op_acquired = led.open_seq[baseline:]

        # map labels -> vfd for op acquisitions
        by_label = {}
        for v in op_acquired:
            by_label.setdefault(led.label[v], []).append(v)
        child_vfd = by_label.get(child_label, [None])[-1]
        parent_vfd = by_label.get(parent_label, [None])[-1] if parent_label else None

        obs = {
            "scenario": label,
            "op": op,
            "target": target,
            "fail_paths": fail_paths,
            "primary": primary,
            "raised_type": type(raised).__name__ if raised else None,
            "raised_cause_type": (type(raised.__cause__).__name__
                                  if raised is not None and raised.__cause__ is not None
                                  else None),
            "raised_cause_errno": (getattr(raised.__cause__, "errno", None)
                                   if raised is not None and raised.__cause__ is not None
                                   else None),
            "op_acquired": len(op_acquired),
            "acquired_labels": [led.label[v] for v in op_acquired],
            "close_attempts": {led.label.get(v, str(v)): led.close_attempts.get(v, 0)
                               for v in op_acquired},
            "double_close": [led.label.get(v, str(v)) for v in led.double_close],
            "close_without_open": list(led.close_without_open),
            "child_label": child_label,
            "child_close_attempts": (led.close_attempts.get(child_vfd, 0)
                                     if child_vfd is not None else None),
            "parent_label": parent_label,
            "parent_close_attempts": (led.close_attempts.get(parent_vfd, 0)
                                      if parent_vfd is not None else None),
            "ambiguous_left_open_real_fds": list(led.ambiguous_left_open),
            "root_still_owned": root_vfd in led.vfd_to_real,
            "root_still_usable": None,
            "primary_preserved": None,
        }

        ambiguous_labels = set(fail_paths) if ambiguous_path else set()

        # --- assertions ---------------------------------------------------
        fails = []

        # 1. every descriptor acquired during the op is released exactly once
        #    (or, for the deliberately ambiguous injection, attempted exactly
        #    once without a claimed release)
        for v in op_acquired:
            n = led.close_attempts.get(v, 0)
            if n != 1:
                fails.append(
                    f"{led.label[v]!r} acquired but close attempted {n} times (want 1)")
            elif v not in led.released and led.label[v] not in ambiguous_labels:
                fails.append(
                    f"{led.label[v]!r} close attempted but descriptor not released")

        # 2. no double close / no close without acquisition
        if led.double_close:
            fails.append(f"double close on {[led.label.get(v, v) for v in led.double_close]}")
        if led.close_without_open:
            fails.append("close without open")

        # 3. child released exactly once (when it is expected to be acquired)
        if child_expected:
            if child_vfd is None:
                fails.append("child descriptor was never acquired")
            elif led.close_attempts.get(child_vfd, 0) != 1:
                fails.append(
                    f"CHILD {child_label!r} close attempts="
                    f"{led.close_attempts.get(child_vfd, 0)} (want exactly 1) -> leak/double")
        else:
            if child_vfd is not None:
                fails.append("child was acquired although the op should have failed earlier")
            obs["note"] = "child never acquired (earlier traversal failed first) - correct"

        # 4. parent (if present) released exactly once, never retried
        if parent_vfd is not None and led.close_attempts.get(parent_vfd, 0) != 1:
            fails.append(
                f"PARENT {parent_label!r} close attempts="
                f"{led.close_attempts.get(parent_vfd, 0)} (want exactly 1)")

        # 5. root remains owned and usable (disable injection first: the
        #    injected read/scandir faults must not poison this probe)
        if root_vfd not in led.vfd_to_real:
            fails.append("root descriptor was closed by the operation")
        led.fail_read = False
        led.fail_scandir = False
        led.fail_close_paths = {}
        try:
            adapter.stat(FileRef("src", "root"))
            adapter.list_children(FileRef("src", "root"))
            obs["root_still_usable"] = True
        except BaseException as exc:  # noqa: BLE001
            obs["root_still_usable"] = f"{type(exc).__name__}: {exc}"
            fails.append(f"root not usable after op: {exc!r}")

        # 6. error semantics
        if primary is not None:
            # a primary failure must be preserved (LocalStorageError with the
            # injected OS cause), never masked by close errors
            if raised is None:
                fails.append("expected a primary failure, got none")
            else:
                if not isinstance(raised, LocalStorageError):
                    fails.append(f"primary error type {type(raised).__name__} "
                                 f"not LocalStorageError")
                cause = raised.__cause__
                if not isinstance(cause, OSError):
                    fails.append("primary error lost its OSError cause")
                obs["primary_preserved"] = isinstance(raised, LocalStorageError) and isinstance(cause, OSError)
        else:
            # success path with injected close failures -> first failure must be
            # raised as LocalStorageError preserving the OSError cause
            if fail_paths:
                if raised is None:
                    fails.append("injected close failure was swallowed")
                elif not isinstance(raised, LocalStorageError):
                    fails.append(f"close failure raised {type(raised).__name__}, "
                                 f"not LocalStorageError")
                elif not isinstance(raised.__cause__, OSError):
                    fails.append("close failure lost its OSError cause")

        # 7. ambiguous close: never retried, never claimed released
        if ambiguous_path:
            av = by_label.get(ambiguous_path, [None])[-1]
            if av is None:
                fails.append(f"ambiguous target {ambiguous_path!r} never acquired")
            else:
                if led.close_attempts.get(av, 0) != 1:
                    fails.append(
                        f"ambiguous close RETRIED ({led.close_attempts.get(av,0)} attempts)")

        obs["failures"] = fails
        obs["ok"] = not fails
        return obs
    finally:
        # tidy up any real fd deliberately left open by an ambiguous injection
        for real in list(locals().get("led", Ledger()).ambiguous_left_open):
            try:
                os.close(real)
            except OSError:
                pass
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    global TREE, JSON_OUT
    args = [a for a in sys.argv[1:]]
    JSON_OUT = None
    if "--json" in args:
        i = args.index("--json")
        JSON_OUT = args[i + 1]
        del args[i:i + 2]
    TREE = args[0] if args else "."
    sys.path.insert(0, TREE)

    import drive_tool.local as local_mod
    from drive_tool.local import LocalAdapter, LocalStorageError, UnsupportedPlatformError
    from drive_tool.storage import FileRef

    InstrumentedAdapter = make_adapter_class(local_mod)

    # does the runtime platform support the adapter? if not, operational
    # ownership checks are legitimately skipped (fail-closed kernel).
    platform_ok = True
    platform_note = ""
    try:
        probe = InstrumentedAdapter("probe", tempfile.mkdtemp(prefix="d012probe_"))
        probe.close()
    except UnsupportedPlatformError as exc:
        platform_ok = False
        platform_note = f"UnsupportedPlatformError: {exc}"

    results = []
    print(f"=== d012 fresh ownership check ===")
    print(f"tree: {os.path.abspath(TREE)}")
    print(f"platform supported: {platform_ok} {platform_note}")
    print()

    if not platform_ok:
        print("SKIP: adapter unsupported on this kernel (legitimate fail-closed).")
        if JSON_OUT:
            with open(JSON_OUT, "w") as fh:
                json.dump({"tree": TREE, "platform_ok": False, "results": []}, fh, indent=2)
        return 0

    scenarios = [
        dict(label="read shallow: parent-handoff close fails after child acquired",
             op="read", target="p/a/file.txt", fail_paths={"a": "after_real"}),
        dict(label="read deep: parent-handoff close fails after child acquired",
             op="read", target="p/a/b/file.txt", fail_paths={"b": "after_real"}),
        dict(label="list shallow: parent-handoff close fails after scan acquired",
             op="list", target="p/a/b", fail_paths={"a": "after_real"}),
        dict(label="list deep: parent-handoff close fails after scan acquired",
             op="list", target="p/a/b/c", fail_paths={"b": "after_real"}),
        dict(label="read deep: MULTIPLE close failures (parent + child)",
             op="read", target="p/a/b/file.txt",
             fail_paths={"b": "after_real", "file.txt": "after_real"}),
        dict(label="list deep: MULTIPLE close failures (parent + scan)",
             op="list", target="p/a/b/c",
             fail_paths={"b": "after_real", "c": "after_real"}),
        dict(label="read deep: earlier traversal close failure (intermediate 'a')",
             op="read", target="p/a/b/file.txt", fail_paths={"a": "after_real"},
             child_expected=False),
        dict(label="read deep: PRIMARY read failure + parent/child close errors",
             op="read", target="p/a/b/file.txt", primary="read",
             fail_paths={"b": "after_real", "file.txt": "after_real"}),
        dict(label="list deep: PRIMARY scandir failure + parent/scan close errors",
             op="list", target="p/a/b/c", primary="scandir",
             fail_paths={"b": "after_real", "c": "after_real"}),
        dict(label="read shallow: AMBIGUOUS close of child (not released, not retried)",
             op="read", target="p/a/file.txt", ambiguous_path="file.txt"),
        dict(label="read deep: AMBIGUOUS close of parent handoff",
             op="read", target="p/a/b/file.txt", ambiguous_path="b"),
    ]

    npass = nfail = 0
    for sc in scenarios:
        try:
            obs = run_scenario(InstrumentedAdapter, FileRef, LocalStorageError,
                               UnsupportedPlatformError, **sc)
        except Exception as exc:  # noqa: BLE001
            obs = {"scenario": sc.get("label"), "ok": False,
                   "failures": [f"scenario crashed: {type(exc).__name__}: {exc}"]}
        results.append(obs)
        status = "PASS" if obs.get("ok") else "FAIL"
        if obs.get("ok"):
            npass += 1
        else:
            nfail += 1
        print(f"[{status}] {obs['scenario']}")
        print(f"        acquired={obs.get('acquired_labels')} "
              f"close_attempts={obs.get('close_attempts')} "
              f"child={obs.get('child_label')}@{obs.get('child_close_attempts')} "
              f"parent={obs.get('parent_label')}@{obs.get('parent_close_attempts')}")
        if obs.get("ambiguous_left_open_real_fds"):
            print(f"        ambiguous: real fds deliberately left open by injection = "
                  f"{obs['ambiguous_left_open_real_fds']} (module did NOT retry; "
                  f"cannot verify release) ")
        for f in obs.get("failures", []):
            print(f"        !! {f}")
        print()

    print(f"RESULT: {npass} passed, {nfail} failed, {len(scenarios)} total")

    if JSON_OUT:
        with open(JSON_OUT, "w") as fh:
            json.dump({"tree": os.path.abspath(TREE), "platform_ok": platform_ok,
                       "passed": npass, "failed": nfail, "results": results},
                      fh, indent=2)

    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

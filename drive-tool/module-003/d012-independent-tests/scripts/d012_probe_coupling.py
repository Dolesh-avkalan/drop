#!/usr/bin/env python3
"""d012 fresh check: probe/runtime flag coupling + platform-denial gating.

Part A (fresh): the runtime no-follow probe must derive its flags from the
production helper ``_dir_open_flags`` -- weakening that helper (drop
O_NOFOLLOW) must make the probe report "following" and the constructor fail
closed with UnsupportedPlatformError.  The probe result must not be cached.

Part B: when STATIC POSIX facilities exist but the RUNTIME probe returns False
(simulated unsupported kernel), the probe/platform-denial tests must still RUN
(not be skipped by the result they test), while OPERATIONAL tests must skip
with a precise reason.  A correctly rejected kernel is fail-closed, not a
defect.

Usage: python3 d012_probe_coupling.py <tree> [--json out.json]
Exit 0 iff all assertions hold.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from unittest import mock

TREE = None
JSON_OUT = None
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
    return cond


def part_a(local_mod):
    from drive_tool.local import (
        _dir_open_flags, _file_open_flags, _no_follow_semantics_available,
        LocalAdapter, UnsupportedPlatformError,
    )
    print("--- Part A: probe follows production flags ---")
    d = _dir_open_flags()
    f = _file_open_flags()
    check(bool(d & os.O_NOFOLLOW), "dir flags missing O_NOFOLLOW")
    check(bool(d & os.O_NONBLOCK), "dir flags missing O_NONBLOCK")
    check(not (d & getattr(os, "O_DIRECTORY", 0)), "dir flags must not use O_DIRECTORY")
    check(d == f, "file and dir flags must be identical (shared safety)")
    print(f"  dir==file flags: {d == f}; has O_NOFOLLOW={bool(d & os.O_NOFOLLOW)}; "
          f"has O_DIRECTORY={bool(d & getattr(os,'O_DIRECTORY',0))}")

    baseline = _no_follow_semantics_available()
    print(f"  baseline probe (real helper) = {baseline}")

    real = _dir_open_flags
    weakened = lambda: real() & ~os.O_NOFOLLOW  # noqa: E731
    with mock.patch.object(local_mod, "_dir_open_flags", side_effect=weakened):
        probe = _no_follow_semantics_available()
        check(probe is False,
              f"weakened production flags (O_NOFOLLOW dropped) not detected; probe={probe}")
        try:
            LocalAdapter("src", "/tmp")
            check(False, "constructor did not fail closed under weakened flags")
        except UnsupportedPlatformError:
            print("  weakened flags -> probe False and constructor fail-closed: OK")
        except Exception as exc:  # noqa: BLE001
            check(False, f"constructor raised {type(exc).__name__} not UnsupportedPlatformError")

    # STRONG coupling: the probe must actually perform its os.open with the
    # flags returned by the production helper.  We mark the helper's return
    # value with a behaviour-neutral bit (O_NOCTTY) and spy on os.open: the
    # probe's opens must carry the marker.  A probe that reconstructs its own
    # flags (the pre-d010 defect) would ignore the marker and fail here even
    # when it happens to return False for an unrelated reason.
    marker = getattr(os, "O_NOCTTY", 0o400)
    calls = []
    real_open = os.open

    def spy(path, flags, *a, **k):
        calls.append(flags)
        return real_open(path, flags, *a, **k)

    with mock.patch.object(os, "open", side_effect=spy), \
         mock.patch.object(local_mod, "_dir_open_flags", side_effect=lambda: real() | marker):
        _no_follow_semantics_available()
    # the probe's own opens are the ones carrying O_NOFOLLOW; tempfile/shutil
    # internals open with unrelated flags and are excluded.
    probe_opens = [c for c in calls if c & os.O_NOFOLLOW]
    coupled = bool(probe_opens) and all((c & marker) for c in probe_opens)
    check(coupled,
          f"probe did NOT open with the production helper's flags "
          f"(probe opens={[hex(c) for c in probe_opens]})")
    print(f"  probe os.open used the production helper's flags: {coupled} "
          f"(probe opens={[hex(c) for c in probe_opens]})")

    # not cached: after restoring, the probe must reflect the real kernel again
    after = _no_follow_semantics_available()
    check(after == baseline, f"probe result cached: baseline={baseline} after={after}")
    print(f"  after restore probe = {after} (not cached): {after == baseline}")

    # explicit distinction test: adding O_DIRECTORY while keeping O_NOFOLLOW.
    # On gVisor O_NOFOLLOW is reportedly ignored when combined with O_DIRECTORY;
    # we REPORT the observed result rather than asserting a fixed value.
    with mock.patch.object(local_mod, "_dir_open_flags",
                           side_effect=lambda: real() | getattr(os, "O_DIRECTORY", 0)):
        with_dir_probe = _no_follow_semantics_available()
    print(f"  [observed] probe with O_DIRECTORY added = {with_dir_probe} "
          f"(reported, not asserted; documents kernel O_DIRECTORY interaction)")
    return baseline


def run_suite_inprocess(tree, force_probe_false):
    """Run the committed suite in-process, optionally forcing the runtime probe
    False, and return (ran, skipped, failures, errors)."""
    sys.path.insert(0, tree)
    tests_dir = os.path.join(tree, "tests")
    sys.path.insert(0, tests_dir)
    import importlib
    import test_local
    import test_storage
    importlib.reload(test_local)
    importlib.reload(test_storage)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromModule(test_local))
    suite.addTests(loader.loadTestsFromModule(test_storage))

    patchers = []
    if force_probe_false:
        import drive_tool.local as _lm
        patchers.append(mock.patch.object(_lm, "_no_follow_semantics_available",
                                          return_value=False))
        patchers.append(mock.patch.object(test_local, "_no_follow_semantics_available",
                                          return_value=False))
        for p in patchers:
            p.start()
    buf = io.StringIO()
    res = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
    for p in patchers:
        p.stop()
    ran = res.testsRun
    skipped = len(res.skipped)
    failed_ids = [t.id() for t, _ in res.failures] + [t.id() for t, _ in res.errors]
    return ran, skipped, len(res.failures), len(res.errors), failed_ids


def part_b(tree):
    print("--- Part B: platform-denial gating when static present, runtime probe False ---")
    sys.path.insert(0, os.path.join(tree, "tests"))
    import importlib
    import test_local
    importlib.reload(test_local)

    if not hasattr(test_local, "_static_posix_prerequisites_met"):
        print("  Part B N/A: this test module has no static/runtime gate split "
              "(pre-d010 self-fulfilling gate) -- expected on the base revision")
        return {"part_b": "n/a (no static/runtime split in test module)"}

    static_ok = test_local._static_posix_prerequisites_met()
    check(static_ok, "static POSIX prerequisites not met on this box (cannot demo denial gating)")
    print(f"  static POSIX prerequisites met: {static_ok}")

    # The raw-kernel cross-check deliberately compares the probe against the
    # REAL kernel.  Simulating an unsupported kernel on a kernel that actually
    # enforces O_NOFOLLOW makes that one test detect the (physically false)
    # disagreement -- expected, and it is the ONLY permitted failure here.
    CROSSCHECK = "test_local.TestPlatformNoFollowSemantics.test_runtime_probe_matches_raw_kernel_nofollow"

    loader = unittest.TestLoader()
    import drive_tool.local as _lm
    with mock.patch.object(_lm, "_no_follow_semantics_available", return_value=False), \
         mock.patch.object(test_local, "_no_follow_semantics_available", return_value=False):
        # denial/probe classes must RUN (not skip) even with probe False
        for name in ("TestPlatformCapabilityGate", "TestPlatformNoFollowSemantics"):
            cls = getattr(test_local, name)
            res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
                loader.loadTestsFromTestCase(cls))
            failed_ids = [t.id() for t, _ in res.failures] + [t.id() for t, _ in res.errors]
            print(f"  {name}: ran={res.testsRun} skipped={len(res.skipped)} "
                  f"failures={len(res.failures)} errors={len(res.errors)} "
                  f"failed_ids={failed_ids}")
            check(res.testsRun > 0, f"{name} did not run")
            check(len(res.skipped) == 0,
                  f"{name} was SKIPPED by the probe result it tests (self-fulfilling gate)")
            check(all(fid == CROSSCHECK for fid in failed_ids),
                  f"{name}: unexpected failures {failed_ids} (only the raw-kernel "
                  f"cross-check may fail under a simulated false probe)")

        # an operational class must skip with a precise reason
        op_cls = test_local.TestConfigurationAndRootValidation
        res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(
            loader.loadTestsFromTestCase(op_cls))
        print(f"  operational {op_cls.__name__}: ran={res.testsRun} "
              f"skipped={len(res.skipped)} (expected: all skipped, precise reason)")
        check(res.testsRun > 0 and len(res.skipped) == res.testsRun,
              "operational tests did not skip when the kernel is unsupported")
        if res.skipped:
            reason = res.skipped[0][1]
            check("unsupported" in reason.lower() or "O_NOFOLLOW" in reason,
                  "operational skip reason is not precise")
            print(f"    skip reason: {reason}")

    # full-suite comparison
    ran_n, skip_n, f_n, e_n, _ = run_suite_inprocess(tree, force_probe_false=False)
    print(f"  full suite (real kernel): ran={ran_n} skipped={skip_n} "
          f"failures={f_n} errors={e_n}")
    ran_u, skip_u, f_u, e_u, fids_u = run_suite_inprocess(tree, force_probe_false=True)
    print(f"  full suite (probe forced False): ran={ran_u} skipped={skip_u} "
          f"failures={f_u} errors={e_u}")
    print(f"    failed_ids under forced False: {fids_u}")
    check(all(fid == CROSSCHECK for fid in fids_u),
          f"forcing probe False produced unexpected failures: {fids_u}")
    check(skip_u > 0, "forcing probe False did not skip any operational tests")
    check(skip_u < ran_u, "forcing probe False skipped everything (denial tests not run)")
    return {"full_real": (ran_n, skip_n, f_n, e_n),
            "full_probe_false": (ran_u, skip_u, f_u, e_u),
            "failed_ids_probe_false": fids_u}


def main():
    global TREE, JSON_OUT
    args = list(sys.argv[1:])
    if "--json" in args:
        i = args.index("--json")
        JSON_OUT = args[i + 1]
        del args[i:i + 2]
    TREE = args[0] if args else "."
    sys.path.insert(0, TREE)

    import drive_tool.local as local_mod

    print("=== d012 probe coupling / platform-denial check ===")
    print(f"tree: {os.path.abspath(TREE)}\n")
    part_a(local_mod)
    print()
    try:
        extra = part_b(TREE)
    except Exception as exc:  # noqa: BLE001
        print(f"  Part B raised: {type(exc).__name__}: {exc}")
        extra = {"part_b": f"error: {type(exc).__name__}: {exc}"}
        FAILS.append(f"Part B error: {type(exc).__name__}: {exc}")
    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)} assertion(s))")
        for m in FAILS:
            print(f"  !! {m}")
        rc = 1
    else:
        print("RESULT: PASS (all assertions held)")
        rc = 0
    if JSON_OUT:
        with open(JSON_OUT, "w") as fh:
            json.dump({"tree": os.path.abspath(TREE), "failures": FAILS, **extra},
                      fh, indent=2)
    return rc


if __name__ == "__main__":
    sys.exit(main())

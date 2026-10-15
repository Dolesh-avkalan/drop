"""d037 independent verification probes for the corrected MODULE-005A candidate.

Re-runs the 40 d034 contract checks and converts the six former d034 findings
into positive assertions (F-B skipped=>incomplete, F-A validate at every depth,
F-C post-yield StorageError charged). Uses its OWN seam (independent of the
candidate's tests). Prints PASS/FAIL lines and a tally.
"""
from __future__ import annotations

import errno
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAND = HERE / "cand"
sys.path.insert(0, str(CAND))
sys.path.insert(0, str(CAND / "tests"))

from drive_tool.local import LocalAdapter, LocalStorageError  # noqa: E402
from drive_tool.search import find  # noqa: E402
from drive_tool.storage import (  # noqa: E402
    ROOT_ID,
    FileMetadata,
    FileRef,
    ScanBatch,
    ScanFailure,
    ScanUnsupportedError,
    StorageError,
    NotFoundError,
)

RESULTS = []


def rec(status, name, detail=""):
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} :: {detail}")


def check(name, cond, detail=""):
    rec("PASS" if cond else "FAIL", name, detail)


# ---------------------------------------------------------------------------
# Independent deterministic seam
# ---------------------------------------------------------------------------
class _Probe:
    def __init__(self, order=None):
        self.order = order
        self.next_attempts = 0
        self.yielded = 0
        self.stat_calls = 0
        self.stat_error = {}
        self.build_error = {}
        self.next_error = None
        self.next_error_after = 0
        self.iterate_error_after = None
        self.close_error = False


class _Entry:
    def __init__(self, inner, probe):
        self._inner = inner
        self._probe = probe

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def stat(self, *, follow_symlinks=True):
        self._probe.stat_calls += 1
        exc = self._probe.stat_error.get(self._inner.name)
        if exc is not None:
            raise exc
        return self._inner.stat(follow_symlinks=follow_symlinks)


class _Scandir:
    def __init__(self, inner, probe):
        self._inner = inner
        self._probe = probe
        self._it = None

    def __enter__(self):
        self._inner.__enter__()
        entries = list(self._inner)
        if self._probe.order is not None:
            rank = {n: i for i, n in enumerate(self._probe.order)}
            entries.sort(key=lambda e: rank.get(e.name, len(rank)))
        self._it = iter(entries)
        return self

    def __iter__(self):
        return self

    def __next__(self):
        self._probe.next_attempts += 1
        if self._probe.next_error is not None and self._probe.yielded >= self._probe.next_error_after:
            raise self._probe.next_error
        after = self._probe.iterate_error_after
        if after is not None and self._probe.yielded >= after:
            raise OSError(errno.EIO, "iteration boom")
        entry = next(self._it)
        self._probe.yielded += 1
        return _Entry(entry, self._probe)

    def __exit__(self, *a):
        r = self._inner.__exit__(*a)
        if self._probe.close_error:
            raise OSError(errno.EIO, "scandir close boom")
        return r


class SeamAdapter(LocalAdapter):
    def __init__(self, source_id, root, *, order=None, **kw):
        self.probe = _Probe(order=order)
        super().__init__(source_id, root, **kw)

    def _os_scandir(self, fd):
        return _Scandir(super()._os_scandir(fd), self.probe)

    def _build_metadata(self, parts, *, kind, size_bytes):
        name = parts[-1] if parts else ""
        exc = self.probe.build_error.get(name)
        if exc is not None:
            raise exc
        return super()._build_metadata(parts, kind=kind, size_bytes=size_bytes)


def files(root, names):
    for n in names:
        (root / n).write_text("x")


def la(root, **kw):
    return SeamAdapter("src", str(root), **kw)


def meta(file_id, name, kind="file"):
    return FileMetadata(FileRef("fake", file_id), name, ROOT_ID, kind,
                        0 if kind == "file" else None)


class Scripted:
    source_id = "fake"

    def __init__(self, script):
        self._script = script
        self.calls = []

    def scan_children(self, parent, *, max_entries):
        self.calls.append((parent.file_id, max_entries))
        r = self._script.get(parent.file_id, ScanBatch((), 0, True))
        if isinstance(r, BaseException):
            raise r
        return r

    def stat(self, ref):
        raise NotImplementedError

    def read_bytes(self, ref):
        raise NotImplementedError


def sfind(script, needle="x", **kw):
    a = Scripted(script)
    return find(a, FileRef("fake", ROOT_ID), needle, **kw), a


# ---------------------------------------------------------------------------
# 40 d034 contract checks (unchanged expectations)
# ---------------------------------------------------------------------------
def p1_p2():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, [f"f{i:02d}.txt" for i in range(10)])
        a = la(root, order=[f"f{i:02d}.txt" for i in range(10)])
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=4)
        check("P1.strict_B_inspected", b.inspected == 4, f"{b.inspected}")
        check("P1.no_B_plus_1_next", a.probe.next_attempts == 4, f"next={a.probe.next_attempts}")
        check("P1.at_most_B_stat", a.probe.stat_calls <= 4, f"stat={a.probe.stat_calls}")
        check("P1.complete_false_at_cap", b.complete is False, f"{b.complete}")
        check("P1.items_le_inspected", len(b.items) <= b.inspected, "")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, [f"e{i}.txt" for i in range(5)])
        a = la(root)
        ex = a.scan_children(FileRef("src", ROOT_ID), max_entries=5)
        check("P2.exact_budget_incomplete", ex.inspected == 5 and ex.complete is False, f"{ex.inspected},{ex.complete}")
        ov = a.scan_children(FileRef("src", ROOT_ID), max_entries=6)
        check("P2.room_to_spare_complete", ov.inspected == 5 and ov.complete is True, f"{ov.inspected},{ov.complete}")
        a.close()


def p3():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); names = [f"z{i:02d}.txt" for i in range(20)]
        files(root, names); (root / "match_here.txt").write_text("x")
        a = la(root, order=["match_here.txt"] + names)
        r = find(a, FileRef("src", ROOT_ID), "match", max_entries=5)
        check("P3.prefix_match_retained", [m.name for m in r.items] == ["match_here.txt"], "")
        check("P3.prefix_truncated_max_entries", r.truncated and r.reason == "max_entries", f"{r.reason}")
        check("P3.inspected_is_B", r.inspected == 5, f"{r.inspected}")
        a.close()


def p4_p5():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "keep.txt").write_text("x")
        (root / ".drive-tool-tmp-abc").write_text("x")
        try:
            os.symlink(root / "keep.txt", root / "link")
        except OSError:
            pass
        fifo = False
        try:
            os.mkfifo(root / "pipe"); fifo = True
        except OSError:
            pass
        a = la(root)
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=20)
        exp = 2 + (1 if os.path.lexists(root / "link") else 0) + (1 if fifo else 0)
        check("P4.omitted_entries_charged", b.inspected == exp, f"{b.inspected} vs {exp}")
        check("P4.only_supported_items", [m.name for m in b.items] == ["keep.txt"], "")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "gone.txt", "c.txt"])
        a = la(root, order=["a.txt", "gone.txt", "c.txt"])
        a.probe.stat_error["gone.txt"] = FileNotFoundError(errno.ENOENT, "gone")
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
        check("P5.enoent_entry_charged", b.inspected == 3, f"{b.inspected}")
        check("P5.enoent_item_omitted", [m.name for m in b.items] == ["a.txt", "c.txt"], "")
        a.close()


def p6_p7_p8():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt", "c.txt"])
        a = la(root, order=["a.txt", "b.txt", "c.txt"])
        a.probe.stat_error["b.txt"] = OSError(errno.EIO, "stat boom")
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "P6.stat_failure_raises", "no exc")
        except ScanFailure as f:
            check("P6.stat_failure_charged", f.inspected == 2, f"{f.inspected}")
            check("P6.stat_failure_error_type", isinstance(f.error, StorageError), type(f.error).__name__)
            check("P6.stat_failure_cause", isinstance(f.__cause__, OSError), type(f.__cause__).__name__)
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt", "c.txt", "d.txt"])
        a = la(root, order=["a.txt", "b.txt", "c.txt", "d.txt"])
        a.probe.iterate_error_after = 2
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "P7.iter_failure_raises", "no exc")
        except ScanFailure as f:
            check("P7.iter_failure_charged", f.inspected == 2, f"{f.inspected}")
        a.close()
    for label, nf, cap in (("partial", 5, 3), ("complete", 3, 10)):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); files(root, [f"f{i}.txt" for i in range(nf)])
            a = la(root); a.probe.close_error = True
            try:
                a.scan_children(FileRef("src", ROOT_ID), max_entries=cap)
                rec("FAIL", f"P8.{label}_close_raises", "no exc")
            except ScanFailure as f:
                check(f"P8.{label}_close_charged", f.inspected == min(nf, cap), f"{f.inspected}")
            a.close()


def p9():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, [f"f{i}.txt" for i in range(6)])
        a = la(root)
        for _ in range(5):
            a.scan_children(FileRef("src", ROOT_ID), max_entries=3)
        base = len(os.listdir("/proc/self/fd"))
        for _ in range(60):
            a.scan_children(FileRef("src", ROOT_ID), max_entries=3)
        a.probe.stat_error["f2.txt"] = OSError(errno.EIO, "boom")
        for _ in range(60):
            try:
                a.scan_children(FileRef("src", ROOT_ID), max_entries=6)
            except ScanFailure:
                pass
        after = len(os.listdir("/proc/self/fd"))
        check("P9.no_fd_growth", after <= base, f"{base}->{after}")
        a.close()


def p10():
    original = LocalStorageError("root original")
    fake = Scripted({ROOT_ID: ScanFailure(2, original)})
    try:
        find(fake, FileRef("fake", ROOT_ID), "x")
        rec("FAIL", "P10.root_identity", "no exc")
    except LocalStorageError as e:
        check("P10.root_identity", e is original, f"{e is original}")


def p11():
    s1 = meta("p/s1", "s1", "directory"); s2 = meta("p/s2", "s2", "directory")
    fake = Scripted({ROOT_ID: ScanBatch((s1, s2), 2, True),
                     "p/s2": ScanBatch((meta("p/s2/hit.txt", "hit.txt"),), 1, True),
                     "p/s1": ScanFailure(1, LocalStorageError("s1 fail"))})
    r = find(fake, FileRef("fake", ROOT_ID), "hit", max_entries=3, max_depth=4)
    check("P11.sibling_not_scanned", [c[0] for c in fake.calls] == [ROOT_ID, "p/s1"], str([c[0] for c in fake.calls]))
    check("P11.truncated_after_exhaust", r.truncated and r.reason == "max_entries", f"{r.reason}")


def p12():
    kids = [meta(f"r/m{i}.txt", f"m{i}.txt") for i in range(5)]
    fake = Scripted({ROOT_ID: ScanBatch(tuple(kids), 5, True)})
    r = find(fake, FileRef("fake", ROOT_ID), "m", max_results=2, max_entries=100)
    check("P12.max_results_precedence", r.truncated and r.reason == "max_results", f"{r.reason}")
    d = meta("p/d", "d", "directory"); dd = meta("p/d/sub", "sub", "directory")
    f2 = Scripted({ROOT_ID: ScanBatch((d,), 1, True), "p/d": ScanBatch((dd,), 1, True), "p/d/sub": ScanBatch((), 0, True)})
    r2 = find(f2, FileRef("fake", ROOT_ID), "zzz", max_depth=0)
    check("P12.depth_truncation_explicit", r2.truncated and r2.reason == "max_depth", f"{r2.reason}")


def p13():
    ok = meta("a.txt", "a.txt")
    cases = {
        "items_not_tuple": ScanBatch(items=[ok], inspected=1, complete=True),
        "inspected_bool": ScanBatch(items=(), inspected=True, complete=True),
        "inspected_str": ScanBatch(items=(), inspected="1", complete=True),
        "inspected_gt_remaining": ScanBatch(items=(), inspected=50, complete=True),
        "inspected_negative": ScanBatch(items=(), inspected=-1, complete=True),
        "complete_not_bool": ScanBatch(items=(), inspected=0, complete=1),
        "items_gt_inspected": ScanBatch(items=(ok,), inspected=0, complete=True),
        "incomplete_no_exhaust": ScanBatch(items=(), inspected=0, complete=False),
    }
    for name, obj in cases.items():
        try:
            find(Scripted({ROOT_ID: obj}), FileRef("fake", ROOT_ID), "a", max_entries=10)
            rec("FAIL", f"P13.{name}", "accepted")
        except StorageError:
            rec("PASS", f"P13.{name}", "rejected")
    try:
        find(Scripted({ROOT_ID: object()}), FileRef("fake", ROOT_ID), "a", max_entries=10)
        rec("FAIL", "P13.missing_attrs", "accepted")
    except StorageError:
        rec("PASS", "P13.missing_attrs", "rejected")


def p14():
    class NoScan:
        source_id = "n"
        def stat(self, ref): raise NotImplementedError
        def read_bytes(self, ref): raise NotImplementedError
        def list_children(self, parent, *, max_entries=None): return []
    try:
        find(NoScan(), FileRef("n", ROOT_ID), "x")
        rec("FAIL", "P14.no_scanner_denied", "no exc")
    except ScanUnsupportedError:
        rec("PASS", "P14.no_scanner_denied", "ScanUnsupportedError")
    class NonCallable:
        source_id = "n"; scan_children = 42
        def stat(self, ref): raise NotImplementedError
        def read_bytes(self, ref): raise NotImplementedError
    try:
        find(NonCallable(), FileRef("n", ROOT_ID), "x")
        rec("FAIL", "P14.non_callable_denied", "no exc")
    except ScanUnsupportedError:
        rec("PASS", "P14.non_callable_denied", "ScanUnsupportedError")
    try:
        find(NoScan(), FileRef("n", ROOT_ID), "", max_results=0)
        rec("FAIL", "P14.arg_validation_first", "no exc")
    except ValueError:
        rec("PASS", "P14.arg_validation_first", "ValueError first")
    except ScanUnsupportedError:
        rec("FAIL", "P14.arg_validation_first", "capability first")


# ---------------------------------------------------------------------------
# F-B converted to positive assertions
# ---------------------------------------------------------------------------
def fb_positive():
    bad = meta("p/bad", "bad", "directory")
    r, _ = sfind({ROOT_ID: ScanBatch((bad,), 1, True), "p/bad": NotFoundError("gone")}, "zzz")
    check("FB.prescan_skipped_not_complete", r.truncated is True and r.reason == "skipped" and r.skipped == ("p/bad",),
          f"truncated={r.truncated} reason={r.reason} skipped={r.skipped}")
    check("FB.skipped_not_not_found", not (not r.truncated and r.items == ()), f"items={r.items}")

    sub = meta("p/sub", "sub", "directory")
    r2, _ = sfind({ROOT_ID: ScanBatch((sub,), 1, True), "p/sub": ScanFailure(2, LocalStorageError("mid"))}, "zzz", max_entries=100)
    check("FB.midscan_skipped_not_complete", r2.truncated is True and r2.reason == "skipped" and r2.inspected == 3,
          f"reason={r2.reason} inspected={r2.inspected}")

    bad2 = meta("p/bad", "bad", "directory"); good = meta("p/good", "good", "directory")
    r3, _ = sfind({ROOT_ID: ScanBatch((bad2, good), 2, True),
                   "p/bad": NotFoundError("gone"),
                   "p/good": ScanBatch((meta("p/good/m0.txt", "m0.txt"), meta("p/good/m1.txt", "m1.txt")), 2, True)},
                  "m0", max_results=1)
    check("FB.max_results_precedence_over_skipped", r3.reason == "max_results" and r3.skipped == ("p/bad",), f"reason={r3.reason}")
    deep = meta("p/deep", "deep", "directory"); dq = meta("p/deep/q", "q", "directory")
    r4, _ = sfind({ROOT_ID: ScanBatch((bad2, deep), 2, True), "p/bad": NotFoundError("gone"),
                   "p/deep": ScanBatch((dq,), 1, True)}, "zzz", max_depth=1)
    check("FB.max_depth_precedence_over_skipped", r4.reason == "max_depth", f"reason={r4.reason}")
    s1 = meta("p/s1", "s1", "directory"); s2 = meta("p/s2", "s2", "directory")
    r5, _ = sfind({ROOT_ID: ScanBatch((s1, s2), 2, True), "p/s1": ScanFailure(1, LocalStorageError("x"))}, "zzz", max_entries=3, max_depth=4)
    check("FB.max_entries_precedence_over_skipped", r5.reason == "max_entries" and r5.skipped == ("p/s1",), f"reason={r5.reason}")
    r6, _ = sfind({ROOT_ID: ScanBatch((meta("m.txt", "m.txt"),), 1, True)}, "m")
    check("FB.empty_skipped_complete", r6.truncated is False and r6.reason is None and r6.skipped == (), f"{r6.truncated},{r6.reason}")


# ---------------------------------------------------------------------------
# F-A converted to positive assertions
# ---------------------------------------------------------------------------
def fa_positive():
    try:
        sfind({ROOT_ID: ScanFailure(1, "not-a-storage-error")}, "x")
        rec("FAIL", "FA.root_malformed_raises", "no exc")
    except StorageError:
        rec("PASS", "FA.root_malformed_raises", "StorageError")
    sub = meta("p/sub", "sub", "directory")
    try:
        r, _ = sfind({ROOT_ID: ScanBatch((sub,), 1, True), "p/sub": ScanFailure(1, "not-a-storage-error")}, "x", max_entries=100)
        rec("FAIL", "FA.depth_malformed_raises", f"accepted skipped={r.skipped}")
    except StorageError:
        rec("PASS", "FA.depth_malformed_raises", "StorageError at depth>0")
    original = LocalStorageError("root boom"); original.__cause__ = OSError(errno.EIO, "underlying")
    try:
        sfind({ROOT_ID: ScanFailure(2, original)}, "x")
        rec("FAIL", "FA.root_identity", "no exc")
    except LocalStorageError as e:
        check("FA.root_identity", e is original, f"{e is original}")
        check("FA.root_cause", isinstance(e.__cause__, OSError), type(e.__cause__).__name__)


# ---------------------------------------------------------------------------
# F-C converted to positive assertions
# ---------------------------------------------------------------------------
def fc_positive():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt"])
        a = la(root, order=["a.txt", "b.txt"]); boom = LocalStorageError("metadata boom")
        a.probe.build_error = {"a.txt": boom}
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.metadata_charged", "no exc")
        except ScanFailure as f:
            check("FC.metadata_charged", f.inspected == 1 and f.error is boom and f.__cause__ is boom,
                  f"inspected={f.inspected} err_is={f.error is boom} cause_is={f.__cause__ is boom}")
        except StorageError as e:
            rec("FAIL", "FC.metadata_charged", f"bare {type(e).__name__}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt"])
        a = la(root, order=["a.txt", "b.txt"]); boom = LocalStorageError("stat seam boom")
        a.probe.stat_error = {"b.txt": boom}
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.stat_charged", "no exc")
        except ScanFailure as f:
            check("FC.stat_charged", f.inspected == 2 and f.error is boom, f"inspected={f.inspected} err_is={f.error is boom}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt", "c.txt"])
        a = la(root, order=["a.txt", "b.txt", "c.txt"]); boom = LocalStorageError("next boom")
        a.probe.next_error = boom; a.probe.next_error_after = 2
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.next_charged", "no exc")
        except ScanFailure as f:
            check("FC.next_charged", f.inspected == 2 and f.error is boom, f"inspected={f.inspected}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt"])
        a = la(root); boom = LocalStorageError("pre-yield boom")
        a.probe.next_error = boom; a.probe.next_error_after = 0
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.pre_yield_unchanged", "no exc")
        except ScanFailure:
            rec("FAIL", "FC.pre_yield_unchanged", "wrapped (should be unchanged)")
        except LocalStorageError as e:
            check("FC.pre_yield_unchanged", e is boom, f"identity={e is boom}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt"])
        a = la(root); inner = ScanFailure(7, LocalStorageError("inner"))
        a.probe.build_error = {"a.txt": inner}
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.no_double_wrap", "no exc")
        except ScanFailure as f:
            check("FC.no_double_wrap", f is inner, f"identity={f is inner}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); (root / "sub").mkdir(); files(root / "sub", ["a.txt", "b.txt"])
        a = la(root, order=["sub"]); boom = LocalStorageError("sub metadata boom")
        a.probe.build_error = {"a.txt": boom}
        r = find(a, FileRef("src", ROOT_ID), "zzz", max_entries=100)
        check("FC.below_root_charged_skipped", r.inspected == 2 and r.skipped == ("p/sub",) and r.truncated and r.reason == "skipped",
              f"inspected={r.inspected} skipped={r.skipped} reason={r.reason}")
        a.close()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td); files(root, ["a.txt", "b.txt"])
        a = la(root, order=["a.txt", "b.txt"])
        primary = LocalStorageError("primary boom"); a.probe.stat_error = {"b.txt": primary}
        real_close = a._os_close
        leaked = {"fd": None}; calls = {"n": 0}
        def failing_close(fd):
            calls["n"] += 1
            if leaked["fd"] is None:
                leaked["fd"] = fd
                raise OSError(errno.EIO, "cleanup boom")
            return real_close(fd)
        a._os_close = failing_close
        before = len(os.listdir("/proc/self/fd"))
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "FC.primary_wins_cleanup", "no exc")
        except ScanFailure as f:
            check("FC.primary_wins_cleanup", f.error is primary and f.inspected == 2, f"err_is_primary={f.error is primary} inspected={f.inspected}")
        a._os_close = real_close
        if leaked["fd"] is not None:
            os.close(leaked["fd"])
        after = len(os.listdir("/proc/self/fd"))
        check("FC.no_close_retry", calls["n"] == 1, f"close_calls={calls['n']}")
        check("FC.no_fd_growth_same_lifetime", before == after, f"{before}->{after}")
        a.close()


def main():
    for fn in (p1_p2, p3, p4_p5, p6_p7_p8, p9, p10, p11, p12, p13, p14,
               fb_positive, fa_positive, fc_positive):
        try:
            fn()
        except Exception:
            rec("ERROR", fn.__name__, traceback.format_exc().splitlines()[-1])
    print("\n==== TALLY ====")
    from collections import Counter
    c = Counter(s for s, _, _ in RESULTS)
    for k in ("PASS", "FAIL", "FINDING", "ERROR"):
        print(f"{k}: {c.get(k,0)}")
    print("\n==== FAILURES ====")
    for s, n, d in RESULTS:
        if s in ("FAIL", "ERROR"):
            print(f"[{s}] {n} :: {d}")


if __name__ == "__main__":
    main()

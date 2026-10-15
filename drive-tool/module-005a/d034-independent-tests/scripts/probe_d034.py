"""d034 independent probes for MODULE-005A candidate 593759a.

Independent of the d032/d033 suites: exercises the strict-B scan seam, the
search accounting contract, and adversarial edge cases the candidate's own
tests bake in. Prints PASS/FAIL/FINDING lines and a final tally.
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
    InMemoryAdapter,
    NotFoundError,
    ScanBatch,
    ScanFailure,
    ScanUnsupportedError,
    StorageError,
)
from test_partial_scan import OrderedScanAdapter  # noqa: E402
from test_search import FakeAdapter, _file  # noqa: E402

RESULTS = []


def rec(status, name, detail=""):
    RESULTS.append((status, name, detail))
    print(f"[{status}] {name} :: {detail}")


def check(name, cond, detail=""):
    rec("PASS" if cond else "FAIL", name, detail)


def finding(name, detail):
    rec("FINDING", name, detail)


def mkdir_files(root: Path, names):
    for n in names:
        (root / n).write_text("x")


def local_adapter(root, **kw):
    return OrderedScanAdapter("src", str(root), **kw)


# ---------------------------------------------------------------------------
# P1/P2: strict B raw yields, no B+1; exact-budget unknown EOF (local)
# ---------------------------------------------------------------------------
def p1_p2():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, [f"f{i:02d}.txt" for i in range(10)])
        a = local_adapter(root, order=[f"f{i:02d}.txt" for i in range(10)])
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=4)
        check("P1.strict_B_inspected", b.inspected == 4, f"inspected={b.inspected}")
        check("P1.no_B_plus_1_next", a.probe.next_attempts == 4,
              f"next() calls={a.probe.next_attempts} (must be exactly B=4)")
        check("P1.at_most_B_stat", a.probe.stat_calls <= 4,
              f"stat calls={a.probe.stat_calls}")
        check("P1.complete_false_at_cap", b.complete is False, f"complete={b.complete}")
        check("P1.items_le_inspected", len(b.items) <= b.inspected,
              f"len(items)={len(b.items)} inspected={b.inspected}")
        a.close()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, [f"e{i}.txt" for i in range(5)])
        a = local_adapter(root)
        exact = a.scan_children(FileRef("src", ROOT_ID), max_entries=5)
        check("P2.exact_budget_incomplete", exact.inspected == 5 and exact.complete is False,
              f"inspected={exact.inspected} complete={exact.complete}")
        over = a.scan_children(FileRef("src", ROOT_ID), max_entries=6)
        check("P2.room_to_spare_complete", over.inspected == 5 and over.complete is True,
              f"inspected={over.inspected} complete={over.complete}")
        a.close()


# ---------------------------------------------------------------------------
# P3: retained prefix matches from an over-budget real dir
# ---------------------------------------------------------------------------
def p3():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        names = [f"z{i:02d}.txt" for i in range(20)]
        mkdir_files(root, names)
        # put a matching name in the scanned prefix
        (root / "match_here.txt").write_text("x")
        order = ["match_here.txt"] + names
        a = local_adapter(root, order=order)
        r = find(a, FileRef("src", ROOT_ID), "match", max_entries=5)
        check("P3.prefix_match_retained", [m.name for m in r.items] == ["match_here.txt"],
              f"items={[m.name for m in r.items]}")
        check("P3.prefix_truncated_max_entries", r.truncated is True and r.reason == "max_entries",
              f"truncated={r.truncated} reason={r.reason}")
        check("P3.inspected_is_B", r.inspected == 5, f"inspected={r.inspected}")
        a.close()


# ---------------------------------------------------------------------------
# P4/P5: mixed omitted/raw entries all charged
# ---------------------------------------------------------------------------
def p4_p5():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "keep.txt").write_text("x")
        (root / ".drive-tool-tmp-abc").write_text("x")          # writer temp
        try:
            os.symlink(root / "keep.txt", root / "link")
        except OSError:
            pass
        made_fifo = False
        try:
            os.mkfifo(root / "pipe")
            made_fifo = True
        except OSError:
            pass
        a = local_adapter(root)
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=20)
        expected_raw = 2 + (1 if os.path.lexists(root / "link") else 0) + (1 if made_fifo else 0)
        item_names = [m.name for m in b.items]
        check("P4.omitted_entries_charged", b.inspected == expected_raw,
              f"inspected={b.inspected} expected_raw={expected_raw} items={item_names}")
        check("P4.only_supported_items", item_names == ["keep.txt"],
              f"items={item_names}")
        a.close()

    # ENOENT-disappearing entry charged (via seam injecting FileNotFoundError)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, ["a.txt", "gone.txt", "c.txt"])
        a = local_adapter(root, order=["a.txt", "gone.txt", "c.txt"])
        a.probe.stat_error["gone.txt"] = FileNotFoundError(errno.ENOENT, "gone")
        b = a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
        check("P5.enoent_entry_charged", b.inspected == 3,
              f"inspected={b.inspected} (all 3 raw entries counted)")
        check("P5.enoent_item_omitted", [m.name for m in b.items] == ["a.txt", "c.txt"],
              f"items={[m.name for m in b.items]}")
        a.close()


# ---------------------------------------------------------------------------
# P6-P8: failed stat / iteration / iterator-close accounting
# ---------------------------------------------------------------------------
def p6_p7_p8():
    # stat failure after a nonzero prefix
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, ["a.txt", "b.txt", "c.txt"])
        a = local_adapter(root, order=["a.txt", "b.txt", "c.txt"])
        a.probe.stat_error["b.txt"] = OSError(errno.EIO, "stat boom")
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "P6.stat_failure_raises", "no exception")
        except ScanFailure as f:
            check("P6.stat_failure_charged", f.inspected == 2, f"inspected={f.inspected}")
            check("P6.stat_failure_error_type", isinstance(f.error, StorageError),
                  f"error={type(f.error).__name__}")
            check("P6.stat_failure_cause", isinstance(f.__cause__, OSError),
                  f"cause={type(f.__cause__).__name__}")
        except StorageError as e:
            rec("FAIL", "P6.stat_failure_raises", f"bare StorageError {type(e).__name__} (uncharged)")
        a.close()

    # iteration failure after a nonzero prefix
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, ["a.txt", "b.txt", "c.txt", "d.txt"])
        a = local_adapter(root, order=["a.txt", "b.txt", "c.txt", "d.txt"])
        a.probe.iterate_error_after = 2
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "P7.iter_failure_raises", "no exception")
        except ScanFailure as f:
            check("P7.iter_failure_charged", f.inspected == 2, f"inspected={f.inspected}")
        except StorageError as e:
            rec("FAIL", "P7.iter_failure_raises", f"bare {type(e).__name__} (uncharged)")
        a.close()

    # iterator close failure (partial return path and complete path)
    for label, nfiles, cap in (("partial", 5, 3), ("complete", 3, 10)):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            mkdir_files(root, [f"f{i}.txt" for i in range(nfiles)])
            a = local_adapter(root)
            a.probe.close_error = True
            try:
                a.scan_children(FileRef("src", ROOT_ID), max_entries=cap)
                rec("FAIL", f"P8.{label}_close_raises", "no exception")
            except ScanFailure as f:
                check(f"P8.{label}_close_charged", f.inspected == min(nfiles, cap),
                      f"inspected={f.inspected} expected={min(nfiles,cap)}")
            except StorageError as e:
                rec("FAIL", f"P8.{label}_close_raises", f"bare {type(e).__name__}")
            a.close()


# ---------------------------------------------------------------------------
# P9: fd hygiene over repeated success + failure scans
# ---------------------------------------------------------------------------
def fd_count():
    return len(os.listdir("/proc/self/fd"))


def p9():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, [f"f{i}.txt" for i in range(6)])
        a = local_adapter(root)
        # warm up
        for _ in range(5):
            a.scan_children(FileRef("src", ROOT_ID), max_entries=3)
        base = fd_count()
        for _ in range(60):
            a.scan_children(FileRef("src", ROOT_ID), max_entries=3)
        a.probe.stat_error["f2.txt"] = OSError(errno.EIO, "boom")
        for _ in range(60):
            try:
                a.scan_children(FileRef("src", ROOT_ID), max_entries=6)
            except ScanFailure:
                pass
        after = fd_count()
        check("P9.no_fd_growth", after <= base,
              f"fds before={base} after={after}")
        a.close()


# ---------------------------------------------------------------------------
# P10: root ScanFailure re-raises original object identity + cause
# ---------------------------------------------------------------------------
def p10():
    original = LocalStorageError("root original")
    fake = FakeAdapter("fake", {ROOT_ID: []}, raise_on={ROOT_ID: ScanFailure(2, original)})
    try:
        find(fake, FileRef("fake", ROOT_ID), "x")
        rec("FAIL", "P10.root_identity", "no exception")
    except LocalStorageError as e:
        check("P10.root_identity", e is original, f"identity preserved={e is original}")
        check("P10.root_cause_chain", e is original, "original object raised")


# ---------------------------------------------------------------------------
# P11: BFS sibling suppression after a failed scan exhausts the budget
# ---------------------------------------------------------------------------
def p11():
    s1 = _file("p/s1", "s1", ROOT_ID, kind="directory")
    s2 = _file("p/s2", "s2", ROOT_ID, kind="directory")
    fake = FakeAdapter(
        "fake",
        {ROOT_ID: [s1, s2], "p/s2": [_file("p/s2/hit.txt", "hit.txt", "p/s2")]},
        raise_on={"p/s1": ScanFailure(1, LocalStorageError("s1 fail"))},
    )
    r = find(fake, FileRef("fake", ROOT_ID), "hit", max_entries=3, max_depth=4)
    check("P11.sibling_not_scanned", [c[0] for c in fake.calls] == [ROOT_ID, "p/s1"],
          f"calls={[c[0] for c in fake.calls]}")
    check("P11.truncated_after_exhaust", r.truncated is True and r.reason == "max_entries",
          f"truncated={r.truncated} reason={r.reason} inspected={r.inspected}")


# ---------------------------------------------------------------------------
# P12: result / depth priority
# ---------------------------------------------------------------------------
def p12():
    # max_results precedence over max_entries
    kids = [_file(f"r/m{i}.txt", f"m{i}.txt", ROOT_ID) for i in range(5)]
    fake = FakeAdapter("fake", {ROOT_ID: kids})
    r = find(fake, FileRef("fake", ROOT_ID), "m", max_results=2, max_entries=100)
    check("P12.max_results_precedence", r.truncated and r.reason == "max_results",
          f"reason={r.reason} items={len(r.items)}")

    # depth truncation explicit
    d = _file("p/d", "d", ROOT_ID, kind="directory")
    dd = _file("p/d/sub", "sub", "p/d", kind="directory")
    fake2 = FakeAdapter("fake", {ROOT_ID: [d], "p/d": [dd], "p/d/sub": []})
    r2 = find(fake2, FileRef("fake", ROOT_ID), "zzz", max_depth=0)
    check("P12.depth_truncation_explicit", r2.truncated and r2.reason == "max_depth",
          f"reason={r2.reason}")


# ---------------------------------------------------------------------------
# P13: malformed batch reports rejected loudly
# ---------------------------------------------------------------------------
class RawScanner:
    """Adapter returning a scripted object from scan_children."""
    source_id = "raw"

    def __init__(self, obj):
        self._obj = obj
        self.calls = []

    def scan_children(self, parent, *, max_entries):
        self.calls.append((parent.file_id, max_entries))
        if callable(self._obj):
            return self._obj(max_entries)
        return self._obj

    def stat(self, ref):
        raise NotImplementedError

    def read_bytes(self, ref):
        raise NotImplementedError


def p13():
    ok_item = _file("a.txt", "a.txt", ROOT_ID)
    cases = {
        "items_not_tuple": ScanBatch(items=[ok_item], inspected=1, complete=True),   # list
        "inspected_bool": ScanBatch(items=(), inspected=True, complete=True),
        "inspected_str": ScanBatch(items=(), inspected="1", complete=True),
        "inspected_gt_remaining": ScanBatch(items=(), inspected=50, complete=True),
        "inspected_negative": ScanBatch(items=(), inspected=-1, complete=True),
        "complete_not_bool": ScanBatch(items=(), inspected=0, complete=1),
        "items_gt_inspected": ScanBatch(items=(ok_item,), inspected=0, complete=True),
        "incomplete_no_exhaust": ScanBatch(items=(), inspected=0, complete=False),
    }
    for name, obj in cases.items():
        fake = RawScanner(obj)
        try:
            find(fake, FileRef("raw", ROOT_ID), "a", max_entries=10)
            rec("FAIL", f"P13.{name}", "accepted malformed report")
        except StorageError:
            rec("PASS", f"P13.{name}", "rejected loudly with StorageError")
        except Exception as e:  # noqa
            rec("FAIL", f"P13.{name}", f"wrong exception {type(e).__name__}")

    # a batch object missing attributes entirely
    fake = RawScanner(object())
    try:
        find(fake, FileRef("raw", ROOT_ID), "a", max_entries=10)
        rec("FAIL", "P13.missing_attrs", "accepted")
    except StorageError:
        rec("PASS", "P13.missing_attrs", "rejected")


# ---------------------------------------------------------------------------
# P14: legacy scanner denial (capability requirement)
# ---------------------------------------------------------------------------
def p14():
    class NoScan:
        source_id = "n"

        def stat(self, ref):
            raise NotImplementedError

        def read_bytes(self, ref):
            raise NotImplementedError

        def list_children(self, parent, *, max_entries=None):
            return []

    try:
        find(NoScan(), FileRef("n", ROOT_ID), "x")
        rec("FAIL", "P14.no_scanner_denied", "no exception")
    except ScanUnsupportedError:
        rec("PASS", "P14.no_scanner_denied", "ScanUnsupportedError")
    except Exception as e:  # noqa
        rec("FAIL", "P14.no_scanner_denied", f"wrong exception {type(e).__name__}")

    # scan_children present but not callable
    class NonCallableScan:
        source_id = "n"
        scan_children = 42

        def stat(self, ref):
            raise NotImplementedError

        def read_bytes(self, ref):
            raise NotImplementedError

    try:
        find(NonCallableScan(), FileRef("n", ROOT_ID), "x")
        rec("FAIL", "P14.non_callable_denied", "no exception")
    except ScanUnsupportedError:
        rec("PASS", "P14.non_callable_denied", "ScanUnsupportedError")

    # argument validation precedes capability check
    try:
        find(NoScan(), FileRef("n", ROOT_ID), "", max_results=0)
        rec("FAIL", "P14.arg_validation_first", "no exception")
    except ValueError:
        rec("PASS", "P14.arg_validation_first", "ValueError before capability check")
    except ScanUnsupportedError:
        rec("FAIL", "P14.arg_validation_first", "capability checked before args")


# ---------------------------------------------------------------------------
# FINDING A: invalid ScanFailure.error validated only at root
# ---------------------------------------------------------------------------
def finding_a():
    bad = ScanFailure(1, "not-a-storage-error")  # .error is a str
    # root
    fake_root = FakeAdapter("fake", {ROOT_ID: []}, raise_on={ROOT_ID: bad})
    try:
        find(fake_root, FileRef("fake", ROOT_ID), "x")
        rec("FAIL", "A.root_bad_error", "accepted")
    except StorageError as e:
        rec("PASS", "A.root_bad_error", f"rejected at root: {type(e).__name__}")
    # depth > 0
    sub = _file("p/sub", "sub", ROOT_ID, kind="directory")
    fake_deep = FakeAdapter("fake", {ROOT_ID: [sub]}, raise_on={"p/sub": bad})
    try:
        r = find(fake_deep, FileRef("fake", ROOT_ID), "x", max_entries=10)
        finding("A.depth_bad_error_not_rejected",
                f"malformed ScanFailure.error accepted at depth>0: "
                f"skipped={r.skipped} truncated={r.truncated} (root rejects the same input)")
    except StorageError as e:
        rec("PASS", "A.depth_bad_error", f"rejected at depth>0: {type(e).__name__}")


# ---------------------------------------------------------------------------
# FINDING B: skipped subdirectory does not set truncated
# ---------------------------------------------------------------------------
def finding_b():
    # pre-scan StorageError on a subdir, no other work
    sub = _file("p/bad", "bad", ROOT_ID, kind="directory")
    fake = FakeAdapter("fake", {ROOT_ID: [sub]}, raise_on={"p/bad": NotFoundError("gone")})
    r = find(fake, FileRef("fake", ROOT_ID), "x")
    finding("B.skipped_but_complete_prescan",
            f"skipped={r.skipped} truncated={r.truncated} reason={r.reason} "
            f"(reports complete coverage with a skipped subtree)")
    # mid-scan ScanFailure that does not exhaust budget
    sub2 = _file("p/sub", "sub", ROOT_ID, kind="directory")
    fake2 = FakeAdapter("fake", {ROOT_ID: [sub2]},
                        raise_on={"p/sub": ScanFailure(2, LocalStorageError("mid"))})
    r2 = find(fake2, FileRef("fake", ROOT_ID), "x", max_entries=100)
    finding("B.skipped_but_complete_midscan",
            f"skipped={r2.skipped} truncated={r2.truncated} reason={r2.reason} "
            f"inspected={r2.inspected}")


# ---------------------------------------------------------------------------
# FINDING C: StorageError raised after an entry is yielded, outside stat,
# escapes ScanFailure (metadata seam), losing raw-work accounting.
# ---------------------------------------------------------------------------
def finding_c():
    # C1: StorageError injected via the stat seam (a metadata operation)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, ["a.txt", "b.txt", "c.txt"])
        a = local_adapter(root, order=["a.txt", "b.txt", "c.txt"])
        a.probe.stat_error["b.txt"] = LocalStorageError("metadata seam boom")
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "C1.meta_storage_error", "no exception")
        except ScanFailure as f:
            rec("PASS", "C1.meta_storage_error", f"charged ScanFailure({f.inspected})")
        except StorageError as e:
            finding("C1.meta_storage_error_uncharged",
                    f"StorageError from stat seam after 1 yielded entry escaped as bare "
                    f"{type(e).__name__} (no ScanFailure, raw work unaccounted)")
        a.close()

    # C2: StorageError from _build_metadata seam
    class MetaBoom(OrderedScanAdapter):
        def __init__(self, *a, **k):
            self._n = 0
            super().__init__(*a, **k)

        def _build_metadata(self, parts, *, kind, size_bytes):
            self._n += 1
            if self._n == 2:
                raise LocalStorageError("build_metadata boom")
            return super()._build_metadata(parts, kind=kind, size_bytes=size_bytes)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        mkdir_files(root, ["a.txt", "b.txt", "c.txt"])
        a = MetaBoom("src", str(root), order=["a.txt", "b.txt", "c.txt"])
        try:
            a.scan_children(FileRef("src", ROOT_ID), max_entries=10)
            rec("FAIL", "C2.build_metadata_storage_error", "no exception")
        except ScanFailure as f:
            rec("PASS", "C2.build_metadata_storage_error", f"charged ScanFailure({f.inspected})")
        except StorageError as e:
            finding("C2.build_metadata_storage_error_uncharged",
                    f"StorageError from metadata seam after 1 yielded entry escaped as bare "
                    f"{type(e).__name__} (raw work unaccounted)")
        a.close()

    # C3: the same escape via find() at depth>0 -> raw work charged as ZERO.
    # A fake adapter whose subdir scan raises a bare StorageError after work.
    class WorkLostFake:
        source_id = "fake"

        def __init__(self):
            self.calls = []

        def scan_children(self, parent, *, max_entries):
            self.calls.append((parent.file_id, max_entries))
            if parent.file_id == ROOT_ID:
                sub = _file("p/sub", "sub", ROOT_ID, kind="directory")
                return ScanBatch((sub,), 1, True)
            # bare StorageError, no ScanFailure, after "raw work"
            raise LocalStorageError("sub scan failed after work")

        def stat(self, ref):
            raise NotImplementedError

        def read_bytes(self, ref):
            raise NotImplementedError

    f = WorkLostFake()
    r = find(f, FileRef("fake", ROOT_ID), "x", max_entries=100)
    finding("C3.raw_work_lost_at_depth",
            f"subdir bare StorageError charged as inspected={r.inspected} "
            f"(root batch charged 1; the subdir's raw work is not counted), "
            f"skipped={r.skipped} truncated={r.truncated}")


def main():
    for fn in (p1_p2, p3, p4_p5, p6_p7_p8, p9, p10, p11, p12, p13, p14,
               finding_a, finding_b, finding_c):
        try:
            fn()
        except Exception:  # noqa
            rec("ERROR", fn.__name__, traceback.format_exc().splitlines()[-1])
    print("\n==== TALLY ====")
    from collections import Counter
    c = Counter(s for s, _, _ in RESULTS)
    for k in ("PASS", "FAIL", "FINDING", "ERROR"):
        print(f"{k}: {c.get(k,0)}")
    print("\n==== FAILURES / FINDINGS ====")
    for s, n, d in RESULTS:
        if s in ("FAIL", "FINDING", "ERROR"):
            print(f"[{s}] {n} :: {d}")


if __name__ == "__main__":
    main()

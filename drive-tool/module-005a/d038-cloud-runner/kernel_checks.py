#!/usr/bin/env python3
"""d038 real-kernel checks for the drive-tool candidate (stdlib only).

Provenance: adapted for d038 from the d014 checks
(drive-tool/readonly-core/d014-cloud-validation/runner/kernel_checks.py). Run
one named check per process so a hang is contained by the orchestrating
runner's wall-clock timeout:

    python3 kernel_checks.py <check> <src-dir>

`<src-dir>` is the extracted candidate root (the directory containing
`drive_tool/`). Checks use REAL synthetic files and REAL os.open/os.scandir
semantics; the implementation is never edited and kernel support is never
mocked.

Two families of check are used and are labelled as such in their output:

* REAL file operations observed through a seam. The check runs the candidate's
  own code against real files on disk; an *observational* seam (a subclass that
  wraps the real `os.scandir` iterator, or a spy over a real syscall) only
  counts what the real code did. It never fabricates a result.
* SIMULATED fault injection. The check deliberately raises an error from a
  seam to exercise an error path. Its output says "SIMULATED" so it is never
  confused with a real filesystem outcome.

Retained d014 checks (where compatible with the candidate API): nofollow,
bounded_read, root_anchor, dir_symlink_swap, fifo, fd_lifetime.
New d038 checks: strict_b_scanner, partial_search, write_collision,
concurrent_writers.

Exit: 0 = PASS, 1 = FAIL, 2 = SKIP (with a precise reason).
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading

MAX_FIXTURE_BYTES = 1024 * 1024  # fixtures stay <= 1 MiB


def _fail(msg):
    print(f"  {msg}")
    return 1


def _write(path, data):
    assert len(data) <= MAX_FIXTURE_BYTES, "fixture exceeds 1 MiB bound"
    with open(path, "wb") as fh:
        fh.write(data)


def _mkroot(prefix):
    raw = tempfile.mkdtemp(prefix=prefix)
    return os.path.realpath(raw)


# --------------------------------------------------------------------------
# Retained d014 checks (real-kernel, compatible with the candidate API)
# --------------------------------------------------------------------------

def check_nofollow():
    """Actual runtime O_NOFOLLOW semantics with the adapter's component flags."""
    from drive_tool.local import _dir_open_flags, _file_open_flags
    base = _mkroot("d038_nofollow_")
    try:
        target = os.path.join(base, "target")
        link = os.path.join(base, "link")
        os.mkdir(target)
        os.symlink(target, link)
        flags = _dir_open_flags()
        print(f"  component flags = {oct(flags)} (O_NOFOLLOW={bool(flags & os.O_NOFOLLOW)}, "
              f"O_DIRECTORY={bool(flags & getattr(os, 'O_DIRECTORY', 0))})")
        followed = False
        err = None
        try:
            fd = os.open(link, flags)
        except OSError as exc:
            err = exc.errno
        else:
            followed = True
            os.close(fd)
        # Report the O_DIRECTORY interaction (informational, not asserted).
        with_dir = None
        try:
            fd2 = os.open(link, flags | getattr(os, "O_DIRECTORY", 0))
        except OSError as exc:
            with_dir = errno.errorcode.get(exc.errno, exc.errno)
        else:
            with_dir = "FOLLOWED"
            os.close(fd2)
        print(f"  open(symlink, component flags) -> "
              f"{'FOLLOWED' if followed else errno.errorcode.get(err, err)}")
        print(f"  open(symlink, flags|O_DIRECTORY) -> {with_dir} (informational)")
        # A real directory must open and fstat as a directory.
        fd3 = os.open(target, flags)
        try:
            is_dir = stat.S_ISDIR(os.fstat(fd3).st_mode)
        finally:
            os.close(fd3)
        print(f"  open(real dir) fstat S_ISDIR = {is_dir}")
        if followed or not is_dir:
            return _fail("kernel does not enforce O_NOFOLLOW with component flags")
        if _file_open_flags() != flags:
            return _fail("file and directory component flags differ")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_bounded_read():
    from drive_tool.local import LocalAdapter, ReadLimitExceededError
    from drive_tool.storage import FileRef
    base = _mkroot("d038_bounded_")
    try:
        for name, size in (("small.bin", 3), ("exact.bin", 8), ("over.bin", 9)):
            _write(os.path.join(base, name), b"x" * size)
        ad = LocalAdapter("s", base, max_read_bytes=8)
        if ad.read_bytes(FileRef("s", "p/small.bin")) != b"x" * 3:
            return _fail("below-limit read wrong")
        if ad.read_bytes(FileRef("s", "p/exact.bin")) != b"x" * 8:
            return _fail("exact-limit read wrong")
        try:
            ad.read_bytes(FileRef("s", "p/over.bin"))
            return _fail("above-limit read not rejected")
        except ReadLimitExceededError:
            pass
        # growth after fstat: fstat lies '5', real file is 100, limit 10
        _write(os.path.join(base, "grow.bin"), b"y" * 100)
        ad.close()

        class Lying(LocalAdapter):
            read_total = 0

            def _os_fstat(self, fd):
                st = os.fstat(fd)
                if stat.S_ISREG(st.st_mode):
                    return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink,
                                           st.st_uid, st.st_gid, 5, 0, 0, 0))
                return st

            def _os_read(self, fd, length):
                chunk = os.read(fd, length)
                type(self).read_total += len(chunk)
                return chunk

        ad2 = Lying("s", base, max_read_bytes=10)
        Lying.read_total = 0
        try:
            ad2.read_bytes(FileRef("s", "p/grow.bin"))
            return _fail("growth-after-fstat not rejected")
        except ReadLimitExceededError:
            pass
        finally:
            ad2.close()
        if Lying.read_total > 11:
            return _fail(f"growth read {Lying.read_total} > limit+1 (11)")
        print(f"  below/exact/above + growth all bounded (growth read {Lying.read_total} <= 11)")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_root_anchor():
    from drive_tool.local import LocalAdapter
    from drive_tool.storage import FileRef
    base = _mkroot("d038_anchor_")
    try:
        root = os.path.join(base, "root")
        outside = os.path.join(base, "outside")
        os.makedirs(root)
        os.makedirs(outside)
        _write(os.path.join(root, "file.txt"), b"ORIGINAL")
        _write(os.path.join(outside, "file.txt"), b"DECOY")
        ad = LocalAdapter("s", root)
        moved = os.path.join(base, "root_moved")
        os.rename(root, moved)
        os.symlink(outside, root)
        got = ad.read_bytes(FileRef("s", "p/file.txt"))
        names = [m.name for m in ad.list_children(FileRef("s", "root"))]
        ad.close()
        print(f"  read after root swap = {got!r}; listing = {names}")
        if got != b"ORIGINAL" or "file.txt" not in names:
            return _fail("root descriptor not anchored to the original directory")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_dir_symlink_swap():
    from drive_tool.local import LocalAdapter, UnsafePathError
    from drive_tool.storage import FileRef
    base = _mkroot("d038_swap_")
    try:
        root = os.path.join(base, "root")
        outside = os.path.join(base, "outside")
        os.makedirs(os.path.join(root, "sub"))
        os.makedirs(outside)
        _write(os.path.join(root, "sub", "inside.txt"), b"INSIDE")
        _write(os.path.join(outside, "secret.txt"), b"SECRET")
        ad = LocalAdapter("s", root)
        # Replace the directory 'sub' with a symlink to 'outside' (a directory
        # symlink swap), then attempt to traverse through it.
        os.rename(os.path.join(root, "sub"), os.path.join(base, "sub_real"))
        os.symlink(outside, os.path.join(root, "sub"))
        results = []
        for op, fid in (("stat", "p/sub/secret.txt"),
                        ("read", "p/sub/secret.txt"),
                        ("list", "p/sub")):
            try:
                if op == "stat":
                    ad.stat(FileRef("s", fid))
                elif op == "read":
                    ad.read_bytes(FileRef("s", fid))
                else:
                    ad.list_children(FileRef("s", fid))
                results.append((op, "ESCAPED"))
            except UnsafePathError:
                results.append((op, "contained"))
            except Exception as exc:  # noqa: BLE001
                results.append((op, f"other:{type(exc).__name__}"))
        ad.close()
        print(f"  swap results = {results}")
        if any(r[1] != "contained" for r in results):
            return _fail("directory symlink swap not contained")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_fifo():
    from drive_tool.local import LocalAdapter, UnsupportedEntryError
    from drive_tool.storage import FileRef
    base = _mkroot("d038_fifo_")
    try:
        fifo = os.path.join(base, "pipe")
        try:
            os.mkfifo(fifo)
        except OSError as exc:
            print(f"  SKIP: mkfifo unavailable: {exc}")
            return 2
        ad = LocalAdapter("s", base)
        # stat must be UnsupportedEntryError
        try:
            ad.stat(FileRef("s", "p/pipe"))
            ad.close()
            return _fail("stat(FIFO) not rejected")
        except UnsupportedEntryError:
            pass
        # read must be UnsupportedEntryError without blocking (a hang would be
        # killed by the orchestrator timeout; we also bound it here)
        try:
            ad.read_bytes(FileRef("s", "p/pipe"))
            ad.close()
            return _fail("read(FIFO) not rejected")
        except UnsupportedEntryError:
            pass
        names = [m.name for m in ad.list_children(FileRef("s", "root"))]
        ad.close()
        print(f"  FIFO rejected; listing = {names}")
        if "pipe" in names:
            return _fail("FIFO not omitted from listing")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_fd_lifetime():
    from drive_tool.local import LocalAdapter, LocalStorageError
    from drive_tool.storage import FileRef, StorageError
    if not os.path.isdir("/proc/self/fd"):
        print("  SKIP: /proc/self/fd unavailable")
        return 2
    base = _mkroot("d038_fd_")
    try:
        os.makedirs(os.path.join(base, "a", "b"))
        _write(os.path.join(base, "a", "file.txt"), b"hello")
        _write(os.path.join(base, "a", "b", "file.txt"), b"deep")

        def nfd():
            return len(os.listdir("/proc/self/fd"))

        # (a) repeated success/failure ops must not grow the fd table
        ad = LocalAdapter("s", base)
        before = nfd()
        for _ in range(200):
            ad.stat(FileRef("s", "p/a/file.txt"))
            ad.list_children(FileRef("s", "root"))
            ad.read_bytes(FileRef("s", "p/a/file.txt"))
            try:
                ad.read_bytes(FileRef("s", "p/missing"))
            except StorageError:
                pass
        ad.close()
        after = nfd()
        print(f"  repeated ops fd count: before={before} after={after}")
        if after > before + 1:
            return _fail("descriptor leak across repeated operations")

        # (b) parent-close handoff: fail the close of the parent directory fd
        #     after the child is acquired; the child must still be released.
        class Handoff(LocalAdapter):
            def __init__(self, *a, fail_close_name=None, **k):
                self._fail = fail_close_name
                self._paths = {}
                super().__init__(*a, **k)

            def _os_open(self, path, flags, *, dir_fd=None):
                fd = super()._os_open(path, flags, dir_fd=dir_fd)
                self._paths[fd] = path
                return fd

            def _os_close(self, fd):
                name = self._paths.get(fd)
                super()._os_close(fd)
                if name == self._fail:
                    raise OSError(errno.EIO, "injected parent-close failure")

        results = []
        for op, fid in (("read", "p/a/file.txt"), ("list", "p/a/b")):
            had = Handoff("s", base, fail_close_name="a")
            b0 = nfd()
            err = None
            try:
                if op == "read":
                    had.read_bytes(FileRef("s", fid))
                else:
                    had.list_children(FileRef("s", fid))
            except LocalStorageError as exc:
                err = exc
            finally:
                b1 = nfd()
                had.close()
            # close() of the root may add nothing; measure growth across the op
            results.append((op, type(err).__name__ if err else None, b1 - b0))
        print(f"  handoff results (op, raised, fd-delta) = {results}")
        for op, raised, delta in results:
            if raised != "LocalStorageError":
                return _fail(f"{op}: expected LocalStorageError, got {raised}")
            if delta > 1:
                return _fail(f"{op}: child descriptor leaked (fd delta {delta})")
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# New d038 checks
# --------------------------------------------------------------------------

class _CountingScandir:
    """Observational wrapper over a REAL os.scandir iterator.

    Counts how many raw entries the candidate's own scan pulls from the real
    iterator (`yields`) and how many entries it stats (`stats`). It performs no
    fabrication: the wrapped iterator is the real one, and every value is a real
    directory entry. Supports the context-manager protocol the scanner uses.
    """

    def __init__(self, inner):
        self._inner = inner
        self.yields = 0
        self.stats = 0

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._inner.__exit__(exc_type, exc, tb)

    def __iter__(self):
        return self

    def __next__(self):
        entry = next(self._inner)  # may raise StopIteration; not counted
        self.yields += 1
        return _CountingEntry(entry, self)


class _CountingEntry:
    """Proxy for a real DirEntry that counts `.stat()` calls only."""

    def __init__(self, entry, counter):
        self._entry = entry
        self._counter = counter

    def __getattr__(self, name):
        return getattr(self._entry, name)

    def stat(self, *, follow_symlinks=True):
        self._counter.stats += 1
        return self._entry.stat(follow_symlinks=follow_symlinks)


class _ObservationalScanAdapter:
    """Factory mixin producing a LocalAdapter whose scandir is observed."""

    @staticmethod
    def build():
        from drive_tool.local import LocalAdapter

        class _Observed(LocalAdapter):
            counters = None

            def _os_scandir(self, fd):
                # Wrap the REAL iterator; record counts for the caller.
                self.counters = _CountingScandir(super()._os_scandir(fd))
                return self.counters

        return _Observed


def check_strict_b_scanner():
    """REAL: strict-B scan yield/stat counts via an observational scandir seam.

    Wraps the real ``os.scandir`` iterator (no fault injection) and asserts the
    candidate's scan pulls exactly ``B`` raw entries and never probes entry
    ``B+1``, and that at most ``B`` entries are stat'ed. Every entry here is a
    real file on disk.
    """
    from drive_tool.storage import FileRef, ROOT_ID
    Observed = _ObservationalScanAdapter.build()
    base_a = _mkroot("d038_strictb_a_")   # 10 valid regular files
    base_b = _mkroot("d038_strictb_b_")   # 10 valid + 1 writer-temp entry
    try:
        for i in range(10):
            _write(os.path.join(base_a, f"f{i:02d}.txt"), b"x")
        for i in range(10):
            _write(os.path.join(base_b, f"f{i:02d}.txt"), b"x")
        # A name with the reserved writer-temp prefix is yielded (counted) but
        # filtered before any stat.
        _write(os.path.join(base_b, ".drive-tool-tmp-deadbeef"), b"x")

        def scan(base, budget):
            ad = Observed("s", base)
            try:
                batch = ad.scan_children(FileRef("s", ROOT_ID), max_entries=budget)
                return batch, ad.counters
            finally:
                ad.close()

        # (a) B < N: exactly B raw yields, never B+1; all valid -> B stats.
        batch, c = scan(base_a, 4)
        print(f"  [REAL] B=4 over 10 files: yields={c.yields} stats={c.stats} "
              f"inspected={batch.inspected} complete={batch.complete}")
        if c.yields != 4:
            return _fail(f"strict-B violated: pulled {c.yields} raw entries, expected 4")
        if batch.inspected != 4 or batch.complete:
            return _fail("budget-4 scan did not report inspected=4, complete=False")
        if c.stats != 4:
            return _fail(f"expected 4 stats on a valid-only dir, got {c.stats}")

        # (b) B == N: N yields, complete=False (EOF never probed).
        batch, c = scan(base_a, 10)
        print(f"  [REAL] B=10 over 10 files: yields={c.yields} stats={c.stats} "
              f"inspected={batch.inspected} complete={batch.complete}")
        if c.yields != 10 or batch.inspected != 10 or batch.complete:
            return _fail("exact-B scan must yield N, inspected=N, complete=False")
        if c.stats != 10:
            return _fail(f"expected 10 stats, got {c.stats}")

        # (c) B > N: N yields, complete=True (EOF observed within budget).
        batch, c = scan(base_a, 11)
        print(f"  [REAL] B=11 over 10 files: yields={c.yields} stats={c.stats} "
              f"inspected={batch.inspected} complete={batch.complete}")
        if c.yields != 10 or not batch.complete or batch.inspected != 10:
            return _fail("B>N scan must yield N, inspected=N, complete=True")
        if c.stats != 10:
            return _fail(f"expected 10 stats, got {c.stats}")

        # (d) a temp-prefixed entry is yielded (counted) but never stat'ed.
        batch, c = scan(base_b, 20)
        print(f"  [REAL] B=20 over 10 files + 1 temp entry: yields={c.yields} "
              f"stats={c.stats} inspected={batch.inspected} complete={batch.complete}")
        if c.yields != 11 or batch.inspected != 11 or not batch.complete:
            return _fail("temp-entry scan must yield 11 raw entries, complete=True")
        if c.stats != 10:
            return _fail(f"temp-prefixed entry must not be stat'ed (got {c.stats})")
        return 0
    finally:
        shutil.rmtree(base_a, ignore_errors=True)
        shutil.rmtree(base_b, ignore_errors=True)


def check_partial_search():
    """Partial search: retained matches plus honest unknown-EOF/truncation.

    REAL sub-case: a directory holding exactly ``B`` entries scanned with budget
    ``B`` never observes EOF, so the scan reports ``complete=False``; ``find``
    keeps its matches and returns ``truncated=True, reason="max_entries"`` (an
    unknown end-of-directory is reported as truncation, not as "not found").

    SIMULATED sub-case: the scandir seam raises after ``k`` real yields for a
    subdirectory (fault injection, labelled). ``find`` charges the raw work,
    records the directory in ``skipped``, retains the matches it already found,
    and returns ``truncated=True, reason="skipped"``.
    """
    from drive_tool.local import LocalAdapter
    from drive_tool.storage import FileRef, ROOT_ID
    from drive_tool.search import find
    base = _mkroot("d038_partial_")
    try:
        # -- REAL: exactly B entries, budget B -> unknown EOF / truncation ----
        names = ["match_a.txt", "match_b.txt", "zzz1", "zzz2", "zzz3"]  # B = 5
        for n in names:
            _write(os.path.join(base, n), b"x")
        ad = LocalAdapter("s", base)
        try:
            res = find(ad, FileRef("s", ROOT_ID), "match",
                       max_entries=5, max_depth=0)
        finally:
            ad.close()
        got = sorted(m.name for m in res.items)
        print(f"  [REAL] exact-B: items={got} truncated={res.truncated} "
              f"reason={res.reason} inspected={res.inspected}")
        if got != ["match_a.txt", "match_b.txt"]:
            return _fail(f"partial search dropped retained matches: {got}")
        if not res.truncated or res.reason != "max_entries":
            return _fail("exact-B scan must report truncated=True, reason=max_entries")
        if res.inspected != 5:
            return _fail(f"inspected must be 5 raw entries, got {res.inspected}")

        # -- SIMULATED: a subdirectory scan fails mid-iteration ---------------
        base2 = _mkroot("d038_partial_fault_")
        try:
            _write(os.path.join(base2, "match_root.txt"), b"x")
            os.makedirs(os.path.join(base2, "sub"))
            for i in range(5):
                _write(os.path.join(base2, "sub", f"s{i}.txt"), b"x")

            class FaultyScan(LocalAdapter):
                calls = 0
                fault_after = 2

                def _os_scandir(self, fd):
                    type(self).calls += 1
                    real = super()._os_scandir(fd)
                    if type(self).calls == 1:
                        return real  # root scan succeeds (real)

                    class _Fault:
                        def __init__(self, it, after):
                            self._it = it
                            self._after = after
                            self._n = 0

                        def __enter__(self):
                            self._it.__enter__()
                            return self

                        def __exit__(self, *a):
                            return self._it.__exit__(*a)

                        def __iter__(self):
                            return self

                        def __next__(self):
                            if self._n >= self._after:
                                raise OSError(errno.EIO, "injected scan fault")
                            self._n += 1
                            return next(self._it)

                    return _Fault(real, type(self).fault_after)

            ad2 = FaultyScan("s", base2)
            FaultyScan.calls = 0
            try:
                res2 = find(ad2, FileRef("s", ROOT_ID), "match", max_depth=1)
            finally:
                ad2.close()
            got2 = [m.name for m in res2.items]
            print(f"  [SIMULATED] mid-scan fault: items={got2} "
                  f"truncated={res2.truncated} reason={res2.reason} "
                  f"skipped={res2.skipped} inspected={res2.inspected}")
            if "match_root.txt" not in got2:
                return _fail("partial search dropped the pre-fault match")
            if not res2.truncated or res2.reason != "skipped":
                return _fail("a skipped subdirectory must give truncated=True, reason=skipped")
            if "p/sub" not in res2.skipped:
                return _fail(f"failed subdirectory not recorded in skipped: {res2.skipped}")
            if res2.inspected != 2 + 2:
                return _fail(f"raw work not charged exactly (got {res2.inspected}, want 4)")
        finally:
            shutil.rmtree(base2, ignore_errors=True)
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_write_collision():
    """REAL: a no-overwrite write collision preserves the original bytes.

    Writes a file once, then attempts a second no-overwrite write of the same
    name with different bytes. The second write must raise AlreadyExistsError
    and the on-disk bytes must remain the original; no temp file is left behind.
    """
    from drive_tool.local import LocalAdapter
    from drive_tool.local_write import LocalWriter
    from drive_tool.storage import AlreadyExistsError, FileRef, ROOT_ID
    base = _mkroot("d038_collision_")
    try:
        ad = LocalAdapter("s", base)
        wr = LocalWriter(ad)
        try:
            wr.write_bytes(FileRef("s", ROOT_ID), "keep.bin", b"ORIGINAL")
            try:
                wr.write_bytes(FileRef("s", ROOT_ID), "keep.bin", b"REPLACEMENT!")
                return _fail("no-overwrite write of an existing name was allowed")
            except AlreadyExistsError:
                pass
            got = ad.read_bytes(FileRef("s", "p/keep.bin"))
            leftovers = sorted(os.listdir(base))
            print(f"  [REAL] bytes after collision = {got!r}; dir = {leftovers}")
            if got != b"ORIGINAL":
                return _fail(f"original bytes not preserved: {got!r}")
            if leftovers != ["keep.bin"]:
                return _fail(f"stray files left after collision: {leftovers}")
        finally:
            ad.close()
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def check_concurrent_writers():
    """REAL: bounded concurrent no-overwrite writers -> exactly one winner.

    Spawns a fixed, small number of threads that each attempt a no-overwrite
    write of the same name with a distinct full payload. Exactly one must win;
    every loser must raise AlreadyExistsError; the published file must hold the
    winner's exact full payload (no truncation, no mixing); and no temp files
    may remain.
    """
    from drive_tool.local import LocalAdapter
    from drive_tool.local_write import LocalWriter
    from drive_tool.storage import AlreadyExistsError, FileRef, ROOT_ID
    base = _mkroot("d038_concurrent_")
    n_threads = 8
    payload_len = 4096
    try:
        ad = LocalAdapter("s", base)
        wr = LocalWriter(ad, max_write_bytes=payload_len)
        root_ref = FileRef("s", ROOT_ID)
        results = []
        lock = threading.Lock()

        def worker(idx):
            payload = bytes(((idx + 1) & 0xFF,)) * payload_len
            try:
                wr.write_bytes(root_ref, "race.bin", payload)
                outcome = ("won", idx, payload)
            except AlreadyExistsError:
                outcome = ("lost", idx, None)
            except Exception as exc:  # noqa: BLE001
                outcome = ("error", idx, f"{type(exc).__name__}: {exc}")
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n_threads)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            winners = [r for r in results if r[0] == "won"]
            losers = [r for r in results if r[0] == "lost"]
            errors = [r for r in results if r[0] == "error"]
            print(f"  [REAL] {n_threads} writers: winners={len(winners)} "
                  f"losers={len(losers)} errors={len(errors)}")
            if errors:
                return _fail(f"unexpected writer errors: {errors}")
            if len(winners) != 1:
                return _fail(f"expected exactly one winner, got {len(winners)}")
            if len(losers) != n_threads - 1:
                return _fail(f"expected {n_threads - 1} losers, got {len(losers)}")
            _, widx, wpayload = winners[0]
            got = ad.read_bytes(FileRef("s", "p/race.bin"))
            if got != wpayload:
                return _fail(
                    f"published bytes != winner payload "
                    f"(len {len(got)} vs {len(wpayload)})")
            if len(got) != payload_len:
                return _fail(f"published payload truncated: {len(got)} != {payload_len}")
            leftovers = sorted(os.listdir(base))
            print(f"  [REAL] winner=writer{widx} bytes={len(got)} dir={leftovers}")
            if leftovers != ["race.bin"]:
                return _fail(f"stray files left after concurrent writes: {leftovers}")
        finally:
            ad.close()
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


CHECKS = {
    "nofollow": check_nofollow,
    "bounded_read": check_bounded_read,
    "root_anchor": check_root_anchor,
    "dir_symlink_swap": check_dir_symlink_swap,
    "fifo": check_fifo,
    "fd_lifetime": check_fd_lifetime,
    "strict_b_scanner": check_strict_b_scanner,
    "partial_search": check_partial_search,
    "write_collision": check_write_collision,
    "concurrent_writers": check_concurrent_writers,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "list"):
        print("checks:", ", ".join(CHECKS))
        return 0
    name = sys.argv[1]
    src = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    sys.path.insert(0, src)
    if name not in CHECKS:
        print(f"unknown check {name!r}")
        return 1
    print(f"=== kernel check: {name} ===")
    rc = CHECKS[name]()
    label = {0: "PASS", 1: "FAIL", 2: "SKIP"}.get(rc, "?")
    print(f"CHECK {name} RESULT: {label}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

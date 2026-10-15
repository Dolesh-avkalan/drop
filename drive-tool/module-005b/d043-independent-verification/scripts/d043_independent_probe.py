#!/usr/bin/env python3
"""D043 independent adversarial probe for LocalAdapter.read_range (MODULE-005B).

Written from scratch by the independent reviewer (Sarvam) against candidate
121faf848b2f33f80721239fc7716adba7a9ba62. It does NOT import or reuse the
builder's tests. Observational syscall spies delegate to the real seams, so
"observed" calls are real kernel calls; controlled fault injection is labelled
as simulated.

Usage: python3 d043_independent_probe.py /path/to/candidate_root
Exit code 0 = all probes pass.
"""
from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
import threading

CAND = sys.argv[1] if len(sys.argv) > 1 else "/scratch/repos/drive-tool"
sys.path.insert(0, CAND)

import drive_tool.local as L  # noqa: E402
from drive_tool.storage import FileRef  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))


class Spy:
    """Wrap the adapter's OS seams to count/record real syscalls."""

    def __init__(self, a):
        self.a = a
        self.opens = 0
        self.fstats = 0
        self.reads = 0
        self.preads: list[tuple[int, int]] = []  # (length, offset)
        self.stats = 0
        self.scandirs = 0
        self._o, self._f, self._p, self._r = (
            a._os_open, a._os_fstat, a._os_pread, a._os_read,
        )
        a._os_open = self._open
        a._os_fstat = self._fstat
        a._os_pread = self._pread
        a._os_read = self._read

    def _open(self, *args, **kw):
        self.opens += 1
        return self._o(*args, **kw)

    def _fstat(self, *args, **kw):
        self.fstats += 1
        return self._f(*args, **kw)

    def _pread(self, fd, length, offset):
        self.preads.append((length, offset))
        return self._p(fd, length, offset)

    def _read(self, fd, length):
        self.reads += 1
        return self._r(fd, length)

    def io_total(self):
        return self.opens + self.fstats + self.reads + len(self.preads)


def mkroot():
    return tempfile.mkdtemp(prefix="d043probe_")


def write(root, rel, data: bytes):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    return p


def main() -> int:
    # ---------- 1. invalid options: TypeError/ValueError before any syscall ----
    root = mkroot()
    try:
        write(root, "f.bin", b"hello world")
        a = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        spy = Spy(a)
        cases = [
            ("offset bool", dict(offset=True), TypeError),
            ("offset float", dict(offset=1.0), TypeError),
            ("offset str", dict(offset="0"), TypeError),
            ("offset neg", dict(offset=-1), ValueError),
            ("offset > 2**63-1", dict(offset=2**63), ValueError),
            ("length bool", dict(length=True), TypeError),
            ("length float", dict(length=1.0), TypeError),
            ("length 0", dict(length=0), ValueError),
            ("length neg", dict(length=-5), ValueError),
            ("length > cap", dict(length=1_048_577), ValueError),
            ("offset+len overflow", dict(offset=2**63 - 1, length=1), ValueError),
            ("offset max default overflow", dict(offset=2**63 - 1), ValueError),
        ]
        before = spy.io_total()
        all_raised = True
        for label, kw, exc in cases:
            try:
                a.read_range(FileRef("s", "p/f.bin"), **kw)
                all_raised = False
                check(f"invalid-option raises ({label})", False, "no exception")
            except exc:
                pass
            except Exception as e:  # wrong exception type
                all_raised = False
                check(f"invalid-option raises ({label})", False,
                      f"{type(e).__name__} not {exc.__name__}")
        check("invalid options raise correct TypeError/ValueError", all_raised)
        check("invalid options perform zero syscalls", spy.io_total() == before,
              f"io_total before={before} after={spy.io_total()}")
        # boundary allowed: offset+len == 2**63-1 exactly
        try:
            r = a.read_range(FileRef("s", "p/f.bin"), offset=2**63 - 6, length=5)
            check("offset+len==2**63-1 accepted (beyond-EOF => empty)",
                  r.data == b"" and r.eof_observed is True,
                  f"data={r.data!r} eof={r.eof_observed}")
        except Exception as e:
            check("offset+len==2**63-1 accepted (beyond-EOF => empty)", False,
                  f"{type(e).__name__}: {e}")

        # ---------- 2. default window = min(262144, cap) -----------------------
        a2 = L.LocalAdapter("s", root, max_read_bytes=100_000)
        spy2 = Spy(a2)
        big = write(root, "big.bin", b"x" * 250_000)
        r = a2.read_range(FileRef("s", "p/big.bin"))
        check("default window == min(262144, cap) (cap=100000)",
              len(r.data) == 100_000 and spy2.preads[0][0] == 65_536,
              f"len={len(r.data)} first_chunk={spy2.preads[0][0]}")
        write(root, "big3.bin", b"y" * 300_000)
        a3 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        spy3 = Spy(a3)
        r = a3.read_range(FileRef("s", "p/big3.bin"))
        check("default window == 262144 when cap large",
              len(r.data) == 262_144 and spy3.preads[0][0] == 65_536,
              f"len={len(r.data)} first_chunk={spy3.preads[0][0]}")

        # ---------- 3. sparse larger-than-cap, tiny high offset, no prefix ----
        a4 = L.LocalAdapter("s", root, max_read_bytes=16)
        big2 = os.path.join(root, "sparse.bin")
        with open(big2, "wb") as f:
            f.truncate(1_048_576)          # sparse 1 MiB
            f.seek(1_000_000)
            f.write(b"WXYZ")
        spy4 = Spy(a4)
        r = a4.read_range(FileRef("s", "p/sparse.bin"), offset=1_000_000, length=4)
        check("sparse high-offset tiny read returns exact bytes",
              r.data == b"WXYZ" and r.observed_size == 1_048_576,
              f"data={r.data!r} size={r.observed_size}")
        check("first pread starts at requested offset (no prefix read)",
              spy4.preads and spy4.preads[0][1] == 1_000_000,
              f"first_pread={spy4.preads[0] if spy4.preads else None}")
        check("no zero-length pread issued",
              all(l >= 1 for l, _ in spy4.preads), f"preads={spy4.preads}")
        try:
            a4.read_bytes(FileRef("s", "p/sparse.bin"))
            check("read_bytes still denies larger-than-cap file", False, "no raise")
        except L.ReadLimitExceededError:
            check("read_bytes still denies larger-than-cap file", True)

        # ---------- 4. exact window: single pread, eof False, no extra probe --
        a5 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        write(root, "exact.bin", b"0123456789")
        spy5 = Spy(a5)
        r = a5.read_range(FileRef("s", "p/exact.bin"), offset=0, length=10)
        check("exact-window fill: eof_observed False",
              r.eof_observed is False and r.data == b"0123456789",
              f"eof={r.eof_observed}")
        check("exact-window fill: exactly one pread, no lookahead probe",
              len(spy5.preads) == 1, f"preads={spy5.preads}")

        # ---------- 5. short nonempty preads + EINTR (simulated seam) ---------
        a6 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        write(root, "short.bin", b"ABCDEFGHIJ")
        real = a6._os_pread
        seq = {"n": 0}

        def short_then_eintr(fd, length, offset):
            seq["n"] += 1
            if seq["n"] == 1:
                return real(fd, 1, offset)          # short nonempty read
            if seq["n"] == 2:
                raise OSError(errno.EINTR, "interrupted")  # EINTR retry
            return real(fd, length, offset)

        a6._os_pread = short_then_eintr
        r = a6.read_range(FileRef("s", "p/short.bin"), offset=0, length=10)
        a6._os_pread = real
        check("short nonempty reads continue + EINTR retried to fill window",
              r.data == b"ABCDEFGHIJ", f"data={r.data!r} calls={seq['n']}")

        # ---------- 6. metadata initial-only; growth visible via pread -------
        a7 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        gp = write(root, "grow.bin", b"abc")
        real7 = a7._os_pread
        grown = {"done": False}

        def grow_before_read(fd, length, offset):
            if not grown["done"]:
                grown["done"] = True
                with open(gp, "ab") as f:
                    f.write(b"def")                 # grow AFTER the fstat
            return real7(fd, length, offset)

        a7._os_pread = grow_before_read
        r = a7.read_range(FileRef("s", "p/grow.bin"), offset=0, length=6)
        a7._os_pread = real7
        check("observed_size is the initial fstat only (not re-stat)",
              r.observed_size == 3, f"observed_size={r.observed_size}")
        check("growth after fstat is visible via pread",
              r.data == b"abcdef", f"data={r.data!r}")

        # ---------- 7. offset beyond EOF, then growth -----------------------
        a8 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        bp = write(root, "beyond.bin", b"abcd")
        r = a8.read_range(FileRef("s", "p/beyond.bin"), offset=10, length=4)
        check("offset beyond EOF => empty data + eof True",
              r.data == b"" and r.eof_observed is True,
              f"data={r.data!r} eof={r.eof_observed}")
        with open(bp, "ab") as f:
            f.write(b"EFGHIJKLMNOP")
        r2 = a8.read_range(FileRef("s", "p/beyond.bin"), offset=10, length=4)
        check("subsequent growth makes previously-beyond-EOF data available",
              r2.data == b"KLMN" and r2.eof_observed is False,
              f"data={r2.data!r} eof={r2.eof_observed}")

        # ---------- 8. truncation after fstat -------------------------------
        a9 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        tp = write(root, "trunc.bin", b"abcdefghij")
        real9 = a9._os_pread
        trunc = {"done": False}

        def trunc_before_read(fd, length, offset):
            if not trunc["done"]:
                trunc["done"] = True
                os.truncate(tp, 2)                  # shrink after fstat
            return real9(fd, length, offset)

        a9._os_pread = trunc_before_read
        r = a9.read_range(FileRef("s", "p/trunc.bin"), offset=0, length=10)
        a9._os_pread = real9
        check("truncation after fstat: observed_size stale, data honest",
              r.observed_size == 10 and r.data == b"ab",
              f"observed_size={r.observed_size} data={r.data!r}")

        # ---------- 9. unavailable / noncallable pread ----------------------
        a10 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        spy10 = Spy(a10)
        saved = os.pread
        try:
            os.pread = None
            before = spy10.io_total()
            try:
                a10.read_range(FileRef("s", "p/exact.bin"))
                check("os.pread=None => UnsupportedPlatformError", False, "no raise")
            except L.UnsupportedPlatformError:
                check("os.pread=None => UnsupportedPlatformError", True)
            check("missing pread fails before filesystem access",
                  spy10.io_total() == before,
                  f"io before={before} after={spy10.io_total()}")
            # construction + read_bytes still work
            a11 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
            check("construction works without pread", True)
            check("read_bytes works without pread",
                  a11.read_bytes(FileRef("s", "p/exact.bin")) == b"0123456789")
            os.pread = 12345  # non-callable
            try:
                a10.read_range(FileRef("s", "p/exact.bin"))
                check("non-callable os.pread => UnsupportedPlatformError", False)
            except L.UnsupportedPlatformError:
                check("non-callable os.pread => UnsupportedPlatformError", True)
        finally:
            os.pread = saved

        # ---------- 10. precedence: source / closed / malformed-id / root ----
        a12 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        try:
            a12.read_range(FileRef("other", "p/exact.bin"), offset=-1)
            check("source mismatch precedes option validation", False)
        except Exception as e:
            check("source mismatch precedes option validation",
                  isinstance(e, L.SourceMismatchError), type(e).__name__)
        try:
            a12.read_range(FileRef("s", "nope-not-prefixed"), offset=-1)
            check("malformed file_id precedes option validation", False)
        except Exception as e:
            check("malformed file_id precedes option validation",
                  isinstance(e, L.UnsafePathError), type(e).__name__)
        try:
            a12.read_range(FileRef("s", "root"), offset=-1)
            check("root ref => IsDirectoryError (matches read_bytes)", False)
        except Exception as e:
            check("root ref => IsDirectoryError (matches read_bytes)",
                  isinstance(e, L.IsDirectoryError), type(e).__name__)
        a12.close()
        try:
            a12.read_range(FileRef("s", "p/exact.bin"), offset=-1)
            check("closed adapter precedes option validation", False)
        except Exception as e:
            check("closed adapter precedes option validation",
                  isinstance(e, L.AdapterClosedError), type(e).__name__)

        # ---------- 11. FIFO rejected without blocking ----------------------
        a13 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        fifo = os.path.join(root, "pipe")
        os.mkfifo(fifo)
        result = {}

        def do_fifo():
            try:
                a13.read_range(FileRef("s", "p/pipe"))
                result["r"] = "no-raise"
            except Exception as e:
                result["r"] = type(e).__name__

        th = threading.Thread(target=do_fifo, daemon=True)
        th.start()
        th.join(timeout=5)
        check("FIFO rejected without blocking",
              not th.is_alive() and result.get("r") == "UnsupportedEntryError",
              f"alive={th.is_alive()} result={result.get('r')}")

        # ---------- 12. final symlink rejected (no-follow) ------------------
        a14 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        outside = mkroot()
        write(outside, "secret.bin", b"SECRET")
        os.symlink(os.path.join(outside, "secret.bin"), os.path.join(root, "link.bin"))
        try:
            a14.read_range(FileRef("s", "p/link.bin"))
            check("final-component symlink rejected", False, "no raise")
        except Exception as e:
            check("final-component symlink rejected",
                  isinstance(e, L.UnsafePathError), type(e).__name__)

        # ---------- 13. root anchoring under rename+replace ----------------
        root2 = mkroot()
        write(root2, "kept.bin", b"ORIGINAL")
        a15 = L.LocalAdapter("s", root2, max_read_bytes=1_048_576)
        moved = root2 + "-moved"
        os.rename(root2, moved)
        decoy = mkroot()
        write(decoy, "kept.bin", b"DECOY!!!")
        os.symlink(decoy, root2)
        try:
            r = a15.read_range(FileRef("s", "p/kept.bin"))
            check("root rename+outside-symlink stays anchored to original",
                  r.data == b"ORIGINAL", f"data={r.data!r}")
        except Exception as e:
            check("root rename+outside-symlink stays anchored to original",
                  False, f"{type(e).__name__}: {e}")
        finally:
            shutil.rmtree(moved, ignore_errors=True)
            os.unlink(root2)
            shutil.rmtree(decoy, ignore_errors=True)
        a15.close()

        # ---------- 14. concurrent independent offsets ---------------------
        a16 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        write(root, "conc.bin", b"0123456789abcdefghij")
        errs = []

        def worker(off, expect):
            try:
                rr = a16.read_range(FileRef("s", "p/conc.bin"), offset=off, length=4)
                if rr.data != expect:
                    errs.append((off, rr.data, expect))
            except Exception as e:
                errs.append((off, type(e).__name__, expect))

        threads = [threading.Thread(target=worker, args=(i, b"0123456789abcdefghij"[i:i+4]))
                   for i in range(0, 17, 4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        check("concurrent independent offsets return correct windows",
              not errs, f"errs={errs}")

        # ---------- 15. fd stability across repeated ops -------------------
        a17 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        fd_dir = "/proc/self/fd"
        if os.path.isdir(fd_dir):
            base = len(os.listdir(fd_dir))
            for _ in range(60):
                a17.read_range(FileRef("s", "p/conc.bin"), offset=0, length=4)
                try:
                    a17.read_range(FileRef("s", "p/nonexistent.bin"))
                except Exception:
                    pass
            after = len(os.listdir(fd_dir))
            check("no fd growth across 60 success+failure ops",
                  after <= base + 1, f"base={base} after={after}")
        else:
            check("no fd growth (skipped: no /proc/self/fd)", True, "N/A on this kernel")

        # ---------- 16. resolver reuse (no independent path resolver) ------
        a18 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        write(root, "sub/inner.bin", b"INNER")
        used = {}
        orig_trav = a18._traverse_parent_dir
        orig_parse = L._parse_file_id
        orig_flags = L._file_open_flags

        def trav(*args, **kw):
            used["traverse"] = True
            return orig_trav(*args, **kw)

        def parse(*args, **kw):
            used["parse"] = True
            return orig_parse(*args, **kw)

        def flags(*args, **kw):
            used["flags"] = True
            return orig_flags(*args, **kw)

        a18._traverse_parent_dir = trav
        L._parse_file_id = parse
        L._file_open_flags = flags
        try:
            r = a18.read_range(FileRef("s", "p/sub/inner.bin"))
        finally:
            a18._traverse_parent_dir = orig_trav
            L._parse_file_id = orig_parse
            L._file_open_flags = orig_flags
        check("read_range reuses _parse_file_id + _traverse_parent_dir + "
              "_file_open_flags (shared machinery)",
              used.get("parse") and used.get("traverse") and used.get("flags"),
              f"used={used}")
        check("nested read via shared resolver returns correct bytes",
              r.data == b"INNER", f"data={r.data!r}")

        # ---------- 17. error priority: primary read error not masked ------
        a19 = L.LocalAdapter("s", root, max_read_bytes=1_048_576)
        write(root, "prio.bin", b"0123456789")

        def failing_pread(fd, length, offset):
            raise OSError(errno.EIO, "simulated read failure")

        def failing_close(fd):
            raise OSError(errno.EIO, "simulated close failure")

        a19._os_pread = failing_pread
        orig_close = a19._os_close
        a19._os_close = failing_close
        try:
            a19.read_range(FileRef("s", "p/prio.bin"))
            check("primary pread error wins over close failure", False, "no raise")
        except L.LocalStorageError as e:
            check("primary pread error wins over close failure",
                  "reading range" in str(e) and isinstance(e.__cause__, OSError),
                  f"{e!r}")
        except Exception as e:
            check("primary pread error wins over close failure", False, type(e).__name__)
        finally:
            a19._os_pread = L.LocalAdapter._os_pread.__get__(a19)
            a19._os_close = orig_close

    finally:
        shutil.rmtree(root, ignore_errors=True)

    npass = sum(1 for _, ok, _ in RESULTS if ok)
    nfail = len(RESULTS) - npass
    print(f"\n=== D043 independent probe: {npass} passed, {nfail} failed "
          f"of {len(RESULTS)} ===")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

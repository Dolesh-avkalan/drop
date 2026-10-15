#!/usr/bin/env python3
"""Independent POSIX / concurrency / adversarial probes for D058.

Fresh probes (not the builder's). Each prints a raw observation and asserts the
contract expectation. Exits non-zero if any expectation fails.
Run: PYTHONPATH=<candidate tree> python3.1x scripts/indep_probes.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from drive_tool.file_service import LocalFileService, ServiceError
from drive_tool.local import LocalAdapter
from drive_tool.service_policy import AgentPolicy, SourceGrant
from drive_tool.storage import ROOT_ID

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(f"{label}: {detail}")
    print(f"[{status}] {label}{(' -> ' + detail) if detail else ''}")


def digest(tok: str) -> bytes:
    return hashlib.sha256(tok.encode()).digest()


PAD = "0123456789abcdef0123456789abcdef"


def tok(s: str) -> str:
    return (s + PAD)[:40]


def grant(alias, root, ops=frozenset({"list", "find", "read", "save"}),
          r=1048576, w=1048576):
    return SourceGrant(alias=alias, root=str(root), operations=ops,
                       max_read_bytes=r, max_write_bytes=w)


def agent(aid, token, grants):
    return AgentPolicy(agent_id=aid, token_sha256=digest(token), grants=grants)


def fd_count():
    for d in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(d):
            return len(os.listdir(d))
    return None


def err_code(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except ServiceError as exc:
        return exc


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="d058_probe_"))
    try:
        # ---- P1 alias isolation & cross-grant matrix ---------------------
        ra, rb = base / "ra", base / "rb"
        ra.mkdir(); rb.mkdir()
        (ra / "a.txt").write_bytes(b"AAA")
        (rb / "b.txt").write_bytes(b"BBB")
        ta, tb = tok("agent-alpha-token"), tok("agent-bravo-token")
        svc = LocalFileService((
            agent("alpha", ta, (grant("shared", ra),)),
            agent("bravo", tb, (grant("shared", rb),)),
        ))
        check("P1.alpha-sees-own", svc.read(ta, "shared", "p/a.txt").data == b"AAA")
        check("P1.bravo-sees-own", svc.read(tb, "shared", "p/b.txt").data == b"BBB")
        check("P1.alpha-cannot-see-bravo",
              (err_code(svc.read, ta, "shared", "p/b.txt") or 0) and
              err_code(svc.read, ta, "shared", "p/b.txt").code == "not_found")
        check("P1.bravo-cannot-see-alpha",
              err_code(svc.read, tb, "shared", "p/a.txt").code == "not_found")
        # cross token/alias: alpha's token cannot use bravo's alias root even
        # if a same-named alias existed -> here alias exists for both, root must
        # still be alpha's
        svc.save(ta, "shared", "p/written_by_alpha.txt", b"x")
        check("P1.alpha-write-lands-in-alpha-root", (ra / "written_by_alpha.txt").is_file())
        check("P1.bravo-root-untouched", not (rb / "written_by_alpha.txt").exists())
        # unknown alias denied
        check("P1.unknown-alias-denied",
              err_code(svc.read, ta, "nope", "p/a.txt").code == "denied")

        # ---- P2 path traversal / malformed ids -> denied, no FS ----------
        for bad in ("p/../ra/a.txt", "/etc/passwd", "p/a/../../x", "p/./a.txt",
                    "a.txt", "p/", "p//a.txt", "p/a.txt/", "p\\a.txt",
                    "p/a\x00.txt"):
            e = err_code(svc.read, ta, "shared", bad)
            check(f"P2.reject[{bad!r}]", e is not None and e.code == "denied",
                  f"code={getattr(e,'code',None)}")
        # root forbidden for read/save
        check("P2.read-root-invalid", err_code(svc.read, ta, "shared", ROOT_ID).code == "invalid")
        check("P2.save-root-invalid",
              err_code(svc.save, ta, "shared", ROOT_ID, b"x").code == "invalid")

        # ---- P3 wrong file kinds -----------------------------------------
        (ra / "sub").mkdir()
        e = err_code(svc.read, ta, "shared", "p/sub")
        check("P3.read-directory-invalid", e is not None and e.code == "invalid", f"code={getattr(e,'code',None)}")
        e = err_code(svc.list, ta, "shared", "p/a.txt")
        check("P3.list-file-invalid", e is not None and e.code == "invalid", f"code={getattr(e,'code',None)}")

        # ---- P4 symlink read refusal + no escape -------------------------
        outside = base / "outside"; outside.mkdir()
        (outside / "secret.txt").write_bytes(b"SECRET")
        os.symlink(outside / "secret.txt", ra / "link.txt")
        e = err_code(svc.read, ta, "shared", "p/link.txt")
        check("P4.read-symlink-denied", e is not None and e.code == "denied", f"code={getattr(e,'code',None)}")
        os.symlink(outside, ra / "linkdir")
        e = err_code(svc.save, ta, "shared", "p/linkdir/pwn.txt", b"bad", create_parents=True, overwrite=True)
        check("P4.save-through-symlink-dir-denied", e is not None and e.code == "denied", f"code={getattr(e,'code',None)}")
        check("P4.outside-untouched", list(outside.iterdir()) == [outside / "secret.txt"] or
              sorted(p.name for p in outside.iterdir()) == ["secret.txt"])

        # ---- P5 caps boundary exact --------------------------------------
        rc_root = base / "caps"; rc_root.mkdir()
        (rc_root / "f.bin").write_bytes(b"Z" * 3000)
        tc = tok("caps-token")
        svc2 = LocalFileService((agent("cap", tc, (grant("c", rc_root, r=1024, w=512),)),))
        check("P5.read-at-cap-ok", len(svc2.read(tc, "c", "p/f.bin", length=1024).data) == 1024)
        e = err_code(svc2.read, tc, "c", "p/f.bin", length=1025)
        check("P5.read-over-cap-too_large", e is not None and e.code == "too_large", f"code={getattr(e,'code',None)}")
        e = err_code(svc2.save, tc, "c", "p/new.bin", b"x" * 513)
        check("P5.write-over-cap-too_large", e is not None and e.code == "too_large", f"code={getattr(e,'code',None)}")
        check("P5.write-at-cap-ok", svc2.save(tc, "c", "p/new.bin", b"x" * 512)["bytes_written"] == 512)

        # ---- P6 EOF semantics raw ----------------------------------------
        eof_root = base / "eof"; eof_root.mkdir()
        (eof_root / "g.bin").write_bytes(b"0123456789")
        te = tok("eof-token")
        svc3 = LocalFileService((agent("e", te, (grant("e", eof_root),)),))
        exact = svc3.read(te, "e", "p/g.bin", offset=0, length=10)
        past = svc3.read(te, "e", "p/g.bin", offset=10, length=10)
        check("P6.exact-fill-eof_observed-False", exact.data == b"0123456789" and exact.eof_observed is False)
        check("P6.past-end-eof_observed-True", past.data == b"" and past.eof_observed is True)
        mid = svc3.read(te, "e", "p/g.bin", offset=5, length=10)
        check("P6.partial-tail", mid.data == b"56789" and mid.eof_observed is True)

        # ---- P7 concurrent no-overwrite publish (atomic link) ------------
        c_root = base / "conc"; c_root.mkdir()
        tq = tok("conc-token")
        svc4 = LocalFileService((agent("q", tq, (grant("q", c_root),)),))
        outcomes = []
        lock = threading.Lock()

        def racer(i):
            try:
                svc4.save(tq, "q", "p/race.txt", f"payload-{i}".encode(), overwrite=False)
                r = "ok"
            except ServiceError as exc:
                r = exc.code
            with lock:
                outcomes.append(r)
        threads = [threading.Thread(target=racer, args=(i,)) for i in range(8)]
        for t in threads: t.start()
        for t in threads: t.join(5)
        check("P7.exactly-one-winner", outcomes.count("ok") == 1, f"outcomes={sorted(outcomes)}")
        check("P7.rest-exists", outcomes.count("exists") == 7, f"outcomes={sorted(outcomes)}")

        # ---- P8 fd stability over many ops -------------------------------
        before = fd_count()
        for _ in range(100):
            svc4.read(tq, "q", "p/race.txt")
            svc4.list(tq, "q")
        after = fd_count()
        check("P8.fd-stable", before is not None and before == after, f"before={before} after={after}")

        # ---- P9 concurrent blocked op + close(timeout) -------------------
        d_root = base / "drain"; d_root.mkdir()
        (d_root / "d.txt").write_bytes(b"live")
        td = tok("drain-token")
        svc5 = LocalFileService((agent("d", td, (grant("d", d_root),)),))
        binding = svc5._bindings[("d", "d")]
        orig = binding.adapter.read_range
        entered, release = threading.Event(), threading.Event()

        def block(ref, *, offset=0, length=None):
            entered.set(); release.wait(5); return orig(ref, offset=offset, length=length)
        binding.adapter.read_range = block
        got = []
        th = threading.Thread(target=lambda: got.append(svc5.read(td, "d", "p/d.txt").data))
        th.start(); entered.wait(2)
        c1 = svc5.close(timeout=0.03)
        check("P9.timeout-close-False", c1 is False)
        check("P9.fd-still-open", binding.closed is False)
        e = err_code(svc5.list, td, "d")
        check("P9.post-drain-unavailable", e is not None and e.code == "unavailable" and e.retry_safe is True,
              f"code={getattr(e,'code',None)}")
        release.set(); th.join(2)
        check("P9.inflight-read-succeeded", got == [b"live"], f"got={got}")
        check("P9.later-close-drains", svc5.close(timeout=2) is True and binding.closed is True)

        # ---- P10 concurrent closes single-close --------------------------
        e_root = base / "cc"; e_root.mkdir()
        (e_root / "c.txt").write_bytes(b"c")
        tcc = tok("cc-token")
        svc6 = LocalFileService((agent("cc", tcc, (grant("cc", e_root),)),))
        b6 = svc6._bindings[("cc", "cc")]
        orig_close = b6.adapter.close
        calls = {"n": 0}
        lk = threading.Lock()

        def counted_close():
            with lk:
                calls["n"] += 1
            orig_close()
        b6.adapter.close = counted_close
        res = []
        cts = [threading.Thread(target=lambda: res.append(svc6.close(timeout=3))) for _ in range(6)]
        for c in cts: c.start()
        for c in cts: c.join(3)
        check("P10.all-close-True", res == [True] * 6, f"res={res}")
        check("P10.single-close", calls["n"] == 1, f"calls={calls['n']}")

        # ---- P11 redaction raw -------------------------------------------
        r_root = base / "red"; r_root.mkdir()
        tr = tok("redaction-token")
        svc7 = LocalFileService((agent("r", tr, (grant("r", r_root),)),))
        b7 = svc7._bindings[("r", "r")]

        def boom(ref, *, offset=0, length=None):
            raise OSError(5, f"io error at {r_root} secret={tr}")
        b7.adapter.read_range = boom
        e = err_code(svc7.read, tr, "r", "p/doc.txt")
        rendered = f"{e} {e!r} {e.args}"
        check("P11.code-unavailable", e.code == "unavailable", f"code={e.code}")
        check("P11.no-root-leak", str(r_root) not in rendered)
        check("P11.no-token-leak", tr not in rendered)
        check("P11.cause-none", e.__cause__ is None)

        # ---- P12 observations (non-blocking, documented deviations) ------
        obs_root = base / "obs"; obs_root.mkdir()
        (obs_root / "one.txt").write_bytes(b"1")
        to = tok("obs-token")
        svc8 = LocalFileService((agent("o", to, (grant("o", obs_root),)),))
        e_ws = err_code(svc8.find, to, "o", name_contains="   ")
        print(f"[OBS] find(whitespace-only) -> {getattr(e_ws,'code',None)}")
        e_off = err_code(svc8.list, to, "o", offset=10_000)
        print(f"[OBS] list(offset beyond total) -> {getattr(e_off,'code',None)}")
        # offset exactly equal to total: ListingService allows offset==total -> empty page
        try:
            page = svc8.list(to, "o", offset=1)
            print(f"[OBS] list(offset==total) -> items={len(page['items'])} next={page['next_offset']}")
        except ServiceError as exc:
            print(f"[OBS] list(offset==total) -> {exc.code}")

        svc8.close(timeout=1); svc7.close(timeout=1)
        return 1 if FAILURES else 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    print(f"\nTOTAL FAILURES: {len(FAILURES)}")
    for f in FAILURES:
        print("  -", f)
    sys.exit(rc)

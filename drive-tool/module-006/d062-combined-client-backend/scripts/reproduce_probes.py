#!/usr/bin/env python3
"""D058 independent backend audit - adversarial / POSIX / concurrency probes.

Runs P1-P11 against synthetic temp roots using the published candidate's
accepted LocalFileService (which opens LocalAdapter per grant). Prints PASS/FAIL
per check and exits non-zero if any check FAILs. Also prints two non-blocking
INFO lines for find(name_contains='   ') and list(offset=10000).

This harness is a reproduction run only: it never edits the candidate source.
"""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import tempfile
import threading
import traceback
from unittest import mock

from drive_tool.file_service import LocalFileService, ServiceError
from drive_tool.local import LocalAdapter
from drive_tool.service_policy import AgentPolicy, SourceGrant
from drive_tool.storage import ROOT_ID

_TOKEN_PAD = "0123456789abcdef0123456789abcdef"


def _pad_token(base: str) -> str:
    return (base + _TOKEN_PAD)[:40]


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _make_grant(alias, root, *, operations=frozenset({"list", "find", "read", "save"}),
                max_read_bytes=1048576, max_write_bytes=1048576):
    return SourceGrant(
        alias=alias,
        root=str(root),
        operations=operations,
        max_read_bytes=max_read_bytes,
        max_write_bytes=max_write_bytes,
    )


def _make_agent(agent_id, token, grants):
    return AgentPolicy(agent_id=agent_id, token_sha256=_token_digest(token), grants=grants)


def _count_open_fds():
    for fd_dir in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(fd_dir):
            try:
                return len(os.listdir(fd_dir))
            except OSError:
                return None
    return None


class Probe:
    """Collects PASS/FAIL results and prints them."""

    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, bool(ok), detail))
        status = "PASS" if ok else "FAIL"
        line = f"[{status}] {name}"
        if detail:
            line += f"  -- {detail}"
        print(line, flush=True)
        return bool(ok)

    def info(self, name: str, detail: str) -> None:
        print(f"[INFO] {name}  -- {detail}", flush=True)

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [r for r in self.results if not r[1]]


def _err_code(fn, *args, **kwargs):
    """Run fn; return ('ok', result) or ('code', code)."""
    try:
        return ("ok", fn(*args, **kwargs))
    except ServiceError as exc:
        return ("code", exc.code)


def probe_P1(tmp: Path, p: Probe) -> None:
    root_a = tmp / "root_a"
    root_b = tmp / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    (root_a / "only_a.txt").write_bytes(b"alpha-content")
    (root_b / "only_b.txt").write_bytes(b"bravo-content")

    token_a = _pad_token("token-agent-alpha-001")
    token_b = _pad_token("token-agent-bravo-002")
    svc = LocalFileService((
        _make_agent("alpha", token_a, (_make_grant("shared", root_a),)),
        _make_agent("bravo", token_b, (_make_grant("shared", root_b),)),
    ))
    try:
        ra = svc.read(token_a, "shared", "p/only_a.txt")
        rb = svc.read(token_b, "shared", "p/only_b.txt")
        p.check("P1.a each reads its own file",
                ra.data == b"alpha-content" and rb.data == b"bravo-content",
                f"a={ra.data!r} b={rb.data!r}")
        cross_a = _err_code(svc.read, token_a, "shared", "p/only_b.txt")
        cross_b = _err_code(svc.read, token_b, "shared", "p/only_a.txt")
        p.check("P1.b each cannot read the other's file (not_found)",
                cross_a == ("code", "not_found") and cross_b == ("code", "not_found"),
                f"a->b={cross_a} b->a={cross_b}")
        svc.save(token_a, "shared", "p/written.txt", b"from-alpha")
        p.check("P1.c write by A lands in A's root only",
                (root_a / "written.txt").is_file() and not (root_b / "written.txt").exists(),
                f"a_exists={(root_a / 'written.txt').is_file()} b_exists={(root_b / 'written.txt').exists()}")
    finally:
        svc.close()


def probe_P2(tmp: Path, p: Probe) -> None:
    root = tmp / "p2_root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"x")
    token = _pad_token("p2-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("src", root),)),))
    malformed = ["p/../x", "/etc/passwd", "p/a/../../x", "p/./a", "a.txt",
                 "p/", "p//a", "p/a/", "p\\a", "p/a\x00"]
    try:
        for fid in malformed:
            res = _err_code(svc.read, token, "src", fid)
            p.check(f"P2.read {fid!r} -> denied", res == ("code", "denied"), f"got {res}")
        for fid in malformed:
            res = _err_code(svc.save, token, "src", fid, b"d")
            p.check(f"P2.save {fid!r} -> denied", res == ("code", "denied"), f"got {res}")
        rr = _err_code(svc.read, token, "src", ROOT_ID)
        sr = _err_code(svc.save, token, "src", ROOT_ID, b"d")
        p.check("P2.read 'root' -> invalid", rr == ("code", "invalid"), f"got {rr}")
        p.check("P2.save 'root' -> invalid", sr == ("code", "invalid"), f"got {sr}")
    finally:
        svc.close()


def probe_P3(tmp: Path, p: Probe) -> None:
    root = tmp / "p3_root"
    root.mkdir()
    (root / "sub").mkdir()
    (root / "file.txt").write_bytes(b"data")
    token = _pad_token("p3-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("src", root),)),))
    try:
        r = _err_code(svc.read, token, "src", "p/sub")
        p.check("P3.read of a directory -> invalid", r == ("code", "invalid"), f"got {r}")
        l = _err_code(svc.list, token, "src", "p/file.txt")
        p.check("P3.list of a file -> invalid", l == ("code", "invalid"), f"got {l}")
    finally:
        svc.close()


def probe_P4(tmp: Path, p: Probe) -> None:
    root = tmp / "p4_root"
    root.mkdir()
    (root / "real.txt").write_bytes(b"real")
    os.symlink(root / "real.txt", root / "link.txt")
    outside = tmp / "p4_outside"
    outside.mkdir()
    os.symlink(outside, root / "escape_dir")
    token = _pad_token("p4-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("work", root),)),))
    try:
        r = _err_code(svc.read, token, "work", "p/link.txt")
        p.check("P4.read of a symlink -> denied", r == ("code", "denied"), f"got {r}")
        s = _err_code(svc.save, token, "work", "p/escape_dir/sub/pwned.txt", b"malicious")
        p.check("P4.save through symlinked parent -> denied", s == ("code", "denied"), f"got {s}")
        p.check("P4.outside dir untouched", list(outside.iterdir()) == [],
                f"entries={list(outside.iterdir())}")
    finally:
        svc.close()


def probe_P5(tmp: Path, p: Probe) -> None:
    root = tmp / "p5_root"
    root.mkdir()
    (root / "f.bin").write_bytes(b"A" * 100)
    token = _pad_token("p5-token")
    grant = _make_grant("src", root, max_read_bytes=100, max_write_bytes=100)
    svc = LocalFileService((_make_agent("agent", token, (grant,)),))
    try:
        at_cap = svc.read(token, "src", "p/f.bin", offset=0, length=100)
        p.check("P5.read at cap ok", at_cap.data == b"A" * 100, f"len={len(at_cap.data)}")
        over_read = _err_code(svc.read, token, "src", "p/f.bin", offset=0, length=101)
        p.check("P5.read cap+1 -> too_large", over_read == ("code", "too_large"), f"got {over_read}")
        over_write = _err_code(svc.save, token, "src", "p/over.bin", b"B" * 101)
        p.check("P5.save cap+1 -> too_large", over_write == ("code", "too_large"), f"got {over_write}")
        at_write = _err_code(svc.save, token, "src", "p/at.bin", b"B" * 100)
        p.check("P5.save at cap ok", at_write[0] == "ok", f"got {at_write}")
    finally:
        svc.close()


def probe_P6(tmp: Path, p: Probe) -> None:
    root = tmp / "p6_root"
    root.mkdir()
    (root / "e.bin").write_bytes(b"0123456789")  # 10 bytes
    token = _pad_token("p6-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("store", root),)),))
    try:
        exact = svc.read(token, "store", "p/e.bin", offset=0, length=10)
        p.check("P6.exact-fill window eof_observed False",
                exact.data == b"0123456789" and exact.eof_observed is False,
                f"data={exact.data!r} eof={exact.eof_observed}")
        at_end = svc.read(token, "store", "p/e.bin", offset=10, length=5)
        p.check("P6.read at end data b'' eof True",
                at_end.data == b"" and at_end.eof_observed is True,
                f"data={at_end.data!r} eof={at_end.eof_observed}")
        past_end = svc.read(token, "store", "p/e.bin", offset=100, length=5)
        p.check("P6.read past end data b'' eof True",
                past_end.data == b"" and past_end.eof_observed is True,
                f"data={past_end.data!r} eof={past_end.eof_observed}")
        partial = svc.read(token, "store", "p/e.bin", offset=6, length=100)
        p.check("P6.partial tail data 4 bytes eof True",
                partial.data == b"6789" and partial.eof_observed is True,
                f"data={partial.data!r} eof={partial.eof_observed}")
    finally:
        svc.close()


def probe_P7(tmp: Path, p: Probe) -> None:
    root = tmp / "p7_root"
    root.mkdir()
    token = _pad_token("p7-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("work", root),)),))
    try:
        n = 8
        barrier = threading.Barrier(n)
        outcomes: list[str] = []
        lock = threading.Lock()

        def worker():
            barrier.wait(timeout=10.0)
            try:
                svc.save(token, "work", "p/new.txt", b"payload", overwrite=False)
                with lock:
                    outcomes.append("ok")
            except ServiceError as exc:
                with lock:
                    outcomes.append(exc.code)
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    outcomes.append(f"exc:{type(exc).__name__}")

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        oks = outcomes.count("ok")
        exists = outcomes.count("exists")
        p.check("P7.8 concurrent saves -> exactly 1 ok",
                oks == 1, f"ok={oks} exists={exists} outcomes={outcomes}")
        p.check("P7.8 concurrent saves -> 7 exists",
                exists == 7, f"ok={oks} exists={exists} outcomes={outcomes}")
    finally:
        svc.close()


def probe_P8(tmp: Path, p: Probe) -> None:
    root = tmp / "p8_root"
    root.mkdir()
    (root / "f.txt").write_bytes(b"ok")
    token = _pad_token("p8-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("g", root),)),))
    try:
        before = _count_open_fds()
        for _ in range(100):
            svc.read(token, "g", "p/f.txt")
            svc.list(token, "g", ROOT_ID)
        after = _count_open_fds()
        p.check("P8.fd count stable before/after 100 read+list ops",
                before is not None and before == after, f"before={before} after={after}")
    finally:
        svc.close()


def probe_P9(tmp: Path, p: Probe) -> None:
    root = tmp / "p9_root"
    root.mkdir()
    (root / "data.txt").write_bytes(b"live-descriptor-data")
    token = _pad_token("p9-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("work", root),)),))
    binding = svc._bindings[("agent", "work")]
    orig_read_range = binding.adapter.read_range
    entered = threading.Event()
    release = threading.Event()

    def blocking_read_range(ref, *, offset=0, length=None):
        entered.set()
        release.wait(timeout=5.0)
        return orig_read_range(ref, offset=offset, length=length)

    read_outcomes: list[object] = []

    def worker():
        try:
            read_outcomes.append(svc.read(token, "work", "p/data.txt").data)
        except BaseException as exc:  # noqa: BLE001
            read_outcomes.append(exc)

    try:
        with mock.patch.object(binding.adapter, "read_range", side_effect=blocking_read_range):
            t = threading.Thread(target=worker)
            t.start()
            p.check("P9.blocked read entered", entered.wait(timeout=2.0))
            closed = svc.close(timeout=0.03)
            p.check("P9.close(timeout=0.03) -> False", closed is False, f"got {closed}")
            p.check("P9.binding still open", binding.closed is False, f"closed={binding.closed}")
            lease = None
            try:
                svc.list(token, "work")
                lease = ("ok", None)
            except ServiceError as exc:
                lease = ("code", exc.code, exc.retry_safe)
            p.check("P9.new lease -> unavailable retry_safe True",
                    lease == ("code", "unavailable", True), f"got {lease}")
            release.set()
            t.join(timeout=5.0)
            p.check("P9.read succeeds after unblock",
                    read_outcomes == [b"live-descriptor-data"], f"outcomes={read_outcomes}")
            later = svc.close(timeout=2.0)
            p.check("P9.later close -> True", later is True, f"got {later}")
    finally:
        if not svc._closed:
            try:
                release.set()
                svc.close(timeout=2.0)
            except Exception:
                pass


def probe_P10(tmp: Path, p: Probe) -> None:
    root = tmp / "p10_root"
    root.mkdir()
    (root / "item.txt").write_bytes(b"content")
    token = _pad_token("p10-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("work", root),)),))
    binding = svc._bindings[("agent", "work")]
    orig_read_range = binding.adapter.read_range
    orig_close = binding.adapter.close
    entered = threading.Event()
    unblock = threading.Event()
    close_calls = 0
    close_lock = threading.Lock()

    def slow_read(ref, *, offset=0, length=None):
        entered.set()
        unblock.wait(timeout=5.0)
        return orig_read_range(ref, offset=offset, length=length)

    def tracked_close():
        nonlocal close_calls
        with close_lock:
            close_calls += 1
        orig_close()

    try:
        with (
            mock.patch.object(binding.adapter, "read_range", side_effect=slow_read),
            mock.patch.object(binding.adapter, "close", side_effect=tracked_close),
        ):
            op = threading.Thread(target=lambda: _err_code(svc.read, token, "work", "p/item.txt"))
            op.start()
            p.check("P10.blocked read entered", entered.wait(timeout=2.0))
            results: list[bool] = []
            threads = [threading.Thread(target=lambda: results.append(svc.close(timeout=3.0)))
                       for _ in range(6)]
            for t in threads:
                t.start()
            unblock.set()
            op.join(timeout=5.0)
            for t in threads:
                t.join(timeout=5.0)
            p.check("P10.6 concurrent close() -> all True",
                    results == [True] * 6, f"results={results}")
            p.check("P10.adapter close called exactly once",
                    close_calls == 1, f"close_calls={close_calls}")
    finally:
        if not svc._closed:
            try:
                unblock.set()
                svc.close(timeout=2.0)
            except Exception:
                pass


def probe_P11(tmp: Path, p: Probe) -> None:
    root = tmp / "p11_root"
    root.mkdir()
    token = _pad_token("p11-secret-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("work", root),)),))
    binding = svc._bindings[("agent", "work")]
    try:
        with mock.patch.object(
            binding.adapter,
            "read_range",
            side_effect=OSError(errno.EIO, f"disk failure at {root} for token {token}"),
        ):
            code = None
            err = None
            try:
                svc.read(token, "work", "p/doc.txt")
            except ServiceError as exc:
                err = exc
                code = exc.code
        p.check("P11.OSError from read_range -> unavailable", code == "unavailable", f"got {code}")
        if err is not None:
            rendered = f"{err} {err!r} " + " ".join(str(a) for a in err.args)
            p.check("P11.no root in rendered error", str(root) not in rendered,
                    f"rendered={rendered!r}")
            p.check("P11.no token in rendered error", token not in rendered,
                    f"rendered={rendered!r}")
            p.check("P11.__cause__ None", err.__cause__ is None, f"cause={err.__cause__!r}")
        else:
            p.check("P11.error captured", False, "no ServiceError raised")
    finally:
        svc.close()


def probe_info(tmp: Path, p: Probe) -> None:
    root = tmp / "info_root"
    root.mkdir()
    (root / "a.txt").write_bytes(b"x")
    token = _pad_token("info-token")
    svc = LocalFileService((_make_agent("agent", token, (_make_grant("src", root),)),))
    try:
        f = _err_code(svc.find, token, "src", ROOT_ID, name_contains="   ")
        p.info("find(name_contains='   ')", f"result={f!r}")
        l = _err_code(svc.list, token, "src", ROOT_ID, offset=10000)
        p.info("list(offset=10000)", f"result={l!r}")
    finally:
        svc.close()


def main() -> int:
    p = Probe()
    with tempfile.TemporaryDirectory(prefix="d058_probes_") as td:
        tmp = Path(td)
        for fn in (probe_P1, probe_P2, probe_P3, probe_P4, probe_P5, probe_P6,
                   probe_P7, probe_P8, probe_P9, probe_P10, probe_P11, probe_info):
            try:
                fn(tmp, p)
            except BaseException:  # noqa: BLE001
                p.check(f"{fn.__name__} (unexpected harness error)", False,
                        "traceback:\n" + traceback.format_exc())
    print("", flush=True)
    total = len(p.results)
    failed = p.failed
    print(f"SUMMARY: {total - len(failed)}/{total} checks PASS, {len(failed)} FAIL", flush=True)
    if failed:
        for name, _ok, detail in failed:
            print(f"  FAILED: {name}  -- {detail}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

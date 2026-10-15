#!/usr/bin/env python3.12
"""D054 raw probe: actual filesystem permission / lease / drain / save-uncertainty
behaviour of the assembled LocalFileService, independent of the unittest suite.

Prints raw observations only (no assertions); the report records the readings.
"""
import errno
import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path

from drive_tool.file_service import LocalFileService, ServiceError
from drive_tool.local import UnsafePathError
from drive_tool.service_policy import AgentPolicy, SourceGrant

OPS = frozenset({"list", "find", "read", "save"})


def agent(agent_id, token, grants):
    return AgentPolicy(
        agent_id=agent_id,
        token_sha256=hashlib.sha256(token.encode()).digest(),
        grants=grants,
    )


def grant(alias, root, ops=OPS, rcap=1_048_576, wcap=1_048_576):
    return SourceGrant(alias=alias, root=str(root), operations=ops,
                       max_read_bytes=rcap, max_write_bytes=wcap)


def fds():
    return len(os.listdir("/proc/self/fd"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="d054_probe_"))
    print("tmp:", tmp)
    print("uid:", os.getuid())

    # ---- 1. real permission denial is reported as a skipped subtree ----
    root = tmp / "perm"; root.mkdir()
    (root / "open.txt").write_bytes(b"visible")
    locked = root / "locked"; locked.mkdir()
    (locked / "secret.txt").write_bytes(b"secret")
    os.chmod(locked, 0o000)
    svc = LocalFileService((agent("a", "tok" + "0" * 40, (grant("s", root),)),))
    tok = "tok" + "0" * 40
    try:
        f = svc.find(tok, "s", "root", name_contains="txt", limit=20, max_entries=2000, max_depth=4)
        print("[perm] find items:", [i["ref"]["file_id"] for i in f["items"]])
        print("[perm] find skipped:", f["skipped"], "truncated:", f["truncated"], "reason:", f["reason"])
    finally:
        svc.close()
    os.chmod(locked, 0o755)

    # ---- 2. two agents, identical alias, different roots stay isolated ----
    ra = tmp / "ra"; rb = tmp / "rb"; ra.mkdir(); rb.mkdir()
    (ra / "a.txt").write_bytes(b"AAA")
    (rb / "b.txt").write_bytes(b"BBB")
    ta, tb = "ta" + "1" * 40, "tb" + "2" * 40
    svc2 = LocalFileService((
        agent("alpha", ta, (grant("shared", ra),)),
        agent("bravo", tb, (grant("shared", rb),)),
    ))
    try:
        print("[alias] alpha reads p/a.txt:", svc2.read(ta, "shared", "p/a.txt").data)
        try:
            svc2.read(ta, "shared", "p/b.txt")
            print("[alias] alpha read b.txt: UNEXPECTED SUCCESS")
        except ServiceError as e:
            print("[alias] alpha reads p/b.txt ->", e.code)
    finally:
        svc2.close()

    # ---- 3. lease / drain: blocked op, timed-out close, fd stays open ----
    rd = tmp / "drain"; rd.mkdir()
    (rd / "d.txt").write_bytes(b"payload")
    td = "td" + "3" * 40
    svc3 = LocalFileService((agent("a", td, (grant("w", rd),)),))
    binding = svc3._bindings[("a", "w")]
    orig = binding.adapter.read_range
    entered = threading.Event(); release = threading.Event()

    def slow(ref, *, offset=0, length=None):
        entered.set(); release.wait(5.0)
        return orig(ref, offset=offset, length=length)

    import unittest.mock as mock
    out = {}
    with mock.patch.object(binding.adapter, "read_range", side_effect=slow):
        t = threading.Thread(target=lambda: out.setdefault("data", svc3.read(td, "w", "p/d.txt").data))
        t.start()
        entered.wait(2.0)
        print("[drain] timed-out close ->", svc3.close(timeout=0.03), "binding.closed:", binding.closed)
        try:
            svc3.list(td, "w")
            print("[drain] post-drain list: UNEXPECTED SUCCESS")
        except ServiceError as e:
            print("[drain] post-drain list ->", e.code, "retry_safe:", e.retry_safe)
        release.set(); t.join(2.0)
        print("[drain] in-flight read data:", out.get("data"))
        print("[drain] draining close ->", svc3.close(timeout=2.0), "binding.closed:", binding.closed)

    # ---- 4. fd stability across open -> drain ----
    f0 = fds()
    rg = tmp / "fdg"; rg.mkdir(); (rg / "g.txt").write_bytes(b"g")
    tg = "tg" + "4" * 40
    svc4 = LocalFileService((agent("a", tg, (grant("g", rg),)),))
    f1 = fds()
    svc4.read(tg, "g", "p/g.txt"); svc4.list(tg, "g")
    svc4.close(timeout=2.0)
    f2 = fds()
    print(f"[fd] before={f0} after-open={f1} after-drain={f2} (open adds adapters, drain restores)")

    # ---- 5. save uncertainty with real published bytes ----
    rs = tmp / "save"; rs.mkdir()
    ts = "ts" + "5" * 40
    svc5 = LocalFileService((agent("a", ts, (grant("w", rs),)),))
    b5 = svc5._bindings[("a", "w")]
    origw = b5.writer.write_bytes

    def pub_then_fail(parent, name, data, *, overwrite=False):
        origw(parent, name, data, overwrite=overwrite)
        raise OSError(errno.EIO, "simulated post-publish fsync EIO")

    err = None
    with mock.patch.object(b5.writer, "write_bytes", side_effect=pub_then_fail):
        try:
            svc5.save(ts, "w", "p/out.bin", b"published-bytes")
            print("[save] UNEXPECTED SUCCESS")
        except ServiceError as e:
            err = e
            print("[save] code:", e.code, "uncertain:", e.outcome_uncertain, "retry_safe:", e.retry_safe)
    print("[save] bytes actually on disk:", (rs / "out.bin").read_bytes())
    print("[save] rendered error:", str(err), "| repr:", repr(err), "| cause:", err.__cause__)
    svc5.close(timeout=2.0)

    print("PROBE DONE")


if __name__ == "__main__":
    main()

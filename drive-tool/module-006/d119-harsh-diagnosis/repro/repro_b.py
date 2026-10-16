#!/usr/bin/env python3
"""D119 repro B: instrumented concurrent overwrite+read, with rich exception
diagnostics, an optional drain-aware lease limiter (D101 pattern), and an
optional non-atomic-publish product mutant.

Modes:
  old        : 2 writers + 3 readers, tight reconnect, NO lease  (first-D110 shape)
  new        : same, WITH drain-aware lease (K=5, hold=55 ms)
  new_mutant : same as new, but the product's publish is made non-atomic

Reads product code; changes no product file on disk (mutant is a runtime patch).
"""
import os, sys, time, json, tempfile, shutil, hashlib, threading, signal

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
sys.path.insert(0, REPO)
from drive_tool.http_adapter import DriveHTTPAdapter
from drive_tool.service_client import DriveClient, DriveClientError
from drive_tool.service_policy import AgentPolicy, SourceGrant
from drive_tool.local_write import LocalWriter

TOKEN = "d119-" + "A" * 40
PAYLEN = 4096
PAYLOADS = [bytes([i]) * PAYLEN for i in range(1, 9)]
PAYSHAS = {hashlib.sha256(p).hexdigest() for p in PAYLOADS}


class Lease:
    def __init__(self, k, hold):
        self.sem = threading.BoundedSemaphore(k)
        self.hold = hold
        self.max_held = 0
        self._l = threading.Lock()
        self._h = 0

    def acquire(self):
        self.sem.acquire()
        with self._l:
            self._h += 1
            self.max_held = max(self.max_held, self._h)

    def release(self, ts):
        w = (ts + self.hold) - time.monotonic()
        if w > 0:
            time.sleep(w)
        with self._l:
            self._h -= 1
        self.sem.release()


def _nonatomic_rename(self, src, dst, src_dir_fd=None, dst_dir_fd=None):
    sfd = os.open(src, os.O_RDONLY, dir_fd=src_dir_fd)
    data = b""
    while True:
        c = os.read(sfd, 65536)
        if not c:
            break
        data += c
    os.close(sfd)
    dfd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644, dir_fd=dst_dir_fd)
    half = len(data) // 2
    os.write(dfd, data[:half])
    time.sleep(0.03)                       # widen the torn window
    os.write(dfd, data[half:])
    os.close(dfd)
    os.unlink(src, dir_fd=src_dir_fd)


def run_once(mode, writers=2, readers=3, reads=30, lease_k=5, hold=0.055):
    base = tempfile.mkdtemp(prefix="d119b-")
    ad = None
    errors, torn = [], []
    lk = threading.Lock()
    patch = None
    try:
        root = os.path.join(base, "root_main")
        os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
        open(os.path.join(root, "readme.txt"), "wb").write(b"r\n" * 4)
        grant = SourceGrant(alias="main", root=os.path.realpath(root),
                            operations=frozenset(("list", "find", "read", "save")),
                            max_read_bytes=1048576, max_write_bytes=1048576)
        pol = AgentPolicy(agent_id="agent-main",
                          token_sha256=hashlib.sha256(TOKEN.encode()).digest(),
                          grants=(grant,))
        if mode == "new_mutant":
            patch = LocalWriter._os_rename
            LocalWriter._os_rename = _nonatomic_rename
        ad = DriveHTTPAdapter((pol,), port=0, socket_timeout=10.0)
        time.sleep(0.1)
        DriveClient(port=ad.port, token=TOKEN, timeout=10.0).save(
            "main", "p/savepool/ow.bin", PAYLOADS[0], overwrite=True)
        lease = Lease(lease_k, hold) if mode in ("new", "new_mutant") else None
        stop = threading.Event()

        def note(exc, op):
            with lk:
                errors.append({
                    "op": op, "kind": type(exc).__name__,
                    "code": getattr(exc, "code", None),
                    "message": str(exc)[:160],
                    "outcome_uncertain": getattr(exc, "outcome_uncertain", None),
                    "retry_safe": getattr(exc, "retry_safe", None),
                })

        def writer(i):
            while not stop.is_set():
                if lease:
                    lease.acquire()
                try:
                    DriveClient(port=ad.port, token=TOKEN, timeout=10.0).save(
                        "main", "p/savepool/ow.bin", PAYLOADS[i % len(PAYLOADS)],
                        overwrite=True)
                except Exception as exc:  # noqa: BLE001
                    note(exc, "save")
                finally:
                    if lease:
                        lease.release(time.monotonic())

        def reader(i):
            try:
                for _ in range(reads):
                    if lease:
                        lease.acquire()
                    try:
                        data = DriveClient(port=ad.port, token=TOKEN, timeout=10.0).read(
                            "main", "p/savepool/ow.bin", offset=0, length=PAYLEN).data
                        if len(data) != PAYLEN or hashlib.sha256(data).hexdigest() not in PAYSHAS:
                            with lk:
                                torn.append({"len": len(data)})
                    finally:
                        if lease:
                            lease.release(time.monotonic())
            except Exception as exc:  # noqa: BLE001
                note(exc, "read")

        wts = [threading.Thread(target=writer, args=(i,)) for i in range(writers)]
        rts = [threading.Thread(target=reader, args=(i,)) for i in range(readers)]
        for t in wts:
            t.start()
        for t in rts:
            t.start()
        for t in rts:
            t.join(timeout=60)
        stop.set()
        for t in wts:
            t.join(timeout=30)
        ad.close(timeout=10.0)
        return {"mode": mode, "errors": errors, "torn": torn,
                "lease_max_held": lease.max_held if lease else None}
    finally:
        if patch is not None:
            LocalWriter._os_rename = patch
        if ad is not None:
            try:
                ad.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def cpu_hogs(n):
    pids = []
    for _ in range(n):
        pid = os.fork()
        if pid == 0:
            try:
                os.nice(15)
                import hashlib as _h
                while True:
                    _h.pbkdf2_hmac("sha256", b"x" * 64, b"y" * 16, 20000)
            except BaseException:
                pass
            os._exit(0)
        pids.append(pid)
    return pids


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    hogs = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    print("nproc", os.cpu_count(), "hogs", hogs)
    pids = cpu_hogs(hogs)
    time.sleep(0.2)
    try:
        for mode in ("old", "new", "new_mutant"):
            fails = 0
            sample = None
            for i in range(n):
                r = run_once(mode)
                bad = bool(r["errors"]) or bool(r["torn"])
                if bad:
                    fails += 1
                    if sample is None:
                        sample = r
            print("== %s : %d/%d runs with errors/torn ==" % (mode, fails, n))
            if sample:
                print("   sample errors:", json.dumps(sample["errors"][:2]))
                print("   sample torn  :", json.dumps(sample["torn"][:2]))
                print("   lease_max_held:", sample["lease_max_held"])
            sys.stdout.flush()
    finally:
        for p in pids:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for p in pids:
            try:
                os.waitpid(p, 0)
            except ChildProcessError:
                pass


if __name__ == "__main__":
    main()

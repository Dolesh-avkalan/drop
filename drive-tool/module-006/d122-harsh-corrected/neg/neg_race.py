#!/usr/bin/env python3
"""D122 race negatives under 2-vCPU CPU contention:
  oldfail : ORIGINAL payload concurrent_ops fails (busy)
  newpass : CORRECTED payload concurrent_ops passes
  mutant  : CORRECTED payload + non-atomic publish -> still FAILs (torn)
Loads both payloads as modules; no product file changed on disk."""
import os, sys, time, signal, importlib.util

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
sys.path.insert(0, REPO)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


O = load("origp", "/scratch/work/d122/orig/harsh_checks_d110.py")
P = load("corrp", "/scratch/work/d122/harsh_checks_d110.corrected.py")

from drive_tool.local_write import LocalWriter
_orig_rename = LocalWriter._os_rename


def nonatomic_rename(self, src, dst, src_dir_fd=None, dst_dir_fd=None):
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
    time.sleep(0.03)
    os.write(dfd, data[half:])
    os.close(dfd)
    os.unlink(src, dir_fd=src_dir_fd)


def cpu_hogs(n):
    pids = []
    for _ in range(n):
        pid = os.fork()
        if pid == 0:
            try:
                os.nice(15)
                import hashlib
                while True:
                    hashlib.pbkdf2_hmac("sha256", b"x" * 64, b"y" * 16, 20000)
            except BaseException:
                pass
            os._exit(0)
        pids.append(pid)
    return pids


def count_fail(mod, n):
    fails = 0
    for _ in range(n):
        r = mod.stage_concurrent_ops(REPO, 120.0)
        if r.get("result") != "PASS":
            fails += 1
    return fails


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    m = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    pids = cpu_hogs(4)
    time.sleep(0.2)
    try:
        fo = count_fail(O, n)
        print("oldfail  ORIGINAL  concurrent_ops: %d/%d FAIL" % (fo, n))
        sys.stdout.flush()
        fn = count_fail(P, n)
        print("newpass  CORRECTED concurrent_ops: %d/%d FAIL (expected 0)" % (fn, n))
        sys.stdout.flush()
        LocalWriter._os_rename = nonatomic_rename
        try:
            fm = count_fail(P, m)
        finally:
            LocalWriter._os_rename = _orig_rename
        print("mutant   CORRECTED + non-atomic publish: %d/%d FAIL (expected all)" % (fm, m))
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

#!/usr/bin/env python3
"""D119 repro C: R2 VmSize diagnosis.

Part 1 (first-D110 shape): measure VmSize single-threaded, then after creating
the 7-thread adapter, then in an os.fork()ed child -- showing the child inherits
the threaded parent's VmSize and cannot fit 192 MiB under the 512 MiB cap.

Part 2 (proposed fix): a CLEAN exec'ed child (fresh interpreter, no inherited
threads) -- measure VmSize, set RLIMIT_AS=512 MiB, allocate 192 MiB ballast,
run service ops, force MemoryError, recover.
"""
import os, sys, time, json, tempfile, subprocess, hashlib

REPO = "/scratch/work/src/drive-tool-337e4c713829af76615472eb47b81244ff399528"
sys.path.insert(0, REPO)
CAP = 512 * 1024 * 1024
BALLAST = 192 * 1024 * 1024
TOKEN = "d119-" + "A" * 40


def vmsize_kb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def part1():
    print("== Part 1: inherited VmSize (first-D110 shape) ==")
    print("  parent single-threaded VmSize_kb =", vmsize_kb())
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    base = tempfile.mkdtemp(prefix="d119c-")
    root = os.path.join(base, "root_main")
    os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
    open(os.path.join(root, "readme.txt"), "wb").write(b"r\n")
    grant = SourceGrant(alias="main", root=os.path.realpath(root),
                        operations=frozenset(("list", "find", "read", "save")),
                        max_read_bytes=1048576, max_write_bytes=1048576)
    pol = AgentPolicy(agent_id="agent-main",
                      token_sha256=hashlib.sha256(TOKEN.encode()).digest(),
                      grants=(grant,))
    ad = DriveHTTPAdapter((pol,), port=0, socket_timeout=10.0)
    time.sleep(0.1)
    print("  parent after adapter (7 threads) VmSize_kb =", vmsize_kb())
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(rfd)
        out = {"child_vm_kb": vmsize_kb(),
               "headroom_kb": BALLAST // 1024,
               "cap_kb": CAP // 1024,
               "fits": (vmsize_kb() + BALLAST // 1024) <= CAP // 1024}
        os.write(wfd, json.dumps(out).encode())
        os._exit(0)
    os.close(wfd)
    buf = os.read(rfd, 4096)
    os.close(rfd)
    os.waitpid(pid, 0)
    ad.close(timeout=5.0)
    child = json.loads(buf.decode())
    print("  forked child:", json.dumps(child))
    print("  -> would SKIP:", not child["fits"])
    import shutil
    shutil.rmtree(base, ignore_errors=True)
    return child


CHILD_SRC = r'''
import os, sys, resource, json, hashlib
repo, root = sys.argv[1], sys.argv[2]
sys.path.insert(0, repo)
def vmsize_kb():
    for l in open("/proc/self/status"):
        if l.startswith("VmSize:"): return int(l.split()[1])
    return None
out = {"fresh_vmsize_kb": vmsize_kb()}
try:
    open("/proc/self/oom_score_adj", "w").write("1000\n")
    out["oom_score_adj"] = "set"
except OSError as e:
    out["oom_score_adj"] = "err"
CAP = 512 * 1024 * 1024
resource.setrlimit(resource.RLIMIT_AS, (CAP, CAP))
out["rlimit_as_set"] = True
from drive_tool.file_service import LocalFileService
from drive_tool.service_policy import AgentPolicy, SourceGrant
token = "d119-" + "A" * 40
grant = SourceGrant(alias="main", root=os.path.realpath(root),
                    operations=frozenset(("list", "find", "read", "save")),
                    max_read_bytes=1048576, max_write_bytes=1048576)
pol = AgentPolicy(agent_id="agent-main",
                  token_sha256=hashlib.sha256(token.encode()).digest(),
                  grants=(grant,))
svc = LocalFileService((pol,))
ballast = bytearray(192 * 1024 * 1024)
ballast[::4096] = b"\x01" * (len(ballast) // 4096)
out["vmsize_after_ballast_kb"] = vmsize_kb()
ok = 0
for i in range(50):
    svc.read(token, "main", "p/readme.txt", offset=0, length=16)
    svc.save(token, "main", "p/savepool/m_%03d.bin" % i, b"m" * 256, overwrite=True)
    ok += 1
out["ops_ok"] = ok
me = None
grow = bytearray()
try:
    for _ in range(200):
        grow.extend(b"\x00" * (8 * 1024 * 1024))
except MemoryError:
    me = "MemoryError"
out["mem_error"] = me
del ballast, grow
rec = 0
for i in range(20):
    svc.save(token, "main", "p/savepool/r_%03d.bin" % i, b"r" * 256, overwrite=True)
    rec += 1
out["recovery_ops"] = rec
svc.close(timeout=5.0)
print("CHILD:" + json.dumps(out))
'''


def part2():
    print("\n== Part 2: clean exec'ed child (proposed fix) ==")
    base = tempfile.mkdtemp(prefix="d119c2-")
    root = os.path.join(base, "root_main")
    os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
    open(os.path.join(root, "readme.txt"), "wb").write(b"r\n" * 4)
    p = subprocess.run([sys.executable, "-c", CHILD_SRC, REPO, root],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    txt = p.stdout.decode("utf-8", "replace")
    line = [l for l in txt.splitlines() if l.startswith("CHILD:")]
    print("  rc =", p.returncode)
    print("  " + (line[0] if line else txt[-300:]))
    import shutil
    shutil.rmtree(base, ignore_errors=True)
    return line[0] if line else None


if __name__ == "__main__":
    part1()
    part2()

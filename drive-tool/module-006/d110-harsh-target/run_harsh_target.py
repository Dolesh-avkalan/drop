#!/usr/bin/env python3
"""d110 harsh target runner (stdlib only).

Outer orchestrator for the D110 harsh-fault extension.  It reuses the exact
D104 runner containment / identity / archive / resource patterns
(drop@c29e3a2b..., drive-tool/module-006/d104-target-http-runner-summary)
and drives the pinned harsh payload ``harsh_gate_d110.py`` against the accepted
final HTTP candidate:

    Dolesh-avkalan/drive-tool @ 337e4c713829af76615472eb47b81244ff399528

It does NOT run on the target from here and no target result is fabricated: the
operator runs it on the disposable instance.  This runner only orchestrates and
records; the payload implements the harsh stages.

Safety / containment (inherited from D104, plus the D110 harsh bounds)
---------------------------------------------------------------------
* stdlib only; no third-party import, no credential, no cloud API, no install,
  no reboot, no service/public binding, no real root, no deploy.
* execution confined to a NEW unique workspace under /tmp (realpath validated,
  mode 0700, strict descendant of the base, never the base itself).
* TMPDIR lives inside the workspace; bytecode writing is disabled.
* the archive sha256, every executable/importable candidate file, and the harsh
  payload sha256 are verified BEFORE anything executes, fail-closed.
* a free-disk floor (>= 1 GiB) is checked before every stage; the retained
  workspace is gated at <= 192 MiB.
* subprocess output is byte-capped and a timeout kills the whole process group.
* every stage stops the aggregate on the first FAIL; the overall exit is
  strictly nonzero on any FAIL / missing / skip / error / timeout.

Exact operator command (target: Debian / CPython 3.13)
-----------------------------------------------------
    cd d110-harsh-target && \\
    timeout 1200 python3 run_harsh_target.py \\
        --confirm-disposable-host=instance-20261015-210506 --json d110_summary.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

# ---------------------------------------------------------------------------
# Pins (frozen)
# ---------------------------------------------------------------------------
OWNER = "Dolesh-avkalan"
REPO = "drive-tool"
COMMIT = "337e4c713829af76615472eb47b81244ff399528"
COMMIT8 = COMMIT[:8]
ARCHIVE_URL = "https://codeload.github.com/%s/%s/tar.gz/%s" % (OWNER, REPO, COMMIT)
ARCHIVE_TOP = "drive-tool-%s" % COMMIT
ARCHIVE_SHA256 = "191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3"

# The exact pinned harsh payload this runner drives.  Verified before use.
HARSH_PAYLOAD_SHA256 = "b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e"
PAYLOAD_FILENAME = "harsh_gate_d110.py"

# Accepted D101 final HTTP gate (kept for reference / optional re-confirmation).
D101_GATE_SHA256 = "3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b"

# Composite source hash of the accepted HTTP overlay files (adapter||test).
SOURCEHASH = "b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c"

# Fixed allow-list of harsh stages (execution order).
REQUIRED_STAGES = (
    "selfcheck", "readdir_order", "http_hostile", "admission", "isolation",
    "concurrency", "crash_kill", "resource_pressure", "enospc",
)

# ---------------------------------------------------------------------------
# Resource bounds (D104 values, plus the D110 harsh bounds)
# ---------------------------------------------------------------------------
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_WORKSPACE_BYTES = 192 * 1024 * 1024   # <= 192 MiB retained workspace
MIN_FREE_BYTES = 1024 * 1024 * 1024       # >= 1 GiB free floor
MAX_SUBPROCESS_OUTPUT = 8 * 1024 * 1024

EXECUTABLE_EXTS = (".py", ".pyc", ".pyo", ".pth", ".so", ".sh", ".bash", ".pyw")
EXECUTABLE_NAMES = ("sitecustomize.py", "usercustomize.py")

DEFAULT_STAGE_TIMEOUT = 180
DEFAULT_OVERALL_DEADLINE = 1080           # < 20 min (1200 s) hard outer timeout
DEFAULT_DOWNLOAD_TIMEOUT = 120

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Pinned candidate manifest (identical to the accepted D104 EXPECTED_BLOBS).
# ---------------------------------------------------------------------------
EXPECTED_BLOBS = {
    "drive_tool/__init__.py": ("9be841b5749acb36c5e362c84b986d98292bae8d", "c73aefd5a746d624eaf1abcd3eb978b32b20183292489b711d1e29576fb5aa62", 539),
    "drive_tool/file_service.py": ("b7e18c606f45066cd54ec66016e70e797486ef50", "befe20bba64252d5595ac68e4af8459f4d8686dd31d14f5bfbf5159fa8b56f8c", 21555),
    "drive_tool/http_adapter.py": ("41279e6290617968c3b4f3f91fc3cf9a7dab505a", "3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c", 40881),
    "drive_tool/listing.py": ("28dddd549c068b00b149a16ad9820445b8af7946", "7a125e899124a1e1a3251f1e949d143b7f08fc89d71ff6ea906284abf0456734", 4750),
    "drive_tool/local.py": ("74a45c61d3ea9c6e64005b1d92834fed17323d62", "8d382347a4d1118440d364c693624de54883d517376779076c753672818ee2b7", 64638),
    "drive_tool/local_write.py": ("9824052f349e94f87ee65215ab96e979b4d2a021", "8a53c8467f5367d9617fd165cebdb0382adbc1ecdcb7a8568af902f6a20585ca", 21701),
    "drive_tool/search.py": ("f2d8407df8a98bb92972eecb7e43e653246d4b1a", "7a03793c05abf58e9f4558d2388ee892715f9ea5fb346e108b9411d0544230b6", 14835),
    "drive_tool/service_client.py": ("d04c637de7b7ed2b9be78d5b18fde60519f71579", "03c009ca1635be9a210c7ba3d2aa55cf90d4f64af8d6021a414294c94468a791", 21886),
    "drive_tool/service_policy.py": ("3e58f99ab4ad0286838743b25cef138638131305", "8feedd9499f52df32449acb4ce8d1d2e2a32e7cbf7d5ab2bed2f1a8547d9aa1c", 8575),
    "drive_tool/storage.py": ("3f4f8dcf50bbf68e97cd807fe40db1ee1bec4576", "422f22fb7e38e9a1dc51e4e3e88868dfc0c77f292dc759801aff93a9c945c6d2", 13718),
    "tests/test_enumeration.py": ("f7e1eef00de1d82fca7001b64a6af9cfc6d1e667", "4d53a946211d2673ef3cd8176dc62b4810f3c7bad8f1c52802ac283cb121dc69", 11474),
    "tests/test_enumeration_proofs.py": ("e18e02c2252c52a46ef97e733f50ecbcec422878", "ef1a6c8b243851c8ce1d857a81637fe03d22ded1c2c0ddf677467b46ca8ea750", 8388),
    "tests/test_file_service.py": ("8b5248f9365d8cac6e1331bb4677dea48a1778ff", "855df6ef02139f003cf7cfd26ccd1c43bce52b14e332c774f23a6de2917ad8dc", 31955),
    "tests/test_http_adapter.py": ("7a7be06d5ef0e25d0ac54e11bc5909cda27500d3", "b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf", 76436),
    "tests/test_listing.py": ("8287db88a4b7ff8d956c082e8150c8d169f0f4f7", "d036ddb160dff53c955916ab712af6f2e8d23a5972b378c33882cf2d5d311e98", 12497),
    "tests/test_local.py": ("b3319752edaf92a02993981fcc62d63f63ebb408", "3ba0e56f434651b3b5d4134a596ee7936650237102d3624b45c69eeb45019265", 68356),
    "tests/test_local_range.py": ("7fa3f80e97e84d8c8e7ff57c9cf2a950d5534fa9", "59651dfac93992563d1e5205a6762f0c435adf3d0d176ec92209ab7ab38b4555", 41910),
    "tests/test_local_range_proofs.py": ("d217e66b72a40de3bbc042f199db1ab25da341ba", "63a7deb685f2761ec510ed895018e90f82166d6e44f0f55696bc2eca85ca81c7", 17275),
    "tests/test_local_write.py": ("85e7bf06357c16ebf499294de9b116fb909e07db", "3b220d279d3895986ac3d4421e5701a58e5e7051ba8b302f49870efed771216e", 26064),
    "tests/test_local_write_proofs.py": ("6abf5f1b4bceae58877cb29182f685f71cd4343c", "7dae581e0eb9d8eca7b94931074dc36bf60190027d07d789a8c943093cd5c69d", 7519),
    "tests/test_partial_scan.py": ("ca73b0704a13d03e09f28a44c86f52ee76478dec", "39f1ec6470611fbb3c2fa5335725bec087196fc9ac8c41614c36f3321d87e444", 28656),
    "tests/test_partial_scan_proofs.py": ("51c990bc26661d98498086371be47cd08764be56", "fb7c6b217b7db603dc9630fb3d9648598f6dc2a7594c31f2fd804d0e86b4145b", 14284),
    "tests/test_partial_scan_review_fixes.py": ("c01003e7015915db3dcac15a168ff7aae3d423db", "4da34a8a5ce25771befa6dc19159992439a79326e1c5450ea3e6533749bfac97", 18702),
    "tests/test_readonly_core.py": ("1b0f746fd8162a9d27691abf7f5a90492548c4d8", "841af8ad17607cef984acfe380c0c8d5879b8b1266f39fa014f0d1559719e2ca", 11579),
    "tests/test_search.py": ("2ef9c5b8f97a9aa1ff912d250612b8fdb53cad29", "b1d4a0848516a5d0349de6c8d428060b324da48ab85e2bd0cee898c57ae1d49d", 19265),
    "tests/test_service_client.py": ("41d94d6ba0a184943ff6c80e1acc3d920ce18034", "e10d6145bdaf52f54edd84cd8e693dd7c39a392c8aeca7bc10915b65ef8ae4f4", 51167),
    "tests/test_service_policy.py": ("97bbf75bd967c29a9558514332e12bd3c908e7b9", "ada2c59e46cab5cc6b188b8d1ddefa9a25cfebe7d40e64df3ad65b3d5501959b", 19732),
    "tests/test_storage.py": ("2126dde7f32b7c0cd4d1e737ff990ab10954caf5", "2aa54aedddee1edd680d97e3c58e1a5a3c6d6c8604bcfd58c99138c971212ce9", 10406),
}


# ---------------------------------------------------------------------------
# Small helpers (verbatim D104 patterns)
# ---------------------------------------------------------------------------
def log(msg=""):
    sys.stderr.write(str(msg) + "\n")
    sys.stderr.flush()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data):
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def dir_allocated_size(path):
    total = 0
    for dp, dn, fn in os.walk(path):
        for name in fn:
            p = os.path.join(dp, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            total += st.st_blocks * 512
    return total


def _kill_group(p):
    try:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            p.kill()
        except OSError:
            pass


def run(cmd, cwd, env, timeout, max_output=MAX_SUBPROCESS_OUTPUT):
    p = subprocess.Popen(cmd, cwd=cwd, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         start_new_session=True)
    buf = bytearray()
    lock = threading.Lock()

    def reader():
        while True:
            b = p.stdout.read(65536)
            if not b:
                break
            with lock:
                if len(buf) < max_output:
                    buf.extend(b[:max_output - len(buf)])

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    timed_out = False
    try:
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_group(p)
        try:
            rc = p.wait(timeout=30)
        except subprocess.TimeoutExpired:
            rc = -9
        timed_out = True
    t.join(timeout=5)
    try:
        p.stdout.close()
    except Exception:
        pass
    with lock:
        out = bytes(buf)
    return rc, out, timed_out


# ---------------------------------------------------------------------------
# Workspace (strict /tmp-only, 0700, new, retained)
# ---------------------------------------------------------------------------
def make_workspace(base_dir, workdir):
    base = os.path.realpath(base_dir)
    tmp_real = os.path.realpath("/tmp")
    if not (base == tmp_real or base.startswith(tmp_real + os.sep)):
        raise SystemExit("base-dir must resolve under %s (got %s)" % (tmp_real, base))
    if workdir:
        ws = os.path.realpath(workdir)
        if not os.path.isdir(ws):
            raise SystemExit("workdir does not exist: %s" % ws)
        if not (ws.startswith(base + os.sep)):
            raise SystemExit("workdir must be a descendant of base-dir (never base itself)")
    else:
        uniq = "%d-%d" % (os.getpid(), int(time.time() * 1000) % 1000000)
        ws = os.path.join(base, "d110-%s-%s" % (COMMIT8, uniq))
        if os.path.exists(ws):
            raise SystemExit("workspace already exists: %s" % ws)
        os.makedirs(ws, mode=0o700)
        os.chmod(ws, 0o700)
    if not (ws.startswith(base + os.sep)):
        raise SystemExit("workspace escaped base-dir")
    mode = os.stat(ws).st_mode & 0o777
    if mode != 0o700:
        raise SystemExit("workspace mode is %o, expected 0700" % mode)
    return ws


def build_env(ws, src):
    env = dict(os.environ)
    tmp = os.path.join(ws, "tmp")
    os.makedirs(tmp, exist_ok=True)
    env["TMPDIR"] = tmp
    env["TEMP"] = tmp
    env["TMP"] = tmp
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    if src:
        env["PYTHONPATH"] = src
    return env


# ---------------------------------------------------------------------------
# Archive acquisition + safe extraction (verbatim D104 patterns)
# ---------------------------------------------------------------------------
def acquire_archive(archive, dest, deadline, download_timeout):
    if archive:
        src = os.path.realpath(archive)
        if not os.path.isfile(src):
            raise SystemExit("archive not found: %s" % src)
        if os.path.getsize(src) > MAX_ARCHIVE_BYTES:
            raise SystemExit("archive exceeds %d bytes" % MAX_ARCHIVE_BYTES)
        shutil.copyfile(src, dest)
        return "local:%s" % src
    remaining = max(5, min(download_timeout, int(deadline - time.monotonic())))
    cmd = ["curl", "-fsSL", "--max-time", str(remaining),
           "--retry", "2", "-o", dest, ARCHIVE_URL]
    rc, out, to = run(cmd, os.path.dirname(dest), dict(os.environ), remaining + 10)
    if rc != 0 or to:
        raise SystemExit("archive download failed rc=%s timeout=%s: %s"
                         % (rc, to, out[-400:].decode("utf-8", "replace")))
    if os.path.getsize(dest) > MAX_ARCHIVE_BYTES:
        raise SystemExit("downloaded archive exceeds %d bytes" % MAX_ARCHIVE_BYTES)
    return "download:%s" % ARCHIVE_URL


def safe_extract(tar_path, dest):
    os.makedirs(dest, mode=0o700, exist_ok=True)
    members = []
    total = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        allm = tar.getmembers()
        if len(allm) > MAX_MEMBERS:
            raise SystemExit("archive has %d members > %d" % (len(allm), MAX_MEMBERS))
        for m in allm:
            name = m.name
            if name.startswith("/") or os.path.isabs(name):
                raise SystemExit("absolute member path: %s" % name)
            parts = name.split("/")
            if any(p == ".." for p in parts):
                raise SystemExit("path traversal member: %s" % name)
            if m.issym() or m.islnk():
                raise SystemExit("link member rejected: %s" % name)
            if not (m.isdir() or m.isfile()):
                raise SystemExit("special member rejected: %s" % name)
            if m.isfile():
                if m.size > MAX_FILE_BYTES:
                    raise SystemExit("member %s exceeds %d bytes" % (name, MAX_FILE_BYTES))
                total += m.size
                if total > MAX_TOTAL_UNCOMPRESSED:
                    raise SystemExit("uncompressed total exceeds %d bytes" % MAX_TOTAL_UNCOMPRESSED)
            members.append(m)
        for m in members:
            target = os.path.join(dest, m.name)
            real = os.path.realpath(target)
            if not (real == os.path.realpath(dest) or real.startswith(os.path.realpath(dest) + os.sep)):
                raise SystemExit("member escapes extract dir: %s" % m.name)
            if m.isdir():
                os.makedirs(target, mode=0o700, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                f = tar.extractfile(m)
                data = f.read() if f else b""
                with open(target, "wb") as out:
                    out.write(data)
                os.chmod(target, 0o600)
    return total


# ---------------------------------------------------------------------------
# Identity verification (fail-closed, verbatim D104)
# ---------------------------------------------------------------------------
def verify_identities(src, expected):
    problems = []
    seen = set()
    expected_paths = set(expected.keys())
    for dp, dn, fn in os.walk(src):
        for name in fn:
            p = os.path.join(dp, name)
            rel = os.path.relpath(p, src)
            try:
                st = os.lstat(p)
            except OSError as e:
                problems.append("cannot stat %s: %s" % (rel, e))
                continue
            import stat as _stat
            if _stat.S_ISLNK(st.st_mode):
                problems.append("symlink present in source: %s" % rel)
                continue
            if not _stat.S_ISREG(st.st_mode):
                problems.append("non-regular file in source: %s" % rel)
                continue
            base = os.path.basename(rel)
            importable = base.endswith(EXECUTABLE_EXTS) or base in EXECUTABLE_NAMES
            under_dt = rel.startswith("drive_tool" + os.sep) or rel == "drive_tool"
            under_ts = rel.startswith("tests" + os.sep) or rel == "tests"
            if rel in expected_paths:
                seen.add(rel)
                data = open(p, "rb").read()
                blob = git_blob_sha1(data)
                sha = sha256_bytes(data)
                eblob, esha, esize = expected[rel]
                if len(data) != esize:
                    problems.append("size mismatch %s: %d != %d" % (rel, len(data), esize))
                if blob != eblob:
                    problems.append("blob mismatch %s: %s != %s" % (rel, blob, eblob))
                if sha != esha:
                    problems.append("sha256 mismatch %s: %s != %s" % (rel, sha, esha))
                continue
            if under_dt or under_ts:
                problems.append("unexpected file under drive_tool/ or tests/: %s" % rel)
                continue
            if importable:
                problems.append("unexpected importable/executable file: %s" % rel)
                continue
    for rel in expected_paths:
        if rel not in seen:
            problems.append("expected file missing: %s" % rel)
    return problems


def verify_payload(path):
    if not os.path.isfile(path):
        return ["payload not found: %s" % path]
    got = sha256_file(path)
    if got != HARSH_PAYLOAD_SHA256:
        return ["payload sha256 mismatch: %s != %s" % (got, HARSH_PAYLOAD_SHA256)]
    return []


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def write_manifest(ws, src):
    rows = []
    for dp, dn, fn in os.walk(src):
        for name in sorted(fn):
            p = os.path.join(dp, name)
            rel = os.path.relpath(p, src)
            st = os.lstat(p)
            if os.path.islink(p):
                rows.append((rel, st.st_size, "LINK", "LINK"))
                continue
            rows.append((rel, st.st_size, git_blob_sha1(open(p, "rb").read()),
                         sha256_file(p)))
    path = os.path.join(ws, "source_manifest.tsv")
    with open(path, "w") as f:
        for rel, size, blob, sha in sorted(rows):
            f.write("%s\t%d\t%s\t%s\n" % (rel, size, blob, sha))
    return path, len(rows)


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------
def run_stage(py, payload, src, stage, ws, env, timeout):
    jpath = os.path.join(ws, "stage_%s.json" % stage)
    log("[d110] stage %s (%ds budget)" % (stage, timeout))
    rc, out, to = run([py, payload, "--repo", src, "--stage", stage,
                       "--json", jpath], src, env, timeout)
    logpath = os.path.join(ws, "logs", "harsh_%s.out" % stage)
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    with open(logpath, "wb") as f:
        f.write(out)
    data = None
    if os.path.isfile(jpath):
        try:
            data = json.load(open(jpath))
        except Exception as e:  # noqa: BLE001
            data = {"stage": stage, "result": "ERROR",
                    "problems": ["stage json unreadable: %s" % e]}
    result = {
        "raw_exit": rc,
        "timed_out": to,
        "json": os.path.relpath(jpath, ws) if os.path.exists(jpath) else None,
        "log": os.path.relpath(logpath, ws),
        "result": (data or {}).get("result"),
        "problems": (data or {}).get("problems", []),
        "detail": data,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="d110 harsh target runner (stdlib only)")
    ap.add_argument("--archive", help="local candidate tar.gz (else download the pin)")
    ap.add_argument("--base-dir", default="/tmp", help="workspace base (must resolve under /tmp)")
    ap.add_argument("--workdir", help="explicit workspace dir (descendant of base, must exist)")
    ap.add_argument("--python", action="append", default=None,
                    help="interpreter to run (default: the interpreter running this script)")
    ap.add_argument("--payload", default=os.path.join(HERE, PAYLOAD_FILENAME),
                    help="path to the pinned harsh_gate_d110.py")
    ap.add_argument("--stage", action="append", default=None,
                    help="run only these stage(s) (default: all)")
    ap.add_argument("--confirm-disposable-host", default=None,
                    help="require socket.gethostname() to equal this exact value")
    ap.add_argument("--json", help="write the run summary to this path")
    ap.add_argument("--stage-timeout", type=int, default=DEFAULT_STAGE_TIMEOUT)
    ap.add_argument("--overall-deadline", type=int, default=DEFAULT_OVERALL_DEADLINE)
    ap.add_argument("--download-timeout", type=int, default=DEFAULT_DOWNLOAD_TIMEOUT)
    ap.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES,
                    help="free-disk floor (default 1 GiB; lower only for sandbox validation)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    start = time.monotonic()
    deadline = start + args.overall_deadline
    pythons = args.python or [sys.executable]
    stages_to_run = args.stage or list(REQUIRED_STAGES)

    hostname = socket.gethostname()
    if args.confirm_disposable_host is not None and hostname != args.confirm_disposable_host:
        raise SystemExit("host identity mismatch: got %r, expected %r"
                         % (hostname, args.confirm_disposable_host))

    summary = {
        "runner": "d110-harsh-target-runner",
        "pin": {"repo": "%s/%s" % (OWNER, REPO), "commit": COMMIT, "archive": ARCHIVE_URL,
                "archive_sha256": ARCHIVE_SHA256},
        "sourcehash": SOURCEHASH,
        "d101_gate_sha256": D101_GATE_SHA256,
        "payload_sha256": HARSH_PAYLOAD_SHA256,
        "hostname": hostname,
        "confirm_disposable_host": args.confirm_disposable_host,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interpreter": sys.version,
        "platform": platform.platform(),
        "pythons": pythons,
        "stages_to_run": stages_to_run,
        "stages": {},
        "problems": [],
    }

    ws = make_workspace(args.base_dir, args.workdir)
    summary["workspace"] = ws
    if not args.quiet:
        log("[d110] workspace %s" % ws)

    if free_bytes(ws) < args.min_free_bytes:
        summary["problems"].append("free disk %d < floor %d"
                                   % (free_bytes(ws), args.min_free_bytes))
        _finalize(ws, summary, True, args.json)
        return 1

    src_root = os.path.join(ws, "src")
    os.makedirs(src_root, mode=0o700, exist_ok=True)
    env = build_env(ws, None)

    # 1. acquire + extract the pinned archive
    arch = os.path.join(ws, "candidate.tar.gz")
    origin = acquire_archive(args.archive, arch, deadline, args.download_timeout)
    summary["archive_origin"] = origin
    summary["archive_bytes"] = os.path.getsize(arch)
    summary["archive_sha256"] = sha256_file(arch)
    if summary["archive_sha256"] != ARCHIVE_SHA256:
        summary["problems"].append("archive sha256 %s != pin %s"
                                   % (summary["archive_sha256"], ARCHIVE_SHA256))
        _finalize(ws, summary, True, args.json)
        return 1
    total_uncompressed = safe_extract(arch, src_root)
    summary["uncompressed_bytes"] = total_uncompressed
    src = os.path.join(src_root, ARCHIVE_TOP)
    if not os.path.isdir(src):
        tops = [d for d in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, d))]
        if len(tops) != 1:
            raise SystemExit("unexpected archive layout: %s" % tops)
        src = os.path.join(src_root, tops[0])
    summary["source_root"] = os.path.relpath(src, ws)

    # 2. identity verification of every executable/importable candidate file
    id_problems = verify_identities(src, EXPECTED_BLOBS)
    summary["identity"] = {"checked": len(EXPECTED_BLOBS), "problems": id_problems}
    if id_problems:
        summary["problems"].extend("identity: %s" % p for p in id_problems)
        _finalize(ws, summary, True, args.json)
        return 1

    # 3. payload verification
    pay_problems = verify_payload(args.payload)
    summary["payload"] = {"path": os.path.relpath(args.payload, HERE)
                          if args.payload.startswith(HERE) else args.payload,
                          "sha256": HARSH_PAYLOAD_SHA256, "problems": pay_problems}
    if pay_problems:
        summary["problems"].extend("payload: %s" % p for p in pay_problems)
        _finalize(ws, summary, True, args.json)
        return 1

    # 4. per-interpreter: run every stage (first failure stops the aggregate)
    overall_fail = False
    for py in pythons:
        per = {"python": py, "stages": {}}
        penv = build_env(ws, src)
        penv["D110_MIN_FREE_BYTES"] = str(args.min_free_bytes)
        # environment/identity capture
        erc, eout, eto = run([py, "-c",
                              "import sys,platform,os;print(sys.version);"
                              "print(platform.platform());print(os.getcwd())"],
                             src, penv, 30)
        per["env"] = {"raw_exit": erc, "out": eout.decode("utf-8", "replace").strip()}
        if erc != 0 or eto:
            per["env"]["problems"] = ["environment/identity check failed"]
            overall_fail = True
            summary["stages"][py] = per
            continue

        for stage in stages_to_run:
            remaining = int(deadline - time.monotonic())
            if remaining <= 5:
                per["stages"][stage] = {"result": "TIMEOUT",
                                        "problems": ["overall deadline reached"]}
                overall_fail = True
                break
            budget = max(5, min(args.stage_timeout, remaining))
            res = run_stage(py, args.payload, src, stage, ws, penv, budget)
            per["stages"][stage] = res
            if res["result"] != "PASS":
                overall_fail = True
        summary["stages"][py] = per

    # 5. resources after + bounds
    alloc = dir_allocated_size(ws)
    summary["resources"] = {
        "workspace_allocated_bytes": alloc,
        "workspace_limit_bytes": MAX_WORKSPACE_BYTES,
        "free_bytes": free_bytes(ws),
        "within_workspace_bound": alloc <= MAX_WORKSPACE_BYTES,
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }
    if alloc > MAX_WORKSPACE_BYTES:
        overall_fail = True
        summary["problems"].append("workspace %d exceeds %d bytes"
                                   % (alloc, MAX_WORKSPACE_BYTES))

    # 6. manifest
    mpath, mcount = write_manifest(ws, src)
    summary["manifest"] = {"path": os.path.relpath(mpath, ws), "files": mcount}

    _finalize(ws, summary, overall_fail, args.json)
    return 1 if overall_fail else 0


def _finalize(ws, summary, failed, json_path):
    summary["result"] = "FAIL" if failed else "PASS"
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["exit"] = 1 if failed else 0
    path = json_path or os.path.join(ws, "d110_summary.json")
    try:
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, sort_keys=True)
    except OSError:
        pass
    log("[d110] result=%s exit=%d summary=%s"
        % (summary["result"], summary["exit"], path))


if __name__ == "__main__":
    sys.exit(main())

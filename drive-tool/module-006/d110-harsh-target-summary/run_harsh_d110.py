#!/usr/bin/env python3
"""d110 harsh-fault outer runner (stdlib only).

Purpose
-------
Drive the pinned D110 harsh-fault payload (``harsh_checks_d110.py``) against
the accepted D102 final HTTP candidate
(Dolesh-avkalan/drive-tool @ 337e4c713829af76615472eb47b81244ff399528) on a
disposable Debian / CPython target, and gate on every harsh stage PASSing.

It is a SEPARATE, bounded harsh-fault extension.  It does NOT modify any
product source/test/acceptance spec/old evidence, and it does NOT duplicate
the active baseline cloud run: it runs only its own fixed allow-list of harsh
stages.

It reuses the D104 runner containment / identity / archive / resource patterns
and adds NO generic remote shell and NO unrelated framework.  It executes only
a fixed allow-list of actions: environment capture, pinned-archive acquisition,
hash verification, and the eight harsh stages.

Safety
------
* stdlib only; no third-party import, no credential, no cloud API, no install,
  no reboot, no service/public binding, no real root, no deploy.
* execution is confined to a NEW unique workspace under /tmp (realpath
  validated, mode 0700, strict descendant, <= 192 MiB, >= 1 GiB free disk
  floor).  Evidence is retained (no cleanup).
* TMPDIR lives inside the workspace; bytecode writing is disabled.
* every executable source/test/importable file is re-hashed and checked against
  the embedded pinned blob sha1 + sha256 BEFORE anything is executed;
  unexpected importable/executable files anywhere, any unexpected drive_tool/
  or tests/ file, symlinks, path traversal, oversize members and oversize
  totals are rejected fail-closed.
* the payload sha256 is verified before execution.
* each stage runs in its OWN process group with a finite per-stage timeout, an
  overall deadline and a hard outer operator timeout (< 20 min); a timeout
  kills that stage's whole process group.  Subprocess capture is byte-capped.
* the runner only ever kills its own child process groups.

Host identity
-------------
The target is ``instance-20261015-210506``.  A target run REQUIRES
``--confirm-disposable-host=instance-20261015-210506`` AND the live hostname to
match; otherwise the runner fails closed.  ``--sandbox`` runs the identical
package locally for harness validation only and is NEVER reported as a target
pass.
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

EXPECTED_HOST = "instance-20261015-210506"

# The exact D110 payload this runner drives.  Verified before use.
PAYLOAD_FILENAME = "harsh_checks_d110.py"
PAYLOAD_SHA256 = "5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43"
PAYLOAD_BYTES = 75545

REQUIRED_STAGES = ("selfcheck", "http_hostile", "admission_exhaustion",
                   "isolation", "concurrent_ops", "crash_kill",
                   "resource_pressure", "enospc")

# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 64 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_WORKSPACE_BYTES = 192 * 1024 * 1024     # <= 192 MiB retained workspace
MIN_FREE_BYTES = 1024 * 1024 * 1024         # >= 1 GiB free disk floor
BALLAST_BYTES = 16 * 1024 * 1024            # 16 MiB emergency reserve
MAX_SUBPROCESS_OUTPUT = 8 * 1024 * 1024

EXECUTABLE_EXTS = (".py", ".pyc", ".pyo", ".pth", ".so", ".sh", ".bash", ".pyw")
EXECUTABLE_NAMES = ("sitecustomize.py", "usercustomize.py")

DEFAULT_STAGE_TIMEOUT = 120
DEFAULT_OVERALL_DEADLINE = 1080           # < 20 min (1200 s) hard outer timeout
DEFAULT_DOWNLOAD_TIMEOUT = 120

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Pinned importable/executable source & test manifest (identical to D104).
# Any unexpected file in drive_tool/ or tests/, or any unexpected
# importable/executable file anywhere, is rejected fail-closed.
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
# Small helpers
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
    for dp, _dn, fn in os.walk(path):
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
def make_workspace(base_dir, workdir, allow_outside_tmp=False):
    base = os.path.realpath(base_dir)
    tmp_real = os.path.realpath("/tmp")
    if not allow_outside_tmp and not (base == tmp_real or base.startswith(tmp_real + os.sep)):
        raise SystemExit("base-dir must resolve under %s (got %s)" % (tmp_real, base))
    if not os.path.isdir(base):
        raise SystemExit("base-dir does not exist: %s" % base)
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
# Archive acquisition + safe extraction
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
# Identity verification (fail-closed)
# ---------------------------------------------------------------------------
def verify_identities(src, expected):
    problems = []
    seen = set()
    expected_paths = set(expected.keys())
    for dp, _dn, fn in os.walk(src):
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
    if os.path.getsize(path) != PAYLOAD_BYTES:
        return ["payload size %d != %d" % (os.path.getsize(path), PAYLOAD_BYTES)]
    got = sha256_file(path)
    if got != PAYLOAD_SHA256:
        return ["payload sha256 mismatch: %s != %s" % (got, PAYLOAD_SHA256)]
    return []


def write_manifest(ws, src):
    rows = []
    for dp, _dn, fn in os.walk(src):
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


def _pytag(py):
    base = os.path.basename(py)
    for t in ("python3.13", "python3.12", "python3.11", "python3", "python"):
        if base.startswith(t):
            return t.replace(".", "")
    return "py"


def parse_harsh_line(out):
    text = out.decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("HARSH_JSON: "):
            try:
                return json.loads(line[len("HARSH_JSON: "):])
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="d110 harsh-fault outer runner (stdlib only)")
    ap.add_argument("--confirm-disposable-host", default=None,
                    help="must equal %s on the disposable target" % EXPECTED_HOST)
    ap.add_argument("--sandbox", action="store_true",
                    help="run the identical package locally for harness validation "
                         "only (never a target pass)")
    ap.add_argument("--archive", help="local candidate tar.gz (else download the pin)")
    ap.add_argument("--base-dir", default="/tmp", help="workspace base (must resolve under /tmp)")
    ap.add_argument("--workdir", help="explicit workspace dir (descendant of base, must exist)")
    ap.add_argument("--python", action="append", default=None,
                    help="interpreter to run (default: the interpreter running this script)")
    ap.add_argument("--payload", default=os.path.join(HERE, PAYLOAD_FILENAME),
                    help="path to the pinned harsh_checks_d110.py")
    ap.add_argument("--json", help="write the run summary to this path")
    ap.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES,
                    help="free-disk floor (only honoured below 1 GiB with --sandbox)")
    ap.add_argument("--stage-timeout", type=int, default=DEFAULT_STAGE_TIMEOUT)
    ap.add_argument("--overall-deadline", type=int, default=DEFAULT_OVERALL_DEADLINE)
    ap.add_argument("--download-timeout", type=int, default=DEFAULT_DOWNLOAD_TIMEOUT)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    start = time.monotonic()
    deadline = start + args.overall_deadline
    pythons = args.python or [sys.executable]

    hostname = socket.gethostname()
    host_verified = (hostname == EXPECTED_HOST
                     and args.confirm_disposable_host == EXPECTED_HOST)
    if not host_verified and not args.sandbox:
        raise SystemExit(
            "host gate failed closed: hostname=%r confirm=%r expected=%r; "
            "pass --confirm-disposable-host=%s on the disposable target, or "
            "--sandbox for local harness validation only"
            % (hostname, args.confirm_disposable_host, EXPECTED_HOST, EXPECTED_HOST))
    mode = "sandbox" if (args.sandbox and not host_verified) else "target"

    summary = {
        "runner": "d110-harsh-fault-runner",
        "mode": mode,
        "host": {"hostname": hostname, "expected": EXPECTED_HOST,
                 "confirmed": args.confirm_disposable_host,
                 "disposable_host_verified": host_verified},
        "pin": {"repo": "%s/%s" % (OWNER, REPO), "commit": COMMIT, "archive": ARCHIVE_URL},
        "payload": {"file": PAYLOAD_FILENAME, "sha256": PAYLOAD_SHA256,
                    "bytes": PAYLOAD_BYTES},
        "required_stages": list(REQUIRED_STAGES),
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interpreter": sys.version,
        "platform": platform.platform(),
        "pythons": pythons,
        "stages": {},
        "problems": [],
    }

    ws = make_workspace(args.base_dir, args.workdir, allow_outside_tmp=args.sandbox)
    summary["workspace"] = ws
    os.makedirs(os.path.join(ws, "logs"), mode=0o700, exist_ok=True)
    if not args.quiet:
        log("[d110] mode=%s workspace %s" % (mode, ws))

    # disk floor + emergency ballast
    base_real = os.path.realpath(args.base_dir)
    floor = min(args.min_free_bytes, MIN_FREE_BYTES) if args.sandbox else MIN_FREE_BYTES
    free_base = free_bytes(base_real)
    free_root = free_bytes("/")
    summary["disk"] = {"base": base_real, "free_base_bytes": free_base,
                       "free_root_bytes": free_root, "floor_bytes": floor}
    summary["sandbox_relaxations"] = (
        ["base-dir outside /tmp allowed", "disk floor lowered to %d bytes" % floor]
        if (args.sandbox and (floor < MIN_FREE_BYTES
                              or not base_real.startswith(os.path.realpath("/tmp")))
            ) else [])
    if free_base < floor or free_root < floor:
        summary["problems"].append("free disk below the %d byte floor" % floor)
        _finalize(ws, summary, args.json)
        return 1
    ballast_path = os.path.join(ws, "logs", ".reserve_ballast")
    try:
        with open(ballast_path, "wb") as fh:
            fh.truncate(BALLAST_BYTES)
    except OSError:
        pass

    src_root = os.path.join(ws, "src")
    os.makedirs(src_root, mode=0o700, exist_ok=True)
    env = build_env(ws, None)

    # 1. acquire + extract the pinned archive
    arch = os.path.join(ws, "candidate.tar.gz")
    origin = acquire_archive(args.archive, arch, deadline, args.download_timeout)
    summary["archive_origin"] = origin
    summary["archive_bytes"] = os.path.getsize(arch)
    summary["archive_sha256"] = sha256_file(arch)
    total_uncompressed = safe_extract(arch, src_root)
    summary["uncompressed_bytes"] = total_uncompressed
    src = os.path.join(src_root, ARCHIVE_TOP)
    if not os.path.isdir(src):
        tops = [d for d in os.listdir(src_root) if os.path.isdir(os.path.join(src_root, d))]
        if len(tops) != 1:
            raise SystemExit("unexpected archive layout: %s" % tops)
        src = os.path.join(src_root, tops[0])
    summary["source_root"] = os.path.relpath(src, ws)

    # 2. identity verification of every executable/importable file
    id_problems = verify_identities(src, EXPECTED_BLOBS)
    summary["identity"] = {"checked": len(EXPECTED_BLOBS), "problems": id_problems}
    if id_problems:
        summary["problems"].extend("identity: %s" % p for p in id_problems)
        _finalize(ws, summary, args.json)
        return 1

    # 3. payload verification
    payload_problems = verify_payload(args.payload)
    summary["payload"]["problems"] = payload_problems
    if payload_problems:
        summary["problems"].extend("payload: %s" % p for p in payload_problems)
        _finalize(ws, summary, args.json)
        return 1

    # 4. run every required stage, per-interpreter
    stage_results = {}
    for py in pythons:
        per = {}
        for stage in REQUIRED_STAGES:
            remaining = deadline - time.monotonic()
            if remaining <= 5:
                per[stage] = {"result": "ERROR", "problems": ["overall deadline exceeded"]}
                continue
            wall = max(10, min(args.stage_timeout, int(remaining)))
            budget = max(5, wall - 15)
            log_path = os.path.join(ws, "logs", "harsh_%s_%s.out" % (stage, _pytag(py)))
            jpath = os.path.join(ws, "logs", "harsh_%s_%s.json" % (stage, _pytag(py)))
            penv = build_env(ws, src)
            cmd = [py, args.payload, "--repo", src, "--stage", stage,
                   "--budget", str(budget), "--json", jpath]
            if not args.quiet:
                log("[d110] %s %s (%ds)" % (py, stage, wall))
            rc, out, to = run(cmd, src, penv, wall)
            with open(log_path, "wb") as f:
                f.write(out)
            res = parse_harsh_line(out)
            if res is None:
                res = {"stage": stage, "result": "ERROR",
                       "problems": ["no HARSH_JSON line (rc=%s timeout=%s)" % (rc, to)]}
            res["raw_exit"] = rc
            res["timed_out"] = to
            res["log"] = os.path.relpath(log_path, ws)
            res["json"] = os.path.relpath(jpath, ws) if os.path.exists(jpath) else None
            per[stage] = res
        stage_results[py] = per
    summary["stages"] = stage_results

    # 5. aggregate
    agg_problems = []
    agg = {}
    for py in pythons:
        per = stage_results[py]
        results = {s: (per.get(s) or {}).get("result") for s in REQUIRED_STAGES}
        missing = [s for s in REQUIRED_STAGES if results[s] is None]
        failed = [s for s in REQUIRED_STAGES if results[s] in ("FAIL", "ERROR", "TIMEOUT")]
        skipped = [s for s in REQUIRED_STAGES if results[s] in ("SKIPPED", "PARTIAL")]
        if missing:
            agg[py] = "INCOMPLETE"
            agg_problems.append("%s missing stages: %s" % (py, missing))
        elif failed:
            agg[py] = "FAIL"
            agg_problems.append("%s failed stages: %s" % (py, failed))
        elif skipped:
            agg[py] = "PARTIAL"
        else:
            agg[py] = "PASS"
    summary["aggregate"] = agg
    summary["problems"].extend(agg_problems)

    # 6. resources after
    if free_bytes("/tmp") < 64 * 1024 * 1024:
        try:
            os.unlink(ballast_path)
        except OSError:
            pass
    alloc = dir_allocated_size(ws)
    summary["resources"] = {
        "workspace_allocated_bytes": alloc,
        "workspace_limit_bytes": MAX_WORKSPACE_BYTES,
        "free_base_bytes": free_bytes(base_real),
        "within_workspace_bound": alloc <= MAX_WORKSPACE_BYTES,
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }
    if alloc > MAX_WORKSPACE_BYTES:
        summary["problems"].append("workspace %d exceeds %d bytes" % (alloc, MAX_WORKSPACE_BYTES))

    # 7. manifest
    mpath, mcount = write_manifest(ws, src)
    summary["manifest"] = {"path": os.path.relpath(mpath, ws), "files": mcount}

    _finalize(ws, summary, args.json)
    overall = summary.get("result")
    return 0 if overall == "PASS" else 1


def _finalize(ws, summary, json_path):
    agg = summary.get("aggregate") or {}
    overalls = set(agg.values()) if agg else set()
    if "FAIL" in overalls or "INCOMPLETE" in overalls or summary.get("problems"):
        overall = "FAIL"
    elif "PARTIAL" in overalls:
        overall = "PARTIAL"
    elif overalls == {"PASS"}:
        overall = "PASS"
    else:
        overall = "FAIL"
    # a sandbox run is never reported as a target pass
    if summary.get("mode") == "sandbox" and overall == "PASS":
        overall = "SANDBOX_PASS"
    summary["result"] = overall
    summary["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    summary["exit"] = 0 if overall == "PASS" else 1
    path = json_path or os.path.join(ws, "d110_summary.json")
    try:
        with open(path, "w") as f:
            json.dump(summary, f, indent=2, sort_keys=True, default=str)
    except OSError:
        pass
    try:
        _write_manifest_md(ws, summary)
    except OSError:
        pass
    log("[d110] result=%s exit=%d summary=%s" % (summary["result"], summary["exit"], path))


def _write_manifest_md(ws, summary):
    lines = []
    lines.append("# D110 harsh-fault run manifest")
    lines.append("")
    lines.append("- runner: %s" % summary.get("runner"))
    lines.append("- mode: %s" % summary.get("mode"))
    lines.append("- host: %s (verified=%s)"
                 % ((summary.get("host") or {}).get("hostname"),
                    (summary.get("host") or {}).get("disposable_host_verified")))
    lines.append("- pin: %s @ %s" % ((summary.get("pin") or {}).get("repo"),
                                     (summary.get("pin") or {}).get("commit")))
    lines.append("- payload sha256: %s" % (summary.get("payload") or {}).get("sha256"))
    lines.append("- workspace: %s" % summary.get("workspace"))
    lines.append("- archive sha256: %s" % summary.get("archive_sha256"))
    lines.append("- result: %s (exit %s)" % (summary.get("result"), summary.get("exit")))
    lines.append("")
    lines.append("## Stages")
    lines.append("")
    lines.append("| interpreter | stage | result | raw exit | timed out |")
    lines.append("| --- | --- | --- | --- | --- |")
    for py, per in (summary.get("stages") or {}).items():
        for stage in REQUIRED_STAGES:
            r = per.get(stage) or {}
            lines.append("| %s | %s | %s | %s | %s |"
                         % (py, stage, r.get("result"), r.get("raw_exit"),
                            r.get("timed_out")))
    lines.append("")
    if summary.get("problems"):
        lines.append("## Problems")
        lines.append("")
        for p in summary["problems"]:
            lines.append("- %s" % p)
    with open(os.path.join(ws, "logs", "MANIFEST.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())

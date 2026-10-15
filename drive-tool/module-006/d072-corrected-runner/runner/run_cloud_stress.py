#!/usr/bin/env python3
"""d063 bounded six-agent cloud stress runner (stdlib only).

Provenance: written for d063 by reusing the proven d014/d038 GitHub-delivered
runner pattern (Dolesh-avkalan/drop drive-tool/readonly-core/d014-cloud-validation).
It is authored and sandbox-tested on the author's side; it does NOT run on the
target from here and NO target result is fabricated. The director runs it on
the separate target instance through the existing Cloud Shell SSH.

Corrections applied under D069 against Gemini D065 findings B1-B3 and limits
L1-L5. The pin, EXPECTED_BLOBS and STRESS_CHECKS_SHA256 are preserved exactly.

  * B1 (directory-order masking): execution is confined to /tmp (realpath
    validated, mode 0700). The native /tmp filesystem type, mount options and
    the observed readdir order are recorded. The known directory-order-
    sensitive test is additionally reproduced deterministically in two
    isolated subprocesses (os.scandir/os.listdir shimmed ascending vs
    descending) and both observations are recorded separately. The committed
    suite gate remains STRICT: a failing suite is never relabelled PASS.
    Smoke/soak/edges still run for diagnostic evidence but the runner exit
    stays NONZERO.
  * B2 (identity fail-closed): verify_identities() now fails closed for ANY
    unexpected file under drive_tool/ or tests/, for ANY unexpected
    importable/executable file anywhere in the extracted source, for
    sitecustomize.py / usercustomize.py at any path, and for any symlink
    inside the extracted tree.
  * B3 (workspace escape): --base-dir and --workdir are canonicalised with
    os.path.realpath and must resolve under /tmp (not /tmp itself). The
    workspace is created with mode 0700 and re-validated after creation.
  * L1: archive download enforces an absolute monotonic wall-clock deadline
    in addition to the per-socket timeout.
  * L2: stress stages receive --deadline-seconds so the child can emit
    STRESS_JSON before the parent's hard timeout fires.
  * L3: subprocess capture is byte-capped and timeouts kill the whole
    process group (start_new_session=True + os.killpg).
  * L4: manifest and size accounting use os.lstat and enumerate symlinks
    explicitly without following them.
  * L5: apparent vs allocated workspace bytes are both recorded.

What it does, in order, and fails closed at every preflight gate:

  1. creates a NEW unique workspace under /tmp (default /tmp/d063-<commit8>-<uniq>);
  2. captures host/version/filesystem/resources BEFORE and gates on free space;
  3. verifies the fixed payload stress_checks.py identity;
  4. downloads the PINNED GitHub archive (codeload tar.gz of the pinned commit)
     with a byte cap and a wall-clock deadline, or copies a supplied archive;
  5. extracts it with path/size/count/link guards;
  6. verifies every pinned EXECUTABLE SOURCE/TEST file's git blob sha1 and
     rejects any unexpected importable/executable or symlinked file;
  7. records native /tmp filesystem + readdir order, and reproduces the
     directory-order-sensitive test deterministically in two subprocesses;
  8. runs the committed 506 suite on every available Python interpreter;
  9. runs a bounded 600-call six-agent backend SMOKE;
 10. ONLY if the smoke passes, runs a bounded 10000-call six-agent backend SOAK;
 11. runs raw edge checks;
 12. captures resources AFTER, gates the workspace size, and writes a
     SHA-256/length manifest plus a summary.

If the committed suite fails, stages 9-11 still run for diagnostic evidence
and the overall runner exit remains NONZERO.

Fixed allow-list of executed actions only (environment capture, committed
suite, smoke, soak, edges). There is NO arbitrary shell/job payload option,
no credential, no cloud API, no install/reboot/service/public binding and no
real root. Only a fresh unique /tmp workspace is touched; TMPDIR lives inside
it and bytecode writing is disabled. Evidence is retained (no cleanup).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request

# -- pins --------------------------------------------------------------------

OWNER = "Dolesh-avkalan"
REPO = "drive-tool"
COMMIT = "b7f8d17b9dcc4aec68d54b38f994290e05264e67"
ARCHIVE_URL = f"https://codeload.github.com/{OWNER}/{REPO}/tar.gz/{COMMIT}"

# git blob sha1 of every EXECUTABLE source/test file at the pinned commit.
EXPECTED_BLOBS = {
    "drive_tool/__init__.py": "9be841b5749acb36c5e362c84b986d98292bae8d",
    "drive_tool/file_service.py": "b7e18c606f45066cd54ec66016e70e797486ef50",
    "drive_tool/listing.py": "28dddd549c068b00b149a16ad9820445b8af7946",
    "drive_tool/local.py": "74a45c61d3ea9c6e64005b1d92834fed17323d62",
    "drive_tool/local_write.py": "9824052f349e94f87ee65215ab96e979b4d2a021",
    "drive_tool/search.py": "f2d8407df8a98bb92972eecb7e43e653246d4b1a",
    "drive_tool/service_client.py": "d04c637de7b7ed2b9be78d5b18fde60519f71579",
    "drive_tool/service_policy.py": "3e58f99ab4ad0286838743b25cef138638131305",
    "drive_tool/storage.py": "3f4f8dcf50bbf68e97cd807fe40db1ee1bec4576",
    "tests/test_enumeration.py": "f7e1eef00de1d82fca7001b64a6af9cfc6d1e667",
    "tests/test_enumeration_proofs.py": "e18e02c2252c52a46ef97e733f50ecbcec422878",
    "tests/test_file_service.py": "8b5248f9365d8cac6e1331bb4677dea48a1778ff",
    "tests/test_listing.py": "8287db88a4b7ff8d956c082e8150c8d169f0f4f7",
    "tests/test_local.py": "b3319752edaf92a02993981fcc62d63f63ebb408",
    "tests/test_local_range.py": "7fa3f80e97e84d8c8e7ff57c9cf2a950d5534fa9",
    "tests/test_local_range_proofs.py": "d217e66b72a40de3bbc042f199db1ab25da341ba",
    "tests/test_local_write.py": "85e7bf06357c16ebf499294de9b116fb909e07db",
    "tests/test_local_write_proofs.py": "6abf5f1b4bceae58877cb29182f685f71cd4343c",
    "tests/test_partial_scan.py": "ca73b0704a13d03e09f28a44c86f52ee76478dec",
    "tests/test_partial_scan_proofs.py": "51c990bc26661d98498086371be47cd08764be56",
    "tests/test_partial_scan_review_fixes.py": "f110f83c95b846bc853069194ff7759b690ebfca",
    "tests/test_readonly_core.py": "1b0f746fd8162a9d27691abf7f5a90492548c4d8",
    "tests/test_search.py": "2ef9c5b8f97a9aa1ff912d250612b8fdb53cad29",
    "tests/test_service_client.py": "41d94d6ba0a184943ff6c80e1acc3d920ce18034",
    "tests/test_service_policy.py": "97bbf75bd967c29a9558514332e12bd3c908e7b9",
    "tests/test_storage.py": "2126dde7f32b7c0cd4d1e737ff990ab10954caf5",
}

# SHA-256 of the fixed executable payload this runner is allowed to invoke.
STRESS_CHECKS_SHA256 = "8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9"

# -- limits (defined BEFORE execution) ---------------------------------------

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 2000
MAX_WORKSPACE_BYTES = 128 * 1024 * 1024   # <= 128 MiB workspace, hard gate
MAX_FIXTURE_BYTES = 32 * 1024 * 1024      # <= 32 MiB new fixture data
MAX_CONCURRENT = 6                        # <= 6 concurrent operations
MIN_FREE_BYTES = 20 * 1024 * 1024
EXPECTED_SUITE_TESTS = 506

MAX_SUBPROCESS_OUTPUT = 8 * 1024 * 1024   # byte cap on captured stdout+stderr
EXECUTABLE_EXTS = (".py", ".pyc", ".pyo", ".pth", ".so", ".sh", ".bash", ".pyw")
EXECUTABLE_NAMES = ("sitecustomize.py", "usercustomize.py")

DEFAULT_DOWNLOAD_TIMEOUT = 120
DEFAULT_SUITE_TIMEOUT = 240
DEFAULT_SMOKE_TIMEOUT = 180
DEFAULT_SOAK_TIMEOUT = 420
DEFAULT_EDGE_TIMEOUT = 120
DEFAULT_OVERALL_DEADLINE = 900            # < 20 min hard outer operator timeout

PYTHON_CANDIDATES = ["python3.14", "python3.13", "python3.12", "python3.11",
                     "python3.10", "python3"]

HERE = os.path.dirname(os.path.abspath(__file__))
STRESS_CHECKS_PY = os.path.join(HERE, "stress_checks.py")

ORDER_SENSITIVE_TEST = (
    "tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests."
    "test_metadata_failure_below_root_is_skipped_and_charged"
)

def log(msg=""):
    print(msg, flush=True)

# -- identity helpers --------------------------------------------------------

def git_blob_sha1(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % len(data))
    h.update(data)
    return h.hexdigest()

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def verify_identities(src, expected):
    """Fail-closed identity verification.

    Returns (problems, extras, hard_extras).

      problems     -- missing/linked pinned file or blob mismatch (abort)
      extras       -- unexpected files present, informational
      hard_extras  -- fail-closed conditions (abort):
                        * unexpected file under drive_tool/ or tests/
                        * unexpected importable/executable file anywhere
                        * sitecustomize.py / usercustomize.py anywhere
                        * any symlink inside the extracted source
    """
    problems = []
    for rel, want in sorted(expected.items()):
        p = os.path.join(src, rel)
        if os.path.islink(p) or not os.path.isfile(p):
            problems.append(f"MISSING_OR_LINK {rel}")
            continue
        with open(p, "rb") as fh:
            got = git_blob_sha1(fh.read())
        if got != want:
            problems.append(f"MISMATCH {rel}: got {got} want {want}")

    extras = []
    hard_extras = []
    for dp, dns, fns in os.walk(src, followlinks=False):
        # Reject any symlinked directory outright; do not descend into it.
        kept = []
        for d in dns:
            full = os.path.join(dp, d)
            rel = os.path.relpath(full, src)
            if d == "__pycache__":
                continue
            if os.path.islink(full):
                hard_extras.append(f"SYMLINK_DIR {rel}")
                continue
            kept.append(d)
        dns[:] = kept
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, src)
            if rel in expected:
                continue
            if os.path.islink(full):
                hard_extras.append(f"SYMLINK {rel}")
                continue
            extras.append(rel)
            parts = rel.split(os.sep)
            base = parts[-1]
            if parts[0] in ("drive_tool", "tests"):
                hard_extras.append(f"UNEXPECTED {rel}")
                continue
            if base in EXECUTABLE_NAMES or base.endswith(EXECUTABLE_EXTS):
                hard_extras.append(f"EXECUTABLE_UNEXPECTED {rel}")
    return problems, extras, hard_extras

# -- workspace canonicalisation (B3) -----------------------------------------

def canonical_workspace(path):
    """Return a canonical /tmp-rooted absolute workspace path, or raise."""
    ap = os.path.abspath(path)
    parent = os.path.dirname(ap) or "/"
    if not os.path.isdir(parent):
        raise ValueError(f"parent directory {parent!r} does not exist")
    real_parent = os.path.realpath(parent)
    base = os.path.basename(ap)
    if base in ("", ".", ".."):
        raise ValueError(f"invalid workspace basename {base!r}")
    candidate = os.path.join(real_parent, base)
    if candidate == "/tmp" or not candidate.startswith("/tmp/"):
        raise ValueError(f"workspace must resolve under /tmp/, got {candidate!r}")
    return candidate

# -- environment -------------------------------------------------------------

def free_bytes(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None

def meminfo():
    info = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, _, v = line.partition(":")
                info[k.strip()] = v.strip()
    except OSError:
        pass
    return info

def os_release():
    rel = {}
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if "=" in line:
                    k, _, v = line.partition("=")
                    rel[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return rel

def tmp_mount_info():
    try:
        with open("/proc/mounts") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == "/tmp":
                    return {"mount": parts[1], "fstype": parts[2], "opts": parts[3]}
    except OSError:
        pass
    return {"mount": "/tmp", "fstype": None, "opts": None}

def _walk_no_follow(root):
    """Yield (relpath, abspath, size, is_link, is_dir_link) without following links."""
    for dp, dns, fns in os.walk(root, followlinks=False):
        dns[:] = [d for d in dns if d != "__pycache__"]
        kept = []
        for d in dns:
            full = os.path.join(dp, d)
            if os.path.islink(full):
                yield (os.path.relpath(full, root), full, 0, True, True)
            else:
                kept.append(d)
        dns[:] = kept
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            is_link = os.path.islink(p)
            yield (os.path.relpath(p, root), p,
                   0 if is_link else st.st_size, is_link, False)

def dir_size(path):
    total = 0
    for _rel, _full, size, is_link, is_dir_link in _walk_no_follow(path):
        if is_link or is_dir_link:
            continue
        total += size
    return total

def dir_allocated_size(path):
    total = 0
    for _rel, full, _size, is_link, is_dir_link in _walk_no_follow(path):
        if is_link or is_dir_link:
            continue
        try:
            st = os.lstat(full)
        except OSError:
            continue
        total += st.st_blocks * 512
    return total

def capture_env(label, workspace):
    return {
        "label": label,
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hostname": socket.gethostname(),
        "uname": " ".join(platform.uname()),
        "os_release": os_release(),
        "runner_python": sys.version.replace("\n", " "),
        "workspace": workspace,
        "workspace_fs_free_bytes": free_bytes(workspace),
        "tmp_free_bytes": free_bytes("/tmp") if os.path.isdir("/tmp") else None,
        "tmp_mount": tmp_mount_info(),
        "meminfo": meminfo(),
        "nproc": os.cpu_count(),
    }

def print_env(env):
    log(f"--- environment ({env['label']}) ---")
    log(f"  time:      {env['time_utc']}")
    log(f"  host:      {env['hostname']}")
    log(f"  uname:     {env['uname']}")
    log(f"  os:        {env['os_release'].get('PRETTY_NAME', '?')}")
    log(f"  runner py: {env['runner_python']}")
    log(f"  nproc:     {env['nproc']}")
    log(f"  ws free:   {env['workspace_fs_free_bytes']} bytes")
    log(f"  /tmp fs:   {env['tmp_mount']['fstype']} opts={env['tmp_mount']['opts']}")
    for k in ("MemTotal", "MemAvailable"):
        if k in env["meminfo"]:
            log(f"  {k}: {env['meminfo'][k]}")

# -- archive (L1) ------------------------------------------------------------

def download_archive(url, dest, max_bytes, timeout):
    """Download with both a per-socket timeout and a wall-clock deadline."""
    deadline = time.monotonic() + timeout
    socket_timeout = max(5, min(30, timeout))
    req = urllib.request.Request(url, headers={"User-Agent": "d063-stress-runner"})
    total = 0
    with urllib.request.urlopen(req, timeout=socket_timeout) as resp, open(dest, "wb") as out:
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"download exceeded wall-clock deadline ({timeout}s)")
            try:
                chunk = resp.read(65536)
            except (socket.timeout, TimeoutError):
                continue
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"archive exceeds cap {max_bytes} bytes")
            out.write(chunk)
    return total

def copy_archive(src, dest, max_bytes):
    size = os.path.getsize(src)
    if size > max_bytes:
        raise RuntimeError(f"archive {size} bytes exceeds cap {max_bytes}")
    shutil.copyfile(src, dest)
    return size

def safe_extract(tar_path, dest):
    """Extract a tar.gz with path/size/count/link guards. Returns member count."""
    dest_real = os.path.realpath(dest)
    count = 0
    total = 0
    with tarfile.open(tar_path, "r:gz") as t:
        for m in t:
            count += 1
            if count > MAX_MEMBERS:
                raise RuntimeError(f"archive has more than {MAX_MEMBERS} members")
            name = m.name
            if name.startswith("/") or os.path.isabs(name):
                raise RuntimeError(f"absolute path in archive: {name!r}")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if ".." in parts or not parts:
                raise RuntimeError(f"unsafe path in archive: {name!r}")
            if m.issym() or m.islnk():
                raise RuntimeError(f"link member in archive: {name!r}")
            outpath = os.path.join(dest, *parts)
            if not os.path.realpath(outpath).startswith(dest_real + os.sep):
                raise RuntimeError(f"path escapes destination: {name!r}")
            if m.isdir():
                os.makedirs(outpath, exist_ok=True)
                continue
            if not m.isfile():
                raise RuntimeError(f"non-regular member in archive: {name!r}")
            if m.size > MAX_FILE_BYTES:
                raise RuntimeError(f"file {name!r} exceeds {MAX_FILE_BYTES} bytes")
            total += m.size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise RuntimeError("archive uncompressed size exceeds cap")
            os.makedirs(os.path.dirname(outpath), exist_ok=True)
            srcf = t.extractfile(m)
            if srcf is None:
                raise RuntimeError(f"cannot read member {name!r}")
            with srcf, open(outpath, "wb") as outf:
                shutil.copyfileobj(srcf, outf, length=65536)
    return count

def find_src_root(extract_dir):
    entries = list(os.listdir(extract_dir))
    if len(entries) != 1 or not os.path.isdir(os.path.join(extract_dir, entries[0])):
        raise RuntimeError(f"archive did not extract to a single top directory: {entries}")
    return os.path.join(extract_dir, entries[0])

# -- interpreters / execution (L3) -------------------------------------------

def discover_pythons(requested):
    found = []
    seen = set()
    for name in (requested or PYTHON_CANDIDATES):
        path = shutil.which(name)
        if not path:
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        try:
            out = subprocess.run(
                [path, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                capture_output=True, text=True, timeout=30)
            ver = out.stdout.strip() if out.returncode == 0 else "unknown"
        except Exception:  # noqa: BLE001
            ver = "unknown"
        found.append({"name": name, "path": path, "version": ver})
    return found

def _kill_group(p, sig):
    try:
        os.killpg(os.getpgid(p.pid), sig)
    except Exception:  # noqa: BLE001
        try:
            p.send_signal(sig)
        except Exception:  # noqa: BLE001
            pass

def run(cmd, cwd, env, timeout, max_output=MAX_SUBPROCESS_OUTPUT):
    """Run a subprocess with a byte-capped capture and process-group kill on timeout."""
    start = time.monotonic()
    try:
        p = subprocess.Popen(
            cmd, cwd=cwd, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"cmd": cmd, "rc": None, "out": "", "err": f"{type(exc).__name__}: {exc}",
                "timed_out": False, "seconds": round(time.monotonic() - start, 2),
                "truncated": False}

    out_buf = bytearray()
    err_buf = bytearray()
    state = {"truncated": False}

    def reader(pipe, buf):
        try:
            while True:
                chunk = pipe.read(65536)
                if not chunk:
                    break
                if len(buf) >= max_output:
                    state["truncated"] = True
                    continue
                take = min(len(chunk), max_output - len(buf))
                buf.extend(chunk[:take])
                if take < len(chunk):
                    state["truncated"] = True
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                pipe.close()
            except Exception:  # noqa: BLE001
                pass

    t_out = threading.Thread(target=reader, args=(p.stdout, out_buf), daemon=True)
    t_err = threading.Thread(target=reader, args=(p.stderr, err_buf), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(p, signal.SIGTERM)
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_group(p, signal.SIGKILL)
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass

    t_out.join(timeout=2)
    t_err.join(timeout=2)

    return {
        "cmd": cmd,
        "rc": p.returncode,
        "out": out_buf.decode("utf-8", "replace"),
        "err": err_buf.decode("utf-8", "replace"),
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - start, 2),
        "truncated": state["truncated"],
    }

def parse_unittest(text):
    ran = skipped = None
    m = re.search(r"Ran (\d+) tests?", text)
    if m:
        ran = int(m.group(1))
    m = re.search(r"skipped=(\d+)", text)
    if m:
        skipped = int(m.group(1))
    elif ran is not None:
        skipped = 0
    ok = bool(re.search(r"^OK", text, re.M))
    failed = bool(re.search(r"^FAILED", text, re.M))
    return {"ran": ran, "skipped": skipped, "ok": ok, "failed": failed}

def build_env(workspace, src):
    env = dict(os.environ)
    tmp = os.path.join(workspace, "tmp")
    os.makedirs(tmp, exist_ok=True)
    env["TMPDIR"] = tmp
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["D063_WORKSPACE"] = workspace
    return env

# -- readdir order confirmation (B1) -----------------------------------------

def capture_readdir_probe(ws):
    probe = os.path.join(ws, "tmp", "readdir-probe")
    os.makedirs(probe, exist_ok=True)
    a = os.path.join(probe, "a.txt")
    b = os.path.join(probe, "b.txt")
    with open(a, "w") as fh:
        fh.write("a")
    with open(b, "w") as fh:
        fh.write("b")
    try:
        order = [e.name for e in os.scandir(probe)]
    except OSError as exc:
        order = [f"<scandir error: {type(exc).__name__}: {exc}>"]
    return {"probe_dir": probe, "created_order": ["a.txt", "b.txt"], "observed_order": order}

DUAL_ORDER_REPRO = r'''
import os, sys, unittest

MODE = sys.argv[1]        # "asc" or "desc"
SRC = sys.argv[2]
TESTNAME = sys.argv[3]
REVERSE = (MODE == "desc")

_orig_scandir = os.scandir
_orig_listdir = os.listdir

def _key(e):
    return getattr(e, "name", e)

class _Iter:
    def __init__(self, items):
        self._it = iter(items)
    def __iter__(self):
        return self
    def __next__(self):
        return next(self._it)
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def close(self):
        pass

def _shim_scandir(path="."):
    entries = list(_orig_scandir(path))
    return _Iter(sorted(entries, key=_key, reverse=REVERSE))

def _shim_listdir(path="."):
    return sorted(_orig_listdir(path), reverse=REVERSE)

os.scandir = _shim_scandir
os.listdir = _shim_listdir

def _patch_modules():
    for m in list(sys.modules.values()):
        if m is None:
            continue
        try:
            if getattr(m, "scandir", None) is _orig_scandir:
                setattr(m, "scandir", _shim_scandir)
            if getattr(m, "listdir", None) is _orig_listdir:
                setattr(m, "listdir", _shim_listdir)
        except Exception:
            pass

sys.path.insert(0, SRC)
os.chdir(SRC)

_patch_modules()
loader = unittest.TestLoader()
suite = loader.loadTestsFromName(TESTNAME)
_patch_modules()
runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
'''

def run_dual_order_repro(ws, src, env, py_path, timeout):
    script_path = os.path.join(ws, "logs", "_dual_order_repro.py")
    with open(script_path, "w") as fh:
        fh.write(DUAL_ORDER_REPRO)
    results = {}
    for mode in ("asc", "desc"):
        r = run([py_path, script_path, mode, src, ORDER_SENSITIVE_TEST],
                cwd=src, env=env, timeout=timeout)
        with open(os.path.join(ws, "logs", f"dual_order_{mode}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
        results[mode] = {"rc": r["rc"], "timed_out": r["timed_out"],
                         "seconds": r["seconds"]}
    confirmed = (results["asc"]["rc"] == 0
                 and results["desc"]["rc"] not in (0, None)
                 and not results["desc"]["timed_out"])
    return results, confirmed

# -- manifest (L4) -----------------------------------------------------------

def write_manifest(workspace):
    rows = []
    links = []
    for rel, full, size, is_link, is_dir_link in _walk_no_follow(workspace):
        if is_link or is_dir_link:
            try:
                target = os.readlink(full)
            except OSError:
                target = "?"
            links.append((rel, target, "dir" if is_dir_link else "file"))
            continue
        rows.append((rel, size, sha256_file(full)))
    rows.sort()
    links.sort()
    lines = ["# d063 workspace manifest", "",
             f"workspace: {workspace}",
             f"generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", "",
             "| file | bytes | sha256 |", "| --- | --- | --- |"]
    for rel, sz, h in rows:
        lines.append(f"| `{rel}` | {sz} | `{h}` |")
    if links:
        lines.append("")
        lines.append("## symlinks (NOT followed)")
        lines.append("")
        lines.append("| path | target | kind |")
        lines.append("| --- | --- | --- |")
        for rel, target, kind in links:
            lines.append(f"| `{rel}` | `{target}` | {kind} |")
    with open(os.path.join(workspace, "logs", "MANIFEST.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return rows, links

# -- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="d063 bounded six-agent cloud stress runner")
    ap.add_argument("--base-dir", default="/tmp",
                    help="where to create the unique workspace (must resolve under /tmp)")
    ap.add_argument("--workdir", default=None,
                    help="explicit workspace path (must not exist; must resolve under /tmp)")
    ap.add_argument("--archive", default=None, help="use a local archive instead of downloading")
    ap.add_argument("--python", action="append", default=None,
                    help="restrict to this interpreter name (repeatable)")
    ap.add_argument("--download-timeout", type=int, default=DEFAULT_DOWNLOAD_TIMEOUT)
    ap.add_argument("--suite-timeout", type=int, default=DEFAULT_SUITE_TIMEOUT)
    ap.add_argument("--smoke-timeout", type=int, default=DEFAULT_SMOKE_TIMEOUT)
    ap.add_argument("--soak-timeout", type=int, default=DEFAULT_SOAK_TIMEOUT)
    ap.add_argument("--edge-timeout", type=int, default=DEFAULT_EDGE_TIMEOUT)
    ap.add_argument("--overall-deadline", type=int, default=DEFAULT_OVERALL_DEADLINE)
    ap.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    args = ap.parse_args()

    overall_start = time.monotonic()
    deadline = overall_start + args.overall_deadline
    summary = {"commit": COMMIT, "archive_url": ARCHIVE_URL,
               "max_concurrent": MAX_CONCURRENT,
               "expected_suite_tests": EXPECTED_SUITE_TESTS,
               "suite_diagnostic_continue": False}

    def remaining():
        return deadline - time.monotonic()

    def stage_timeout(cap):
        return max(1, int(min(cap, remaining())))

    # 1. workspace (B3)
    if args.workdir:
        try:
            ws = canonical_workspace(args.workdir)
        except ValueError as exc:
            log(f"FATAL: {exc}")
            return 1
        if os.path.exists(ws):
            log(f"FATAL: workspace {ws} already exists; refusing to reuse")
            return 1
        os.makedirs(ws, mode=0o700)
    else:
        try:
            real_base = os.path.realpath(args.base_dir)
        except OSError as exc:
            log(f"FATAL: cannot resolve --base-dir {args.base_dir!r}: {exc}")
            return 1
        if real_base == "/tmp" or not real_base.startswith("/tmp/"):
            log(f"FATAL: --base-dir must resolve under /tmp/ (got {real_base!r})")
            return 1
        os.makedirs(real_base, exist_ok=True)
        ws = tempfile.mkdtemp(prefix=f"d063-{COMMIT[:8]}-", dir=real_base)
        ws = os.path.realpath(ws)

    real_ws = os.path.realpath(ws)
    if real_ws == "/tmp" or not real_ws.startswith("/tmp/"):
        log(f"FATAL: workspace realpath escaped /tmp: {real_ws!r}")
        return 1
    os.chmod(ws, 0o700)
    os.makedirs(os.path.join(ws, "logs"), mode=0o700, exist_ok=True)
    log(f"workspace: {ws} (mode 0700)")
    summary["workspace"] = ws
    summary["workspace_mode"] = "0700"

    # 1b. payload identity
    if not os.path.isfile(STRESS_CHECKS_PY):
        log(f"FAIL-CLOSED: payload {STRESS_CHECKS_PY} not found")
        return 1
    payload_sha = sha256_file(STRESS_CHECKS_PY)
    summary["payload_sha256"] = payload_sha
    if payload_sha != STRESS_CHECKS_SHA256:
        log(f"FAIL-CLOSED: payload sha256 {payload_sha} != pinned {STRESS_CHECKS_SHA256}")
        return 1
    log(f"payload stress_checks.py sha256 OK: {payload_sha}")

    # 2. env before + resource gate
    env_before = capture_env("before", ws)
    print_env(env_before)
    with open(os.path.join(ws, "logs", "env_before.json"), "w") as fh:
        json.dump(env_before, fh, indent=2)
    preflight = []
    if env_before["workspace_fs_free_bytes"] is None:
        preflight.append("cannot determine free space on workspace filesystem")
    elif env_before["workspace_fs_free_bytes"] < args.min_free_bytes:
        preflight.append(f"insufficient free space: {env_before['workspace_fs_free_bytes']} "
                         f"< {args.min_free_bytes} bytes")
    if preflight:
        log("FAIL-CLOSED (preflight): " + "; ".join(preflight))
        return 1

    # 3. archive
    tgz = os.path.join(ws, "archive.tar.gz")
    try:
        if args.archive:
            size = copy_archive(args.archive, tgz, MAX_ARCHIVE_BYTES)
            log(f"copied archive {args.archive} ({size} bytes)")
        else:
            size = download_archive(ARCHIVE_URL, tgz, MAX_ARCHIVE_BYTES, args.download_timeout)
            log(f"downloaded archive ({size} bytes)")
        summary["archive_bytes"] = size
        summary["archive_sha256"] = sha256_file(tgz)
    except Exception as exc:  # noqa: BLE001
        log(f"FAIL-CLOSED (archive): {type(exc).__name__}: {exc}")
        return 1

    # 4. extract
    extract_dir = os.path.join(ws, "extract")
    try:
        os.makedirs(extract_dir, exist_ok=True)
        members = safe_extract(tgz, extract_dir)
        src = find_src_root(extract_dir)
        log(f"extracted {members} members; src root = {os.path.basename(src)}")
        summary["members"] = members
    except Exception as exc:  # noqa: BLE001
        log(f"FAIL-CLOSED (extract): {type(exc).__name__}: {exc}")
        return 1

    # 5. identity (B2, fail-closed BEFORE any execution)
    problems, extras, hard_extras = verify_identities(src, EXPECTED_BLOBS)
    with open(os.path.join(ws, "logs", "identity.txt"), "w") as fh:
        fh.write(f"commit: {COMMIT}\nexpected executable files: {len(EXPECTED_BLOBS)}\n")
        fh.write("problems:\n" + ("\n".join("  " + p for p in problems) if problems
                                  else "  (none)") + "\n")
        fh.write("extra files (informational):\n" +
                 ("\n".join("  " + e for e in extras) if extras else "  (none)") + "\n")
        fh.write("fail-closed extras:\n" +
                 ("\n".join("  " + e for e in hard_extras) if hard_extras
                  else "  (none)") + "\n")
    if extras:
        log(f"note: {len(extras)} unexpected non-executable file(s): {extras[:5]}")
    if problems or hard_extras:
        log("FAIL-CLOSED (identity):")
        for p in problems:
            log(f"  {p}")
        for e in hard_extras:
            log(f"  {e}")
        return 1
    log(f"identity OK: all {len(EXPECTED_BLOBS)} pinned executable files match; "
        f"no unexpected importable/executable or symlinked file")

    # 6. readdir order confirmation + deterministic dual-order repro (B1)
    tmp_info = tmp_mount_info()
    probe = capture_readdir_probe(ws)
    log(f"/tmp mount: {tmp_info['fstype']} opts={tmp_info['opts']}")
    log(f"native readdir probe order: {probe['observed_order']} "
        f"(created a.txt before b.txt)")

    pythons = discover_pythons(args.python)
    summary["pythons"] = pythons
    log(f"interpreters found: {[p['name'] + '=' + p['version'] for p in pythons]}")
    if args.python:
        for want in args.python:
            if not any(p["name"] == want for p in pythons):
                log(f"note: requested interpreter {want!r} is unavailable")
    if not pythons:
        log("FAIL-CLOSED: no Python interpreter available")
        return 1

    env = build_env(ws, src)

    dual_results, dual_confirmed = run_dual_order_repro(
        ws, src, env, pythons[0]["path"], stage_timeout(min(120, args.suite_timeout)))
    log(f"dual-order repro: asc rc={dual_results['asc']['rc']} "
        f"desc rc={dual_results['desc']['rc']} confirmed={dual_confirmed}")
    order_report = {
        "tmp_mount": tmp_info,
        "native_probe": probe,
        "dual_order_repro": dual_results,
        "confirmed_order_sensitive_defect": dual_confirmed,
        "order_sensitive_test": ORDER_SENSITIVE_TEST,
    }
    with open(os.path.join(ws, "logs", "readdir_order_confirmation.json"), "w") as fh:
        json.dump(order_report, fh, indent=2)
    summary["readdir_order_confirmation"] = {
        "tmp_fstype": tmp_info["fstype"],
        "native_observed_order": probe["observed_order"],
        "dual_order_repro": dual_results,
        "confirmed_order_sensitive_defect": dual_confirmed,
    }

    # 7. committed suite (STRICT gate; diagnostic continue on failure)
    suite_results = {}
    suite_failures = []
    stage_failures = []

    for py in pythons:
        tag = py["name"]
        log(f"=== committed suite on {tag} ({py['version']}) ===")
        r = run([py["path"], "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=src, env=env, timeout=stage_timeout(args.suite_timeout))
        parsed = parse_unittest(r["out"] + r["err"])
        r.update(parsed)
        with open(os.path.join(ws, "logs", f"suite_{tag}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} "
                     f"truncated={r['truncated']} seconds={r['seconds']}\n")
        suite_results[tag] = r
        log(f"  ran={parsed['ran']} skipped={parsed['skipped']} ok={parsed['ok']} "
            f"failed={parsed['failed']} exit={r['rc']} timeout={r['timed_out']} "
            f"trunc={r['truncated']}")
        if r["timed_out"]:
            suite_failures.append(f"suite timeout on {tag}")
        elif r["rc"] != 0 or not parsed["ok"]:
            suite_failures.append(f"suite failed on {tag} (exit {r['rc']})")
        if parsed["ran"] is not None and parsed["ran"] != EXPECTED_SUITE_TESTS:
            suite_failures.append(f"suite on {tag} ran {parsed['ran']} != {EXPECTED_SUITE_TESTS}")

    summary["suite"] = {t: {k: r[k] for k in ("rc", "ran", "skipped", "ok", "failed",
                                              "timed_out", "truncated", "seconds")}
                        for t, r in suite_results.items()}
    summary["suite_failures"] = suite_failures

    if suite_failures:
        # B1: never relabel a known fail as pass; still run stages for evidence.
        log("SUITE DID NOT PASS - continuing to stress stages for diagnostic evidence "
            "(overall exit will remain NONZERO)")
        summary["suite_diagnostic_continue"] = True

    # 8/9/10. stress stages (fixed allow-listed actions only) (L2)
    py_path = pythons[0]["path"]
    stages = [("smoke", args.smoke_timeout), ("soak", args.soak_timeout),
              ("edges", args.edge_timeout)]
    stage_summary = {}
    smoke_passed = False
    for action, cap in stages:
        if remaining() <= 5:
            stage_failures.append(f"overall deadline exceeded before stage {action}")
            break
        if action == "soak" and not smoke_passed:
            stage_summary["soak"] = {"skipped": "smoke did not pass"}
            log("=== stress stage: soak (skipped: smoke did not pass) ===")
            continue
        log(f"=== stress stage: {action} ===")
        internal_deadline = max(5, int(min(cap - 10, remaining() - 5)))
        cmd = [py_path, STRESS_CHECKS_PY, action, src,
               "--deadline-seconds", str(internal_deadline)]
        r = run(cmd, cwd=ws, env=env, timeout=stage_timeout(cap))
        with open(os.path.join(ws, "logs", f"stress_{action}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} "
                     f"truncated={r['truncated']} seconds={r['seconds']}\n")
        stress_json = None
        for line in r["out"].splitlines():
            if line.startswith("STRESS_JSON: "):
                try:
                    stress_json = json.loads(line[len("STRESS_JSON: "):])
                except ValueError:
                    stress_json = None
        stage_summary[action] = {
            "rc": r["rc"], "timed_out": r["timed_out"], "truncated": r["truncated"],
            "seconds": r["seconds"],
            "result": (stress_json or {}).get("result"),
            "calls_completed": (stress_json or {}).get("calls_completed"),
            "internal_deadline_seconds": internal_deadline,
        }
        passed = (not r["timed_out"] and r["rc"] == 0
                  and (stress_json or {}).get("result") == "PASS")
        if r["timed_out"]:
            stage_failures.append(f"stress {action} timed out")
        elif not passed:
            stage_failures.append(f"stress {action} did not pass (exit {r['rc']})")
        if action == "smoke" and passed:
            smoke_passed = True
        log(f"  {action}: rc={r['rc']} timeout={r['timed_out']} "
            f"calls={(stress_json or {}).get('calls_completed')}")
    summary["stages"] = stage_summary

    # 11. env after + workspace size gate + manifest (L4)
    env_after = capture_env("after", ws)
    print_env(env_after)
    with open(os.path.join(ws, "logs", "env_after.json"), "w") as fh:
        json.dump(env_after, fh, indent=2)
    ws_bytes = dir_size(ws)
    ws_alloc = dir_allocated_size(ws)
    summary["workspace_bytes"] = ws_bytes
    summary["workspace_allocated_bytes"] = ws_alloc
    if ws_bytes > MAX_WORKSPACE_BYTES:
        stage_failures.append(f"workspace {ws_bytes} bytes exceeds {MAX_WORKSPACE_BYTES}")

    return _finalize(ws, summary, suite_failures + stage_failures, overall_start)

def _finalize(ws, summary, failures, overall_start):
    summary["failures"] = failures
    summary["result"] = "PASS" if not failures else "FAIL"
    summary["seconds"] = round(time.monotonic() - overall_start, 2)
    with open(os.path.join(ws, "logs", "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    rows, links = write_manifest(ws)
    log("")
    log("=== summary ===")
    for t, r in summary.get("suite", {}).items():
        log(f"  suite {t}: ran={r['ran']} skipped={r['skipped']} ok={r['ok']}")
    if summary.get("suite_diagnostic_continue"):
        log("  suite diagnostic continue: True (stages ran for evidence only)")
    roc = summary.get("readdir_order_confirmation") or {}
    if roc:
        log(f"  /tmp fstype: {roc.get('tmp_fstype')}")
        log(f"  native readdir order: {roc.get('native_observed_order')}")
        log(f"  dual-order confirmed: {roc.get('confirmed_order_sensitive_defect')}")
    for a, s in summary.get("stages", {}).items():
        if "skipped" in s:
            log(f"  stage {a}: skipped ({s['skipped']})")
        else:
            log(f"  stage {a}: {s.get('result')} calls={s.get('calls_completed')} "
                f"trunc={s.get('truncated')}")
    log(f"  workspace apparent bytes: {summary.get('workspace_bytes')}")
    log(f"  workspace allocated bytes: {summary.get('workspace_allocated_bytes')}")
    log(f"  manifest entries: {len(rows)} files, {len(links)} symlinks (not followed)")
    if failures:
        log("RESULT: FAIL (fail-closed)")
        for f in failures:
            log(f"  !! {f}")
    else:
        log("RESULT: PASS")
    log("")
    log("Exact target invocation (single command, from the runner directory):")
    log("  python3 run_cloud_stress.py")
    log("")
    log("Result packaging command (evidence is retained; run to collect it):")
    base = os.path.dirname(ws)
    log(f"  tar -czf d063-evidence-{COMMIT[:8]}.tar.gz -C {base} {os.path.basename(ws)}")
    log("")
    log("Safe, precise cleanup (run only when evidence is no longer needed):")
    log(f"  rm -rf {ws}")
    return 0 if not failures else 1

if __name__ == "__main__":
    sys.exit(main())

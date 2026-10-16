#!/usr/bin/env python3
"""d063 bounded six-agent cloud stress runner (stdlib only).

Provenance: written for d063 by reusing the proven d014/d038 GitHub-delivered
runner pattern (Dolesh-avkalan/drop drive-tool/readonly-core/d014-cloud-validation).
It is authored and sandbox-tested on the author's side; it does NOT run on the
target from here and NO target result is fabricated. The director runs it on
the separate target instance through the existing Cloud Shell SSH.

What it does, in order, and fails closed at every gate:

  1. creates a NEW unique workspace (default /tmp/d063-<commit8>-<uniq>);
  2. captures host/version/filesystem/resources BEFORE and gates on free space;
  3. downloads the PINNED GitHub archive (codeload tar.gz of the pinned commit)
     with a byte cap and a wall-clock timeout, or copies a supplied archive;
  4. extracts it with path/size/count/link guards (no absolute or '..' paths, no
     symlinks/hardlinks, per-file and total size caps, member-count cap);
  5. verifies every pinned EXECUTABLE SOURCE/TEST file's git blob sha1 against
     the pinned commit's known hashes BEFORE executing anything (fail-closed);
  6. runs the committed 506 suite on every available Python interpreter;
  7. runs a bounded 600-call six-agent backend SMOKE;
  8. ONLY if the smoke passes, runs a bounded 10000-call six-agent backend SOAK;
  9. runs raw edge checks (grants, races, refusal, caps, EOF, leases, fault);
 10. captures resources AFTER, gates the workspace size, and writes a
     SHA-256/length manifest and a summary.

Fixed allow-list of executed actions only (environment capture, committed
suite, smoke, soak, edges). There is NO arbitrary shell/job payload option, no
credential, no cloud API, no install/reboot/service/public binding and no real
root. Only a fresh unique /tmp workspace is touched; TMPDIR lives inside it and
bytecode writing is disabled. Evidence is retained (no automatic cleanup).

Exit 0 only if identity, resources, suite, smoke, soak and edge checks all pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

# -- pins --------------------------------------------------------------------

OWNER = "Dolesh-avkalan"
REPO = "drive-tool"
COMMIT = "b7f8d17b9dcc4aec68d54b38f994290e05264e67"
ARCHIVE_URL = f"https://codeload.github.com/{OWNER}/{REPO}/tar.gz/{COMMIT}"

# git blob sha1 of every EXECUTABLE source/test file at the pinned commit.
# Verified against the published commit before anything is executed.
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
    problems = []
    for rel, want in sorted(expected.items()):
        p = os.path.join(src, rel)
        if not os.path.isfile(p):
            problems.append(f"MISSING {rel}")
            continue
        with open(p, "rb") as fh:
            got = git_blob_sha1(fh.read())
        if got != want:
            problems.append(f"MISMATCH {rel}: got {got} want {want}")
    extra = []
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), src)
            if rel not in expected:
                extra.append(rel)
    return problems, extra


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


def dir_size(path):
    total = 0
    for dp, dns, fns in os.walk(path):
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                total += os.path.getsize(p)
            except OSError:
                pass
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
    for k in ("MemTotal", "MemAvailable"):
        if k in env["meminfo"]:
            log(f"  {k}: {env['meminfo'][k]}")


# -- archive -----------------------------------------------------------------

def download_archive(url, dest, max_bytes, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "d063-stress-runner"})
    total = 0
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
        while True:
            chunk = resp.read(65536)
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


# -- interpreters / execution ------------------------------------------------

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


def run(cmd, cwd, env, timeout):
    start = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return {"cmd": cmd, "rc": p.returncode, "out": p.stdout, "err": p.stderr,
                "timed_out": False, "seconds": round(time.time() - start, 2)}
    except subprocess.TimeoutExpired as exc:
        def _txt(v):
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return {"cmd": cmd, "rc": None, "out": _txt(exc.stdout), "err": _txt(exc.stderr),
                "timed_out": True, "seconds": round(time.time() - start, 2)}
    except Exception as exc:  # noqa: BLE001
        return {"cmd": cmd, "rc": None, "out": "", "err": f"{type(exc).__name__}: {exc}",
                "timed_out": False, "seconds": round(time.time() - start, 2)}


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


# -- manifest ----------------------------------------------------------------

def write_manifest(workspace):
    rows = []
    for dp, dns, fns in os.walk(workspace):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rows.append((os.path.relpath(p, workspace), os.path.getsize(p), sha256_file(p)))
    rows.sort()
    lines = ["# d063 workspace manifest", "",
             f"workspace: {workspace}",
             f"generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", "",
             "| file | bytes | sha256 |", "| --- | --- | --- |"]
    for rel, sz, h in rows:
        lines.append(f"| `{rel}` | {sz} | `{h}` |")
    with open(os.path.join(workspace, "logs", "MANIFEST.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return rows


# -- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="d063 bounded six-agent cloud stress runner")
    ap.add_argument("--base-dir", default="/tmp", help="where to create the unique workspace")
    ap.add_argument("--workdir", default=None, help="explicit workspace path (must not exist)")
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
    failures = []
    summary = {"commit": COMMIT, "archive_url": ARCHIVE_URL,
               "max_concurrent": MAX_CONCURRENT,
               "expected_suite_tests": EXPECTED_SUITE_TESTS}

    def remaining():
        return deadline - time.monotonic()

    def stage_timeout(cap):
        return max(1, int(min(cap, remaining())))

    # 1. workspace
    if args.workdir:
        ws = args.workdir
        if os.path.exists(ws):
            log(f"FATAL: workspace {ws} already exists; refusing to reuse")
            return 1
        os.makedirs(ws)
    else:
        os.makedirs(args.base_dir, exist_ok=True)
        ws = tempfile.mkdtemp(prefix=f"d063-{COMMIT[:8]}-", dir=args.base_dir)
    os.makedirs(os.path.join(ws, "logs"), exist_ok=True)
    log(f"workspace: {ws}")
    summary["workspace"] = ws

    # 1b. verify the fixed payload identity before anything runs
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
    if env_before["workspace_fs_free_bytes"] is None:
        failures.append("cannot determine free space on workspace filesystem")
    elif env_before["workspace_fs_free_bytes"] < args.min_free_bytes:
        failures.append(f"insufficient free space: {env_before['workspace_fs_free_bytes']} "
                        f"< {args.min_free_bytes} bytes")
    if failures:
        log("FAIL-CLOSED (preflight): " + "; ".join(failures))
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

    # 5. identity (BEFORE executing anything)
    problems, extra = verify_identities(src, EXPECTED_BLOBS)
    with open(os.path.join(ws, "logs", "identity.txt"), "w") as fh:
        fh.write(f"commit: {COMMIT}\nexpected executable files: {len(EXPECTED_BLOBS)}\n")
        fh.write("problems:\n" + ("\n".join(problems) if problems else "  (none)") + "\n")
        fh.write("extra files:\n" +
                 ("\n".join("  " + e for e in extra) if extra else "  (none)") + "\n")
    if extra:
        log(f"note: {len(extra)} file(s) present beyond the pinned set: {extra[:5]}")
    if problems:
        log("FAIL-CLOSED (identity):")
        for p in problems:
            log(f"  {p}")
        return 1
    log(f"identity OK: all {len(EXPECTED_BLOBS)} executable files match pinned blobs")

    # 6. interpreters + committed suite
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
    suite_results = {}
    for py in pythons:
        tag = py["name"]
        log(f"=== committed suite on {tag} ({py['version']}) ===")
        r = run([py["path"], "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=src, env=env, timeout=stage_timeout(args.suite_timeout))
        parsed = parse_unittest(r["out"] + r["err"])
        r.update(parsed)
        with open(os.path.join(ws, "logs", f"suite_{tag}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
        suite_results[tag] = r
        log(f"  ran={parsed['ran']} skipped={parsed['skipped']} ok={parsed['ok']} "
            f"failed={parsed['failed']} exit={r['rc']} timeout={r['timed_out']}")
        if r["timed_out"]:
            failures.append(f"suite timeout on {tag}")
        elif r["rc"] != 0 or not parsed["ok"]:
            failures.append(f"suite failed on {tag} (exit {r['rc']})")
        elif parsed["ran"] != EXPECTED_SUITE_TESTS:
            failures.append(f"suite on {tag} ran {parsed['ran']} != {EXPECTED_SUITE_TESTS}")
    summary["suite"] = {t: {k: r[k] for k in ("rc", "ran", "skipped", "ok", "failed",
                                              "timed_out", "seconds")}
                        for t, r in suite_results.items()}
    if failures:
        log("FAIL-CLOSED: committed suite did not pass; not running stress stages")
        _finalize(ws, summary, failures, overall_start)
        return 1

    # 7/8/9. stress stages (fixed allow-listed actions only)
    py = pythons[0]["path"]
    stages = [("smoke", args.smoke_timeout), ("soak", args.soak_timeout),
              ("edges", args.edge_timeout)]
    stage_summary = {}
    for action, cap in stages:
        if remaining() <= 5:
            failures.append(f"overall deadline exceeded before stage {action}")
            break
        log(f"=== stress stage: {action} ===")
        r = run([py, STRESS_CHECKS_PY, action, src], cwd=ws, env=env,
                timeout=stage_timeout(cap))
        with open(os.path.join(ws, "logs", f"stress_{action}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n{r['out']}\n--- stderr ---\n{r['err']}\n")
            fh.write(f"EXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
        stress_json = None
        for line in r["out"].splitlines():
            if line.startswith("STRESS_JSON: "):
                try:
                    stress_json = json.loads(line[len("STRESS_JSON: "):])
                except ValueError:
                    stress_json = None
        stage_summary[action] = {
            "rc": r["rc"], "timed_out": r["timed_out"], "seconds": r["seconds"],
            "result": (stress_json or {}).get("result"),
            "calls_completed": (stress_json or {}).get("calls_completed"),
        }
        if r["timed_out"]:
            failures.append(f"stress {action} timed out")
            break
        if r["rc"] != 0 or (stress_json or {}).get("result") != "PASS":
            failures.append(f"stress {action} did not pass (exit {r['rc']})")
            if action == "smoke":
                break   # soak is gated on smoke
        log(f"  {action}: rc={r['rc']} timeout={r['timed_out']} "
            f"calls={(stress_json or {}).get('calls_completed')}")
    summary["stages"] = stage_summary

    # 10. env after + workspace size gate + manifest
    env_after = capture_env("after", ws)
    print_env(env_after)
    with open(os.path.join(ws, "logs", "env_after.json"), "w") as fh:
        json.dump(env_after, fh, indent=2)
    ws_bytes = dir_size(ws)
    summary["workspace_bytes"] = ws_bytes
    if ws_bytes > MAX_WORKSPACE_BYTES:
        failures.append(f"workspace {ws_bytes} bytes exceeds {MAX_WORKSPACE_BYTES}")

    return _finalize(ws, summary, failures, overall_start)


def _finalize(ws, summary, failures, overall_start):
    summary["failures"] = failures
    summary["result"] = "PASS" if not failures else "FAIL"
    summary["seconds"] = round(time.monotonic() - overall_start, 2)
    with open(os.path.join(ws, "logs", "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    rows = write_manifest(ws)
    log("")
    log("=== summary ===")
    for t, r in summary.get("suite", {}).items():
        log(f"  suite {t}: ran={r['ran']} skipped={r['skipped']} ok={r['ok']}")
    for a, s in summary.get("stages", {}).items():
        log(f"  stage {a}: {s.get('result')} calls={s.get('calls_completed')}")
    log(f"  workspace bytes: {summary.get('workspace_bytes')}")
    log(f"  manifest entries: {len(rows)}")
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

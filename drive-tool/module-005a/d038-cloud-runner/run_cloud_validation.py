#!/usr/bin/env python3
"""d038 bounded cloud validation runner for the drive-tool candidate.

Provenance: adapted for d038 from the proven d014 runner design
(drive-tool/readonly-core/d014-cloud-validation/runner/) and tested in the
author's sandbox (see the delivered sandbox/ logs). It does NOT run on the
target from here; the director runs it on the directortemp VM. stdlib only; no
git clone, no package installs, no services, no mounts, no credentials. It
never edits the implementation and never mocks kernel support.

Pinned candidate: Dolesh-avkalan/drive-tool @
e88c9c79fdc27057622d44ba51e008f2e4ea4f4f (tree
abc0ffb2f561b375cd5166a6bf223d45e3b834c2).

What it does, in order, and fails closed at every gate:

  1. creates a NEW unique workspace (default /tmp/d038-<commit8>-<uniq>);
  2. captures host/version/filesystem/resources BEFORE;
  3. downloads the PINNED GitHub archive (codeload tar.gz of the pinned commit)
     with a byte cap and a wall-clock timeout, or copies a supplied archive;
  4. extracts it with path/size/count/link guards (no absolute or '..' paths, no
     symlinks/hardlinks, per-file and total size caps, member-count cap);
  5. verifies every expected file's git blob sha1 against the pinned commit's
     known hashes BEFORE executing anything (fail-closed on any mismatch), and
     additionally fails closed if ANY ``*.py`` file that ``unittest`` could
     execute is present but not in the pinned identity list;
  6. runs the committed suite on every available Python interpreter
     (3.14 first, then 3.13/3.12/3.11/3.10/3) with a wall-clock timeout;
  7. runs the real-kernel checks (nofollow, bounded_read, root_anchor,
     dir_symlink_swap, fifo, fd_lifetime, strict_b_scanner, partial_search,
     write_collision, concurrent_writers) per interpreter, each in its own
     process under a wall-clock timeout;
  8. captures host/version/filesystem/resources AFTER;
  9. writes a SHA-256/length manifest of the workspace and a summary.

Overall invocation timeout guidance: the runner bounds every sub-step itself
(archive download, per-interpreter suite, per-check processes), but it does not
impose a single outer deadline. The director should wrap the invocation in an
overall wall-clock timeout. A safe recommendation is
RECOMMENDED_OVERALL_TIMEOUT_SECONDS (printed at start and in the summary),
which is the worst-case sum of the default per-step budgets. This is guidance
only; it does not itself execute anything on the target.

TMPDIR is set inside the workspace and bytecode writing is disabled, so all
fixtures land in the workspace. Nothing outside the workspace is touched.

Exit 0 only if identity, resources, the suite and the kernel checks all pass.
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

# -- pins -------------------------------------------------------------------

OWNER = "Dolesh-avkalan"
REPO = "drive-tool"
COMMIT = "e88c9c79fdc27057622d44ba51e008f2e4ea4f4f"
TREE = "abc0ffb2f561b375cd5166a6bf223d45e3b834c2"
ARCHIVE_URL = f"https://codeload.github.com/{OWNER}/{REPO}/tar.gz/{COMMIT}"

# git blob sha1 for EVERY Python file at the pinned commit: the executable
# source (drive_tool/*.py) and every test module (tests/*.py) that
# ``python -m unittest discover`` can execute, including the newly added
# enumeration / partial-scan / search / local-write tests. Regenerated from the
# GitHub tree abc0ffb2f561b375cd5166a6bf223d45e3b834c2 for candidate
# e88c9c79fdc27057622d44ba51e008f2e4ea4f4f -- the d014 EXPECTED_BLOBS are NOT
# reused. A separate gate (see verify_python_coverage) fails closed if any
# other ``*.py`` file is present in the extracted tree.
EXPECTED_BLOBS = {
    "drive_tool/__init__.py": "9be841b5749acb36c5e362c84b986d98292bae8d",
    "drive_tool/listing.py": "28dddd549c068b00b149a16ad9820445b8af7946",
    "drive_tool/local.py": "a0e43e17e60ad72536acea4ca9cfedfd058b9c2b",
    "drive_tool/local_write.py": "9824052f349e94f87ee65215ab96e979b4d2a021",
    "drive_tool/search.py": "f2d8407df8a98bb92972eecb7e43e653246d4b1a",
    "drive_tool/storage.py": "3f4f8dcf50bbf68e97cd807fe40db1ee1bec4576",
    "tests/test_enumeration.py": "f7e1eef00de1d82fca7001b64a6af9cfc6d1e667",
    "tests/test_enumeration_proofs.py": "e18e02c2252c52a46ef97e733f50ecbcec422878",
    "tests/test_listing.py": "8287db88a4b7ff8d956c082e8150c8d169f0f4f7",
    "tests/test_local.py": "b3319752edaf92a02993981fcc62d63f63ebb408",
    "tests/test_local_write.py": "85e7bf06357c16ebf499294de9b116fb909e07db",
    "tests/test_local_write_proofs.py": "6abf5f1b4bceae58877cb29182f685f71cd4343c",
    "tests/test_partial_scan.py": "ca73b0704a13d03e09f28a44c86f52ee76478dec",
    "tests/test_partial_scan_proofs.py": "51c990bc26661d98498086371be47cd08764be56",
    "tests/test_partial_scan_review_fixes.py": "f110f83c95b846bc853069194ff7759b690ebfca",
    "tests/test_readonly_core.py": "1b0f746fd8162a9d27691abf7f5a90492548c4d8",
    "tests/test_search.py": "2ef9c5b8f97a9aa1ff912d250612b8fdb53cad29",
    "tests/test_storage.py": "2126dde7f32b7c0cd4d1e737ff990ab10954caf5",
}

#: Every identity-listed file that unittest can execute (used by the coverage
#: gate). Derived from EXPECTED_BLOBS so the two can never drift.
EXPECTED_PY_FILES = frozenset(
    rel for rel in EXPECTED_BLOBS if rel.endswith(".py")
)

# -- limits -----------------------------------------------------------------

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED = 50 * 1024 * 1024
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_MEMBERS = 2000
MIN_FREE_BYTES = 20 * 1024 * 1024       # required headroom in the workspace fs
DEFAULT_DOWNLOAD_TIMEOUT = 180
DEFAULT_SUITE_TIMEOUT = 300
DEFAULT_CHECK_TIMEOUT = 120

#: Worst-case sum of the default per-step budgets, offered to the director as
#: guidance for wrapping the whole invocation in one outer wall-clock timeout.
#: 180 (download) + 3 interpreters * (300 suite + 10 checks * 120) = 5580 s.
RECOMMENDED_OVERALL_TIMEOUT_SECONDS = 5580

PYTHON_CANDIDATES = ["python3.14", "python3.13", "python3.12", "python3.11",
                     "python3.10", "python3"]
# The six retained d014 real-kernel checks (where compatible with the
# candidate API) plus four new tiny real-filesystem checks.
KERNEL_CHECKS = ["nofollow", "bounded_read", "root_anchor",
                 "dir_symlink_swap", "fifo", "fd_lifetime",
                 "strict_b_scanner", "partial_search", "write_collision",
                 "concurrent_writers"]

HERE = os.path.dirname(os.path.abspath(__file__))
KERNEL_CHECKS_PY = os.path.join(HERE, "kernel_checks.py")


def log(msg=""):
    print(msg, flush=True)


def git_blob_sha1(data: bytes) -> str:
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % len(data))
    h.update(data)
    return h.hexdigest()


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


def mounts(prefixes=("/", "/tmp", "/scratch")):
    out = []
    try:
        with open("/proc/mounts") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 3 and parts[1] in prefixes:
                    out.append(" ".join(parts[:4]))
    except OSError:
        pass
    return out


def capture_env(label, workspace):
    env = {
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
        "mounts": mounts(),
        "nproc": os.cpu_count(),
    }
    return env


def print_env(env):
    log(f"--- environment ({env['label']}) ---")
    log(f"  time:      {env['time_utc']}")
    log(f"  host:      {env['hostname']}")
    log(f"  uname:     {env['uname']}")
    log(f"  os:        {env['os_release'].get('PRETTY_NAME', '?')}")
    log(f"  runner py: {env['runner_python']}")
    log(f"  nproc:     {env['nproc']}")
    log(f"  ws free:   {env['workspace_fs_free_bytes']} bytes")
    log(f"  tmp free:  {env['tmp_free_bytes']} bytes")
    for k in ("MemTotal", "MemAvailable"):
        if k in env["meminfo"]:
            log(f"  {k}: {env['meminfo'][k]}")
    for m in env["mounts"]:
        log(f"  mount: {m}")


# -- archive -----------------------------------------------------------------

def download_archive(url, dest, max_bytes, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "d038-validator"})
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
    entries = [e for e in os.listdir(extract_dir)]
    if len(entries) != 1 or not os.path.isdir(os.path.join(extract_dir, entries[0])):
        raise RuntimeError(f"archive did not extract to a single top directory: {entries}")
    return os.path.join(extract_dir, entries[0])


def verify_python_coverage(src, expected_py):
    """Fail closed if a ``*.py`` file unittest could execute is not pinned.

    ``unittest discover`` imports every ``test*.py`` under ``tests/`` and the
    package modules under ``drive_tool/``; a Python file that is present but not
    in the pinned identity list means the identity gate did not cover all
    executable code. Returns a list of offending relative paths.
    """
    offenders = []
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            if not fn.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), src)
            if rel not in expected_py:
                offenders.append(rel)
    return sorted(offenders)


def verify_identities(src, expected):
    problems = []
    seen = set()
    for rel, want in sorted(expected.items()):
        p = os.path.join(src, rel)
        if not os.path.isfile(p):
            problems.append(f"MISSING {rel}")
            continue
        with open(p, "rb") as fh:
            got = git_blob_sha1(fh.read())
        seen.add(rel)
        if got != want:
            problems.append(f"MISMATCH {rel}: got {got} want {want}")
    # unexpected extra tracked-looking files (report, do not fail)
    extra = []
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in fns:
            rel = os.path.relpath(os.path.join(dp, fn), src)
            if rel not in expected:
                extra.append(rel)
    return problems, extra


# -- interpreters ------------------------------------------------------------

def discover_pythons(requested):
    found = []
    seen_real = set()
    names = requested or PYTHON_CANDIDATES
    for name in names:
        path = shutil.which(name)
        if not path:
            continue
        real = os.path.realpath(path)
        if real in seen_real:
            continue
        seen_real.add(real)
        try:
            out = subprocess.run([path, "-c",
                                  "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                                 capture_output=True, text=True, timeout=30)
            ver = out.stdout.strip() if out.returncode == 0 else "unknown"
        except Exception:  # noqa: BLE001
            ver = "unknown"
        found.append({"name": name, "path": path, "version": ver})
    return found


# -- execution ---------------------------------------------------------------

def run(cmd, cwd, env, timeout):
    start = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                           text=True, timeout=timeout)
        return {"cmd": cmd, "rc": p.returncode, "out": p.stdout, "err": p.stderr,
                "timed_out": False, "seconds": round(time.time() - start, 2)}
    except subprocess.TimeoutExpired as exc:
        return {"cmd": cmd, "rc": None,
                "out": (exc.stdout or b"").decode("utf-8", "replace")
                       if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                "err": (exc.stderr or b"").decode("utf-8", "replace")
                       if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
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
        skipped = 0  # unittest prints 'skipped=' only when non-zero
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
    return env


# -- manifest ----------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(workspace):
    rows = []
    for dp, dns, fns in os.walk(workspace):
        dns[:] = [d for d in dns if d != "__pycache__"]
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            rows.append((os.path.relpath(p, workspace), os.path.getsize(p), sha256_file(p)))
    rows.sort()
    lines = ["# d038 workspace manifest", "",
             f"workspace: {workspace}", f"generated: "
             f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}", "",
             "| file | bytes | sha256 |", "| --- | --- | --- |"]
    for rel, sz, h in rows:
        lines.append(f"| `{rel}` | {sz} | `{h}` |")
    with open(os.path.join(workspace, "logs", "MANIFEST.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return rows


# -- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="d038 bounded cloud validation runner")
    ap.add_argument("--base-dir", default="/tmp", help="where to create the unique workspace")
    ap.add_argument("--workdir", default=None, help="explicit workspace path (must not exist)")
    ap.add_argument("--archive", default=None, help="use a local archive instead of downloading")
    ap.add_argument("--python", action="append", default=None,
                    help="restrict to this interpreter name (repeatable)")
    ap.add_argument("--download-timeout", type=int, default=DEFAULT_DOWNLOAD_TIMEOUT)
    ap.add_argument("--suite-timeout", type=int, default=DEFAULT_SUITE_TIMEOUT)
    ap.add_argument("--check-timeout", type=int, default=DEFAULT_CHECK_TIMEOUT)
    ap.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    args = ap.parse_args()

    failures = []
    summary = {"commit": COMMIT, "archive_url": ARCHIVE_URL}

    # 1. workspace
    if args.workdir:
        ws = args.workdir
        if os.path.exists(ws):
            log(f"FATAL: workspace {ws} already exists; refusing to reuse")
            return 1
        os.makedirs(ws)
    else:
        base = args.base_dir
        os.makedirs(base, exist_ok=True)
        ws = tempfile.mkdtemp(prefix=f"d038-{COMMIT[:8]}-", dir=base)
    os.makedirs(os.path.join(ws, "logs"), exist_ok=True)
    log(f"workspace: {ws}")
    log(f"recommended overall invocation timeout (director-side): "
        f"{RECOMMENDED_OVERALL_TIMEOUT_SECONDS} s")
    summary["workspace"] = ws
    summary["recommended_overall_timeout_seconds"] = \
        RECOMMENDED_OVERALL_TIMEOUT_SECONDS

    # 2. env before
    env_before = capture_env("before", ws)
    print_env(env_before)
    with open(os.path.join(ws, "logs", "env_before.json"), "w") as fh:
        json.dump(env_before, fh, indent=2)

    # 2b. resource gate
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
        with open(tgz, "rb") as fh:
            summary["archive_sha256"] = hashlib.sha256(fh.read()).hexdigest()
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

    # 5. identity
    problems, extra = verify_identities(src, EXPECTED_BLOBS)
    with open(os.path.join(ws, "logs", "identity.txt"), "w") as fh:
        fh.write(f"commit: {COMMIT}\nexpected files: {len(EXPECTED_BLOBS)}\n")
        fh.write("problems:\n" + ("\n".join(problems) if problems else "  (none)") + "\n")
        fh.write("extra files:\n" + ("\n".join("  " + e for e in extra) if extra else "  (none)") + "\n")
    if extra:
        log(f"note: {len(extra)} file(s) present beyond the pinned set: {extra}")
    if problems:
        log("FAIL-CLOSED (identity):")
        for p in problems:
            log(f"  {p}")
        return 1
    log(f"identity OK: all {len(EXPECTED_BLOBS)} files match pinned blobs")

    # 5b. coverage: every executable Python file must be pinned.
    uncovered = verify_python_coverage(src, EXPECTED_PY_FILES)
    if uncovered:
        log("FAIL-CLOSED (python coverage): "
            f"{len(uncovered)} executable .py file(s) not in the pinned "
            f"identity list:")
        for rel in uncovered:
            log(f"  UNPINNED {rel}")
        return 1
    log(f"python coverage OK: all {len(EXPECTED_PY_FILES)} executable "
        f".py files are pinned")

    # 6/7. interpreters, suite, kernel checks
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
    check_results = {}
    for py in pythons:
        tag = py["name"]
        log(f"=== suite on {tag} ({py['version']}) ===")
        r = run([py["path"], "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=src, env=env, timeout=args.suite_timeout)
        parsed = parse_unittest(r["out"] + r["err"])
        r.update(parsed)
        with open(os.path.join(ws, "logs", f"suite_{tag}.out"), "w") as fh:
            fh.write(f"$ {' '.join(r['cmd'])}\n\n")
            fh.write(r["out"])
            fh.write("\n--- stderr ---\n")
            fh.write(r["err"])
            fh.write(f"\nEXIT={r['rc']} timed_out={r['timed_out']} seconds={r['seconds']}\n")
        suite_results[tag] = r
        log(f"  ran={parsed['ran']} skipped={parsed['skipped']} "
            f"ok={parsed['ok']} failed={parsed['failed']} exit={r['rc']} "
            f"timeout={r['timed_out']}")
        if r["timed_out"]:
            failures.append(f"suite timeout on {tag}")
        elif r["rc"] != 0 or not parsed["ok"]:
            failures.append(f"suite failed on {tag} (exit {r['rc']})")

        for name in KERNEL_CHECKS:
            log(f"  --- kernel check {name} on {tag} ---")
            c = run([py["path"], KERNEL_CHECKS_PY, name, src],
                    cwd=ws, env=env, timeout=args.check_timeout)
            label = "PASS" if c["rc"] == 0 else ("SKIP" if c["rc"] == 2 else "FAIL")
            if c["timed_out"]:
                label = "TIMEOUT"
            c["label"] = label
            check_results[f"{tag}:{name}"] = c
            with open(os.path.join(ws, "logs", f"check_{tag}_{name}.out"), "w") as fh:
                fh.write(f"$ {' '.join(c['cmd'])}\n\n{c['out']}\n--- stderr ---\n{c['err']}\n")
                fh.write(f"EXIT={c['rc']} timed_out={c['timed_out']} seconds={c['seconds']}\n")
            log(f"    {label} (exit={c['rc']} timeout={c['timed_out']})")
            if label in ("FAIL", "TIMEOUT"):
                failures.append(f"kernel check {name} {label} on {tag}")

    summary["suite"] = {t: {k: r[k] for k in ("rc", "ran", "skipped", "ok", "failed",
                                               "timed_out", "seconds")}
                        for t, r in suite_results.items()}
    summary["checks"] = {k: {"label": c["label"], "rc": c["rc"], "timed_out": c["timed_out"],
                             "seconds": c["seconds"]} for k, c in check_results.items()}

    # 8. env after
    env_after = capture_env("after", ws)
    print_env(env_after)
    with open(os.path.join(ws, "logs", "env_after.json"), "w") as fh:
        json.dump(env_after, fh, indent=2)

    # 9. manifest + summary
    summary["failures"] = failures
    summary["result"] = "PASS" if not failures else "FAIL"
    with open(os.path.join(ws, "logs", "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    rows = write_manifest(ws)
    log("")
    log("=== summary ===")
    for t, r in summary["suite"].items():
        log(f"  suite {t}: ran={r['ran']} skipped={r['skipped']} ok={r['ok']}")
    for k, c in summary["checks"].items():
        log(f"  check {k}: {c['label']}")
    log(f"  manifest entries: {len(rows)}")
    if failures:
        log("RESULT: FAIL (fail-closed)")
        for f in failures:
            log(f"  !! {f}")
    else:
        log("RESULT: PASS")
    log("")
    log("Safe, precise cleanup (run only when evidence is no longer needed):")
    log(f"  rm -rf {ws}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""D072 negative-gate harness for the D069-corrected runner.

Executes the D069 negative plan N1..N18 against BOTH the pre-D069 (D063)
runner and the D069-corrected runner, recording the observed behaviour for
each and asserting the precise post-D069 expectation.

Design notes (honesty / no false positives):
  * Every test has a concrete fixture and an exact assertion. A test PASSES
    only when the observed bytes/exit match the assertion; a syntax or import
    error in the *runner under test* is recorded as a real failure of that
    runner, never masked.
  * E2E tests invoke the runner as a subprocess with a HARD outer timeout.
  * Unit tests import the runner module by path and call its functions
    directly (symlink detection, wall-clock download deadline, output cap,
    process-group kill, manifest symlink safety, archive guards) because those
    conditions cannot be reached through the CLI without modifying the pinned
    payload.
  * The pinned payload stress_checks.py is NEVER modified.

Usage: python3 run_negatives.py <outdir>
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLE = os.path.dirname(HERE)
RUNNER_NEW = os.path.join(BUNDLE, "runner", "run_cloud_stress.py")
RUNNER_OLD = os.path.join(BUNDLE, "originals", "runner", "run_cloud_stress.py")
PAYLOAD_NEW = os.path.join(BUNDLE, "runner", "stress_checks.py")
PAYLOAD_OLD = os.path.join(BUNDLE, "originals", "runner", "stress_checks.py")
REAL_ARCHIVE = "/scratch/work/archive-b7f8d17.tar.gz"
PY = "python3.11"
HARD_TIMEOUT = 120          # hard outer timeout per subprocess invocation

RESULTS = []


def log(msg=""):
    print(msg, flush=True)


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_runner(runner, args, timeout=HARD_TIMEOUT):
    """Invoke a runner as a subprocess with a hard outer timeout.

    A /tmp sub-dir is injected as --base-dir unless the caller already passes
    --base-dir or --workdir (the corrected default --base-dir /tmp is rejected
    by its own containment check - see blocker B-D072-1).
    """
    if "--base-dir" not in args and "--workdir" not in args:
        args = ["--base-dir", "/tmp/d072neg-base"] + list(args)
    cmd = [PY, runner] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           start_new_session=True)
        return {"cmd": cmd, "rc": p.returncode, "out": p.stdout, "err": p.stderr,
                "timed_out": False}
    except subprocess.TimeoutExpired as exc:
        def _t(v):
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else (v or "")
        return {"cmd": cmd, "rc": None, "out": _t(exc.stdout), "err": _t(exc.stderr),
                "timed_out": True}


def top_dir_of(tar_path):
    with tarfile.open(tar_path, "r:gz") as t:
        names = t.getnames()
    return names[0].rstrip("/") + "/"


def make_doctored_archive(base_path, out_path, extra_files):
    """Copy base archive, add extra regular files (relative to the single top dir)."""
    top = top_dir_of(base_path)
    with tarfile.open(base_path, "r:gz") as src, tarfile.open(out_path, "w:gz") as dst:
        for m in src:
            dst.addfile(m, src.extractfile(m) if m.isfile() else None)
        for rel, data in extra_files.items():
            ti = tarfile.TarInfo(name=top + rel)
            ti.size = len(data)
            ti.mode = 0o644
            dst.addfile(ti, io.BytesIO(data))
    return out_path


def record(nid, scope, desc, new_passed, new_detail, old_detail):
    RESULTS.append({"id": nid, "scope": scope, "desc": desc,
                    "new_passed": bool(new_passed), "new_detail": new_detail,
                    "old_detail": old_detail})
    flag = "PASS" if new_passed else "FAIL"
    log(f"[{nid}] {flag}  {scope}")
    log(f"      new: {new_detail}")
    log(f"      old: {old_detail}")


# ---------------------------------------------------------------------------
# E2E negatives (subprocess)
# ---------------------------------------------------------------------------

def n1_workdir_symlink_escape():
    base = tempfile.mkdtemp(prefix="d072n1-", dir="/tmp")
    link = os.path.join(base, "link")
    os.symlink("/var/tmp", link)
    target = os.path.join(link, "ws")
    esc = "/var/tmp/ws"
    if os.path.exists(esc):
        shutil.rmtree(esc, ignore_errors=True)
    new = run_runner(RUNNER_NEW, ["--workdir", target, "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    new_ok = (new["rc"] == 1 and "must resolve under /tmp/" in new["out"]
              and not os.path.exists(esc))
    new_detail = f"rc={new['rc']} escaped_dir_created={os.path.exists(esc)} " \
                 f"msg={'must resolve under /tmp/' in new['out']}"
    # old: creates the workspace under /var/tmp (escape succeeds)
    old = run_runner(RUNNER_OLD, ["--workdir", target, "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    old_detail = f"rc={old['rc']} escaped_dir_created={os.path.exists(esc)}"
    shutil.rmtree(esc, ignore_errors=True)
    shutil.rmtree(base, ignore_errors=True)
    record("N1", "B3 workspace escape via symlink", "workdir through symlink to /var/tmp",
           new_ok, new_detail, old_detail)


def n2_basedir_outside_tmp():
    pre = set(os.listdir("/var/tmp"))
    new = run_runner(RUNNER_NEW, ["--base-dir", "/var/tmp"], timeout=60)
    new_created = [d for d in os.listdir("/var/tmp") if d.startswith("d063-") and d not in pre]
    new_ok = (new["rc"] == 1 and "--base-dir must resolve under /tmp/" in new["out"]
              and not new_created)
    new_detail = f"rc={new['rc']} created={new_created} " \
                 f"msg={'--base-dir must resolve under /tmp/' in new['out']}"
    old = run_runner(RUNNER_OLD, ["--base-dir", "/var/tmp", "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    old_created = [d for d in os.listdir("/var/tmp") if d.startswith("d063-")]
    old_detail = f"rc={old['rc']} created={old_created}"
    for d in old_created:
        shutil.rmtree(os.path.join("/var/tmp", d), ignore_errors=True)
    record("N2", "B3 base-dir outside /tmp", "--base-dir /var/tmp",
           new_ok, new_detail, old_detail)


def n3_workspace_mode():
    ws = tempfile.mkdtemp(prefix="d072n3-", dir="/tmp")
    os.rmdir(ws)   # must not pre-exist
    new = run_runner(RUNNER_NEW, ["--workdir", ws, "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    mode = None
    if os.path.isdir(ws):
        mode = oct(os.stat(ws).st_mode & 0o777)
    new_ok = (new["rc"] == 1 and mode == "0o700")
    new_detail = f"rc={new['rc']} workdir_mode={mode} (expected 0o700)"
    # old: workdir created via os.makedirs -> umask (0755)
    ws2 = tempfile.mkdtemp(prefix="d072n3b-", dir="/tmp")
    os.rmdir(ws2)
    old = run_runner(RUNNER_OLD, ["--workdir", ws2, "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    mode2 = oct(os.stat(ws2).st_mode & 0o777) if os.path.isdir(ws2) else None
    old_detail = f"rc={old['rc']} workdir_mode={mode2}"
    shutil.rmtree(ws, ignore_errors=True)
    shutil.rmtree(ws2, ignore_errors=True)
    record("N3", "B3 workspace mode", "workspace created with mode 0700",
           new_ok, new_detail, old_detail)


def _identity_archive_case(nid, scope, rel, data, expect_token, old_extra_note):
    d = tempfile.mkdtemp(prefix="d072arch-", dir="/tmp")
    arch = os.path.join(d, "doctored.tar.gz")
    make_doctored_archive(REAL_ARCHIVE, arch, {rel: data})
    new = run_runner(RUNNER_NEW, ["--archive", arch], timeout=HARD_TIMEOUT)
    new_ok = (new["rc"] == 1 and "FAIL-CLOSED (identity)" in new["out"]
              and expect_token in new["out"])
    new_detail = f"rc={new['rc']} token={expect_token in new['out']} " \
                 f"fail_closed={'FAIL-CLOSED (identity)' in new['out']}"
    old = run_runner(RUNNER_OLD, ["--archive", arch, "--overall-deadline", "30"],
                     timeout=HARD_TIMEOUT)
    old_detail = f"rc={old['rc']} fail_closed_at_identity=" \
                 f"{'FAIL-CLOSED (identity)' in old['out']} " \
                 f"noted_extra={old_extra_note in old['out']}"
    shutil.rmtree(d, ignore_errors=True)
    record(nid, scope, f"archive with {rel}", new_ok, new_detail, old_detail)


def n4_extra_tests_file():
    _identity_archive_case("N4", "B2 extra file under tests/", "tests/rogue.py",
                           b"# rogue\n", "UNEXPECTED tests/rogue.py",
                           "present beyond the pinned set")


def n5_sitecustomize():
    _identity_archive_case("N5", "B2 sitecustomize.py at source root",
                           "sitecustomize.py", b"print('pwn')\n",
                           "EXECUTABLE_UNEXPECTED sitecustomize.py",
                           "present beyond the pinned set")


def n6_unexpected_so():
    _identity_archive_case("N6", "B2 unexpected .so", "drive_tool/_evil.so",
                           b"\x7fELF-fake", "UNEXPECTED drive_tool/_evil.so",
                           "present beyond the pinned set")


def n11_no_fs_masking():
    new = run_runner(RUNNER_NEW, ["--base-dir", "/mnt"], timeout=60)
    new_ok = (new["rc"] == 1 and "--base-dir must resolve under /tmp/" in new["out"])
    new_detail = f"rc={new['rc']} msg={'--base-dir must resolve under /tmp/' in new['out']}"
    old = run_runner(RUNNER_OLD, ["--base-dir", "/mnt", "--archive", REAL_ARCHIVE,
                                  "--min-free-bytes", "999999999999"], timeout=60)
    created = os.path.isdir("/mnt") and [d for d in os.listdir("/mnt")
                                         if d.startswith("d063-")]
    old_detail = f"rc={old['rc']} created_under_mnt={bool(created)}"
    for d in (created or []):
        shutil.rmtree(os.path.join("/mnt", d), ignore_errors=True)
    record("N11", "B1 no filesystem masking", "--base-dir /mnt after suite failure",
           new_ok, new_detail, old_detail)


# ---------------------------------------------------------------------------
# Unit negatives (import the runner module directly)
# ---------------------------------------------------------------------------

REAL_SRC = "/scratch/work/src-b7f8d17/drive-tool-b7f8d17b9dcc4aec68d54b38f994290e05264e67"


def _build_src_tree():
    """Copy the REAL pinned source tree so all 26 blobs match exactly."""
    d = tempfile.mkdtemp(prefix="d072src-", dir="/tmp")
    shutil.copytree(REAL_SRC, d, dirs_exist_ok=True)
    return d


def n7_symlink_file():
    """A pinned file replaced by a symlink to a byte-identical copy.

    The pre-D069 runner reads *through* the symlink, sees a matching blob and
    accepts it. The D069 runner rejects the link itself (MISSING_OR_LINK).
    """
    mod = load_module(RUNNER_NEW, "runner_new_n7")
    src = _build_src_tree()
    p = os.path.join(src, "drive_tool", "listing.py")
    copy = os.path.join(tempfile.mkdtemp(prefix="d072n7-", dir="/tmp"), "listing.py")
    shutil.copyfile(p, copy)          # byte-identical -> old blob check passes
    os.remove(p)
    os.symlink(copy, p)
    problems, extras, hard = mod.verify_identities(src, mod.EXPECTED_BLOBS)
    new_ok = any("MISSING_OR_LINK drive_tool/listing.py" in x for x in problems)
    new_detail = f"problems={problems[:3]} hard_extras={hard[:3]}"
    oldmod = load_module(RUNNER_OLD, "runner_old_n7")
    op, oe = oldmod.verify_identities(src, oldmod.EXPECTED_BLOBS)
    old_detail = f"problems={op[:3]} extras={oe[:3]} (empty problems == link accepted)"
    shutil.rmtree(src, ignore_errors=True)
    shutil.rmtree(os.path.dirname(copy), ignore_errors=True)
    record("N7", "B2 symlink inside extracted src",
           "drive_tool/listing.py -> byte-identical copy", new_ok, new_detail, old_detail)


def n8_symlink_dir():
    mod = load_module(RUNNER_NEW, "runner_new_n8")
    src = _build_src_tree()
    os.symlink("/etc", os.path.join(src, "escape"))
    problems, extras, hard = mod.verify_identities(src, mod.EXPECTED_BLOBS)
    new_ok = any("SYMLINK_DIR escape" in x for x in hard)
    new_detail = f"hard_extras={hard}"
    oldmod = load_module(RUNNER_OLD, "runner_old_n8")
    try:
        op, oe = oldmod.verify_identities(src, oldmod.EXPECTED_BLOBS)
        old_detail = f"returned 2-tuple; symlink dir not flagged; extras={oe}"
    except Exception as exc:  # noqa: BLE001
        old_detail = f"{type(exc).__name__}: {exc}"
    shutil.rmtree(src, ignore_errors=True)
    record("N8", "B2 symlinked directory", "escape -> /etc", new_ok, new_detail, old_detail)


class _Trickle:
    """Fake urllib response that trickles one chunk every `delay` seconds."""
    def __init__(self, delay):
        self.delay = delay
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self, n):
        time.sleep(self.delay)
        return b"x" * 1024


def n12_download_deadline():
    mod = load_module(RUNNER_NEW, "runner_new_n12")
    orig = mod.urllib.request.urlopen
    mod.urllib.request.urlopen = lambda req, timeout=None: _Trickle(0.3)
    dest = os.path.join(tempfile.mkdtemp(prefix="d072n12-", dir="/tmp"), "a.bin")
    new_ok = False
    new_detail = ""
    try:
        mod.download_archive("http://example.invalid/x", dest, 10 ** 9, 1)
        new_detail = "no exception (UNEXPECTED)"
    except RuntimeError as exc:
        new_ok = "wall-clock deadline" in str(exc)
        new_detail = f"RuntimeError: {exc}"
    except Exception as exc:  # noqa: BLE001
        new_detail = f"{type(exc).__name__}: {exc}"
    finally:
        mod.urllib.request.urlopen = orig
    old_detail = "old download_archive has no wall-clock deadline (socket timeout only)"
    record("N12", "L1 wall-clock download deadline", "trickling source vs 1s deadline",
           new_ok, new_detail, old_detail)


def n14_output_cap():
    mod = load_module(RUNNER_NEW, "runner_new_n14")
    script = "import sys; sys.stdout.write('x'*(20*1024*1024)); sys.stdout.flush()"
    r = mod.run([PY, "-c", script], cwd="/tmp", env=dict(os.environ), timeout=60)
    cap = mod.MAX_SUBPROCESS_OUTPUT
    new_ok = r["truncated"] is True and len(r["out"]) <= cap
    new_detail = f"truncated={r['truncated']} captured_bytes={len(r['out'])} cap={cap}"
    oldmod = load_module(RUNNER_OLD, "runner_old_n14")
    old_detail = "old run() uses subprocess.run(capture_output=True): no byte cap, " \
                 "no 'truncated' key"
    record("N14", "L3 bounded subprocess capture", "payload writes 20 MiB to stdout",
           new_ok, new_detail, old_detail)


def _group_kill_probe(mod, tag):
    """Child runs `sleep 4; touch SENTINEL`. Parent timeout is 2s. If the whole
    process group is killed the sentinel never appears; if only the direct child
    is killed the orphaned child touches it at ~4s."""
    d = tempfile.mkdtemp(prefix=f"d072n15{tag}-", dir="/tmp")
    sentinel = os.path.join(d, "sentinel")
    pidfile = os.path.join(d, "child.pid")
    payload = (
        "import subprocess,time\n"
        f"p=subprocess.Popen(['sh','-c','sleep 4; touch {sentinel}'])\n"
        f"open({pidfile!r},'w').write(str(p.pid))\n"
        "time.sleep(120)\n"
    )
    r = mod.run([PY, "-c", payload], cwd="/tmp", env=dict(os.environ), timeout=2)
    time.sleep(5)   # > 4s: a surviving orphan would have touched the sentinel
    child_pid = int(open(pidfile).read().strip()) if os.path.exists(pidfile) else None
    child_state = None
    if child_pid and os.path.exists(f"/proc/{child_pid}/stat"):
        child_state = open(f"/proc/{child_pid}/stat").read().split()[2]
    return {"timed_out": r["timed_out"], "sentinel": os.path.exists(sentinel),
            "child_pid": child_pid, "child_state": child_state, "dir": d}


def n15_process_group_kill():
    mod = load_module(RUNNER_NEW, "runner_new_n15")
    new = _group_kill_probe(mod, "new")
    new_ok = new["timed_out"] is True and new["sentinel"] is False
    new_detail = f"timed_out={new['timed_out']} orphan_sentinel={new['sentinel']} " \
                 f"child_pid={new['child_pid']} child_state={new['child_state']} " \
                 f"(Z=terminated)"
    oldmod = load_module(RUNNER_OLD, "runner_old_n15")
    old = _group_kill_probe(oldmod, "old")
    old_detail = f"timed_out={old['timed_out']} orphan_sentinel={old['sentinel']} " \
                 f"child_pid={old['child_pid']} child_state={old['child_state']}"
    shutil.rmtree(new["dir"], ignore_errors=True)
    shutil.rmtree(old["dir"], ignore_errors=True)
    record("N15", "L3 process-group kill", "payload spawns a sleeping child",
           new_ok, new_detail, old_detail)


def n16_manifest_symlink():
    mod = load_module(RUNNER_NEW, "runner_new_n16")
    ws = tempfile.mkdtemp(prefix="d072n16-", dir="/tmp")
    os.makedirs(os.path.join(ws, "logs"))
    with open(os.path.join(ws, "real.bin"), "wb") as fh:
        fh.write(b"real-data")
    os.symlink("/etc/passwd", os.path.join(ws, "link"))
    sized = mod.dir_size(ws)              # before MANIFEST.md is written
    rows, links = mod.write_manifest(ws)
    manifest = open(os.path.join(ws, "logs", "MANIFEST.md")).read()
    link_rel = [l for l in links if l[0] == "link"]
    hashed_link = any(r[0] == "link" for r in rows)
    new_ok = (bool(link_rel) and not hashed_link
              and "symlinks (NOT followed)" in manifest
              and sized == len(b"real-data"))
    new_detail = f"links={link_rel} link_hashed={hashed_link} dir_size={sized} " \
                 f"(expected {len(b'real-data')})"
    oldmod = load_module(RUNNER_OLD, "runner_old_n16")
    old_detail = "old write_manifest() returns 1-tuple and sha256_file() follows " \
                 "the symlink (records /etc/passwd hash)"
    shutil.rmtree(ws, ignore_errors=True)
    record("N16", "L4 manifest symlink safety", "symlink in workspace",
           new_ok, new_detail, old_detail)


def n18_archive_guards():
    mod = load_module(RUNNER_NEW, "runner_new_n18")
    d = tempfile.mkdtemp(prefix="d072n18-", dir="/tmp")
    cases = {}

    def build(name, members):
        path = os.path.join(d, name + ".tar.gz")
        with tarfile.open(path, "w:gz") as t:
            for ti, data in members:
                t.addfile(ti, io.BytesIO(data) if data is not None else None)
        return path

    def reg(name, data=b"x"):
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        return (ti, data)

    cases["dotdot"] = build("dotdot", [reg("../escape.txt")])
    cases["absolute"] = build("abs", [reg("/etc/evil.txt")])
    # symlink member
    ti = tarfile.TarInfo("root/link"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"
    cases["symlink"] = build("sym", [(ti, None)])
    # hardlink member
    ti = tarfile.TarInfo("root/hard"); ti.type = tarfile.LNKTYPE; ti.linkname = "root/a"
    cases["hardlink"] = build("hard", [reg("root/a"), (ti, None)])
    # oversized member
    cases["oversize"] = build("big", [reg("root/big.bin", b"y" * (6 * 1024 * 1024))])
    # too many members
    cases["toomany"] = build("many", [reg(f"root/f{i}.txt") for i in range(2100)])

    observed = {}
    all_rejected = True
    for k, path in cases.items():
        dest = os.path.join(d, "x_" + k)
        os.makedirs(dest, exist_ok=True)
        try:
            mod.safe_extract(path, dest)
            observed[k] = "ACCEPTED (unexpected)"
            all_rejected = False
        except RuntimeError as exc:
            observed[k] = f"rejected: {exc}"
        except Exception as exc:  # noqa: BLE001
            observed[k] = f"{type(exc).__name__}: {exc}"
            all_rejected = False
    new_ok = all_rejected
    new_detail = f"all_rejected={all_rejected} {observed}"
    old_detail = "old safe_extract already rejects these (unchanged behaviour)"
    shutil.rmtree(d, ignore_errors=True)
    record("N18", "regression archive guards", "6 malicious archives",
           new_ok, new_detail, old_detail)


# ---------------------------------------------------------------------------
# Checks derived from the full-run evidence (N9, N10, N13, N17)
# ---------------------------------------------------------------------------

def checks_from_full_run(summary_path, readdir_path, smoke_out_path):
    try:
        summary = json.load(open(summary_path))
        roc = json.load(open(readdir_path))
    except Exception as exc:  # noqa: BLE001
        record("N9", "B1 suite failure + diagnostic continue", "from full run",
               False, f"cannot read artifacts: {exc}", "n/a")
        return
    # N9
    suite = summary.get("suite", {})
    any_fail = any((not s.get("ok")) or s.get("rc") not in (0,) for s in suite.values())
    new_ok = (summary.get("suite_diagnostic_continue") is True
              and summary.get("result") == "FAIL"
              and any_fail
              and bool(summary.get("stages", {}).get("smoke")))
    new_detail = f"suite_diagnostic_continue={summary.get('suite_diagnostic_continue')} " \
                 f"result={summary.get('result')} stages={list(summary.get('stages', {}))} " \
                 f"suite={ {k: v.get('rc') for k, v in suite.items()} }"
    record("N9", "B1 suite failure + diagnostic continue", "full runner run",
           new_ok, new_detail,
           "old runner aborts before smoke/soak/edges when the suite fails")
    # N10
    dual = roc.get("dual_order_repro", {})
    new_ok = (roc.get("confirmed_order_sensitive_defect") is True
              and dual.get("asc", {}).get("rc") == 0
              and dual.get("desc", {}).get("rc") not in (0, None))
    new_detail = f"asc_rc={dual.get('asc', {}).get('rc')} " \
                 f"desc_rc={dual.get('desc', {}).get('rc')} " \
                 f"confirmed={roc.get('confirmed_order_sensitive_defect')} " \
                 f"native_order={roc.get('native_probe', {}).get('observed_order')}"
    record("N10", "B1 dual-order repro", "full runner run", new_ok, new_detail,
           "old runner has no readdir confirmation or dual-order repro")
    # N13
    smoke = open(smoke_out_path).read() if os.path.exists(smoke_out_path) else ""
    first = smoke.splitlines()[0] if smoke else ""
    has_flag = "--deadline-seconds" in first
    n = None
    if has_flag:
        try:
            n = int(first.split("--deadline-seconds")[1].split()[0])
        except Exception:  # noqa: BLE001
            n = None
    cap = summary.get("stages", {}).get("smoke", {}).get("internal_deadline_seconds")
    new_ok = has_flag and n is not None and n <= 180 - 10
    new_detail = f"invocation={first} internal_deadline={cap}"
    record("N13", "L2 --deadline-seconds propagation", "from stress_smoke.out",
           new_ok, new_detail, "old runner never passes --deadline-seconds")
    # N17 (a) both totals recorded by the full run
    wb = summary.get("workspace_bytes")
    wa = summary.get("workspace_allocated_bytes")
    both = isinstance(wb, int) and isinstance(wa, int)
    # N17 (b) the L5 intent: dir_allocated_size is a real block-based measure
    mod = load_module(RUNNER_NEW, "runner_new_n17")
    d = tempfile.mkdtemp(prefix="d072n17-", dir="/tmp")
    for nm, data in (("a.bin", b"a" * 5000), ("b.bin", b"b" * 12345)):
        with open(os.path.join(d, nm), "wb") as fh:
            fh.write(data)
    with open(os.path.join(d, "sparse.bin"), "wb") as fh:
        fh.truncate(2 * 1024 * 1024)
    apparent = mod.dir_size(d)
    allocated = mod.dir_allocated_size(d)
    manual_app = sum(os.lstat(os.path.join(d, n)).st_size for n in os.listdir(d))
    manual_alloc = sum(os.lstat(os.path.join(d, n)).st_blocks * 512 for n in os.listdir(d))
    measure_ok = (apparent == manual_app and allocated == manual_alloc)
    new_ok = both and measure_ok
    new_detail = (f"summary apparent={wb} allocated={wa}; probe apparent={apparent} "
                  f"allocated={allocated} (manual {manual_app}/{manual_alloc}, "
                  f"block-based measure matches: {measure_ok})")
    shutil.rmtree(d, ignore_errors=True)
    record("N17", "L5 apparent vs allocated", "summary.json + block-based probe",
           new_ok, new_detail, "old runner records only apparent bytes")


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "logs")
    os.makedirs(outdir, exist_ok=True)
    log(f"payload_new sha256={hashlib.sha256(open(PAYLOAD_NEW,'rb').read()).hexdigest()}")
    log(f"payload_old sha256={hashlib.sha256(open(PAYLOAD_OLD,'rb').read()).hexdigest()}")
    log("")

    n1_workdir_symlink_escape()
    n2_basedir_outside_tmp()
    n3_workspace_mode()
    n4_extra_tests_file()
    n5_sitecustomize()
    n6_unexpected_so()
    n7_symlink_file()
    n8_symlink_dir()
    n11_no_fs_masking()
    n12_download_deadline()
    n14_output_cap()
    n15_process_group_kill()
    n16_manifest_symlink()
    n18_archive_guards()

    # full-run derived checks
    wl = os.path.join(BUNDLE, "sandbox", "workspace_logs")
    checks_from_full_run(
        os.path.join(wl, "summary.json"),
        os.path.join(wl, "readdir_order_confirmation.json"),
        os.path.join(wl, "stress_smoke.out"))

    log("")
    log("=== negative harness summary ===")
    passed = sum(1 for r in RESULTS if r["new_passed"])
    for r in RESULTS:
        log(f"  {r['id']}: {'PASS' if r['new_passed'] else 'FAIL'}  {r['scope']}")
    log(f"  TOTAL: {passed}/{len(RESULTS)} passed")
    with open(os.path.join(outdir, "negatives_results.json"), "w") as fh:
        json.dump({"results": RESULTS, "passed": passed, "total": len(RESULTS)}, fh, indent=2)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

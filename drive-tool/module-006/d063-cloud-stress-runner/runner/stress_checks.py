#!/usr/bin/env python3
"""d063 six-agent backend stress + raw edge checks (stdlib only).

This module is the ONLY executable payload the d063 runner is allowed to
invoke. It exposes a fixed allow-list of actions and accepts no arbitrary
shell/job payload:

    python3 stress_checks.py <action> <src-dir> [--deadline-seconds N]

Actions (fixed):
    env    -- import the pinned drive_tool package and print its identity
    smoke  -- 600-call bounded six-agent backend smoke
    soak   -- 10000-call bounded six-agent backend soak (gated on smoke)
    edges  -- raw edge checks (grants, races, refusal, caps, EOF, leases)

`<src-dir>` is the extracted pinned candidate root (the directory that holds
`drive_tool/`). Everything runs against REAL synthetic POSIX fixtures under a
fresh workspace; nothing outside the workspace is touched, no credentials,
cloud API, install, service, reboot or public binding is used. Payloads and
file counts are bounded so no destructive memory/disk exhaustion is possible.

Exit: 0 = PASS, 1 = FAIL. A machine-readable `STRESS_JSON:` line is printed.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import random
import stat
import sys
import threading
import time

# -- bounds (defined BEFORE execution; never moved to fit a result) ----------

MAX_CONCURRENT = 6                # <= 6 concurrent operations, ever
SMOKE_CALLS = 600                 # exact completed-call target for smoke
SOAK_CALLS = 10000                # exact completed-call target for soak
MAX_FIXTURE_BYTES = 32 * 1024 * 1024   # <= 32 MiB new fixture data
MAX_RSS_GROWTH_KB = 96 * 1024          # conservative RSS growth budget (96 MiB)
MAX_FD_SLACK = 2                       # fd table may differ by at most this
MAX_THREAD_SLACK = 2                   # extra live threads beyond pool size
SAVE_POOL = 32                         # bounded reused save slots per agent
SPARSE_SIZE = 2 * 1024 * 1024          # apparent size of the sparse probe file

ROOT_FILES = ["readme.txt", "data.bin", "short.bin", "empty.bin",
              "big.bin", "sparse.bin", "sub/note.txt"]
READ_IDS = ["p/" + f for f in ROOT_FILES]

# per-agent (token, alias, can_save, max_read_len, max_save_len)
AGENT_SPECS = [
    ("d063agent00-token-" + "K" * 40, "s0", True, 262144, 4096),
    ("d063agent01-token-" + "K" * 40, "s1", True, 262144, 4096),
    ("d063agent02-token-" + "K" * 40, "s2", False, 262144, 0),      # read-only
    ("d063agent03-token-" + "K" * 40, "s3", True, 262144, 4096),
    ("d063agent04-token-" + "K" * 40, "s4", True, 4096, 2048),      # small caps
    ("d063agent05-token-" + "K" * 40, "s5", True, 262144, 4096),
]
N_AGENTS = len(AGENT_SPECS)


def _log(msg=""):
    print(msg, flush=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: str, data: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def _rss_kb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _nfd():
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


# -- fixtures ----------------------------------------------------------------

def build_roots(ws: str):
    """Create bounded, reused synthetic fixtures. Returns (roots, outside, bytes)."""
    roots = []
    total = 0
    outside = os.path.join(ws, "outside")
    os.makedirs(outside, exist_ok=True)
    _write(os.path.join(outside, "secret.txt"), b"SECRET-OUTSIDE-DATA")
    total += len(b"SECRET-OUTSIDE-DATA")

    for i in range(N_AGENTS):
        root = os.path.join(ws, "roots", f"r{i}")
        os.makedirs(os.path.join(root, "sub"), exist_ok=True)
        os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
        fixtures = {
            "readme.txt": b"d063 fixture readme\n" * 4,
            "data.bin": bytes(range(256)) * 16,          # 4096 bytes
            "short.bin": b"abcde",                        # 5 bytes
            "empty.bin": b"",                             # 0 bytes
            "big.bin": b"B" * 262144,                     # 256 KiB
            "sub/note.txt": b"nested note\n",
        }
        for name, data in fixtures.items():
            _write(os.path.join(root, name), data)
            total += len(data)
        # large sparse probe (apparent size only; ~0 real disk)
        sparse = os.path.join(root, "sparse.bin")
        with open(sparse, "wb") as fh:
            fh.truncate(SPARSE_SIZE)   # large apparent size, ~0 real disk
        total += SPARSE_SIZE  # counted as fixture bytes (apparent)
        # a symlink inside the root that points OUTSIDE (refusal probe)
        try:
            os.symlink(outside, os.path.join(root, "link_out"))
        except OSError:
            pass
        roots.append(os.path.realpath(root))
    return roots, outside, total


def build_policies(roots):
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    policies = []
    for i, (token, alias, can_save, mrl, mwl) in enumerate(AGENT_SPECS):
        ops = {"find", "list", "read"} | ({"save"} if can_save else set())
        grant = SourceGrant(
            alias=alias,
            root=roots[i],
            operations=frozenset(ops),
            max_read_bytes=max(mrl, 1),
            max_write_bytes=max(mwl, 1),
        )
        policies.append(
            AgentPolicy(
                agent_id=f"agent{i}",
                token_sha256=hashlib.sha256(token.encode("ascii")).digest(),
                grants=(grant,),
            )
        )
    return tuple(policies)


def make_service(policies):
    from drive_tool.file_service import LocalFileService
    return LocalFileService(policies)


# -- workload ----------------------------------------------------------------

def _do_call(svc, agent, rng, tag_counts):
    """Perform exactly one backend call for `agent`. Returns an outcome tag."""
    from drive_tool.file_service import ServiceError

    token, alias, can_save, mrl, mwl = AGENT_SPECS[agent]
    roll = rng.random()
    try:
        if roll < 0.05:
            # deliberate denial: use another agent's alias (alias isolation)
            other = (agent + 1) % N_AGENTS
            svc.list(token, AGENT_SPECS[other][1], "root", limit=5)
            return "unexpected_allow"
        if roll < 0.28:
            svc.list(token, alias, "root", limit=rng.choice([5, 20, 100]))
            return "list"
        if roll < 0.50:
            svc.find(token, alias, "root",
                     name_contains=rng.choice(["data", "readme", "sub", ".txt"]),
                     limit=rng.choice([5, 20]),
                     max_depth=rng.choice([0, 1, 4]))
            return "find"
        if roll < 0.85:
            fid = rng.choice(READ_IDS)
            length = rng.choice([1, 64, 1024, 4096, 65536, 262144])
            length = min(length, mrl)
            offset = rng.choice([0, 1, 100, 4096, SPARSE_SIZE - 65536])
            svc.read(token, alias, fid, offset=offset, length=length)
            return "read"
        # save into a bounded reused pool
        slot = rng.randrange(SAVE_POOL)
        size = rng.choice([0, 1, 7, 256, 1024])
        size = min(size, mwl)
        data = bytes([slot & 0xFF]) * size
        overwrite = rng.random() < 0.5
        svc.save(token, alias, f"p/savepool/f{slot:02d}.bin", data,
                 overwrite=overwrite)
        return "save"
    except ServiceError as exc:
        return "err:" + exc.code


def run_workload(calls: int, seed: int, deadline: float):
    from concurrent.futures import ThreadPoolExecutor
    ws = os.environ["D063_WORKSPACE"]
    roots, outside, fixture_bytes = build_roots(ws)
    policies = build_policies(roots)
    fd0, rss0, thr0 = _nfd(), _rss_kb(), threading.active_count()
    svc = make_service(policies)

    counts = {}
    lock = threading.Lock()
    unexpected = []
    peak = {"n": thr0}
    start = time.monotonic()

    def worker(w):
        rng = random.Random(seed * 1000 + w)
        local = {}
        for ticket in range(w, calls, N_AGENTS):
            if time.monotonic() > deadline:
                break
            try:
                tag = _do_call(svc, ticket % N_AGENTS, rng, local)
            except BaseException as exc:  # noqa: BLE001
                tag = "EXC:" + type(exc).__name__
                with lock:
                    unexpected.append(tag)
            local[tag] = local.get(tag, 0) + 1
            n = threading.active_count()
            if n > peak["n"]:
                with lock:
                    if n > peak["n"]:
                        peak["n"] = n
        with lock:
            for k, v in local.items():
                counts[k] = counts.get(k, 0) + v

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as ex:
        list(ex.map(worker, range(MAX_CONCURRENT)))

    thr_peak = peak["n"]
    closed = svc.close(timeout=10.0)
    fd1, rss1 = _nfd(), _rss_kb()

    completed = sum(v for k, v in counts.items())
    leaked = _scan_temp_leaks(roots)
    summary = {
        "calls_requested": calls,
        "calls_completed": completed,
        "outcomes": dict(sorted(counts.items())),
        "unexpected": unexpected,
        "closed_ok": bool(closed),
        "fd_before": fd0, "fd_after": fd1,
        "rss_before_kb": rss0, "rss_after_kb": rss1,
        "threads_before": thr0, "threads_peak": thr_peak,
        "temp_leaks": leaked,
        "fixture_bytes": fixture_bytes,
        "seconds": round(time.monotonic() - start, 2),
    }

    failures = []
    if unexpected:
        failures.append(f"{len(unexpected)} unexpected exceptions: {unexpected[:3]}")
    if completed != calls:
        failures.append(f"completed {completed} != requested {calls}")
    if counts.get("unexpected_allow"):
        failures.append("alias isolation leaked an allow")
    if not closed:
        failures.append("service.close() did not return True")
    if fd0 is not None and fd1 is not None and fd1 > fd0 + MAX_FD_SLACK:
        failures.append(f"fd growth {fd0}->{fd1} exceeds slack {MAX_FD_SLACK}")
    if rss0 is not None and rss1 is not None and (rss1 - rss0) > MAX_RSS_GROWTH_KB:
        failures.append(f"rss growth {rss1 - rss0} KiB exceeds {MAX_RSS_GROWTH_KB}")
    if thr_peak > thr0 + MAX_CONCURRENT + MAX_THREAD_SLACK:
        failures.append(f"thread peak {thr_peak} exceeds bound")
    if leaked:
        failures.append(f"leaked temp files: {leaked[:3]}")
    if fixture_bytes > MAX_FIXTURE_BYTES:
        failures.append(f"fixture bytes {fixture_bytes} exceeds {MAX_FIXTURE_BYTES}")
    summary["failures"] = failures
    return summary


def _scan_temp_leaks(roots):
    from drive_tool.local_write import TEMP_PREFIX
    leaks = []
    for root in roots:
        for dp, dns, fns in os.walk(root):
            for fn in fns + dns:
                if fn.startswith(TEMP_PREFIX):
                    leaks.append(os.path.join(dp, fn))
    return leaks


# -- edge checks -------------------------------------------------------------

def _expect_error(fn, code, label, failures):
    from drive_tool.file_service import ServiceError
    try:
        fn()
    except ServiceError as exc:
        if exc.code != code:
            failures.append(f"{label}: expected code {code!r}, got {exc.code!r}")
        return
    except BaseException as exc:  # noqa: BLE001
        failures.append(f"{label}: expected ServiceError, got {type(exc).__name__}")
        return
    failures.append(f"{label}: expected ServiceError {code!r}, call succeeded")


def run_edges(deadline: float):
    from drive_tool.file_service import ServiceError
    from drive_tool import local_write

    ws = os.environ["D063_WORKSPACE"]
    roots, outside, fixture_bytes = build_roots(ws)
    policies = build_policies(roots)
    checks = {}
    failures = []
    fd0 = _nfd()
    svc = make_service(policies)
    t0 = time.monotonic()

    def ok(name, cond, detail=""):
        checks[name] = bool(cond)
        if not cond:
            failures.append(f"{name}: {detail}")

    # 1. alias isolation (agent0 must not use agent1's alias)
    _expect_error(lambda: svc.list(AGENT_SPECS[0][0], "s1", "root"),
                  "denied", "alias_isolation", failures)

    # 2. readonly denial (agent2 has no save grant)
    _expect_error(lambda: svc.save(AGENT_SPECS[2][0], "s2", "p/x.bin", b"hi"),
                  "denied", "readonly_denial", failures)

    # 3. traversal refusal
    _expect_error(lambda: svc.read(AGENT_SPECS[0][0], "s0",
                                   "p/../outside/secret.txt", offset=0, length=16),
                  "denied", "traversal_refusal", failures)

    # 4. symlink refusal (component is a symlink pointing outside)
    _expect_error(lambda: svc.read(AGENT_SPECS[0][0], "s0",
                                   "p/link_out/secret.txt", offset=0, length=16),
                  "denied", "symlink_refusal", failures)
    names = [it["name"] for it in svc.list(AGENT_SPECS[0][0], "s0", "root",
                                           limit=100)["items"]]
    ok("symlink_omitted_from_listing", "link_out" not in names, names)

    # 5. grant-specific limits (agent4: max_read 4096, max_write 2048)
    _expect_error(lambda: svc.read(AGENT_SPECS[4][0], "s4", "p/data.bin",
                                   offset=0, length=4097),
                  "too_large", "grant_read_cap", failures)
    _expect_error(lambda: svc.save(AGENT_SPECS[4][0], "s4", "p/savepool/lim.bin",
                                   b"x" * 2049),
                  "too_large", "grant_write_cap", failures)

    # 6. service-level caps
    _expect_error(lambda: svc.read(AGENT_SPECS[0][0], "s0", "p/data.bin",
                                   offset=0, length=1048577),
                  "too_large", "service_read_cap", failures)

    # 7. cap edges / EOF / sparse ranges / short / empty
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/data.bin", offset=0, length=4096)
    ok("read_exact_window", len(r.data) == 4096 and r.eof_observed is False,
       f"len={len(r.data)} eof={r.eof_observed}")
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/data.bin", offset=4096, length=64)
    ok("read_at_eof", r.data == b"" and r.eof_observed is True,
       f"len={len(r.data)} eof={r.eof_observed}")
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/data.bin", offset=10 ** 9, length=64)
    ok("read_past_eof", r.data == b"" and r.eof_observed is True,
       f"len={len(r.data)} eof={r.eof_observed}")
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/short.bin", offset=0, length=100)
    ok("read_short_file", r.data == b"abcde" and r.eof_observed is True,
       f"data={r.data!r} eof={r.eof_observed}")
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/empty.bin", offset=0, length=16)
    ok("read_empty_file",
       r.data == b"" and r.eof_observed is True and r.observed_size == 0,
       f"data={r.data!r} size={r.observed_size}")
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/sparse.bin",
                 offset=SPARSE_SIZE - 65536, length=65536)
    ok("sparse_large_range", len(r.data) == 65536,
       f"len={len(r.data)} size={r.observed_size}")

    # 8. empty-data save round-trip
    svc.save(AGENT_SPECS[0][0], "s0", "p/savepool/empty.bin", b"",
             overwrite=True)
    r = svc.read(AGENT_SPECS[0][0], "s0", "p/savepool/empty.bin", offset=0,
                 length=16)
    ok("empty_save_roundtrip", r.data == b"" and r.observed_size == 0,
       f"data={r.data!r} size={r.observed_size}")

    # 9. concurrent no-overwrite: exactly one winner, exact full payload
    race_name = "p/savepool/race.bin"
    payloads = [bytes([i]) * 128 for i in range(MAX_CONCURRENT)]
    barrier = threading.Barrier(MAX_CONCURRENT)
    results = []

    def racer(i):
        barrier.wait()
        try:
            svc.save(AGENT_SPECS[0][0], "s0", race_name, payloads[i],
                     overwrite=False)
            results.append(("ok", i))
        except ServiceError as exc:
            results.append((exc.code, i))

    threads = [threading.Thread(target=racer, args=(i,)) for i in range(MAX_CONCURRENT)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [i for tag, i in results if tag == "ok"]
    others_ok = all(tag == "exists" for tag, i in results if tag != "ok")
    ok("race_single_winner", len(winners) == 1 and others_ok,
       f"results={results}")
    if len(winners) == 1:
        got = svc.read(AGENT_SPECS[0][0], "s0", race_name, offset=0,
                       length=1024).data
        ok("race_exact_payload", got == payloads[winners[0]],
           f"winner={winners[0]} got_len={len(got)}")

    # 10. close / active-lease / idempotent concurrency
    stop = threading.Event()
    seen = {"codes": {}, "ok": 0}

    def lease_worker():
        while not stop.is_set():
            try:
                svc.list(AGENT_SPECS[0][0], "s0", "root", limit=5)
                seen["ok"] += 1
            except ServiceError as exc:
                seen["codes"][exc.code] = seen["codes"].get(exc.code, 0) + 1
            time.sleep(0.001)

    lw = [threading.Thread(target=lease_worker) for _ in range(MAX_CONCURRENT)]
    for t in lw:
        t.start()
    time.sleep(0.02)
    closed1 = svc.close(timeout=10.0)
    stop.set()
    for t in lw:
        t.join()
    closed2 = svc.close(timeout=5.0)  # idempotent
    ok("close_active_lease", closed1 is True, f"closed1={closed1}")
    ok("close_idempotent", closed2 is True, f"closed2={closed2}")
    ok("post_close_unavailable",
       seen["codes"].get("unavailable", 0) >= 1,
       f"codes={seen['codes']}")
    _expect_error(lambda: svc.list(AGENT_SPECS[0][0], "s0", "root"),
                  "unavailable", "post_close_call", failures)

    # 11. fault-injected post-publish uncertainty (SIMULATED, clearly labelled)
    svc2 = make_service(build_policies(roots))
    fi_name = "p/savepool/fault.bin"
    fi_payload = b"FAULT-PAYLOAD-1234"
    orig_link = local_write.LocalWriter._os_link

    def inject(self, *a, **k):
        orig_link(self, *a, **k)      # publish really happens ...
        raise OSError(errno.EIO, "injected post-publish failure")

    local_write.LocalWriter._os_link = inject
    fi_code = fi_uncertain = fi_retry = None
    try:
        try:
            svc2.save(AGENT_SPECS[0][0], "s0", fi_name, fi_payload,
                      overwrite=False)
            failures.append("fault_injection: save unexpectedly succeeded")
        except ServiceError as exc:
            fi_code, fi_uncertain, fi_retry = exc.code, exc.outcome_uncertain, exc.retry_safe
    finally:
        local_write.LocalWriter._os_link = orig_link
    ok("fault_post_publish_code", fi_code == "unavailable", f"code={fi_code}")
    ok("fault_outcome_uncertain", fi_uncertain is True, f"uncertain={fi_uncertain}")
    ok("fault_retry_not_safe", fi_retry is False, f"retry_safe={fi_retry}")
    # the file WAS published before the error -> genuine uncertainty
    published = svc2.read(AGENT_SPECS[0][0], "s0", fi_name, offset=0,
                          length=64).data
    ok("fault_published_before_error", published == fi_payload,
       f"published={published!r}")
    svc2.close(timeout=5.0)

    # 12. resource gates
    fd1 = _nfd()
    if fd0 is not None and fd1 is not None:
        ok("fd_returns_baseline", fd1 <= fd0 + MAX_FD_SLACK, f"{fd0}->{fd1}")
    leaked = _scan_temp_leaks(roots)
    ok("no_temp_leaks", not leaked, f"{leaked[:3]}")

    summary = {
        "checks": checks,
        "failures": failures,
        "outcomes_seen": seen["codes"],
        "seconds": round(time.monotonic() - t0, 2),
    }
    return summary


# -- entry -------------------------------------------------------------------

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    deadline_s = None
    for a in sys.argv[1:]:
        if a.startswith("--deadline-seconds="):
            deadline_s = float(a.split("=", 1)[1])
    if not args:
        _log("usage: stress_checks.py <env|smoke|soak|edges> <src-dir>")
        return 1
    action = args[0]
    src = args[1] if len(args) > 1 else os.getcwd()
    if src not in sys.path:
        sys.path.insert(0, src)
    deadline = (time.monotonic() + deadline_s) if deadline_s else float("inf")

    if action == "env":
        import drive_tool
        _log(f"  drive_tool at {os.path.dirname(drive_tool.__file__)}")
        _log(f"  python {sys.version.split()[0]}")
        summary = {"action": "env", "ok": True}
    elif action == "smoke":
        summary = run_workload(SMOKE_CALLS, seed=1, deadline=deadline)
        summary["action"] = "smoke"
    elif action == "soak":
        summary = run_workload(SOAK_CALLS, seed=2, deadline=deadline)
        summary["action"] = "soak"
    elif action == "edges":
        summary = run_edges(deadline)
        summary["action"] = "edges"
    else:
        _log(f"unknown action {action!r}")
        return 1

    failures = summary.get("failures", [])
    summary["result"] = "PASS" if not failures else "FAIL"
    for f in failures:
        _log(f"  !! {f}")
    _log(f"STRESS_RESULT {action}: {summary['result']}")
    _log("STRESS_JSON: " + json.dumps(summary, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

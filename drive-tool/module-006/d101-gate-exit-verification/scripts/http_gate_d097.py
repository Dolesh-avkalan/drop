#!/usr/bin/env python3
"""D096 independent HTTP stress-gate harness (stdlib only).

Separate harness, NOT a production or test file.  It drives the frozen candidate
adapter (base b962a04df1c5abdb78c37617d3a6adca02d04024) over synthetic roots and
accounts for every scheduled intent with the D089 orthogonal buckets.

Frozen before any execution
---------------------------
schedule seed        0xD096
smoke600             600 = 580 valid + 20 read-only saves
soak10000            10000 = 9680 valid + 320 read-only saves
agents               6 distinct personas, 6 distinct roots
client leases        5 global, held until response + 55 ms monotonic hold
saturation           50 cycles x (6 occupiers + 1 excess) = 300 success + 50 busy
resources            <=128 MiB workspace, <=32 MiB fixtures, fd back to baseline,
                     7 adapter threads reaped, RSS growth <=64 MiB after warmup,
                     no temp residue, 900 s outer budget per stage

Accounting buckets (D089)
-------------------------
valid_below_capacity_success | expected_readonly_denial | expected_saturation_busy
| unexpected_unavailable | unexpected_other_error

A busy below capacity, any unavailable, any other unexpected error, or an
expected bucket that does not match its frozen count is a gate FAIL.  There are
no blind retries and no error budgets.

Usage
-----
  python3 http_gate.py --repo <repo> --stage smoke|soak|saturation|bounded|adversarial
  python3 http_gate.py --repo <repo> --gate          # smoke, then soak only if smoke passes
  python3 http_gate.py --selfcheck                   # schedule/accounting checks, no adapter
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import socket
import sys
import tempfile
import threading
import time

# --------------------------------------------------------------------------
# Frozen constants.  Nothing here may be tuned after a run has started.
# --------------------------------------------------------------------------
FROZEN_SEED = 0x0D096
AGENT_COUNT = 6

SMOKE_TOTAL = 600
SMOKE_VALID = 580
SMOKE_RO_SAVE = 20

SOAK_TOTAL = 10000
SOAK_VALID = 9680
SOAK_RO_SAVE = 320

CLIENT_LEASES = 5
DRAIN_HOLD_SECONDS = 0.055

SAT_CYCLES = 50
SAT_OCCUPIERS = 6
SAT_EXCESS = 1

MAX_WORKSPACE_BYTES = 128 * 1024 * 1024
MAX_FIXTURE_BYTES = 32 * 1024 * 1024
FD_BASELINE_SLACK = 2
EXPECTED_ADAPTER_THREADS = 7
MAX_RSS_GROWTH_BYTES = 64 * 1024 * 1024
STAGE_BUDGET_SECONDS = 900

# Agent personas: (label, root_name, alias, operations, read_cap, write_cap)
PERSONAS = (
    ("agent-main", "main", "main", ("find", "list", "read", "save"), None, None),
    ("agent-other", "other", "other", ("find", "list", "read", "save"), None, None),
    ("agent-small", "small", "small", ("find", "list", "read", "save"), 1024, 1024),
    ("agent-ro", "ro", "ro", ("find", "list", "read"), None, None),
    ("agent-alias-a", "alias_a", "shared", ("find", "list", "read", "save"), None, None),
    ("agent-alias-b", "alias_b", "shared", ("find", "list", "read", "save"), None, None),
)
READ_ONLY_AGENT = 3          # index of agent-ro in PERSONAS
VALID_OPS = ("list", "find", "read", "save")

# Tokens are synthetic and never printed; only a short label is ever reported.
_TOKENS = (
    "d096-main-" + "A" * 40,
    "d096-other-" + "B" * 40,
    "d096-small-" + "C" * 40,
    "d096-ro-" + "D" * 40,
    "d096-alias-a-" + "E" * 40,
    "d096-alias-b-" + "F" * 40,
)


def token_label(index: int) -> str:
    """A stable, non-secret label for an agent (never the token itself)."""
    return "agent%d" % index


# --------------------------------------------------------------------------
# Frozen schedule
# --------------------------------------------------------------------------
class Intent:
    __slots__ = ("seq", "agent", "op", "file_id", "expect")

    def __init__(self, seq, agent, op, file_id, expect):
        self.seq = seq
        self.agent = agent
        self.op = op
        self.file_id = file_id
        self.expect = expect          # "ok" | "denied" | "busy"

    def as_dict(self):
        return {"seq": self.seq, "agent": token_label(self.agent), "op": self.op,
                "file_id": self.file_id, "expect": self.expect}


def frozen_schedule(total=SMOKE_TOTAL, valid=SMOKE_VALID, ro_save=SMOKE_RO_SAVE,
                    seed=FROZEN_SEED):
    """Build the frozen, replayable intent schedule.

    Exactly ``ro_save`` intents are dispatched by the read-only persona running
    ``save`` (expected denial); the remaining ``valid`` intents are authorized
    operations on their own persona's root (expected OK).
    """
    if valid + ro_save != total:
        raise ValueError("valid + ro_save must equal total")
    items = []
    for k in range(ro_save):
        items.append((READ_ONLY_AGENT, "save", "p/savepool/ro%03d.bin" % k, "denied"))
    for k in range(valid):
        agent = k % AGENT_COUNT
        op = VALID_OPS[k % len(VALID_OPS)]
        if agent == READ_ONLY_AGENT and op == "save":
            op = "read"                      # read-only persona cannot write
        if op == "list":
            file_id = "root"
        elif op == "find":
            file_id = "root"
        elif op == "read":
            file_id = "p/readme.txt"      # canonical prefix; the client rejects bare names
        else:
            file_id = "p/savepool/v%03d.bin" % (k % 64)
        items.append((agent, op, file_id, "ok"))
    random.Random(seed).shuffle(items)
    return [Intent(i, a, o, f, e) for i, (a, o, f, e) in enumerate(items)]


def schedule_fingerprint(intents) -> str:
    h = hashlib.sha256()
    for it in intents:
        h.update(("%d|%d|%s|%s|%s\n" % (it.seq, it.agent, it.op, it.file_id,
                                        it.expect)).encode("ascii"))
    return h.hexdigest()


def schedule_counts(intents):
    counts = {"ok": 0, "denied": 0, "busy": 0}
    per_agent = {}
    for it in intents:
        counts[it.expect] += 1
        per_agent[token_label(it.agent)] = per_agent.get(token_label(it.agent), 0) + 1
    return counts, per_agent


# --------------------------------------------------------------------------
# Accounting (D089 orthogonal buckets)
# --------------------------------------------------------------------------
BUCKETS = ("valid_below_capacity_success", "expected_readonly_denial",
           "expected_saturation_busy", "unexpected_unavailable",
           "unexpected_other_error")


def classify(expect, status, code, transport_exc):
    """Map one terminal outcome to exactly one accounting bucket.

    ``expect`` is the frozen pre-dispatch intent: "ok", "denied" (read-only save)
    or "busy" (deterministic saturation excess probe).
    """
    if transport_exc is not None:
        return "unexpected_unavailable" if code == "unavailable" else "unexpected_other_error"
    if code == "unavailable":
        return "unexpected_unavailable"
    if code == "timeout":
        return "unexpected_other_error"
    if expect == "busy":
        if code == "busy":
            return "expected_saturation_busy"
        return "unexpected_other_error"
    if expect == "denied":
        if code == "denied":
            return "expected_readonly_denial"
        return "unexpected_other_error"       # an RO save that was NOT denied
    # expect == "ok"
    if status == 200 and code is None:
        return "valid_below_capacity_success"
    return "unexpected_other_error"           # busy below capacity, denied, 5xx


def verdict(buckets, expected):
    """A gate passes only when every bucket matches its frozen count exactly."""
    problems = []
    for name in BUCKETS:
        want = expected.get(name, 0)
        got = buckets.get(name, 0)
        if got != want:
            problems.append("%s: expected %d, got %d" % (name, want, got))
    return (not problems), problems


# --------------------------------------------------------------------------
# Synthetic roots (bounded)
# --------------------------------------------------------------------------
def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


def build_roots(base):
    """Create six distinct persona roots with bounded fixtures (<=32 MiB total)."""
    total = 0
    roots = {}
    for _label, root_name, _alias, _ops, _rc, _wc in PERSONAS:
        root = os.path.join(base, "root_" + root_name)
        os.makedirs(os.path.join(root, "sub"), exist_ok=True)
        os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
        total += _write(os.path.join(root, "readme.txt"), b"d096 fixture readme\n" * 4)
        total += _write(os.path.join(root, "data.bin"), bytes(range(256)) * 16)
        total += _write(os.path.join(root, "empty.bin"), b"")
        total += _write(os.path.join(root, "sub", "note.txt"), b"nested note\n")
        roots[root_name] = os.path.realpath(root)
    if total > MAX_FIXTURE_BYTES:
        raise RuntimeError("fixtures exceed the frozen 32 MiB bound")
    return roots, total


def build_policies(roots):
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    policies = []
    for idx, (label, root_name, alias, ops, rc, wc) in enumerate(PERSONAS):
        grant = SourceGrant(
            alias=alias,
            root=roots[root_name],
            operations=frozenset(ops),
            max_read_bytes=rc if rc is not None else 1048576,
            max_write_bytes=wc if wc is not None else 1048576,
        )
        policies.append(AgentPolicy(
            agent_id=label,
            token_sha256=hashlib.sha256(_TOKENS[idx].encode("ascii")).digest(),
            grants=(grant,),
        ))
    return tuple(policies)


# --------------------------------------------------------------------------
# Drain-aware lease limiter
# --------------------------------------------------------------------------
class LeaseLimiter:
    """K global client leases; each is held until response + a monotonic hold."""

    def __init__(self, capacity, hold_seconds):
        self._sem = threading.BoundedSemaphore(capacity)
        self._hold = hold_seconds
        self.max_held = 0
        self._lock = threading.Lock()
        self._held = 0

    def acquire(self):
        self._sem.acquire()
        with self._lock:
            self._held += 1
            if self._held > self.max_held:
                self.max_held = self._held

    def release(self, response_ts):
        wait = (response_ts + self._hold) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        with self._lock:
            self._held -= 1
        self._sem.release()


# --------------------------------------------------------------------------
# Resource / lifecycle accounting
# --------------------------------------------------------------------------
def _nfd():
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return None


def _rss_kb():
    try:
        with open("/proc/self/status", "r") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _adapter_threads():
    return sorted(t.name for t in threading.enumerate()
                  if t.name.startswith("drive-http"))


def _tree_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


# --------------------------------------------------------------------------
# Stage runner
# --------------------------------------------------------------------------
def run_stage(repo, total, valid, ro_save, stage, hold=DRAIN_HOLD_SECONDS,
              leases=CLIENT_LEASES, budget=STAGE_BUDGET_SECONDS):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient, DriveClientError

    base = tempfile.mkdtemp(prefix="d096-gate-")
    started = time.monotonic()
    try:
        adapter = None
        roots, fixture_bytes = build_roots(base)
        policies = build_policies(roots)
        intents = frozen_schedule(total, valid, ro_save)
        counts, per_agent = schedule_counts(intents)

        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
        time.sleep(0.1)                       # warmup before the RSS baseline
        fd0, rss0 = _nfd(), _rss_kb()
        threads_live = _adapter_threads()

        limiter = LeaseLimiter(leases, hold)
        buckets = {name: 0 for name in BUCKETS}
        records = []
        lock = threading.Lock()
        deadline = started + budget

        def worker(shard):
            local = []
            for intent in shard:
                if time.monotonic() > deadline:
                    break
                limiter.acquire()
                t0 = time.monotonic()
                status = None
                code = None
                unc = retry = None
                transport_exc = None
                alias = PERSONAS[intent.agent][2]
                try:
                    client = DriveClient(port=adapter.port, token=_TOKENS[intent.agent],
                                         timeout=5.0)
                    if intent.op == "list":
                        client.list(alias, limit=20)
                    elif intent.op == "find":
                        client.find(alias, name_contains="data", limit=10)
                    elif intent.op == "read":
                        client.read(alias, intent.file_id, offset=0, length=64)
                    else:
                        client.save(alias, intent.file_id, b"x" * 8, overwrite=True)
                    status = 200
                except DriveClientError as exc:
                    code = exc.code
                    unc = exc.outcome_uncertain
                    retry = exc.retry_safe
                except Exception as exc:      # noqa: BLE001
                    transport_exc = type(exc).__name__
                response_ts = time.monotonic()
                bucket = classify(intent.expect, status, code, transport_exc)
                local.append({
                    "seq": intent.seq, "agent": token_label(intent.agent),
                    "op": intent.op, "expect": intent.expect, "bucket": bucket,
                    "status": status, "code": code,
                    "outcome_uncertain": unc, "retry_safe": retry,
                    "transport": transport_exc,
                    "duration_ms": round((response_ts - t0) * 1000.0, 3),
                })
                limiter.release(response_ts)
            with lock:
                for rec in local:
                    buckets[rec["bucket"]] += 1
                records.extend(local)

        shards = [intents[i::leases] for i in range(leases)]
        threads = [threading.Thread(target=worker, args=(s,), name="d096-client-%d" % i)
                   for i, s in enumerate(shards)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=budget)

        closed = adapter.close(timeout=10.0)
        elapsed = time.monotonic() - started
        fd1, rss1 = _nfd(), _rss_kb()
        threads_after = _adapter_threads()
        workspace_bytes = _tree_bytes(base)

        expected = {"valid_below_capacity_success": valid,
                    "expected_readonly_denial": ro_save,
                    "expected_saturation_busy": 0,
                    "unexpected_unavailable": 0,
                    "unexpected_other_error": 0}
        ok, problems = verdict(buckets, expected)

        resources = {
            "workspace_bytes": workspace_bytes,
            "workspace_limit_bytes": MAX_WORKSPACE_BYTES,
            "fixture_bytes": fixture_bytes,
            "fixture_limit_bytes": MAX_FIXTURE_BYTES,
            "fd_before": fd0, "fd_after": fd1,
            "fd_ok": (fd0 is None or fd1 is None or fd1 <= fd0 + FD_BASELINE_SLACK),
            "adapter_threads_live": threads_live,
            "adapter_threads_after_close": threads_after,
            "adapter_threads_ok": (len(threads_live) == EXPECTED_ADAPTER_THREADS
                                   and not threads_after),
            "rss_before_kb": rss0, "rss_after_kb": rss1,
            "rss_growth_bytes": (None if rss0 is None or rss1 is None
                                 else (rss1 - rss0) * 1024),
            "rss_ok": (rss0 is None or rss1 is None
                       or (rss1 - rss0) * 1024 <= MAX_RSS_GROWTH_BYTES),
            "closed": closed,
            "max_leases_held": limiter.max_held,
            "elapsed_seconds": round(elapsed, 3),
            "within_budget": elapsed <= budget,
        }
        if not resources["closed"]:
            ok, problems = False, problems + ["adapter.close() did not return True"]
        for key in ("fd_ok", "adapter_threads_ok", "rss_ok", "within_budget"):
            if not resources[key]:
                ok, problems = False, problems + ["resource bound failed: " + key]
        if resources["workspace_bytes"] > MAX_WORKSPACE_BYTES:
            ok, problems = False, problems + ["workspace exceeds the frozen bound"]
        if resources["max_leases_held"] > leases:
            ok, problems = False, problems + ["client leases exceeded K"]

        records.sort(key=lambda r: r["seq"])
        return {
            "harness": "d096-http-gate-harness",
            "stage": stage,
            "frozen": {"seed": FROZEN_SEED, "total": total, "valid": valid,
                       "ro_save": ro_save, "leases": leases, "hold_seconds": hold,
                       "budget_seconds": budget},
            "schedule_fingerprint": schedule_fingerprint(intents),
            "schedule_counts": counts,
            "schedule_per_agent": per_agent,
            "requested": len(records),
            "buckets": buckets,
            "expected": expected,
            "result": "PASS" if ok else "FAIL",
            "problems": problems,
            "resources": resources,
            "records": records,
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        residue = _tree_bytes(base)
        shutil.rmtree(base, ignore_errors=True)
        if residue and os.path.isdir(base):
            sys.stderr.write("warning: temp residue at %s\n" % base)


# --------------------------------------------------------------------------
# Track B: deterministic 6+1 saturation
# --------------------------------------------------------------------------
def _raw_request(path, token, body, ctype=b"application/json"):
    head = (b"POST " + path.encode("ascii") + b" HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Authorization: Bearer " + token.encode("ascii") + b"\r\n"
            b"Content-Type: " + ctype + b"\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n")
    return head + body


def _raw_exchange(port, payload, *, timeout=5.0, read_delay=0.0):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(payload)
        if read_delay:
            time.sleep(read_delay)
        s.settimeout(timeout)
        chunks = []
        while True:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        s.close()


def _status_code(raw):
    if not raw:
        return None, None
    try:
        status = int(raw.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return None, None
    code = None
    if b"\r\n\r\n" in raw:
        try:
            obj = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
            if isinstance(obj, dict) and obj.get("ok") is False \
                    and isinstance(obj.get("error"), dict):
                code = obj["error"].get("code")
        except Exception:  # noqa: BLE001
            pass
    return status, code


# --------------------------------------------------------------------------
# Track B: deterministic 6+1 saturation (D097 correction)
#
# D096/D095 placed the excess probe inside a 50 ms drain window using a
# threading.Barrier plus a read_delay and a 10 ms excess sleep.  That is a
# timing race: if the excess connection is accepted before all six occupiers
# hold a worker slot, the excess is admitted and an occupier is rejected busy
# (the D095 "299 valid / 49 busy / 2 other" flake).  It is not deterministic.
#
# The D097 correction holds the six admitted operations at a REAL service-entry
# barrier: the harness service blocks inside its list() handler until all six
# workers have confirmed entry, the excess probe is sent only then (while all
# six slots are provably held in-handler), and the six are released only after
# the probe has been fully answered.  No socket-open / drain-window timing is
# used anywhere on the saturation path.
# --------------------------------------------------------------------------
class _EntryGate:
    """A per-cycle real service-entry barrier for exactly ``n`` workers."""

    def __init__(self, n):
        self._n = n
        self._lock = threading.Lock()
        self._count = 0
        self.entered = threading.Event()      # set once all n have entered
        self.release = threading.Event()      # main sets to let them proceed

    @property
    def count(self):
        with self._lock:
            return self._count

    def enter(self):
        with self._lock:
            self._count += 1
            if self._count >= self._n:
                self.entered.set()
        self.release.wait(timeout=30.0)


def _make_gated_service(policies):
    """LocalFileService subclass whose list() waits on the active entry gate."""
    from drive_tool.file_service import LocalFileService

    class _GatedService(LocalFileService):
        _gate = None

        def list(self, token, source_id, file_id="root", **kwargs):
            gate = self._gate
            if gate is not None:
                gate.enter()
            return super().list(token, source_id, file_id, **kwargs)

    return _GatedService(policies)


def run_saturation(repo, cycles=SAT_CYCLES, budget=STAGE_BUDGET_SECONDS):
    """Deterministic overload with a REAL service-entry barrier.

    Six admitted list operations are held inside the service handler until all
    six workers have confirmed entry; only then is the excess probe sent.  With
    every worker slot provably occupied in-handler, the excess must receive a
    503 busy envelope, and no occupier can be rejected.
    """
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter

    base = tempfile.mkdtemp(prefix="d097-sat-")
    started = time.monotonic()
    try:
        adapter = None
        roots, _fixture = build_roots(base)
        policies = build_policies(roots)
        service = _make_gated_service(policies)
        adapter = DriveHTTPAdapter(service=service, port=0, socket_timeout=5.0)
        time.sleep(0.1)
        fd0 = _nfd()
        threads_live = _adapter_threads()
        token = _TOKENS[0]
        payload = json.dumps({"source_id": "main", "file_id": "root",
                              "limit": 20, "offset": 0}).encode("ascii")
        req = _raw_request("/v1/list", token, payload)

        results = []
        for cycle in range(cycles):
            gate = _EntryGate(SAT_OCCUPIERS)
            service._gate = gate
            cycle_out = {}

            def occupier(slot):
                raw = _raw_exchange(adapter.port, req, timeout=15.0)
                status, code = _status_code(raw)
                cycle_out[("occupier", slot)] = (status, code)

            threads = [threading.Thread(target=occupier, args=(i,))
                       for i in range(SAT_OCCUPIERS)]
            for t in threads:
                t.start()

            entered_ok = gate.entered.wait(timeout=20.0)
            entered_count = gate.count

            # All six worker slots are provably held inside the handler here.
            exc_raw = _raw_exchange(adapter.port, req, timeout=15.0)
            exc = _status_code(exc_raw)
            cycle_out[("excess", 0)] = exc

            # Release the six only after the excess probe is complete.
            gate.release.set()
            for t in threads:
                t.join(timeout=20.0)

            service._gate = None

            occ = [cycle_out.get(("occupier", i), (None, None))
                   for i in range(SAT_OCCUPIERS)]
            results.append({"cycle": cycle, "entered_count": entered_count,
                            "entered_ok": entered_ok,
                            "occupiers": occ, "excess": exc})

        closed = adapter.close(timeout=10.0)
        elapsed = time.monotonic() - started
        fd1 = _nfd()
        threads_after = _adapter_threads()

        occ_ok = sum(1 for r in results for (s, c) in r["occupiers"] if s == 200)
        occ_bad = sum(1 for r in results for (s, c) in r["occupiers"]
                      if not (s == 200))
        exc_busy = sum(1 for r in results if r["excess"][1] == "busy")
        exc_unavail = sum(1 for r in results if r["excess"][1] == "unavailable")
        exc_other = len(results) - exc_busy - exc_unavail
        entered_misses = sum(1 for r in results if not r["entered_ok"])

        buckets = {
            "valid_below_capacity_success": occ_ok,
            "expected_readonly_denial": 0,
            "expected_saturation_busy": exc_busy,
            "unexpected_unavailable": exc_unavail,
            "unexpected_other_error": occ_bad + exc_other,
        }
        expected = {"valid_below_capacity_success": SAT_OCCUPIERS * cycles,
                    "expected_readonly_denial": 0,
                    "expected_saturation_busy": SAT_EXCESS * cycles,
                    "unexpected_unavailable": 0,
                    "unexpected_other_error": 0}
        ok, problems = verdict(buckets, expected)
        if entered_misses:
            ok, problems = False, problems + [
                "service-entry barrier not reached in %d cycle(s)" % entered_misses]
        if not closed:
            ok, problems = False, problems + ["adapter.close() did not return True"]
        if threads_after:
            ok, problems = False, problems + ["adapter threads not reaped"]
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_BASELINE_SLACK:
            ok, problems = False, problems + ["fd did not return to baseline"]

        return {
            "harness": "d097-http-gate-harness",
            "stage": "saturation_6plus1",
            "saturation_mode": "real-service-entry-barrier",
            "frozen": {"cycles": cycles, "occupiers": SAT_OCCUPIERS,
                       "excess": SAT_EXCESS, "budget_seconds": budget},
            "requested": cycles * (SAT_OCCUPIERS + SAT_EXCESS),
            "buckets": buckets,
            "expected": expected,
            "result": "PASS" if ok else "FAIL",
            "problems": problems,
            "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                          "adapter_threads_live": threads_live,
                          "adapter_threads_after_close": threads_after,
                          "elapsed_seconds": round(elapsed, 3),
                          "within_budget": elapsed <= budget},
            "cycles": results,
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# Adversarial protocol track: best effort, never a normal gate pass
# --------------------------------------------------------------------------
def run_adversarial(repo, budget=STAGE_BUDGET_SECONDS):
    """Adversarial framing probes.  Reported separately; never a gate pass."""
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter

    base = tempfile.mkdtemp(prefix="d096-adv-")
    try:
        adapter = None
        roots, _fixture = build_roots(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=1.0)
        time.sleep(0.1)
        token = _TOKENS[0]
        body = json.dumps({"source_id": "main", "file_id": "root",
                           "limit": 20, "offset": 0}).encode("ascii")
        cases = {
            "overlong_request_line": b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n",
            "overlong_header_block":
                b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n",
            "bare_lf_header_block": b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n",
            "huge_digit_content_length":
                _raw_request("/v1/list", token, b"").replace(
                    b"Content-Length: 0", b"Content-Length: " + b"9" * 5000),
            "duplicate_content_length": (
                b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                b"Authorization: Bearer " + token.encode("ascii") + b"\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"Connection: close\r\n\r\n" + body),
            "non_digit_content_length":
                _raw_request("/v1/list", token, body).replace(
                    b"Content-Length: " + str(len(body)).encode("ascii"),
                    b"Content-Length: +5"),
            "buffered_trailing_bytes": _raw_request("/v1/list", token, body) + b"X",
        }
        observed = {}
        for name, payload in sorted(cases.items()):
            raw = _raw_exchange(adapter.port, payload, timeout=2.0)
            status, code = _status_code(raw)
            observed[name] = {"status": status, "code": code,
                              "bytes": len(raw)}
        adapter.close(timeout=5.0)
        return {
            "harness": "d096-http-gate-harness",
            "stage": "adversarial_protocol",
            "kind": "adversarial-best-effort",
            "gate_pass": False,
            "note": ("Adversarial framing probes are recorded for information "
                     "only.  This track is NOT a normal gate pass and must never "
                     "be reported as acceptance."),
            "observed": observed,
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# Gating helper: smoke, then soak only if smoke passes
# --------------------------------------------------------------------------
def run_gate(repo, allow_diagnostic_soak=False):
    smoke = run_stage(repo, SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE, "smoke600")
    if smoke["result"] != "PASS" and not allow_diagnostic_soak:
        return {"smoke": smoke, "soak": None,
                "note": "soak withheld: smoke did not pass (no soak after smoke fail)"}
    soak = run_stage(repo, SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE, "soak10000")
    if smoke["result"] != "PASS":
        soak = dict(soak, result="DIAGNOSTIC-NOT-GATED-PASS",
                    note="smoke failed; this soak run is diagnostic only")
    return {"smoke": smoke, "soak": soak}


# --------------------------------------------------------------------------
# Self-check (schedule + accounting), no adapter required
# --------------------------------------------------------------------------
def selfcheck():
    problems = []
    smoke = frozen_schedule(SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE)
    soak = frozen_schedule(SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE)
    for name, intents, total, valid, ro in (
            ("smoke600", smoke, SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE),
            ("soak10000", soak, SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE)):
        counts, per_agent = schedule_counts(intents)
        if len(intents) != total:
            problems.append("%s: %d intents != %d" % (name, len(intents), total))
        if counts["ok"] != valid:
            problems.append("%s: ok %d != %d" % (name, counts["ok"], valid))
        if counts["denied"] != ro:
            problems.append("%s: denied %d != %d" % (name, counts["denied"], ro))
        if len(per_agent) != AGENT_COUNT:
            problems.append("%s: %d personas != %d" % (name, len(per_agent), AGENT_COUNT))
        for it in intents:
            if it.agent == READ_ONLY_AGENT and it.op == "save" and it.expect != "denied":
                problems.append("%s: RO save not marked denied" % name)
            if it.expect == "ok" and it.op == "save" and it.agent == READ_ONLY_AGENT:
                problems.append("%s: RO agent given an authorized save" % name)
        again = frozen_schedule(total, valid, ro)
        if schedule_fingerprint(again) != schedule_fingerprint(intents):
            problems.append("%s: schedule is not replayable" % name)

    # accounting truth table
    table = [
        ("ok", 200, None, None, "valid_below_capacity_success"),
        ("ok", None, "busy", None, "unexpected_other_error"),
        ("ok", None, "denied", None, "unexpected_other_error"),
        ("ok", None, "unavailable", None, "unexpected_unavailable"),
        ("ok", None, "timeout", None, "unexpected_other_error"),
        ("denied", None, "denied", None, "expected_readonly_denial"),
        ("denied", 200, None, None, "unexpected_other_error"),
        ("denied", None, "busy", None, "unexpected_other_error"),
        ("denied", None, "unavailable", None, "unexpected_unavailable"),
        ("busy", None, "busy", None, "expected_saturation_busy"),
        ("busy", None, "unavailable", None, "unexpected_unavailable"),
        ("busy", 200, None, None, "unexpected_other_error"),
        ("ok", None, "unavailable", "RemoteDisconnected", "unexpected_unavailable"),
        ("ok", None, None, "OSError", "unexpected_other_error"),
    ]
    for expect, status, code, exc, want in table:
        got = classify(expect, status, code, exc)
        if got != want:
            problems.append("classify(%r,%r,%r,%r) -> %s != %s"
                            % (expect, status, code, exc, got, want))

    # saturation arithmetic
    if SAT_OCCUPIERS * SAT_CYCLES != 300:
        problems.append("saturation success arithmetic != 300")
    if SAT_EXCESS * SAT_CYCLES != 50:
        problems.append("saturation busy arithmetic != 50")
    if DRAIN_HOLD_SECONDS < 0.055:
        problems.append("drain hold below the frozen 55 ms")

    return {
        "harness": "d096-http-gate-harness",
        "stage": "selfcheck",
        "result": "PASS" if not problems else "FAIL",
        "problems": problems,
        "schedule_fingerprints": {
            "smoke600": schedule_fingerprint(smoke),
            "soak10000": schedule_fingerprint(soak),
        },
        "schedule_counts": {
            "smoke600": schedule_counts(smoke)[0],
            "soak10000": schedule_counts(soak)[0],
        },
        "saturation_arithmetic": {"valid": SAT_OCCUPIERS * SAT_CYCLES,
                                  "busy": SAT_EXCESS * SAT_CYCLES},
        "frozen": {"seed": FROZEN_SEED, "leases": CLIENT_LEASES,
                   "hold_seconds": DRAIN_HOLD_SECONDS},
    }


def run_bounded(repo, calls=60, budget=120):
    """Bounded cleanup check: a small workload plus full resource accounting."""
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient

    base = tempfile.mkdtemp(prefix="d096-bounded-")
    try:
        adapter = None
        roots, fixture_bytes = build_roots(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
        time.sleep(0.1)
        fd0, rss0 = _nfd(), _rss_kb()
        live = _adapter_threads()
        token = _TOKENS[0]
        ok = 0
        for i in range(calls):
            DriveClient(port=adapter.port, token=token, timeout=5.0).list(
                "main", limit=20)
            ok += 1
        closed = adapter.close(timeout=10.0)
        time.sleep(0.05)
        fd1, rss1 = _nfd(), _rss_kb()
        after = _adapter_threads()
        residue = _tree_bytes(base)
        problems = []
        if not closed:
            problems.append("close did not return True")
        if after:
            problems.append("adapter threads not reaped: %s" % after)
        if len(live) != EXPECTED_ADAPTER_THREADS:
            problems.append("live adapter threads %d != %d"
                            % (len(live), EXPECTED_ADAPTER_THREADS))
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_BASELINE_SLACK:
            problems.append("fd %s -> %s" % (fd0, fd1))
        if rss0 is not None and rss1 is not None and (rss1 - rss0) * 1024 > MAX_RSS_GROWTH_BYTES:
            problems.append("rss grew beyond the frozen bound")
        return {
            "harness": "d096-http-gate-harness",
            "stage": "bounded_cleanup",
            "calls": calls, "ok": ok,
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                          "adapter_threads_live": live,
                          "adapter_threads_after_close": after,
                          "rss_before_kb": rss0, "rss_after_kb": rss1,
                          "fixture_bytes": fixture_bytes,
                          "residue_bytes": residue},
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="D096 independent HTTP stress-gate harness")
    ap.add_argument("--repo", help="path to the drive-tool checkout to exercise")
    ap.add_argument("--stage", choices=("smoke", "soak", "saturation", "bounded",
                                        "adversarial"))
    ap.add_argument("--gate", action="store_true",
                    help="run smoke, then soak only if smoke passes")
    ap.add_argument("--allow-diagnostic-soak", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--dump-schedule", metavar="PATH",
                    help="write the frozen schedules + fingerprints to PATH and exit")
    ap.add_argument("--json", help="write the full result to this path")
    ap.add_argument("--quiet", action="store_true", help="omit per-call records")
    args = ap.parse_args(argv)

    if args.dump_schedule:
        smoke = frozen_schedule(SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE)
        soak = frozen_schedule(SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE)
        dump = {
            "harness": "d096-http-gate-harness",
            "stage": "frozen_schedule",
            "frozen": {"seed": FROZEN_SEED, "leases": CLIENT_LEASES,
                       "hold_seconds": DRAIN_HOLD_SECONDS,
                       "budget_seconds": STAGE_BUDGET_SECONDS},
            "schedules": {},
        }
        for name, intents in (("smoke600", smoke), ("soak10000", soak)):
            counts, per_agent = schedule_counts(intents)
            dump["schedules"][name] = {
                "fingerprint": schedule_fingerprint(intents),
                "counts": counts,
                "per_agent": per_agent,
                "intents": [it.as_dict() for it in intents],
            }
        with open(args.dump_schedule, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, indent=2, sort_keys=True)
        print("wrote", args.dump_schedule)
        return 0
    if args.selfcheck:
        out = selfcheck()
    elif args.gate:
        if not args.repo:
            ap.error("--repo is required")
        out = run_gate(args.repo, args.allow_diagnostic_soak)
    elif args.stage:
        if not args.repo:
            ap.error("--repo is required")
        if args.stage == "smoke":
            out = run_stage(args.repo, SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE, "smoke600")
        elif args.stage == "soak":
            out = run_stage(args.repo, SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE, "soak10000")
        elif args.stage == "saturation":
            out = run_saturation(args.repo)
        elif args.stage == "bounded":
            out = run_bounded(args.repo)
        else:
            out = run_adversarial(args.repo)
    else:
        ap.error("choose --selfcheck, --gate or --stage")

    if args.quiet and isinstance(out, dict):
        out = dict(out)
        if isinstance(out.get("records"), list):
            out["records"] = "<%d records omitted>" % len(out["records"])
        if isinstance(out.get("cycles"), list):
            out["cycles"] = "<%d cycles omitted>" % len(out["cycles"])
    text = json.dumps(out, indent=2, sort_keys=True, default=str)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0 if out.get("result") == "PASS" or out.get("stage") == "adversarial_protocol" else 1


if __name__ == "__main__":
    raise SystemExit(main())

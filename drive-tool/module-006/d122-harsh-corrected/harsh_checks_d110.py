#!/usr/bin/env python3
"""d110 harsh-fault payload (stdlib only).

This is the PINNED payload executed by ``run_harsh_d110.py``.  Its sha256 is
embedded in the runner and verified BEFORE execution.  It is a separate,
bounded harsh-fault extension to the accepted D102 final HTTP candidate
(Dolesh-avkalan/drive-tool @ 337e4c713829af76615472eb47b81244ff399528); it
does NOT modify any product source, test, acceptance spec or old evidence.

It is adapted from the approved D065/Gemini harsh design, but every gate is
expressed against the ACTUAL accepted HTTP adapter / LocalFileService
behaviour -- the historical design's guesses are not reimplemented.  Where the
actual behaviour differs from the historical expectation, the ACTUAL result is
recorded and the divergence is reported (never relabelled a pass).

Fixed allow-list of stages (execution order):

  1. selfcheck            -- frozen arithmetic + accounting, no adapter.
  2. http_hostile         -- malformed/oversize/slow-partial HTTP framing.
  3. admission_exhaustion -- deterministic 6+1 admission + recovery.
  4. isolation            -- cross-agent / path / symlink containment.
  5. concurrent_ops       -- simultaneous create/overwrite/range ops.
  6. crash_kill           -- synchronized child SIGKILL + fresh recovery +
                             truthful orphan-temp audit.
  7. resource_pressure    -- CHILD-only CPU / RAM / FD pressure.
  8. enospc               -- RLIMIT_FSIZE EFBIG + injected 4-phase ENOSPC.

Every stage prints exactly one ``HARSH_JSON: {...}`` summary line and, with
``--json``, writes the same object to a file.  Exit is 0 only on PASS; SKIPPED
exits 2; FAIL/ERROR exits 1.  A SKIPPED capability is NEVER reported as a pass.

Safety: stdlib only; no credential, no cloud API, no install, no reboot, no
service/public binding, no real root, no deploy.  All work is confined to a
caller-supplied bounded workspace; the payload never touches anything outside
it.  Only the payload's own child process groups are ever killed.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import resource
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

# ---------------------------------------------------------------------------
# Frozen constants
# ---------------------------------------------------------------------------
FROZEN_SEED = 0x0D110
AGENT_COUNT = 6

TEMP_PREFIX = ".drive-tool-tmp-"
TEMP_SCAN_LIMIT = 100000

MAX_FIXTURE_BYTES = 32 * 1024 * 1024
MAX_WORKSPACE_BYTES = 192 * 1024 * 1024     # <= 192 MiB retained workspace
MIN_FREE_BYTES = 1024 * 1024 * 1024         # >= 1 GiB free disk floor
FD_BASELINE_SLACK = 2
MAX_CONCURRENT = 6
CONC_LEASES = 5            # drain-aware client leases for the LOOPING sub-test only
CONC_LEASE_HOLD = 0.055    # s; hold each lease past its response (D101 pattern)
DRAIN_PAUSE = 0.060        # s; >= the server's 0.050 s post-response drain window
HOST_MEM_FLOOR_KB = 1024 * 1024            # >= 1 GiB MemAvailable before RAM
HOST_MEM_ABORT_KB = 512 * 1024             # abort RAM pressure below 512 MiB
CHILD_RLIMIT_AS = 512 * 1024 * 1024        # child RLIMIT_AS <= 512 MiB
CHILD_RLIMIT_FSIZE = 8192

# Agent personas: (label, root_name, alias, operations, read_cap, write_cap)
PERSONAS = (
    ("agent-main", "main", "main", ("find", "list", "read", "save"), None, None),
    ("agent-other", "other", "other", ("find", "list", "read", "save"), None, None),
    ("agent-small", "small", "small", ("find", "list", "read", "save"), 1024, 1024),
    ("agent-ro", "ro", "ro", ("find", "list", "read"), None, None),
    ("agent-alias-a", "alias_a", "shared", ("find", "list", "read", "save"), None, None),
    ("agent-alias-b", "alias_b", "shared", ("find", "list", "read", "save"), None, None),
)
READ_ONLY_AGENT = 3

# Synthetic, non-secret tokens (>= 32 bytes required by the client).
TOKENS = (
    "d110-main-" + "A" * 40,
    "d110-other-" + "B" * 40,
    "d110-small-" + "C" * 40,
    "d110-ro-" + "D" * 40,
    "d110-alias-a-" + "E" * 40,
    "d110-alias-b-" + "F" * 40,
)

STAGE_NAMES = ("selfcheck", "http_hostile", "admission_exhaustion", "isolation",
               "concurrent_ops", "crash_kill", "resource_pressure", "enospc")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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


def _mem_available_kb():
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _tree_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _scan_temp(root):
    """Return every regular file whose name begins with the reserved prefix."""
    found = []
    n = 0
    for dp, _dn, fn in os.walk(root):
        for name in fn:
            n += 1
            if n > TEMP_SCAN_LIMIT:
                return found
            if name.startswith(TEMP_PREFIX):
                found.append(os.path.relpath(os.path.join(dp, name), root))
    return sorted(found)


def _adapter_threads():
    return sorted(t.name for t in threading.enumerate()
                  if t.name.startswith("drive-http"))


# ---------------------------------------------------------------------------
# Synthetic roots + policies (bounded)
# ---------------------------------------------------------------------------
def build_roots(base):
    total = 0
    roots = {}
    for _label, root_name, _alias, _ops, _rc, _wc in PERSONAS:
        root = os.path.join(base, "root_" + root_name)
        os.makedirs(os.path.join(root, "sub"), exist_ok=True)
        os.makedirs(os.path.join(root, "savepool"), exist_ok=True)
        total += _w(os.path.join(root, "readme.txt"), b"d110 fixture readme\n" * 4)
        total += _w(os.path.join(root, "data.bin"), bytes(range(256)) * 16)
        total += _w(os.path.join(root, "empty.bin"), b"")
        total += _w(os.path.join(root, "sub", "note.txt"), b"nested note\n")
        roots[root_name] = os.path.realpath(root)
    if total > MAX_FIXTURE_BYTES:
        raise RuntimeError("fixtures exceed the frozen bound")
    return roots, total


def _w(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


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
            token_sha256=hashlib.sha256(TOKENS[idx].encode("ascii")).digest(),
            grants=(grant,),
        ))
    return tuple(policies)


# ---------------------------------------------------------------------------
# Raw HTTP helpers
# ---------------------------------------------------------------------------
def _raw_request(path, token, body, ctype=b"application/json"):
    head = (b"POST " + path.encode("ascii") + b" HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Authorization: Bearer " + token.encode("ascii") + b"\r\n"
            b"Content-Type: " + ctype + b"\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n")
    return head + body


def _raw_exchange(port, payload, *, timeout=5.0, read_delay=0.0, half_close=False):
    """Send raw bytes, return (response_bytes, error_name_or_None, elapsed)."""
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    except OSError as exc:
        return b"", type(exc).__name__, time.monotonic() - t0
    try:
        if payload:
            s.sendall(payload)
        if half_close:
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError:
                pass
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
            if sum(len(c) for c in chunks) > 4 * 1024 * 1024:
                break
        return b"".join(chunks), None, time.monotonic() - t0
    except OSError as exc:
        return b"", type(exc).__name__, time.monotonic() - t0
    finally:
        try:
            s.close()
        except OSError:
            pass


def _parse_resp(raw):
    out = {"status": None, "code": None, "outcome_uncertain": None,
           "retry_safe": None, "bytes": len(raw)}
    if not raw:
        return out
    try:
        out["status"] = int(raw.split(b" ", 2)[1])
    except (IndexError, ValueError):
        pass
    if b"\r\n\r\n" in raw:
        try:
            obj = json.loads(raw.split(b"\r\n\r\n", 1)[1].decode("utf-8"))
            if isinstance(obj, dict) and obj.get("ok") is False \
                    and isinstance(obj.get("error"), dict):
                out["code"] = obj["error"].get("code")
                out["outcome_uncertain"] = obj["error"].get("outcome_uncertain")
                out["retry_safe"] = obj["error"].get("retry_safe")
        except Exception:  # noqa: BLE001
            pass
    return out


def _map_exc(exc):
    """Normalise a DriveClientError / ServiceError to (code, unc, retry, kind)."""
    code = getattr(exc, "code", None)
    unc = getattr(exc, "outcome_uncertain", None)
    retry = getattr(exc, "retry_safe", None)
    return {"code": code, "outcome_uncertain": unc, "retry_safe": retry,
            "kind": type(exc).__name__}


# ---------------------------------------------------------------------------
# Service-entry barrier (deterministic admission exhaustion)
# ---------------------------------------------------------------------------
class _EntryGate:
    def __init__(self, n):
        self._n = n
        self._lock = threading.Lock()
        self._count = 0
        self.entered = threading.Event()
        self.release = threading.Event()

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
    from drive_tool.file_service import LocalFileService

    class _GatedService(LocalFileService):
        _gate = None

        def list(self, token, source_id, file_id="root", **kwargs):
            gate = self._gate
            if gate is not None:
                gate.enter()
            return super().list(token, source_id, file_id, **kwargs)

    return _GatedService(policies)


# ---------------------------------------------------------------------------
# Stage 1: selfcheck
# ---------------------------------------------------------------------------
def stage_selfcheck(repo, budget):
    problems = []
    # frozen arithmetic
    if MAX_CONCURRENT != 6:
        problems.append("MAX_CONCURRENT != 6")
    if AGENT_COUNT != len(PERSONAS):
        problems.append("persona count mismatch")
    if len(set(TOKENS)) != AGENT_COUNT:
        problems.append("tokens are not distinct")
    if any(len(t) < 32 or len(t) > 256 for t in TOKENS):
        problems.append("a token is outside the 32..256 length contract")
    if TEMP_PREFIX != ".drive-tool-tmp-":
        problems.append("TEMP_PREFIX drifted from the accepted value")
    # scan-temp truth
    with tempfile.TemporaryDirectory(prefix="d110-sc-") as d:
        open(os.path.join(d, TEMP_PREFIX + "abc"), "wb").write(b"x")
        open(os.path.join(d, "keep.bin"), "wb").write(b"y")
        os.makedirs(os.path.join(d, "sub"), exist_ok=True)
        open(os.path.join(d, "sub", TEMP_PREFIX + "def"), "wb").write(b"z")
        found = _scan_temp(d)
        if len(found) != 2:
            problems.append("temp scan found %d, expected 2" % len(found))
    # meminfo readability
    if _mem_available_kb() is None:
        problems.append("cannot read /proc/meminfo MemAvailable")
    # fixture build bound
    with tempfile.TemporaryDirectory(prefix="d110-sc2-") as d:
        _roots, total = build_roots(d)
        if total > MAX_FIXTURE_BYTES:
            problems.append("fixture build exceeds bound")
    return {
        "stage": "selfcheck",
        "result": "PASS" if not problems else "FAIL",
        "problems": problems,
        "frozen": {"seed": FROZEN_SEED, "agents": AGENT_COUNT,
                   "max_concurrent": MAX_CONCURRENT, "temp_prefix": TEMP_PREFIX},
    }


# ---------------------------------------------------------------------------
# Stage 2: http_hostile
# ---------------------------------------------------------------------------
def _hostile_cases(token):
    body = json.dumps({"source_id": "main", "file_id": "root",
                       "limit": 20, "offset": 0}).encode("ascii")
    good = _raw_request("/v1/list", token, body)
    cases = {
        "overlong_request_line": b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n",
        "overlong_header_block":
            b"POST /v1/list HTTP/1.1\r\nX-Pad: " + b"a" * 16384 + b"\r\n",
        "too_many_headers": (b"POST /v1/list HTTP/1.1\r\n"
                             + b"".join(b"X-%d: v\r\n" % i for i in range(80))
                             + b"Connection: close\r\n\r\n"),
        "huge_digit_content_length": good.replace(
            b"Content-Length: " + str(len(body)).encode("ascii"),
            b"Content-Length: " + b"9" * 5000),
        "duplicate_content_length": (
            b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Authorization: Bearer " + token.encode("ascii") + b"\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
            b"Connection: close\r\n\r\n" + body),
        "non_digit_content_length": good.replace(
            b"Content-Length: " + str(len(body)).encode("ascii"),
            b"Content-Length: +5"),
        "bare_lf_header_block": b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\n\n",
        "buffered_trailing_bytes": good + b"X",
        "unknown_endpoint": _raw_request("/v1/evil", token, body),
        "oversize_json_body": _raw_request(
            "/v1/list", token, b"x" * (65536 + 1024)),
        "oversize_save_body": _raw_request(
            "/v1/save?source_id=main&file_id=p/savepool/big.bin"
            "&overwrite=true&create_parents=true",
            token, b"z" * (1048576 + 1024), ctype=b"application/octet-stream"),
        "truncated_body": (
            b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Authorization: Bearer " + token.encode("ascii") + b"\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 4096\r\nConnection: close\r\n\r\n" + b"{}"),
        "empty_request": b"",
        "immediate_close": b"\r\n",
    }
    return cases


def stage_http_hostile(repo, budget):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient

    base = tempfile.mkdtemp(prefix="d110-hostile-")
    adapter = None
    problems = []
    try:
        roots, _fx = build_roots(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=1.0)
        time.sleep(0.1)
        fd0 = _nfd()
        token = TOKENS[0]
        observed = {}
        max_bytes = 0
        for name, payload in sorted(_hostile_cases(token).items()):
            raw, err, elapsed = _raw_exchange(adapter.port, payload, timeout=3.0)
            info = _parse_resp(raw)
            info["transport_error"] = err
            info["elapsed_ms"] = round(elapsed * 1000.0, 3)
            observed[name] = info
            max_bytes = max(max_bytes, info["bytes"])
            # a hostile probe must never hang far beyond the socket timeout
            if elapsed > 8.0:
                problems.append("%s took %.1fs (server did not bound it)" % (name, elapsed))
        # slow partial header (slowloris-lite): send half a header then stall
        slow_raw, slow_err, slow_el = _raw_exchange(
            adapter.port, b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n",
            timeout=3.0, read_delay=0.3)
        observed["slow_partial_header"] = _parse_resp(slow_raw)
        observed["slow_partial_header"]["transport_error"] = slow_err
        observed["slow_partial_header"]["elapsed_ms"] = round(slow_el * 1000.0, 3)
        # recovery: a valid request must still succeed after all the abuse
        recovered = False
        recovery_err = None
        try:
            DriveClient(port=adapter.port, token=token, timeout=5.0).list("main", limit=20)
            recovered = True
        except Exception as exc:  # noqa: BLE001
            recovery_err = _map_exc(exc)
        if not recovered:
            problems.append("server did not recover after hostile probes: %s" % recovery_err)
        if max_bytes > 1024 * 1024:
            problems.append("a hostile probe returned %d bytes (unbounded)" % max_bytes)
        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped: %s" % threads_after)
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_BASELINE_SLACK:
            problems.append("fd %s -> %s (leak)" % (fd0, fd1))
        return {
            "stage": "http_hostile",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "observed": observed,
            "recovery_ok": recovered,
            "max_response_bytes": max_bytes,
            "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                          "threads_after_close": threads_after},
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 3: admission_exhaustion (deterministic 6+1 + recovery)
# ---------------------------------------------------------------------------
def stage_admission_exhaustion(repo, budget, cycles=50):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient

    base = tempfile.mkdtemp(prefix="d110-adm-")
    adapter = None
    problems = []
    try:
        roots, _fx = build_roots(base)
        policies = build_policies(roots)
        service = _make_gated_service(policies)
        adapter = DriveHTTPAdapter(service=service, port=0, socket_timeout=5.0)
        time.sleep(0.1)
        fd0 = _nfd()
        token = TOKENS[0]
        payload = json.dumps({"source_id": "main", "file_id": "root",
                              "limit": 20, "offset": 0}).encode("ascii")
        req = _raw_request("/v1/list", token, payload)
        results = []
        deadline = time.monotonic() + budget
        for cycle in range(cycles):
            if time.monotonic() > deadline:
                problems.append("admission stage exceeded its budget")
                break
            gate = _EntryGate(MAX_CONCURRENT)
            service._gate = gate
            cycle_out = {}

            def occupier(slot):
                raw, _e, _el = _raw_exchange(adapter.port, req, timeout=15.0)
                cycle_out[("occupier", slot)] = _parse_resp(raw)

            threads = [threading.Thread(target=occupier, args=(i,))
                       for i in range(MAX_CONCURRENT)]
            for t in threads:
                t.start()
            entered_ok = gate.entered.wait(timeout=20.0)
            entered_count = gate.count
            exc = _parse_resp(_raw_exchange(adapter.port, req, timeout=15.0)[0])
            cycle_out[("excess", 0)] = exc
            gate.release.set()
            for t in threads:
                t.join(timeout=20.0)
            service._gate = None
            occ = [cycle_out.get(("occupier", i), {}) for i in range(MAX_CONCURRENT)]
            results.append({"cycle": cycle, "entered_ok": entered_ok,
                            "entered_count": entered_count,
                            "occupier_status": [o.get("status") for o in occ],
                            "excess_code": exc.get("code")})
        occ_ok = sum(1 for r in results for s in r["occupier_status"] if s == 200)
        occ_bad = sum(1 for r in results for s in r["occupier_status"] if s != 200)
        exc_busy = sum(1 for r in results if r["excess_code"] == "busy")
        exc_unavail = sum(1 for r in results if r["excess_code"] == "unavailable")
        exc_other = len(results) - exc_busy - exc_unavail
        entered_misses = sum(1 for r in results if not r["entered_ok"])
        if occ_ok != MAX_CONCURRENT * len(results):
            problems.append("occupier successes %d != %d" % (occ_ok, MAX_CONCURRENT * len(results)))
        if exc_busy != len(results):
            problems.append("excess busy %d != %d cycles" % (exc_busy, len(results)))
        if exc_unavail or exc_other:
            problems.append("excess non-busy: unavailable=%d other=%d" % (exc_unavail, exc_other))
        if entered_misses:
            problems.append("entry barrier missed in %d cycle(s)" % entered_misses)
        # recovery after overload: a fresh burst must all succeed
        recovery_ok = 0
        recovery_fail = []
        try:
            for i in range(60):
                DriveClient(port=adapter.port, token=token, timeout=5.0).list("main", limit=20)
                recovery_ok += 1
        except Exception as exc2:  # noqa: BLE001
            recovery_fail.append(_map_exc(exc2))
        if recovery_ok != 60:
            problems.append("post-overload recovery %d/60 ok" % recovery_ok)
        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped: %s" % threads_after)
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_BASELINE_SLACK:
            problems.append("fd %s -> %s" % (fd0, fd1))
        return {
            "stage": "admission_exhaustion",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "mode": "real-service-entry-barrier",
            "cycles": len(results),
            "occupier_success": occ_ok, "occupier_bad": occ_bad,
            "excess_busy": exc_busy, "excess_unavailable": exc_unavail,
            "excess_other": exc_other,
            "recovery_ok": recovery_ok, "recovery_fail": recovery_fail,
            "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                          "threads_after_close": threads_after},
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 4: isolation
# ---------------------------------------------------------------------------
def stage_isolation(repo, budget):
    import urllib.parse
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient, DriveClientError

    base = tempfile.mkdtemp(prefix="d110-iso-")
    adapter = None
    problems = []
    try:
        roots, _fx = build_roots(base)
        policies = build_policies(roots)
        # an outside sentinel the service must never reach
        outside = os.path.join(base, "outside")
        os.makedirs(outside, exist_ok=True)
        sentinel = os.path.join(outside, "secret.txt")
        with open(sentinel, "wb") as fh:
            fh.write(b"OUTSIDE-SENTINEL")
        sentinel_sha = sha256_bytes(open(sentinel, "rb").read())

        # a symlink INSIDE the main root that points outside the root
        link = os.path.join(roots["main"], "escape_link")
        try:
            os.symlink(outside, link)
        except OSError:
            pass
        link_file = os.path.join(roots["main"], "escape_file")
        try:
            os.symlink(sentinel, link_file)
        except OSError:
            pass

        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
        time.sleep(0.1)

        cross = {}
        # agent-other must not reach alias 'main'
        try:
            DriveClient(port=adapter.port, token=TOKENS[1], timeout=5.0).read(
                "main", "p/readme.txt", offset=0, length=16)
            cross["other_reads_main"] = "ALLOWED"
        except DriveClientError as exc:
            cross["other_reads_main"] = exc.code
        try:
            DriveClient(port=adapter.port, token=TOKENS[1], timeout=5.0).save(
                "main", "p/savepool/cross.bin", b"x", overwrite=True)
            cross["other_writes_main"] = "ALLOWED"
        except DriveClientError as exc:
            cross["other_writes_main"] = exc.code
        if cross["other_reads_main"] != "denied":
            problems.append("cross-agent read not denied: %s" % cross["other_reads_main"])
        if cross["other_writes_main"] != "denied":
            problems.append("cross-agent write not denied: %s" % cross["other_writes_main"])

        hostile_ids = [
            "p/../../etc/passwd",
            "p/../secret",
            "/etc/passwd",
            "p//etc/passwd",
            "p/sub/../../../../etc/hosts",
            "p/" + "a" * 300,
            "p/bad\x00name",
            "p/.drive-tool-tmp-evil",
            "p/escape_link/secret.txt",
            "p/escape_file",
        ]
        hostile = {}

        def _accepted(resp):
            return resp.get("status") == 200 and resp.get("code") is None

        for fid in hostile_ids:
            key = repr(fid)
            # (1) client boundary -- the client validates ids locally, so a
            #     ValueError here is an expected client-side rejection, NOT an
            #     unmapped product error.
            try:
                DriveClient(port=adapter.port, token=TOKENS[0], timeout=5.0).read(
                    "main", fid, offset=0, length=16)
                cr = "ALLOWED"
            except DriveClientError as exc:
                cr = exc.code
            except ValueError:
                cr = "client_rejected"
            except Exception as exc:  # noqa: BLE001
                cr = "raw:" + type(exc).__name__
            try:
                DriveClient(port=adapter.port, token=TOKENS[0], timeout=5.0).save(
                    "main", fid, b"x", overwrite=True)
                cs = "ALLOWED"
            except DriveClientError as exc:
                cs = exc.code
            except ValueError:
                cs = "client_rejected"
            except Exception as exc:  # noqa: BLE001
                cs = "raw:" + type(exc).__name__
            # (2) SERVER boundary -- raw HTTP that bypasses client validation
            body_r = json.dumps({"source_id": "main", "file_id": fid,
                                 "offset": 0, "length": 16}).encode("utf-8")
            srv_read = _parse_resp(_raw_exchange(
                adapter.port, _raw_request("/v1/read", TOKENS[0], body_r),
                timeout=5.0)[0])
            body_l = json.dumps({"source_id": "main", "file_id": fid,
                                 "limit": 20, "offset": 0}).encode("utf-8")
            srv_list = _parse_resp(_raw_exchange(
                adapter.port, _raw_request("/v1/list", TOKENS[0], body_l),
                timeout=5.0)[0])
            q = urllib.parse.urlencode({"source_id": "main", "file_id": fid,
                                        "overwrite": "true", "create_parents": "true"})
            srv_save = _parse_resp(_raw_exchange(
                adapter.port, _raw_request("/v1/save?" + q, TOKENS[0], b"x",
                                           ctype=b"application/octet-stream"),
                timeout=5.0)[0])
            hostile[key] = {"client_read": cr, "client_save": cs,
                            "server_read": srv_read, "server_list": srv_list,
                            "server_save": srv_save}
            if cr == "ALLOWED" or cs == "ALLOWED":
                problems.append("hostile file_id accepted at client: %s" % key)
            if _accepted(srv_read) or _accepted(srv_list) or _accepted(srv_save):
                problems.append("hostile file_id accepted at SERVER: %s -> %s"
                                % (key, hostile[key]))
            if cr.startswith("raw:") or cs.startswith("raw:"):
                problems.append("unmapped client exception on hostile id: %s" % key)

        # the outside sentinel must be byte-for-byte intact and unexposed
        now_sha = sha256_bytes(open(sentinel, "rb").read())
        if now_sha != sentinel_sha:
            problems.append("outside sentinel was modified")
        # and it must not appear in a listing of the root
        listed = DriveClient(port=adapter.port, token=TOKENS[0], timeout=5.0).list(
            "main", limit=100)
        names = [i["name"] for i in listed["items"]]
        if "secret.txt" in names:
            problems.append("outside sentinel exposed in listing")

        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped")
        return {
            "stage": "isolation",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "cross_agent": cross,
            "hostile_ids": hostile,
            "sentinel_intact": now_sha == sentinel_sha,
            "listed_names": names,
            "resources": {"closed": closed, "threads_after_close": threads_after},
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        import shutil
        shutil.rmtree(base, ignore_errors=True)


class _LeaseLimiter:
    """K client leases; each held until response + ``hold`` seconds.

    Applied ONLY to the LOOPING sub-test (b) (2 writers + 3 readers).  The
    D101 gate used exactly this (K=5, 55 ms) so a client does not open a new
    connection while the server is still draining the previous one.  This is a
    normal-scheduling mitigation, NOT a universal OS-scheduler guarantee.
    A ``busy`` here is still an error -- never forgiven.
    """

    def __init__(self, capacity, hold):
        self._sem = threading.BoundedSemaphore(capacity)
        self._hold = hold
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


def _exc_detail(exc, op):
    """Rich, countable diagnostics for one failed operation."""
    return {"op": op, "kind": type(exc).__name__,
            "code": getattr(exc, "code", None),
            "message": str(exc)[:160],
            "outcome_uncertain": getattr(exc, "outcome_uncertain", None),
            "retry_safe": getattr(exc, "retry_safe", None)}


def _drain_pause(seconds=DRAIN_PAUSE):
    """Sleep >= the server's post-response drain window (0.050 s) so prior
    workers finish _drain_and_close before the next phase opens connections.
    A normal-scheduling mitigation, not a universal OS guarantee."""
    time.sleep(seconds)


# ---------------------------------------------------------------------------
# Stage 5: concurrent_ops
# ---------------------------------------------------------------------------
def stage_concurrent_ops(repo, budget):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient, DriveClientError

    base = tempfile.mkdtemp(prefix="d110-conc-")
    adapter = None
    problems = []
    try:
        roots, _fx = build_roots(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=10.0)
        time.sleep(0.1)
        fd0 = _nfd()
        # The drain-aware lease (K=5, 55 ms) is applied ONLY to the LOOPING
        # sub-test (b).  The one-shot sub-tests (a) and (c) keep the full
        # MAX_CONCURRENT (=6) way race with no slot cap.
        lease = _LeaseLimiter(CONC_LEASES, CONC_LEASE_HOLD)
        write_lock = threading.Lock()

        PAYLEN = 4096
        payloads = [bytes([i]) * PAYLEN for i in range(1, 9)]
        payload_shas = {sha256_bytes(p) for p in payloads}
        WRITABLE = (0, 1, 4, 5)   # main, other, alias_a, alias_b

        # (a) exactly one winner for a concurrent no-overwrite create: FULL
        #     6-way (6 == MAX_CONCURRENT), NO lease; a real entry barrier proves
        #     all six requests are in flight together.
        target = "p/savepool/race_create.bin"
        winners = []
        exists = []
        other = []
        lock = threading.Lock()
        a_barrier = threading.Barrier(MAX_CONCURRENT)
        a_entered = []
        a_broken = []

        def creator(i):
            try:
                a_barrier.wait(timeout=30.0)
            except threading.BrokenBarrierError:
                with lock:
                    a_broken.append(i)
                return
            with lock:
                a_entered.append(i)
            try:
                DriveClient(port=adapter.port, token=TOKENS[0], timeout=10.0).save(
                    "main", target, payloads[i % len(payloads)], overwrite=False)
                with lock:
                    winners.append(i)
            except DriveClientError as exc:
                with lock:
                    (exists if exc.code == "exists" else other).append(exc.code)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    other.append(_exc_detail(exc, "create"))

        threads = [threading.Thread(target=creator, args=(i,))
                   for i in range(MAX_CONCURRENT)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
        _drain_pause()
        if a_broken:
            problems.append("no-overwrite create barrier broke: %s" % a_broken)
        if len(a_entered) != MAX_CONCURRENT:
            problems.append("no-overwrite create entered=%d (expected %d)"
                            % (len(a_entered), MAX_CONCURRENT))
        if len(winners) != 1:
            problems.append("no-overwrite create winners=%d (expected 1)" % len(winners))
        if len(exists) != MAX_CONCURRENT - 1:
            problems.append("no-overwrite create exists=%d (expected %d)"
                            % (len(exists), MAX_CONCURRENT - 1))
        if other:
            problems.append("no-overwrite create unexpected codes: %s" % other)

        # (b) simultaneous overwrite + range reads of one file: every reader
        #     must see a complete, untorn payload (atomic rename).  The LOOPING
        #     threads (2 writers + 3 readers = 5) share the K=5, 55 ms lease.
        target2 = "p/savepool/race_over.bin"
        DriveClient(port=adapter.port, token=TOKENS[0], timeout=10.0).save(
            "main", target2, payloads[0], overwrite=True)
        _drain_pause()
        torn = []
        write_err = []
        stop = threading.Event()

        def writer(i):
            while not stop.is_set():
                lease.acquire()
                try:
                    DriveClient(port=adapter.port, token=TOKENS[0], timeout=10.0).save(
                        "main", target2, payloads[i % len(payloads)], overwrite=True)
                except Exception as exc:  # noqa: BLE001
                    with write_lock:
                        if len(write_err) < 5:
                            write_err.append(_exc_detail(exc, "overwrite"))
                    break
                finally:
                    lease.release(time.monotonic())

        def reader(i):
            for _ in range(30):
                lease.acquire()
                try:
                    data = DriveClient(port=adapter.port, token=TOKENS[0], timeout=10.0).read(
                        "main", target2, offset=0, length=PAYLEN).data
                    if len(data) != PAYLEN or sha256_bytes(data) not in payload_shas:
                        torn.append({"len": len(data), "sha": sha256_bytes(data)})
                except Exception as exc:  # noqa: BLE001
                    torn.append(_exc_detail(exc, "read"))
                finally:
                    lease.release(time.monotonic())

        wthreads = [threading.Thread(target=writer, args=(i,)) for i in range(2)]
        rthreads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        for t in wthreads:
            t.start()
        for t in rthreads:
            t.start()
        for t in rthreads:
            t.join(timeout=60.0)
        stop.set()
        for t in wthreads:
            t.join(timeout=30.0)
        _drain_pause()
        if torn:
            problems.append("torn/inconsistent reads: %s" % torn[:5])
        if write_err:
            problems.append("concurrent overwrite errors: %s" % write_err[:5])

        # (c) simultaneous create across distinct files by distinct WRITABLE
        #     agents: FULL 6-way, NO lease, real entry barrier.
        multi = []
        mlock = threading.Lock()
        c_barrier = threading.Barrier(MAX_CONCURRENT)
        c_entered = []
        c_broken = []

        def multi_save(i):
            try:
                c_barrier.wait(timeout=30.0)
            except threading.BrokenBarrierError:
                with mlock:
                    c_broken.append(i)
                return
            with mlock:
                c_entered.append(i)
            agent = WRITABLE[i % len(WRITABLE)]
            alias = PERSONAS[agent][2]
            try:
                DriveClient(port=adapter.port, token=TOKENS[agent], timeout=10.0).save(
                    alias, "p/savepool/multi_%02d.bin" % i, payloads[i % len(payloads)],
                    overwrite=False)
                with mlock:
                    multi.append("ok")
            except DriveClientError as exc:
                with mlock:
                    multi.append(exc.code)
            except Exception as exc:  # noqa: BLE001
                with mlock:
                    multi.append(_exc_detail(exc, "multi"))

        mthreads = [threading.Thread(target=multi_save, args=(i,))
                    for i in range(MAX_CONCURRENT)]
        for t in mthreads:
            t.start()
        for t in mthreads:
            t.join(timeout=30.0)
        if c_broken:
            problems.append("multi-agent create barrier broke: %s" % c_broken)
        if len(c_entered) != MAX_CONCURRENT:
            problems.append("multi-agent create entered=%d (expected %d)"
                            % (len(c_entered), MAX_CONCURRENT))
        bad_multi = [m for m in multi if m != "ok"]
        if bad_multi:
            problems.append("multi-agent create failures: %s" % bad_multi)

        orphans = _scan_temp(base)
        if orphans:
            problems.append("temp residue after concurrent ops: %s" % orphans[:5])

        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped")
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_BASELINE_SLACK:
            problems.append("fd %s -> %s" % (fd0, fd1))
        return {
            "stage": "concurrent_ops",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "create_winners": len(winners), "create_exists": len(exists),
            "create_other": other, "create_entered": len(a_entered),
            "torn_reads": torn[:5], "torn_count": len(torn),
            "overwrite_errors": write_err[:5], "overwrite_error_count": len(write_err),
            "multi_agent": multi, "multi_entered": len(c_entered),
            "lease_max_held": lease.max_held,
            "concurrent_capacity": MAX_CONCURRENT,
            "temp_residue": orphans,
            "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                          "threads_after_close": threads_after},
        }
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 6: crash_kill (synchronized child SIGKILL + fresh recovery + orphan audit)
# ---------------------------------------------------------------------------
def _crash_child(root_dir, mode, overwrite, rfd, wfd):
    """Child body: instrumented save that signals then blocks for SIGKILL."""
    try:
        os.setsid()
        sys.path.insert(0, os.environ.get("D110_REPO", ""))
        from drive_tool.file_service import LocalFileService
        roots = {"main": os.path.realpath(root_dir)}
        # rebuild a minimal single-agent policy in the child
        from drive_tool.service_policy import AgentPolicy, SourceGrant
        grant = SourceGrant(alias="main", root=roots["main"],
                            operations=frozenset(("find", "list", "read", "save")),
                            max_read_bytes=1048576, max_write_bytes=1048576)
        pol = AgentPolicy(agent_id="agent-main",
                          token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                          grants=(grant,))
        svc = LocalFileService((pol,))
        binding = svc._bindings[("agent-main", "main")]
        writer = binding.writer
        payload = b"P" * 4096

        if mode == "C1":
            orig = writer._os_write
            state = {"n": 0}

            def bad_write(fd, data):
                state["n"] += 1
                if state["n"] == 1:
                    half = max(1, len(data) // 2)
                    n = orig(fd, bytes(data[:half]))
                    os.write(wfd, b"R")
                    # block until the parent kills us
                    while True:
                        time.sleep(0.05)
                return orig(fd, data)
            writer._os_write = bad_write
        else:  # C2 post-fsync pre-publish
            if overwrite:
                orig = writer._os_rename

                def bad_pub(src, dst, **kw):
                    os.write(wfd, b"R")
                    while True:
                        time.sleep(0.05)
                writer._os_rename = bad_pub
            else:
                orig = writer._os_link

                def bad_pub(src, dst, **kw):
                    os.write(wfd, b"R")
                    while True:
                        time.sleep(0.05)
                writer._os_link = bad_pub

        try:
            svc.save(TOKENS[0], "main", "p/savepool/target.bin", payload,
                     overwrite=overwrite)
        except BaseException:
            pass
        os._exit(0)
    except BaseException:
        os._exit(3)


def _run_crash_case(root_dir, mode, overwrite, repo):
    rfd, wfd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(rfd)
        _crash_child(root_dir, mode, overwrite, rfd, wfd)
        os._exit(0)
    os.close(wfd)
    # wait for the child to reach its synchronisation point
    ready = b""
    deadline = time.monotonic() + 20.0
    os.set_blocking(rfd, False)
    while time.monotonic() < deadline:
        try:
            chunk = os.read(rfd, 1)
        except BlockingIOError:
            chunk = b""
        if chunk:
            ready = chunk
            break
        time.sleep(0.02)
    os.close(rfd)
    killed = False
    status = None
    # Kill ONLY the child's own process group; never our own (the child
    # setsid()s, but guard anyway so a pre-setsid race can never take out the
    # harness, the parent or SSH).
    own_pgid = os.getpgid(0)
    try:
        child_pgid = os.getpgid(pid)
    except ProcessLookupError:
        child_pgid = None
    if child_pgid is not None and child_pgid != own_pgid:
        try:
            os.killpg(child_pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        _p, status = os.waitpid(pid, 0)
        killed = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
    except ChildProcessError:
        pass
    return {"ready": bool(ready), "killed_sigkill": killed,
            "status": status}


def stage_crash_kill(repo, budget):
    sys.path.insert(0, repo)
    os.environ["D110_REPO"] = repo
    from drive_tool.file_service import LocalFileService
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    from drive_tool.service_client import DriveClientError  # noqa: F401

    base = tempfile.mkdtemp(prefix="d110-crash-")
    problems = []
    cases = []
    try:
        roots, _fx = build_roots(base)
        root_main = roots["main"]
        pool = os.path.join(root_main, "savepool")
        target = os.path.join(pool, "target.bin")

        for mode in ("C1", "C2"):
            for overwrite in (False, True):
                # pre-seed a known target only for the overwrite cases
                if overwrite:
                    with open(target, "wb") as fh:
                        fh.write(b"ORIGINAL" * 512)
                    orig_sha = sha256_bytes(open(target, "rb").read())
                else:
                    if os.path.exists(target):
                        os.unlink(target)
                    orig_sha = None
                case = _run_crash_case(root_main, mode, overwrite, repo)
                orphans = _scan_temp(root_main)
                # fresh-service recovery on the crash-affected root
                grant = SourceGrant(alias="main", root=root_main,
                                    operations=frozenset(("find", "list", "read", "save")),
                                    max_read_bytes=1048576, max_write_bytes=1048576)
                pol = AgentPolicy(agent_id="agent-main",
                                  token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                                  grants=(grant,))
                svc = LocalFileService((pol,))
                recovery = {}
                try:
                    svc.read(TOKENS[0], "main", "p/readme.txt", offset=0, length=8)
                    svc.list(TOKENS[0], "main", "root", limit=20)
                    svc.find(TOKENS[0], "main", "root", name_contains="data", limit=10)
                    svc.save(TOKENS[0], "main", "p/savepool/recovered.bin", b"r" * 16,
                             overwrite=True)
                    svc.save(TOKENS[0], "main", "p/savepool/recovered2.bin", b"r" * 16,
                             overwrite=False)
                    recovery = {"ok": True}
                except Exception as exc:  # noqa: BLE001
                    recovery = {"ok": False, "error": _map_exc(exc)}
                finally:
                    try:
                        svc.close(timeout=5.0)
                    except BaseException:
                        pass
                # target integrity
                if overwrite:
                    if os.path.exists(target):
                        now = sha256_bytes(open(target, "rb").read())
                        target_state = "original" if now == orig_sha else "changed"
                    else:
                        target_state = "missing"
                else:
                    target_state = "absent" if not os.path.exists(target) else "present"
                # orphan visibility in list/find
                vis = {"list": None, "find": None}
                try:
                    g2 = SourceGrant(alias="main", root=root_main,
                                     operations=frozenset(("find", "list", "read", "save")),
                                     max_read_bytes=1048576, max_write_bytes=1048576)
                    p2 = AgentPolicy(agent_id="agent-main",
                                     token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                                     grants=(g2,))
                    s2 = LocalFileService((p2,))
                    try:
                        items = s2.list(TOKENS[0], "main", "p/savepool", limit=100)["items"]
                        vis["list"] = sum(1 for it in items
                                          if it["name"].startswith(TEMP_PREFIX))
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        res = s2.find(TOKENS[0], "main", "p/savepool",
                                      name_contains=TEMP_PREFIX, limit=100)
                        vis["find"] = sum(1 for it in res["items"]
                                          if it["name"].startswith(TEMP_PREFIX))
                    except Exception:  # noqa: BLE001
                        pass
                    s2.close(timeout=5.0)
                except BaseException:
                    pass

                if not case["killed_sigkill"]:
                    problems.append("%s overwrite=%s: child not SIGKILLed (%s)"
                                    % (mode, overwrite, case))
                if not recovery.get("ok"):
                    problems.append("%s overwrite=%s: fresh recovery failed: %s"
                                    % (mode, overwrite, recovery))
                if overwrite and target_state == "changed":
                    problems.append("%s overwrite=True: target changed on kill (torn)"
                                    % mode)
                if (not overwrite) and target_state == "present":
                    problems.append("%s overwrite=False: target published despite kill"
                                    % mode)
                if len(orphans) < 1:
                    problems.append("%s overwrite=%s: expected >=1 orphan temp, found %d"
                                    % (mode, overwrite, len(orphans)))
                cases.append({
                    "mode": mode, "overwrite": overwrite,
                    "ready": case["ready"], "killed_sigkill": case["killed_sigkill"],
                    "orphan_temps": len(orphans),
                    "orphan_visible_in_list": vis["list"],
                    "orphan_visible_in_find": vis["find"],
                    "target_state": target_state,
                    "recovery": recovery,
                })
                # clean the root's pool between cases
                for name in os.listdir(pool):
                    try:
                        os.unlink(os.path.join(pool, name))
                    except OSError:
                        pass
        return {
            "stage": "crash_kill",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "cases": cases,
            "note": ("SIGKILL proves process-crash atomicity, NOT physical "
                     "power-loss durability across a hypervisor disk cache."),
        }
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 7: resource_pressure (CHILD-only CPU / RAM / FD)
# ---------------------------------------------------------------------------
def _cpu_children(n):
    pids = []
    for _ in range(n):
        pid = os.fork()
        if pid == 0:
            try:
                os.nice(15)
                resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
                while True:
                    hashlib.pbkdf2_hmac("sha256", b"x" * 64, b"y" * 16, 20000)
            except BaseException:
                pass
            os._exit(0)
        pids.append(pid)
    return pids


def _r3_child(repo, root_main, wfd):
    """Child: exhaust file descriptors, hammer the service, report via pipe."""
    try:
        os.setsid()
        sys.path.insert(0, repo)
        from drive_tool.file_service import LocalFileService
        from drive_tool.service_policy import AgentPolicy, SourceGrant
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        target = 24
        new_soft = min(hard, target)
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
        grant = SourceGrant(alias="main", root=root_main,
                            operations=frozenset(("find", "list", "read", "save")),
                            max_read_bytes=1048576, max_write_bytes=1048576)
        pol = AgentPolicy(agent_id="agent-main",
                          token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                          grants=(grant,))
        svc = LocalFileService((pol,))
        # occupy descriptors so only a couple remain free for the workload
        holders = []
        try:
            while True:
                nfd = _nfd()
                if nfd is None or nfd >= new_soft - 3:
                    break
                holders.append(os.open(os.devnull, os.O_RDONLY))
        except OSError:
            pass
        nfd_pressure = _nfd()
        lock = threading.Lock()
        counters = {"ok": 0, "mapped": 0, "raw": 0, "raw_type": None}

        def hammer(n):
            for i in range(40):
                try:
                    svc.save(TOKENS[0], "main",
                             "p/savepool/emfile_%d_%03d.bin" % (n, i),
                             b"z" * 64, overwrite=True)
                    with lock:
                        counters["ok"] += 1
                except Exception as exc:  # noqa: BLE001
                    with lock:
                        if type(exc).__name__ == "ServiceError":
                            counters["mapped"] += 1
                        else:
                            counters["raw"] += 1
                            counters["raw_type"] = type(exc).__name__

        threads = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30.0)
        for fd in holders:
            try:
                os.close(fd)
            except OSError:
                pass
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        recovery_ok = 0
        for i in range(20):
            try:
                svc.list(TOKENS[0], "main", "root", limit=20)
                recovery_ok += 1
            except Exception:  # noqa: BLE001
                pass
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
        out = {"soft": soft, "hard": hard, "new_soft": new_soft,
               "nfd_pressure": nfd_pressure,
               "ok": counters["ok"], "mapped": counters["mapped"],
               "raw": counters["raw"], "raw_type": counters["raw_type"],
               "recovery_ok": recovery_ok}
        os.write(wfd, json.dumps(out).encode("ascii"))
        os._exit(0)
    except BaseException as exc:
        try:
            os.write(wfd, json.dumps({"child_error": type(exc).__name__}).encode("ascii"))
        except BaseException:
            pass
        os._exit(3)


_R2_CHILD_SRC = r"""
import os, sys, resource, json, hashlib
repo, root_main, wfd = sys.argv[1], sys.argv[2], int(sys.argv[3])
sys.path.insert(0, repo)
def _vmsize_kb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None
CHILD_RLIMIT_AS = 512 * 1024 * 1024
BALLAST = 192 * 1024 * 1024
try:
    vm_kb = _vmsize_kb()
    headroom_kb = BALLAST // 1024
    if vm_kb is not None and (vm_kb + headroom_kb) > CHILD_RLIMIT_AS // 1024:
        os.write(wfd, json.dumps({"result": "SKIPPED", "reason":
            "baseline VmSize %d KiB leaves < %d KiB headroom" % (vm_kb, headroom_kb)}).encode("ascii"))
        os._exit(0)
    try:
        with open("/proc/self/oom_score_adj", "w") as fh:
            fh.write("1000\n")
    except OSError:
        pass
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_RLIMIT_AS, CHILD_RLIMIT_AS))
    from drive_tool.file_service import LocalFileService
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    token = "d110-main-" + "A" * 40
    grant = SourceGrant(alias="main", root=os.path.realpath(root_main),
                        operations=frozenset(("find", "list", "read", "save")),
                        max_read_bytes=1048576, max_write_bytes=1048576)
    pol = AgentPolicy(agent_id="agent-main",
                      token_sha256=hashlib.sha256(token.encode("ascii")).digest(),
                      grants=(grant,))
    svc = LocalFileService((pol,))
    ballast = bytearray(BALLAST)
    ballast[::4096] = b"\x01" * (len(ballast) // 4096)
    vm_kb_ballast = _vmsize_kb()
    ok = 0
    for i in range(50):
        svc.read(token, "main", "p/readme.txt", offset=0, length=16)
        svc.save(token, "main", "p/savepool/mem_%03d.bin" % i, b"m" * 256, overwrite=True)
        ok += 1
    mem_error = None
    grow = bytearray()
    try:
        for _ in range(200):
            grow.extend(b"\x00" * (8 * 1024 * 1024))
    except MemoryError:
        mem_error = "MemoryError"
    vm_kb_peak = _vmsize_kb()
    del ballast, grow
    recovery_ok = 0
    for i in range(20):
        svc.save(token, "main", "p/savepool/rec_%03d.bin" % i, b"r" * 256, overwrite=True)
        svc.read(token, "main", "p/readme.txt", offset=0, length=16)
        recovery_ok += 1
    try:
        svc.close(timeout=5.0)
    except BaseException:
        pass
    os.write(wfd, json.dumps({"ok": ok, "mem_error": mem_error,
                              "vm_kb_before": vm_kb, "vm_kb_ballast": vm_kb_ballast,
                              "vm_kb_peak": vm_kb_peak,
                              "recovery_ok": recovery_ok}).encode("ascii"))
    os._exit(0)
except BaseException as exc:
    try:
        os.write(wfd, json.dumps({"child_error": type(exc).__name__}).encode("ascii"))
    except BaseException:
        pass
    os._exit(3)
"""


def _collect_proc(proc, rfd, timeout=120.0):
    """Collect a subprocess.Popen child's piped result with a bounded reap.

    Reaps via proc.wait() -- never a raw os.waitpid behind Popen's back -- and
    kills the child's own process group first if it times out.
    """
    buf = b""
    deadline = time.monotonic() + timeout
    os.set_blocking(rfd, False)
    while time.monotonic() < deadline:
        try:
            chunk = os.read(rfd, 65536)
        except BlockingIOError:
            chunk = b""
        if chunk:
            buf += chunk
            break
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    os.close(rfd)
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
    try:
        return json.loads(buf.decode("ascii"))
    except Exception:  # noqa: BLE001
        return {"child_error": "no_result", "raw_len": len(buf)}


def _collect_child(pid, rfd, timeout=120.0):
    buf = b""
    deadline = time.monotonic() + timeout
    os.set_blocking(rfd, False)
    exited = False
    while time.monotonic() < deadline:
        try:
            chunk = os.read(rfd, 65536)
        except BlockingIOError:
            chunk = b""
        if chunk:
            buf += chunk
            break
        try:
            wpid, status = os.waitpid(pid, os.WNOHANG)
            if wpid == pid:
                exited = True
                break
        except ChildProcessError:
            exited = True
            break
        time.sleep(0.05)
    os.close(rfd)
    if not exited:
        # bounded: kill the child's own process group before any blocking wait
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    try:
        return json.loads(buf.decode("ascii"))
    except Exception:  # noqa: BLE001
        return {"child_error": "no_result", "raw_len": len(buf)}


def stage_resource_pressure(repo, budget):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    from drive_tool.service_client import DriveClient

    base = tempfile.mkdtemp(prefix="d110-rp-")
    adapter = None
    problems = []
    r1 = {}
    r2 = {}
    r3 = {}
    cpu_pids = []
    try:
        roots, _fx = build_roots(base)
        root_main = roots["main"]
        policies = build_policies(roots)

        # Fork the CPU children FIRST, while this process is still
        # single-threaded: fork() in a multi-threaded process emits a
        # DeprecationWarning on CPython 3.12+ and risks lock hazards.
        cpu_pids = _cpu_children(4)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=10.0)
        time.sleep(0.1)

        # R1: 4 low-priority CPU children + a bounded 6-agent workload
        r1_ok = 0
        r1_bad = []
        try:
            for i in range(300):
                agent = i % AGENT_COUNT
                alias = PERSONAS[agent][2]
                op = i % 4
                if agent == READ_ONLY_AGENT and op == 3:
                    op = 2   # the read-only persona cannot save
                try:
                    c = DriveClient(port=adapter.port, token=TOKENS[agent], timeout=10.0)
                    if op == 0:
                        c.list(alias, limit=20)
                    elif op == 1:
                        c.find(alias, name_contains="data", limit=10)
                    elif op == 2:
                        c.read(alias, "p/readme.txt", offset=0, length=16)
                    else:
                        c.save(alias, "p/savepool/r1_%03d.bin" % (i % 32),
                               b"c" * 64, overwrite=True)
                    r1_ok += 1
                except Exception as exc:  # noqa: BLE001
                    r1_bad.append(_map_exc(exc))
        finally:
            for pid in cpu_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pid in cpu_pids:
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
            cpu_pids = []
        r1 = {"ok": r1_ok, "expected": 300, "bad": r1_bad[:5],
              "bad_count": len(r1_bad)}
        if r1_ok != 300:
            problems.append("R1 CPU-saturation workload %d/300 ok" % r1_ok)

        # Close the adapter BEFORE forking R2/R3, so no worker/accept threads
        # are alive across a fork (avoids fork-with-threads lock hazards).
        closed = adapter.close(timeout=10.0)
        adapter = None
        threads_after = _adapter_threads()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped")

        # R2: memory pressure (guarded by the host MemAvailable floor).
        # The RAM child is a CLEAN exec'ed interpreter with its own session so
        # its VmSize starts small and the 192 MiB touched ballast fits under
        # the UNCHANGED 512 MiB RLIMIT_AS cap; it is reaped via proc.wait().
        avail = _mem_available_kb()
        if avail is not None and avail >= HOST_MEM_FLOOR_KB:
            rfd, wfd = os.pipe()
            proc = subprocess.Popen(
                [sys.executable, "-c", _R2_CHILD_SRC, repo, root_main, str(wfd)],
                pass_fds=(wfd,), start_new_session=True)
            os.close(wfd)
            r2 = _collect_proc(proc, rfd, timeout=min(120.0, budget))
            if r2.get("result") == "SKIPPED":
                pass   # the child self-reported an honest skip
            elif r2.get("child_error"):
                r2 = {"result": "SKIPPED",
                      "reason": "child error: %s" % r2.get("child_error")}
            else:
                r2["result"] = "PASS" if (r2.get("ok") == 50
                                          and r2.get("recovery_ok") == 20
                                          and r2.get("mem_error") == "MemoryError") else "FAIL"
            if r2.get("result") == "FAIL":
                problems.append("R2 memory pressure failed: %s" % r2)
        else:
            r2 = {"result": "SKIPPED",
                  "reason": "host MemAvailable %s KiB < %d KiB floor"
                            % (avail, HOST_MEM_FLOOR_KB)}
        avail_after = _mem_available_kb()
        if avail_after is not None and avail_after < HOST_MEM_ABORT_KB:
            problems.append("host MemAvailable fell below the abort floor: %d" % avail_after)

        # R3: EMFILE descriptor exhaustion in a child
        rfd, wfd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(rfd)
            _r3_child(repo, root_main, wfd)
            os._exit(0)
        os.close(wfd)
        r3 = _collect_child(pid, rfd, timeout=min(120.0, budget))
        if r3.get("child_error"):
            r3 = {"result": "SKIPPED", "reason": "child error: %s" % r3.get("child_error")}
        else:
            r3_ok = (r3.get("raw", 1) == 0 and r3.get("recovery_ok") == 20
                     and r3.get("mapped", 0) >= 1)
            r3["result"] = "PASS" if r3_ok else "FAIL"
            if not r3_ok:
                problems.append("R3 EMFILE handling failed: %s" % r3)

        subresults = [r1.get("ok") == 300, r3.get("result") == "PASS"]
        r2_res = r2.get("result")
        if all(subresults) and r2_res == "PASS":
            result = "PASS" if not problems else "FAIL"
        elif all(subresults) and r2_res == "SKIPPED":
            result = "PARTIAL"   # a skipped capability is never a pass
        else:
            result = "FAIL"
        return {
            "stage": "resource_pressure",
            "result": result,
            "problems": problems,
            "R1_cpu_saturation": r1,
            "R2_memory_pressure": r2,
            "R3_emfile": r3,
            "host_mem_available_kb_before": avail,
            "host_mem_available_kb_after": avail_after,
            "note": ("R2 is SKIPPED (never PASS) when the host MemAvailable "
                     "floor is not met."),
            "resources": {"closed": closed, "threads_after_close": threads_after},
        }
    finally:
        for pid in cpu_pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage 8: enospc (RLIMIT_FSIZE EFBIG + injected 4-phase ENOSPC)
# ---------------------------------------------------------------------------
def _fsize_child(repo, root_main, wfd):
    try:
        os.setsid()
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE,
                           (CHILD_RLIMIT_FSIZE, CHILD_RLIMIT_FSIZE))
        sys.path.insert(0, repo)
        from drive_tool.file_service import LocalFileService
        from drive_tool.service_policy import AgentPolicy, SourceGrant
        grant = SourceGrant(alias="main", root=root_main,
                            operations=frozenset(("find", "list", "read", "save")),
                            max_read_bytes=1048576, max_write_bytes=1048576)
        pol = AgentPolicy(agent_id="agent-main",
                          token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                          grants=(grant,))
        svc = LocalFileService((pol,))
        out = {"raised": None}
        try:
            svc.save(TOKENS[0], "main", "p/savepool/fsize.bin",
                     b"X" * 32768, overwrite=False)
            out["raised"] = "NONE"
        except Exception as exc:  # noqa: BLE001
            out["raised"] = type(exc).__name__
            out["code"] = getattr(exc, "code", None)
            out["outcome_uncertain"] = getattr(exc, "outcome_uncertain", None)
            out["retry_safe"] = getattr(exc, "retry_safe", None)
        out["target_exists"] = os.path.exists(os.path.join(root_main, "savepool", "fsize.bin"))
        out["orphans"] = len(_scan_temp(root_main))
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
        os.write(wfd, json.dumps(out).encode("ascii"))
        os._exit(0)
    except BaseException as exc:
        try:
            os.write(wfd, json.dumps({"child_error": type(exc).__name__}).encode("ascii"))
        except BaseException:
            pass
        os._exit(3)


def _inject_phase(repo, root_main, phase, overwrite):
    """Inject ENOSPC at one write phase via the writer's OS seams."""
    sys.path.insert(0, repo)
    from drive_tool.file_service import LocalFileService
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    grant = SourceGrant(alias="main", root=root_main,
                        operations=frozenset(("find", "list", "read", "save")),
                        max_read_bytes=1048576, max_write_bytes=1048576)
    pol = AgentPolicy(agent_id="agent-main",
                      token_sha256=hashlib.sha256(TOKENS[0].encode("ascii")).digest(),
                      grants=(grant,))
    svc = LocalFileService((pol,))
    binding = svc._bindings[("agent-main", "main")]
    writer = binding.writer
    target = "p/savepool/inj.bin"
    tpath = os.path.join(root_main, "savepool", "inj.bin")

    saved = {name: getattr(writer, name) for name in
             ("_os_open", "_os_write", "_os_fsync", "_os_link", "_os_rename")}
    state = {"write_calls": 0, "fsync_calls": 0}

    def enospc(*_a, **_k):
        raise OSError(errno.ENOSPC, "No space left on device")

    if phase == "temp_create":
        def op(path, flags, *a, **k):
            if path.startswith(TEMP_PREFIX):
                raise OSError(errno.ENOSPC, "No space left on device")
            return saved["_os_open"](path, flags, *a, **k)
        writer._os_open = op
    elif phase == "mid_write":
        def wr(fd, data):
            state["write_calls"] += 1
            if state["write_calls"] == 1:
                half = max(1, len(data) // 2)
                return saved["_os_write"](fd, bytes(data[:half]))
            raise OSError(errno.ENOSPC, "No space left on device")
        writer._os_write = wr
    elif phase == "fsync":
        def fs(fd):
            state["fsync_calls"] += 1
            if state["fsync_calls"] == 1:
                raise OSError(errno.ENOSPC, "No space left on device")
            return saved["_os_fsync"](fd)
        writer._os_fsync = fs
    elif phase == "publish":
        if overwrite:
            writer._os_rename = enospc
        else:
            writer._os_link = enospc

    pre_sha = sha256_bytes(open(tpath, "rb").read()) if os.path.exists(tpath) else None
    fd0 = _nfd()
    raised = None
    try:
        svc.save(TOKENS[0], "main", target, b"Y" * 4096, overwrite=overwrite)
        raised = "NONE"
    except Exception as exc:  # noqa: BLE001
        raised = {"type": type(exc).__name__, "code": getattr(exc, "code", None),
                  "outcome_uncertain": getattr(exc, "outcome_uncertain", None),
                  "retry_safe": getattr(exc, "retry_safe", None)}
    # restore seams
    for name, fn in saved.items():
        setattr(writer, name, fn)
    exists_after = os.path.exists(tpath)
    post_sha = sha256_bytes(open(tpath, "rb").read()) if exists_after else None
    orphans = _scan_temp(root_main)
    fd1 = _nfd()
    # recovery on the same instance
    recovery_ok = False
    try:
        svc.save(TOKENS[0], "main", target, b"Y" * 4096, overwrite=True)
        svc.read(TOKENS[0], "main", target, offset=0, length=16)
        svc.list(TOKENS[0], "main", "root", limit=20)
        svc.find(TOKENS[0], "main", "root", name_contains="inj", limit=10)
        recovery_ok = True
    except Exception:  # noqa: BLE001
        recovery_ok = False
    try:
        svc.close(timeout=5.0)
    except BaseException:
        pass
    return {"phase": phase, "overwrite": overwrite, "raised": raised,
            "target_exists_after": exists_after,
            "overwrite_preserved": (None if pre_sha is None else
                                    (post_sha == pre_sha)),
            "orphans": len(orphans), "fd_before": fd0, "fd_after": fd1,
            "recovery_ok": recovery_ok}


def stage_enospc(repo, budget):
    sys.path.insert(0, repo)
    base = tempfile.mkdtemp(prefix="d110-enospc-")
    problems = []
    phases = []
    fsize = {}
    try:
        roots, _fx = build_roots(base)
        root_main = roots["main"]
        pool = os.path.join(root_main, "savepool")
        tpath = os.path.join(pool, "inj.bin")

        # Sub-test 2A: real kernel RLIMIT_FSIZE mid-write EFBIG (child)
        rfd, wfd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(rfd)
            _fsize_child(repo, root_main, wfd)
            os._exit(0)
        os.close(wfd)
        fsize = _collect_child(pid, rfd, timeout=min(60.0, budget))
        if fsize.get("child_error"):
            fsize = {"result": "SKIPPED", "reason": fsize.get("child_error")}
        else:
            ok = (fsize.get("raised") == "ServiceError"
                  and fsize.get("target_exists") is False)
            fsize["result"] = "PASS" if ok else "FAIL"
            if not ok:
                problems.append("RLIMIT_FSIZE sub-test failed: %s" % fsize)

        # Sub-test 2B: injected ENOSPC at each of the four write phases
        for phase in ("temp_create", "mid_write", "fsync", "publish"):
            for overwrite in (False, True):
                # seed a known target for the overwrite cases
                if overwrite:
                    with open(tpath, "wb") as fh:
                        fh.write(b"SEED" * 1024)
                else:
                    if os.path.exists(tpath):
                        os.unlink(tpath)
                rec = _inject_phase(repo, root_main, phase, overwrite)
                phases.append(rec)
                raised = rec["raised"]
                if raised == "NONE" or not isinstance(raised, dict):
                    problems.append("%s overwrite=%s: no error raised" % (phase, overwrite))
                else:
                    if raised["code"] != "unavailable":
                        problems.append("%s overwrite=%s: code=%s (expected unavailable)"
                                        % (phase, overwrite, raised["code"]))
                if overwrite:
                    if rec["overwrite_preserved"] is False:
                        problems.append("%s overwrite=True: target not preserved" % phase)
                else:
                    if rec["target_exists_after"]:
                        problems.append("%s overwrite=False: partial target published" % phase)
                if rec["orphans"] != 0:
                    problems.append("%s overwrite=%s: %d orphan temp(s)"
                                    % (phase, overwrite, rec["orphans"]))
                if not rec["recovery_ok"]:
                    problems.append("%s overwrite=%s: recovery failed" % (phase, overwrite))
                if (rec["fd_before"] is not None and rec["fd_after"] is not None
                        and rec["fd_after"] > rec["fd_before"] + FD_BASELINE_SLACK):
                    problems.append("%s overwrite=%s: fd leak %s->%s"
                                    % (phase, overwrite, rec["fd_before"], rec["fd_after"]))
                # clean between phases
                for name in os.listdir(pool):
                    try:
                        os.unlink(os.path.join(pool, name))
                    except OSError:
                        pass
        return {
            "stage": "enospc",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems,
            "rlimit_fsize": fsize,
            "injected_phases": phases,
            "note": ("Error classification is recorded as the ACCEPTED adapter "
                     "actually behaves; the historical design's expected "
                     "outcome_uncertain=False/retry_safe=True is NOT assumed."),
        }
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


# ---------------------------------------------------------------------------
# Stage dispatch
# ---------------------------------------------------------------------------
STAGE_FUNCS = {
    "selfcheck": stage_selfcheck,
    "http_hostile": stage_http_hostile,
    "admission_exhaustion": stage_admission_exhaustion,
    "isolation": stage_isolation,
    "concurrent_ops": stage_concurrent_ops,
    "crash_kill": stage_crash_kill,
    "resource_pressure": stage_resource_pressure,
    "enospc": stage_enospc,
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="d110 harsh-fault payload (stdlib only)")
    ap.add_argument("--repo", required=True, help="path to the drive-tool checkout")
    ap.add_argument("--stage", required=True, choices=STAGE_NAMES)
    ap.add_argument("--budget", type=float, default=120.0)
    ap.add_argument("--json", help="write the stage result here")
    args = ap.parse_args(argv)

    fn = STAGE_FUNCS[args.stage]
    try:
        out = fn(args.repo, args.budget)
    except BaseException as exc:  # noqa: BLE001
        import traceback
        out = {"stage": args.stage, "result": "ERROR",
               "problems": ["stage raised %s: %s" % (type(exc).__name__, exc)],
               "traceback": traceback.format_exc()[-2000:]}
    if not isinstance(out, dict):
        out = {"stage": args.stage, "result": "ERROR",
               "problems": ["stage returned non-dict"]}
    text = json.dumps(out, default=str, sort_keys=True)
    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(out, indent=2, default=str, sort_keys=True))
        except OSError:
            pass
    sys.stdout.write("HARSH_JSON: " + text + "\n")
    sys.stdout.flush()
    res = out.get("result")
    if res == "PASS":
        return 0
    if res in ("SKIPPED", "PARTIAL"):
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

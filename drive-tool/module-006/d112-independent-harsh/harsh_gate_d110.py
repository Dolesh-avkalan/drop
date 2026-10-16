#!/usr/bin/env python3
"""d110 harsh target gate payload (stdlib only).

Pinned payload driven by run_harsh_target.py.  It exercises the ACCEPTED final
HTTP candidate (Dolesh-avkalan/drive-tool @ 337e4c71..., the D102 final HTTP
overlay) with hostile-fault stages that are deliberately harsher than the D101
reliability gate.  It is authored to run on the disposable target instance and
is sandbox-tested only.

Stages (fixed allow-list, execution order)
------------------------------------------
  selfcheck          capability probes + invariant arithmetic, no adapter
  readdir_order      directory-order confirmation (dual-order, no masking)
  http_hostile       malformed / oversize / slow-partial HTTP requests
  admission          deterministic 6+1 admission exhaustion + recovery
  isolation          cross-agent / path-traversal / symlink escape
  concurrency        simultaneous create / overwrite / range reads
  crash_kill         synchronized child SIGKILL mid-write / pre-publish + recovery
  resource_pressure  CHILD-only CPU / RAM(RLIMIT_AS) / FD(RLIMIT_NOFILE)
  enospc             injected ENOSPC at save phases + child RLIMIT_FSIZE

Every stage returns a dict with a ``result`` of PASS / FAIL / SKIP.  SKIP is used
ONLY for an explicitly unsupported capability and is never reported as a pass.
A stage that raises is reported ERROR; one that overruns is TIMEOUT.  Adverse
diagnostics are never relabelled as normal success.

Child roles
-----------
When invoked with ``--child-spec <json>`` the payload runs one bounded child
role (crash worker, recovery probe, ENOSPC/RLIMIT_FSIZE worker, FD worker, RAM
worker, CPU worker) and prints one ``CHILD_JSON:`` line.  Child roles are used so
that process-group SIGKILL, RLIMIT_FSIZE, RLIMIT_AS and RLIMIT_NOFILE pressure
are confined to the CHILD only.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import random
import resource
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

# --------------------------------------------------------------------------
# Frozen constants
# --------------------------------------------------------------------------
TEMP_PREFIX = ".drive-tool-tmp-"
PATH_PREFIX = "p/"
MAX_IN_FLIGHT = 6                      # product: MAX_IN_FLIGHT_OPERATIONS
KNOWN_CODES = frozenset(
    {"invalid", "denied", "not_found", "exists", "too_large", "busy",
     "unavailable", "timeout"}
)
EXPECTED_ADAPTER_THREADS = 7           # 1 accept + 6 workers
FD_SLACK = 2
MEM_AVAILABLE_FLOOR_KB = 512 * 1024    # abort RAM pressure below this
MEM_AVAILABLE_PREFLIGHT_KB = 1024 * 1024
FREE_DISK_FLOOR_BYTES = 1024 * 1024 * 1024

SAT_CYCLES = 8                         # bounded deterministic admission cycles
SAT_OCCUPIERS = 6
SAT_EXCESS = 1

CONC_CREATE_THREADS = 6          # must stay <= MAX_IN_FLIGHT (admission)
CONC_OVERWRITE_THREADS = 6
CONC_READ_THREADS = 2
CONC_READ_DURING_WRITERS = 3     # readers + writers must stay <= MAX_IN_FLIGHT
CONC_ROUNDS = 6

CRASH_STORM_CHILDREN = 4
CRASH_STORM_CYCLES = 10
CRASH_STORM_FILES = 8

REQUIRED_STAGES = (
    "selfcheck", "readdir_order", "http_hostile", "admission", "isolation",
    "concurrency", "crash_kill", "resource_pressure", "enospc",
)

# Personas: (label, root_name, alias, operations)
PERSONAS = (
    ("agent-main", "main", "main", ("list", "find", "read", "save")),
    ("agent-other", "other", "other", ("list", "find", "read", "save")),
    ("agent-ro", "ro", "ro", ("list", "find", "read")),
    ("agent-shared-a", "shared", "shared", ("list", "find", "read", "save")),
    ("agent-shared-b", "shared", "shared", ("list", "find", "read", "save")),
)
RO_AGENT = 2
# Tokens are synthetic, >=32 chars, never printed.
_TOKENS = tuple("d110-%s-" % label + ("A" * 40) for label, *_ in PERSONAS)


def _tlabel(i):
    return "agent%d" % i


def _log(msg=""):
    sys.stderr.write(str(msg) + "\n")
    sys.stderr.flush()


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _free_floor():
    """Free-disk floor; strict default, overridable only for sandbox validation."""
    v = os.environ.get("D110_MIN_FREE_BYTES")
    try:
        return int(v)
    except (TypeError, ValueError):
        return FREE_DISK_FLOOR_BYTES


def _free_bytes(path):
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def _mem_available_kb():
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


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


def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


# --------------------------------------------------------------------------
# Raw HTTP
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


def _slow_partial(port, payload, *, half_after=0.15, timeout=3.0):
    """Send headers + partial body, then close without completing."""
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(payload)
        time.sleep(half_after)
        s.settimeout(timeout)
        try:
            return s.recv(4096)
        except socket.timeout:
            return b""
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
# Fixtures / policies
# --------------------------------------------------------------------------
def build_fixtures(base):
    """Six roots + an OUTSIDE secret dir + symlinks pointing out of a root."""
    roots = {}
    for name in ("main", "other", "ro", "shared"):
        r = os.path.join(base, "root_" + name)
        os.makedirs(os.path.join(r, "sub"), exist_ok=True)
        os.makedirs(os.path.join(r, "savepool"), exist_ok=True)
        _write(os.path.join(r, "readme.txt"), b"d110 fixture readme\n" * 4)
        _write(os.path.join(r, "data.bin"), bytes(range(256)) * 16)
        _write(os.path.join(r, "sub", "note.txt"), b"nested note\n")
        roots[name] = os.path.realpath(r)
    outside = os.path.join(base, "outside")
    os.makedirs(outside, exist_ok=True)
    _write(os.path.join(outside, "secret.txt"), b"TOP-SECRET-OUTSIDE\n")
    # symlinks inside the main root that point OUTSIDE it
    os.symlink(outside, os.path.join(roots["main"], "link"))
    os.symlink(outside, os.path.join(roots["main"], "slink"))
    roots["_outside"] = os.path.realpath(outside)
    return roots


def build_policies(roots):
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    policies = []
    for idx, (label, root_name, alias, ops) in enumerate(PERSONAS):
        grant = SourceGrant(
            alias=alias,
            root=roots[root_name],
            operations=frozenset(ops),
            max_read_bytes=1048576,
            max_write_bytes=1048576,
        )
        policies.append(AgentPolicy(
            agent_id=label,
            token_sha256=hashlib.sha256(_TOKENS[idx].encode("ascii")).digest(),
            grants=(grant,),
        ))
    return tuple(policies)


def _client(port, token, timeout=5.0):
    from drive_tool.service_client import DriveClient
    return DriveClient(port=port, token=token, timeout=timeout)


def _classify_client_error(exc):
    from drive_tool.service_client import DriveClientError
    if isinstance(exc, DriveClientError):
        return {"code": exc.code, "outcome_uncertain": exc.outcome_uncertain,
                "retry_safe": exc.retry_safe}
    return None


# --------------------------------------------------------------------------
# Deterministic service-entry barrier (reused from the accepted D101 gate)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# STAGE: selfcheck
# --------------------------------------------------------------------------
def stage_selfcheck(repo):
    problems = []
    caps = {}
    sys.path.insert(0, repo)
    try:
        from drive_tool import http_adapter as ha
        from drive_tool import local as lo
        from drive_tool import local_write as lw
    except Exception as exc:  # noqa: BLE001
        return {"stage": "selfcheck", "result": "FAIL",
                "problems": ["product import failed: %r" % (exc,)],
                "capabilities": {}}

    if ha.MAX_IN_FLIGHT_OPERATIONS != MAX_IN_FLIGHT:
        problems.append("MAX_IN_FLIGHT_OPERATIONS %s != %d"
                        % (ha.MAX_IN_FLIGHT_OPERATIONS, MAX_IN_FLIGHT))
    if getattr(lo, "TEMP_PREFIX", None) != TEMP_PREFIX:
        problems.append("TEMP_PREFIX %r != %r" % (getattr(lo, "TEMP_PREFIX", None), TEMP_PREFIX))
    if getattr(lo, "PATH_PREFIX", None) != PATH_PREFIX:
        problems.append("PATH_PREFIX %r != %r" % (getattr(lo, "PATH_PREFIX", None), PATH_PREFIX))
    if not hasattr(lw, "LocalWriter"):
        problems.append("LocalWriter missing")

    caps["mem_available_kb"] = _mem_available_kb()
    caps["free_bytes"] = _free_bytes(repo)
    caps["tmp_fstype"] = _mount_fstype("/tmp")
    caps["oom_score_adj_writable"] = _writable("/proc/self/oom_score_adj")
    caps["rlimit_fsize_settable"] = _rlimit_settable(resource.RLIMIT_FSIZE)
    caps["rlimit_as_settable"] = _rlimit_settable(resource.RLIMIT_AS)
    caps["rlimit_nofile_settable"] = _rlimit_settable(resource.RLIMIT_NOFILE)
    caps["os_link_supported"] = _os_link_supported()
    caps["sigxfsz_ignorable"] = _sigxfsz_ignorable()
    caps["python"] = sys.version
    caps["platform"] = sys.platform

    if caps["mem_available_kb"] is not None \
            and caps["mem_available_kb"] < MEM_AVAILABLE_PREFLIGHT_KB:
        problems.append("host MemAvailable %d KiB < %d KiB"
                        % (caps["mem_available_kb"], MEM_AVAILABLE_PREFLIGHT_KB))
    floor = _free_floor()
    caps["free_floor_bytes"] = floor
    if caps["free_bytes"] is not None and caps["free_bytes"] < floor:
        problems.append("free disk %d < %d bytes" % (caps["free_bytes"], floor))

    # invariant arithmetic
    if SAT_OCCUPIERS * SAT_CYCLES <= 0 or SAT_EXCESS <= 0:
        problems.append("saturation arithmetic invalid")
    if MAX_IN_FLIGHT != SAT_OCCUPIERS:
        problems.append("MAX_IN_FLIGHT (%d) != SAT_OCCUPIERS (%d)"
                        % (MAX_IN_FLIGHT, SAT_OCCUPIERS))
    if CONC_CREATE_THREADS > MAX_IN_FLIGHT:
        problems.append("CONC_CREATE_THREADS %d > MAX_IN_FLIGHT %d"
                        % (CONC_CREATE_THREADS, MAX_IN_FLIGHT))
    if CONC_READ_DURING_WRITERS + CONC_READ_THREADS > MAX_IN_FLIGHT:
        problems.append("reader+writer concurrency %d > MAX_IN_FLIGHT %d"
                        % (CONC_READ_DURING_WRITERS + CONC_READ_THREADS, MAX_IN_FLIGHT))

    return {"stage": "selfcheck",
            "result": "PASS" if not problems else "FAIL",
            "problems": problems, "capabilities": caps}


def _mount_fstype(path):
    try:
        with open("/proc/mounts", "r") as fh:
            best = None
            for line in fh:
                p = line.split()
                if len(p) >= 3 and p[1] == path:
                    best = p[2]
            return best
    except OSError:
        return None


def _writable(path):
    try:
        fd = os.open(path, os.O_WRONLY)
        os.close(fd)
        return True
    except OSError:
        return False


def _rlimit_settable(which):
    try:
        soft, hard = resource.getrlimit(which)
        resource.setrlimit(which, (soft, hard))
        return True
    except (OSError, ValueError):
        return False


def _os_link_supported():
    try:
        d = tempfile.mkdtemp(prefix="d110-link-")
        a = os.path.join(d, "a")
        b = os.path.join(d, "b")
        _write(a, b"x")
        os.link(a, b)
        ok = os.path.exists(b)
        shutil.rmtree(d, ignore_errors=True)
        return ok
    except OSError:
        return False


def _sigxfsz_ignorable():
    try:
        old = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        signal.signal(signal.SIGXFSZ, old)
        return True
    except (ValueError, OSError, AttributeError):
        return False


# --------------------------------------------------------------------------
# STAGE: readdir_order
# --------------------------------------------------------------------------
def stage_readdir_order(repo):
    base = tempfile.mkdtemp(prefix="d110-order-")
    problems = []
    try:
        probe = os.path.join(base, "probe")
        os.makedirs(probe)
        _write(os.path.join(probe, "a.txt"), b"a")
        _write(os.path.join(probe, "b.txt"), b"b")
        native = [e.name for e in os.scandir(probe)]
        fstype = _mount_fstype("/tmp")

        test_id = ("tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests."
                   "test_metadata_failure_below_root_is_skipped_and_charged")
        env = dict(os.environ)
        env["PYTHONPATH"] = repo
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        def run_order(mode):
            if mode == "native":
                code = ("import sys,unittest;"
                        "unittest.main(module=None,argv=['x','-v',%r])" % test_id)
            else:
                code = (
                    "import os,sys,unittest\n"
                    "_s=os.scandir\n"
                    "class _Rev:\n"
                    "    def __init__(self,e): self._i=iter(e)\n"
                    "    def __enter__(self): return self\n"
                    "    def __exit__(self,*a): return False\n"
                    "    def __iter__(self): return self\n"
                    "    def __next__(self): return next(self._i)\n"
                    "os.scandir=lambda p='.': _Rev(list(reversed(list(_s(p)))))\n"
                    "_l=os.listdir\n"
                    "os.listdir=lambda p='.': list(reversed(_l(p)))\n"
                    "unittest.main(module=None,argv=['x','-v',%r])" % test_id)
            p = subprocess.run([sys.executable, "-c", code], cwd=repo, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=120)
            out = p.stdout.decode("utf-8", "replace")
            ok = (p.returncode == 0 and "FAILED" not in out and "Ran " in out)
            return {"rc": p.returncode, "ok": ok,
                    "tail": out.strip().splitlines()[-3:]}

        native_run = run_order("native")
        inverted_run = run_order("inverted")

        if not native_run["ok"]:
            problems.append("order test failed under native order")
        if not inverted_run["ok"]:
            problems.append("order test failed under forced-inverted readdir order")

        return {"stage": "readdir_order",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems,
                "tmp_fstype": fstype,
                "native_readdir_order": native,
                "test_id": test_id,
                "native_run": native_run,
                "inverted_run": inverted_run,
                "note": ("The committed test is order-explicit (it injects both "
                         "['a.txt','b.txt'] and ['b.txt','a.txt']); the accepted "
                         "fix must pass under either host readdir order.")}
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# STAGE: http_hostile
# --------------------------------------------------------------------------
def stage_http_hostile(repo):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    base = tempfile.mkdtemp(prefix="d110-hostile-")
    adapter = None
    problems = []
    observations = {}
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=2.0)
        time.sleep(0.1)
        fd0 = _nfd()
        token = _TOKENS[0]
        good = _raw_request("/v1/list", token,
                            json.dumps({"source_id": "main", "file_id": "root",
                                        "limit": 20, "offset": 0}).encode())
        valid_body = json.dumps({"source_id": "main", "file_id": "root",
                                 "limit": 20, "offset": 0}).encode()

        cases = {}
        cases["overlong_request_line"] = b"POST /" + b"a" * 8200 + b" HTTP/1.1\r\n"
        cases["overlong_header_block"] = (b"POST /v1/list HTTP/1.1\r\nX-Pad: "
                                          + b"a" * 16384 + b"\r\n")
        cases["too_many_headers"] = (
            b"POST /v1/list HTTP/1.1\r\n"
            + b"".join(b"X-%d: v\r\n" % i for i in range(80))
            + b"\r\n")
        cases["huge_digit_content_length"] = _raw_request(
            "/v1/list", token, b"").replace(
            b"Content-Length: 0", b"Content-Length: " + b"9" * 5000)
        cases["non_digit_content_length"] = _raw_request(
            "/v1/list", token, valid_body).replace(
            b"Content-Length: %d" % len(valid_body), b"Content-Length: +5")
        cases["duplicate_content_length"] = (
            b"POST /v1/list HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            b"Authorization: Bearer " + token.encode() + b"\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: " + str(len(valid_body)).encode() + b"\r\n"
            b"Content-Length: " + str(len(valid_body)).encode() + b"\r\n"
            b"Connection: close\r\n\r\n" + valid_body)
        cases["bare_lf_header_block"] = (
            b"POST /v1/list HTTP/1.1\nHost: 127.0.0.1\nAuthorization: Bearer "
            + token.encode() + b"\n\n")
        cases["buffered_trailing_bytes"] = good + b"X"
        cases["bad_method"] = good.replace(b"POST ", b"GET ", 1)
        cases["unknown_endpoint"] = good.replace(b"/v1/list", b"/v1/nope")
        cases["oversize_json_body"] = _raw_request(
            "/v1/list", token, b"a" * 70000)
        cases["oversize_save_body"] = _raw_request(
            "/v1/save?source_id=main&file_id=p%2Fbig.bin&overwrite=true&create_parents=true",
            token, b"a" * (1048576 + 4096), ctype=b"application/octet-stream")

        for name, payload in sorted(cases.items()):
            try:
                raw = _raw_exchange(adapter.port, payload, timeout=4.0)
                status, code = _status_code(raw)
                observations[name] = {"status": status, "code": code,
                                      "bytes": len(raw)}
            except Exception as exc:  # noqa: BLE001
                observations[name] = {"exception": type(exc).__name__}
                problems.append("%s: transport exception %s" % (name, type(exc).__name__))

        # slow partial body: declare a large body, send a little, hold, close
        try:
            partial = _raw_request("/v1/save?source_id=main&file_id=p%2Fslow.bin"
                                   "&overwrite=false&create_parents=true",
                                   token, b"x" * 4096,
                                   ctype=b"application/octet-stream")
            # rewrite Content-Length to a large value while sending few bytes
            partial = partial.replace(b"Content-Length: 4096", b"Content-Length: 999999")
            raw = _slow_partial(adapter.port, partial, half_after=0.3)
            status, code = _status_code(raw)
            observations["slow_partial_body"] = {"status": status, "code": code,
                                                 "bytes": len(raw)}
        except Exception as exc:  # noqa: BLE001
            observations["slow_partial_body"] = {"exception": type(exc).__name__}
            problems.append("slow_partial_body: transport exception %s" % type(exc).__name__)

        # Every hostile case must terminate in a typed 4xx/5xx envelope or a
        # clean close -- never a 2xx success and never a hang.
        for name, obs in observations.items():
            st = obs.get("status")
            if st is not None and 200 <= st < 300:
                problems.append("%s: unexpected 2xx success (status=%s)" % (name, st))
            if st is not None and st not in (400, 403, 404, 409, 413, 503, 504):
                problems.append("%s: unexpected status %s" % (name, st))

        # Recovery: the adapter must still serve a valid request.
        rec = _raw_exchange(adapter.port, good, timeout=5.0)
        rstatus, rcode = _status_code(rec)
        observations["post_hostile_recovery"] = {"status": rstatus, "code": rcode,
                                                 "bytes": len(rec)}
        if rstatus != 200:
            problems.append("adapter did not recover: recovery status %s" % rstatus)

        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped: %s" % threads_after)
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_SLACK:
            problems.append("fd %s -> %s (leak)" % (fd0, fd1))

        return {"stage": "http_hostile",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems,
                "cases": observations,
                "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed,
                              "threads_after": threads_after}}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# STAGE: admission (deterministic 6+1 exhaustion + recovery)
# --------------------------------------------------------------------------
def stage_admission(repo):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    base = tempfile.mkdtemp(prefix="d110-adm-")
    adapter = None
    problems = []
    cycles = []
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        service = _make_gated_service(policies)
        adapter = DriveHTTPAdapter(service=service, port=0, socket_timeout=5.0)
        time.sleep(0.1)
        fd0 = _nfd()
        token = _TOKENS[0]
        req = _raw_request("/v1/list", token,
                           json.dumps({"source_id": "main", "file_id": "root",
                                       "limit": 20, "offset": 0}).encode())

        for cycle in range(SAT_CYCLES):
            gate = _EntryGate(SAT_OCCUPIERS)
            service._gate = gate
            out = {}

            def occupier(slot):
                raw = _raw_exchange(adapter.port, req, timeout=15.0)
                out[("occ", slot)] = _status_code(raw)

            threads = [threading.Thread(target=occupier, args=(i,))
                       for i in range(SAT_OCCUPIERS)]
            for t in threads:
                t.start()
            entered = gate.entered.wait(timeout=20.0)
            exc = _status_code(_raw_exchange(adapter.port, req, timeout=15.0))
            gate.release.set()
            for t in threads:
                t.join(timeout=20.0)
            service._gate = None

            occ = [out.get(("occ", i), (None, None)) for i in range(SAT_OCCUPIERS)]
            occ_ok = sum(1 for (s, c) in occ if s == 200)
            occ_bad = sum(1 for (s, c) in occ if s != 200)
            exc_busy = 1 if exc[1] == "busy" else 0
            exc_unavail = 1 if exc[1] == "unavailable" else 0
            exc_other = 0 if (exc_busy or exc_unavail) else 1
            cycles.append({"cycle": cycle, "entered": entered,
                           "occupiers_ok": occ_ok, "occupiers_bad": occ_bad,
                           "excess": exc})
            if not entered:
                problems.append("cycle %d: service-entry barrier not reached" % cycle)
            if occ_ok != SAT_OCCUPIERS:
                problems.append("cycle %d: %d/%d occupiers admitted (expected all)"
                                % (cycle, occ_ok, SAT_OCCUPIERS))
            if occ_bad:
                problems.append("cycle %d: %d occupier(s) wrongly rejected" % (cycle, occ_bad))
            if exc_busy != 1:
                problems.append("cycle %d: excess not busy (got %r)" % (cycle, exc))
            if exc_unavail or exc_other:
                problems.append("cycle %d: excess unexpected (%r)" % (cycle, exc))

        # Recovery after exhaustion: a normal request must succeed.
        rec = _status_code(_raw_exchange(adapter.port, req, timeout=5.0))
        if rec[0] != 200:
            problems.append("post-admission recovery failed: %r" % (rec,))

        closed = adapter.close(timeout=10.0)
        threads_after = _adapter_threads()
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if threads_after:
            problems.append("adapter threads not reaped: %s" % threads_after)
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_SLACK:
            problems.append("fd %s -> %s (leak)" % (fd0, fd1))

        return {"stage": "admission",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems,
                "frozen": {"cycles": SAT_CYCLES, "occupiers": SAT_OCCUPIERS,
                           "excess": SAT_EXCESS},
                "recovery": {"status": rec[0], "code": rec[1]},
                "cycles": cycles,
                "resources": {"fd_before": fd0, "fd_after": fd1, "closed": closed}}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# STAGE: isolation
# --------------------------------------------------------------------------
def stage_isolation(repo):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    base = tempfile.mkdtemp(prefix="d110-iso-")
    adapter = None
    problems = []
    checks = {}
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=5.0)
        time.sleep(0.1)
        secret_path = os.path.join(roots["_outside"], "secret.txt")
        secret = open(secret_path, "rb").read()

        def call(fn, *a, **k):
            try:
                return {"ok": True, "value": fn(*a, **k)}
            except (ValueError, TypeError) as exc:
                # client-side validation rejection (never dispatched)
                return {"ok": False, "client_reject": type(exc).__name__}
            except Exception as exc:  # noqa: BLE001
                info = _classify_client_error(exc)
                if info is None:
                    return {"ok": False, "unhandled": type(exc).__name__}
                return {"ok": False, "error": info}

        # 1. cross-agent: main token asking for the "other" source
        checks["cross_agent_other"] = call(
            _client(adapter.port, _TOKENS[0]).list, "other", limit=20)
        # 2. cross-agent read
        checks["cross_agent_other_read"] = call(
            _client(adapter.port, _TOKENS[0]).read, "other", "p/readme.txt",
            offset=0, length=64)
        # 3. path traversal in file_id
        checks["traversal_dotdot"] = call(
            _client(adapter.port, _TOKENS[0]).read, "main",
            "p/../../outside/secret.txt", offset=0, length=64)
        checks["traversal_encoded"] = call(
            _client(adapter.port, _TOKENS[0]).read, "main",
            "p/%2e%2e/secret.txt", offset=0, length=64)
        # 4. symlink escape via read
        checks["symlink_read"] = call(
            _client(adapter.port, _TOKENS[0]).read, "main",
            "p/link/secret.txt", offset=0, length=64)
        # 5. symlink escape via list
        checks["symlink_list"] = call(
            _client(adapter.port, _TOKENS[0]).list, "main", "p/link", limit=20)
        # 6. symlink escape via save (must not create a file outside)
        checks["symlink_save"] = call(
            _client(adapter.port, _TOKENS[0]).save, "main",
            "p/slink/evil.bin", b"pwn", overwrite=True)
        # 7. shared alias: two agents on the same alias/root both succeed
        checks["shared_alias_a"] = call(
            _client(adapter.port, _TOKENS[3]).list, "shared", limit=20)
        checks["shared_alias_b"] = call(
            _client(adapter.port, _TOKENS[4]).list, "shared", limit=20)
        # 8. read-only agent cannot save
        checks["ro_save_denied"] = call(
            _client(adapter.port, _TOKENS[RO_AGENT]).save, "ro",
            "p/savepool/x.bin", b"x" * 8, overwrite=True)

        # Verdicts
        def is_denied_or_error(name):
            r = checks[name]
            if r.get("ok"):
                return False
            if "client_reject" in r:
                return True
            if "unhandled" in r:
                return False
            return r.get("error", {}).get("code") in KNOWN_CODES

        for name in ("cross_agent_other", "cross_agent_other_read",
                     "traversal_dotdot", "traversal_encoded",
                     "symlink_read", "symlink_list", "symlink_save",
                     "ro_save_denied"):
            if not is_denied_or_error(name):
                problems.append("%s: not a typed denial: %r" % (name, checks[name]))
            if "unhandled" in checks[name]:
                problems.append("%s: unhandled exception %s"
                                % (name, checks[name]["unhandled"]))

        # symlink_read must not return the outside secret
        r = checks["symlink_read"]
        if r.get("ok"):
            data = getattr(r["value"], "data", b"")
            if secret[:16] in data:
                problems.append("symlink_read: ESCAPED root, returned outside secret")

        for name in ("shared_alias_a", "shared_alias_b"):
            if not checks[name].get("ok"):
                problems.append("%s: shared alias access denied: %r" % (name, checks[name]))

        # Outside dir must be unchanged and contain no new file
        if not os.path.isfile(secret_path) or open(secret_path, "rb").read() != secret:
            problems.append("outside secret was modified")
        outside_listing = sorted(os.listdir(roots["_outside"]))
        if outside_listing != ["secret.txt"]:
            problems.append("outside dir mutated: %s" % outside_listing)

        closed = adapter.close(timeout=10.0)
        if not closed:
            problems.append("adapter.close() did not return True")
        return {"stage": "isolation",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems, "checks": checks,
                "outside_listing": outside_listing}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# STAGE: concurrency
# --------------------------------------------------------------------------
def stage_concurrency(repo):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    base = tempfile.mkdtemp(prefix="d110-conc-")
    adapter = None
    problems = []
    detail = {}
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=10.0)
        time.sleep(0.1)
        fd0 = _nfd()
        token = _TOKENS[0]

        # 1. simultaneous create (overwrite=False) of the same NEW name
        winners = []
        exists = []
        others = []
        barrier = threading.Barrier(CONC_CREATE_THREADS)

        def create_worker(i):
            barrier.wait()
            try:
                _client(adapter.port, token).save(
                    "main", "p/savepool/race.bin", b"c%d" % i, overwrite=False)
                winners.append(i)
            except Exception as exc:  # noqa: BLE001
                info = _classify_client_error(exc)
                if info and info["code"] == "exists":
                    exists.append(i)
                else:
                    others.append((i, info or type(exc).__name__))

        ts = [threading.Thread(target=create_worker, args=(i,))
              for i in range(CONC_CREATE_THREADS)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        detail["create"] = {"winners": len(winners), "exists": len(exists),
                            "other": others}
        if len(winners) != 1:
            problems.append("create race: %d winners (expected exactly 1)" % len(winners))
        if others:
            problems.append("create race: unexpected errors %r" % others)

        # 2. simultaneous overwrite of the same name with distinct payloads
        payloads = [("o%d" % i).encode() * 64 for i in range(CONC_OVERWRITE_THREADS)]
        ow_err = []
        barrier2 = threading.Barrier(CONC_READ_DURING_WRITERS)

        def ow_worker(i):
            barrier2.wait()
            try:
                _client(adapter.port, token).save(
                    "main", "p/savepool/ow.bin", payloads[i], overwrite=True)
            except Exception as exc:  # noqa: BLE001
                ow_err.append((i, _classify_client_error(exc) or type(exc).__name__))

        # 3. concurrent readers while overwrites happen
        torn = []
        busy_seen = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    r = _client(adapter.port, token).read(
                        "main", "p/savepool/ow.bin", offset=0, length=256)
                    data = r.data
                    if data and data not in payloads and not any(
                            p.startswith(data) for p in payloads):
                        torn.append(len(data))
                except Exception as exc:  # noqa: BLE001
                    info = _classify_client_error(exc)
                    code = info["code"] if info else None
                    if code == "not_found":
                        pass                       # not yet created
                    elif code == "busy":
                        busy_seen.append(1)        # admission, not corruption
                    else:
                        torn.append("err:%s" % (info or type(exc).__name__))

        rts = [threading.Thread(target=reader) for _ in range(CONC_READ_THREADS)]
        for t in rts:
            t.start()
        owts = [threading.Thread(target=ow_worker, args=(i,))
                for i in range(CONC_READ_DURING_WRITERS)]
        for t in owts:
            t.start()
        for t in owts:
            t.join(timeout=30)
        stop.set()
        for t in rts:
            t.join(timeout=10)

        detail["overwrite"] = {"errors": ow_err, "torn_reads": torn[:10],
                               "torn_count": len(torn),
                               "busy_reads": len(busy_seen)}
        if ow_err:
            problems.append("overwrite race: unexpected errors %r" % ow_err)
        if torn:
            problems.append("range read observed torn/partial data: %d" % len(torn))

        # 4. concurrent create_parents of distinct nested paths
        cp_err = []
        barrier3 = threading.Barrier(CONC_CREATE_THREADS)

        def cp_worker(i):
            barrier3.wait()
            try:
                _client(adapter.port, token).save(
                    "main", "p/nest%d/a/b/c.bin" % i, b"n%d" % i,
                    overwrite=True, create_parents=True)
            except Exception as exc:  # noqa: BLE001
                cp_err.append((i, _classify_client_error(exc) or type(exc).__name__))

        ts = [threading.Thread(target=cp_worker, args=(i,))
              for i in range(CONC_CREATE_THREADS)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        detail["create_parents"] = {"errors": cp_err}
        if cp_err:
            problems.append("create_parents race: unexpected errors %r" % cp_err)

        # final published ow.bin must equal exactly one complete payload
        final = open(os.path.join(roots["main"], "savepool", "ow.bin"), "rb").read()
        if final not in payloads:
            problems.append("final overwrite file is not a complete payload")

        # no temp residue in any root
        leaked = _count_temp(roots)
        detail["temp_leaks"] = leaked
        if leaked:
            problems.append("temp residue after concurrency: %s" % leaked)

        closed = adapter.close(timeout=10.0)
        fd1 = _nfd()
        if not closed:
            problems.append("adapter.close() did not return True")
        if fd0 is not None and fd1 is not None and fd1 > fd0 + FD_SLACK:
            problems.append("fd %s -> %s (leak)" % (fd0, fd1))
        return {"stage": "concurrency",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems, "detail": detail}
    finally:
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


def _count_temp(roots):
    leaks = {}
    for key, root in roots.items():
        if key.startswith("_"):
            continue
        n = 0
        for dp, dn, fn in os.walk(root):
            for name in fn:
                if name.startswith(TEMP_PREFIX):
                    n += 1
        if n:
            leaks[key] = n
    return leaks


# --------------------------------------------------------------------------
# STAGE: crash_kill  (synchronized child SIGKILL + fresh-process recovery)
# --------------------------------------------------------------------------
def _spawn_child(repo, spec, extra_fds=(), timeout=None):
    payload = [sys.executable, os.path.abspath(__file__),
               "--repo", repo, "--child-spec", json.dumps(spec)]
    env = dict(os.environ)
    env["PYTHONPATH"] = repo
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.Popen(payload, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env,
                         start_new_session=True, pass_fds=extra_fds)
    return p


def _read_child_json(p, timeout=60):
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except OSError:
            pass
        out, err = p.communicate()
    text = out.decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("CHILD_JSON:"):
            try:
                return json.loads(line[len("CHILD_JSON:"):])
            except ValueError:
                pass
    return {"child_error": True, "rc": p.returncode,
            "stderr_tail": err.decode("utf-8", "replace")[-400:]}


def _kill_and_reap(p):
    try:
        pgid = os.getpgid(p.pid)
    except OSError:
        pgid = None
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        try:
            p.kill()
        except OSError:
            pass
    try:
        _, status = os.waitpid(p.pid, 0)
        return status
    except ChildProcessError:
        return None


def stage_crash_kill(repo):
    base = tempfile.mkdtemp(prefix="d110-crash-")
    problems = []
    cases = {}
    try:
        roots = build_fixtures(base)
        root = roots["main"]
        parent_dir = os.path.join(root, "savepool")
        token = _TOKENS[0]

        def run_crash_case(name, mode):
            target = os.path.join(parent_dir, "crash_%s.bin" % name)
            # remove any prior artifact
            for n in os.listdir(parent_dir):
                if n.startswith(TEMP_PREFIX) or n == os.path.basename(target):
                    try:
                        os.unlink(os.path.join(parent_dir, n))
                    except OSError:
                        pass
            rfd, wfd = os.pipe()          # child signals ready
            brfd, bwfd = os.pipe()        # child blocks reading brfd
            spec = {"role": "crash_worker", "mode": mode, "root": root,
                    "alias": "main", "token": token, "parent": "savepool",
                    "name": "crash_%s.bin" % name, "sig_fd": wfd, "blk_fd": brfd,
                    "payload_hex": (b"Z" * 4096).hex()}
            p = _spawn_child(repo, spec, extra_fds=(wfd, brfd))
            os.close(wfd)
            os.close(brfd)
            # wait for the ready byte
            os.set_blocking(rfd, False)
            ready = False
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    b = os.read(rfd, 1)
                    if b:
                        ready = True
                        break
                except BlockingIOError:
                    time.sleep(0.02)
            status = _kill_and_reap(p)
            os.close(rfd)
            os.close(bwfd)
            killed_by_sigkill = (status is not None and os.WIFSIGNALED(status)
                                 and os.WTERMSIG(status) == signal.SIGKILL)
            temps = [n for n in os.listdir(parent_dir) if n.startswith(TEMP_PREFIX)]
            published = os.path.exists(target)
            # fresh-process recovery
            rec = _read_child_json(_spawn_child(repo, {
                "role": "recover_probe", "root": root, "alias": "main",
                "token": token}), timeout=60)
            cases[name] = {"mode": mode, "ready": ready,
                           "killed_by_sigkill": killed_by_sigkill,
                           "orphan_temps": len(temps),
                           "published": published,
                           "recovery": rec}
            if not ready:
                problems.append("%s: child never signalled ready" % name)
            if not killed_by_sigkill:
                problems.append("%s: child not terminated by SIGKILL" % name)
            if len(temps) < 1:
                problems.append("%s: no orphan temp after kill (staging not interrupted)"
                                % name)
            if published:
                problems.append("%s: partial publish visible after kill" % name)
            _check_recovery(name, rec, problems)
            return temps

        run_crash_case("midwrite", "mid_write")
        run_crash_case("prepublish", "pre_publish")

        # orphan temp visibility: temp names must be hidden from list()/find()
        rec = _read_child_json(_spawn_child(repo, {
            "role": "recover_probe", "root": root, "alias": "main", "token": token}),
            timeout=60)
        if rec.get("temp_in_list") or rec.get("temp_in_find"):
            problems.append("orphan TEMP_PREFIX files are exposed by list()/find()")
        cases["orphan_visibility"] = {"temp_in_list": rec.get("temp_in_list"),
                                      "temp_in_find": rec.get("temp_in_find"),
                                      "on_disk_temps": rec.get("on_disk_temps")}

        # C3: uninstrumented multi-process SIGKILL storm
        storm = _run_storm(repo, base, roots)
        cases["storm"] = storm
        if storm.get("torn"):
            problems.append("storm: %d torn/corrupt target file(s)" % storm["torn"])
        if storm.get("errors"):
            problems.append("storm: unexpected errors %r" % storm["errors"][:5])

        return {"stage": "crash_kill",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems, "cases": cases,
                "note": ("SIGKILL terminates user space only; this proves "
                         "process-crash atomicity, NOT physical power-loss "
                         "durability. No physical-power-loss claim is made.")}
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _check_recovery(name, rec, problems):
    if rec.get("child_error"):
        problems.append("%s: recovery probe failed: %r" % (name, rec))
        return
    if not rec.get("list_ok"):
        problems.append("%s: fresh service list() failed after crash" % name)
    if not rec.get("read_ok"):
        problems.append("%s: fresh service read() failed after crash" % name)
    if not rec.get("save_ok"):
        problems.append("%s: fresh service save() failed after crash" % name)
    if not rec.get("find_ok"):
        problems.append("%s: fresh service find() failed after crash" % name)


STORM_SEED = b"seed" * 8


def _run_storm(repo, base, roots):
    root = roots["main"]
    parent_dir = os.path.join(root, "savepool")
    # seed shared files with a KNOWN initial value (a valid terminal state)
    for i in range(CRASH_STORM_FILES):
        _write(os.path.join(parent_dir, "s%02d.bin" % i), STORM_SEED)
    procs = []
    token = _TOKENS[0]
    for w in range(CRASH_STORM_CHILDREN):
        spec = {"role": "crash_storm", "root": root, "alias": "main",
                "token": token, "parent": "savepool",
                "files": CRASH_STORM_FILES, "worker": w}
        procs.append(_spawn_child(repo, spec))
    rng = random.Random(0xD110)
    killed = 0
    for _ in range(CRASH_STORM_CYCLES):
        time.sleep(0.05)
        live = [p for p in procs if p.poll() is None]
        if not live:
            break
        victim = rng.choice(live)
        try:
            os.killpg(os.getpgid(victim.pid), signal.SIGKILL)
        except OSError:
            pass
        killed += 1
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    torn = 0
    errors = []
    for i in range(CRASH_STORM_FILES):
        pth = os.path.join(parent_dir, "s%02d.bin" % i)
        if not os.path.exists(pth):
            continue
        data = open(pth, "rb").read()
        # each file must equal its initial seed OR a complete, valid new write
        if data != STORM_SEED and not _valid_payload(data):
            torn += 1
            errors.append("torn:%s(%d bytes)" % (os.path.basename(pth), len(data)))
    # fresh recovery after storm
    rec = _read_child_json(_spawn_child(repo, {
        "role": "recover_probe", "root": root, "alias": "main", "token": token}),
        timeout=60)
    if rec.get("child_error"):
        errors.append("storm recovery probe failed")
    return {"killed": killed, "torn": torn, "errors": errors,
            "recovery_ok": bool(rec.get("list_ok") and rec.get("read_ok")
                                and rec.get("save_ok"))}


def _valid_payload(data):
    # payload format: 32-byte ascii sha256 hex header + body
    if len(data) < 32:
        return False
    head = data[:32]
    try:
        hexdigest = head.decode("ascii")
    except UnicodeDecodeError:
        return False
    if len(hexdigest) != 32:
        return False
    return hashlib.sha256(data[32:]).hexdigest()[:32] == hexdigest


# --------------------------------------------------------------------------
# STAGE: resource_pressure  (CHILD-only CPU / RAM / FD)
# --------------------------------------------------------------------------
def stage_resource_pressure(repo):
    sys.path.insert(0, repo)
    from drive_tool.http_adapter import DriveHTTPAdapter
    base = tempfile.mkdtemp(prefix="d110-res-")
    adapter = None
    problems = []
    sub = {}
    cpu_procs = []
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        adapter = DriveHTTPAdapter(policies, port=0, socket_timeout=10.0)
        time.sleep(0.1)
        token = _TOKENS[0]

        # ---- R1: CPU saturation by 4 low-priority children ----
        for _ in range(4):
            cpu_procs.append(_spawn_child(repo, {"role": "cpu_child"}))
        time.sleep(0.2)
        ok = 0
        err = []
        for i in range(200):
            try:
                _client(adapter.port, token).list("main", limit=20)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                err.append(_classify_client_error(exc) or type(exc).__name__)
        sub["cpu"] = {"calls_ok": ok, "errors": err[:5]}
        if err:
            problems.append("R1: %d errors under CPU saturation" % len(err))
        if ok != 200:
            problems.append("R1: only %d/200 calls succeeded" % ok)
        for p in cpu_procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
        for p in cpu_procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

        # ---- R2: child RAM pressure (RLIMIT_AS) ----
        mem_before = _mem_available_kb()
        if mem_before is not None and mem_before < MEM_AVAILABLE_PREFLIGHT_KB:
            sub["ram"] = {"skipped": "host MemAvailable below preflight floor",
                          "mem_before_kb": mem_before}
            problems.append("R2 skipped: host MemAvailable too low")
        else:
            ram = _read_child_json(_spawn_child(repo, {
                "role": "ram_child", "root": roots["main"], "alias": "main",
                "token": token, "as_mib": 384}), timeout=90)
            mem_after = _mem_available_kb()
            sub["ram"] = {"result": ram, "mem_before_kb": mem_before,
                          "mem_after_kb": mem_after}
            if ram.get("child_error"):
                problems.append("R2: ram child failed: %r" % ram)
            else:
                if not ram.get("ops_ok"):
                    problems.append("R2: reads/saves failed under RAM pressure")
                if mem_after is not None and mem_after < MEM_AVAILABLE_FLOOR_KB:
                    problems.append("R2: host MemAvailable %d < floor %d"
                                    % (mem_after, MEM_AVAILABLE_FLOOR_KB))

        # ---- R3: child FD exhaustion (RLIMIT_NOFILE) ----
        fd = _read_child_json(_spawn_child(repo, {
            "role": "fd_child", "root": roots["main"], "alias": "main",
            "token": token}), timeout=90)
        sub["fd"] = fd
        if fd.get("child_error"):
            problems.append("R3: fd child failed: %r" % fd)
        else:
            if not fd.get("emfile_forced"):
                problems.append("R3: EMFILE was NOT forced (inconclusive, not a pass)")
            if fd.get("unhandled"):
                problems.append("R3: unhandled error under EMFILE: %r" % fd["unhandled"])
            if not fd.get("recovered"):
                problems.append("R3: no recovery after restoring RLIMIT_NOFILE")

        closed = adapter.close(timeout=10.0)
        if not closed:
            problems.append("adapter.close() did not return True")
        return {"stage": "resource_pressure",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems, "sub": sub}
    finally:
        for p in cpu_procs:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except OSError:
                pass
        if adapter is not None:
            try:
                adapter.close(timeout=5.0)
            except BaseException:
                pass
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# STAGE: enospc  (injected ENOSPC at save phases + child RLIMIT_FSIZE)
# --------------------------------------------------------------------------
def stage_enospc(repo):
    sys.path.insert(0, repo)
    from drive_tool.file_service import LocalFileService
    from drive_tool.local_write import LocalWriter
    base = tempfile.mkdtemp(prefix="d110-enospc-")
    problems = []
    phases = {}
    try:
        roots = build_fixtures(base)
        policies = build_policies(roots)
        token = _TOKENS[0]
        target_rel = "savepool/existing.bin"
        existing = os.path.join(roots["main"], target_rel)
        _write(existing, b"E" * 4096)
        existing_sha = _sha256(open(existing, "rb").read())

        def fresh_service():
            return LocalFileService(policies)

        def inject(phase):
            """Return (patch_ctx, restore_fn) that raises ENOSPC at ``phase``."""
            originals = {}

            def enospc(*a, **k):
                raise OSError(errno.ENOSPC, "No space left on device")

            if phase == "temp_create":
                originals["_create_temp_file"] = LocalWriter._create_temp_file
                LocalWriter._create_temp_file = enospc
            elif phase == "mid_write":
                originals["_write_all"] = LocalWriter._write_all
                LocalWriter._write_all = enospc
            elif phase == "fsync":
                originals["_os_fsync"] = LocalWriter._os_fsync
                LocalWriter._os_fsync = enospc
            elif phase == "publish":
                originals["_os_rename"] = LocalWriter._os_rename
                LocalWriter._os_rename = enospc
                originals["_os_link"] = LocalWriter._os_link
                LocalWriter._os_link = enospc

            def restore():
                for k, v in originals.items():
                    setattr(LocalWriter, k, v)
            return restore

        for phase in ("temp_create", "mid_write", "fsync", "publish"):
            restore = inject(phase)
            svc = fresh_service()
            fd0 = _nfd()
            result = {}
            try:
                try:
                    svc.save(token, "main", "p/" + target_rel, b"N" * 2048,
                             overwrite=True)
                    result["unexpected_success"] = True
                except Exception as exc:  # noqa: BLE001
                    info = _classify_client_error(exc)
                    if info is None:
                        from drive_tool.file_service import ServiceError
                        if isinstance(exc, ServiceError):
                            info = {"code": exc.code,
                                    "outcome_uncertain": exc.outcome_uncertain,
                                    "retry_safe": exc.retry_safe}
                        else:
                            result["unhandled"] = type(exc).__name__
                    result["error"] = info
                # overwrite target preserved
                result["target_preserved"] = (
                    os.path.exists(existing)
                    and _sha256(open(existing, "rb").read()) == existing_sha)
                # no partial publish (overwrite=False case)
                try:
                    svc.save(token, "main", "p/savepool/new_%s.bin" % phase,
                             b"N" * 2048, overwrite=False)
                except Exception:  # noqa: BLE001
                    pass
                result["no_partial_new"] = not os.path.exists(
                    os.path.join(roots["main"], "savepool", "new_%s.bin" % phase))
                # temp leak?
                result["temp_leaks"] = _count_temp(roots)
                fd1 = _nfd()
                result["fd_delta"] = (None if (fd0 is None or fd1 is None)
                                      else fd1 - fd0)
            finally:
                restore()
                try:
                    svc.close(timeout=5.0)
                except BaseException:
                    pass
            phases[phase] = result
            if result.get("unexpected_success"):
                problems.append("%s: ENOSPC write reported success" % phase)
            if result.get("unhandled"):
                problems.append("%s: unhandled %s" % (phase, result["unhandled"]))
            info = result.get("error") or {}
            if info.get("code") != "unavailable":
                problems.append("%s: error code %r (expected 'unavailable')"
                                % (phase, info.get("code")))
            # safety: a write-in-flight failure must never claim retry_safe
            if info.get("retry_safe") is True and info.get("outcome_uncertain") is False:
                problems.append("%s: claims retry_safe on an uncertain write" % phase)
            if not result.get("target_preserved"):
                problems.append("%s: overwrite target NOT preserved" % phase)
            if not result.get("no_partial_new"):
                problems.append("%s: partial new file published" % phase)
            if result.get("temp_leaks"):
                problems.append("%s: temp leak %s" % (phase, result["temp_leaks"]))
            if result.get("fd_delta"):
                problems.append("%s: fd leak +%s" % (phase, result["fd_delta"]))

        # Recovery: after removing the fault, a normal save/read/list works.
        svc = fresh_service()
        try:
            svc.save(token, "main", "p/savepool/recovered.bin", b"R" * 16,
                     overwrite=True)
            got = svc.read(token, "main", "p/savepool/recovered.bin",
                           offset=0, length=16)
            phases["recovery"] = {"ok": getattr(got, "data", None) == b"R" * 16}
            if not phases["recovery"]["ok"]:
                problems.append("ENOSPC recovery read mismatch")
        except Exception as exc:  # noqa: BLE001
            phases["recovery"] = {"error": type(exc).__name__}
            problems.append("ENOSPC recovery failed: %s" % type(exc).__name__)
        finally:
            try:
                svc.close(timeout=5.0)
            except BaseException:
                pass

        # Real child RLIMIT_FSIZE -> kernel EFBIG mid-write
        rl = _read_child_json(_spawn_child(repo, {
            "role": "enospc_rlimit", "root": roots["main"], "alias": "main",
            "token": token, "fsize": 8192, "size": 32768}), timeout=60)
        phases["rlimit_fsize"] = rl
        if rl.get("child_error"):
            problems.append("RLIMIT_FSIZE child failed: %r" % rl)
        else:
            if rl.get("unexpected_success"):
                problems.append("RLIMIT_FSIZE: oversized write reported success")
            if rl.get("code") != "unavailable":
                problems.append("RLIMIT_FSIZE: code %r (expected 'unavailable')"
                                % rl.get("code"))
            if not rl.get("target_preserved"):
                problems.append("RLIMIT_FSIZE: overwrite target not preserved")
            if rl.get("temp_leaks"):
                problems.append("RLIMIT_FSIZE: temp leak %s" % rl["temp_leaks"])

        return {"stage": "enospc",
                "result": "PASS" if not problems else "FAIL",
                "problems": problems, "phases": phases}
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --------------------------------------------------------------------------
# CHILD ROLES
# --------------------------------------------------------------------------
def _emit(obj):
    sys.stdout.write("CHILD_JSON:" + json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def child_main(spec):
    role = spec["role"]
    repo = spec.get("repo") or os.environ.get("PYTHONPATH")
    sys.path.insert(0, repo)

    if role == "crash_worker":
        _child_crash_worker(spec)
    elif role == "crash_storm":
        _child_crash_storm(spec)
    elif role == "recover_probe":
        _child_recover_probe(spec)
    elif role == "enospc_rlimit":
        _child_enospc_rlimit(spec)
    elif role == "fd_child":
        _child_fd(spec)
    elif role == "ram_child":
        _child_ram(spec)
    elif role == "cpu_child":
        _child_cpu(spec)
    else:
        _emit({"child_error": True, "reason": "unknown role %r" % role})


def _build_single_service(root, alias, token):
    import hashlib as _h
    from drive_tool.service_policy import AgentPolicy, SourceGrant
    from drive_tool.file_service import LocalFileService
    grant = SourceGrant(alias=alias, root=os.path.realpath(root),
                        operations=frozenset(("list", "find", "read", "save")),
                        max_read_bytes=1048576, max_write_bytes=1048576)
    pol = AgentPolicy(agent_id="child", token_sha256=_h.sha256(token.encode()).digest(),
                      grants=(grant,))
    return LocalFileService((pol,))


def _child_crash_worker(spec):
    from drive_tool.local_write import LocalWriter
    sig_fd = spec["sig_fd"]
    blk_fd = spec["blk_fd"]
    payload = bytes.fromhex(spec["payload_hex"])
    mode = spec["mode"]

    def signal_and_block():
        try:
            os.write(sig_fd, b"R")
        except OSError:
            pass
        # block until the parent SIGKILLs this process group
        try:
            os.read(blk_fd, 1)
        except OSError:
            pass
        time.sleep(3600)

    if mode == "mid_write":
        orig = LocalWriter._os_write

        def patched(self, fd, data):
            n = orig(self, fd, bytes(data[: max(1, len(data) // 2)]))
            signal_and_block()
            return n
        LocalWriter._os_write = patched
    else:  # pre_publish
        orig = LocalWriter._os_rename

        def patched(self, *a, **k):
            signal_and_block()
            return orig(self, *a, **k)
        LocalWriter._os_rename = patched

    svc = _build_single_service(spec["root"], spec["alias"], spec["token"])
    try:
        svc.save(spec["token"], spec["alias"],
                 "p/%s/%s" % (spec["parent"], spec["name"]), payload,
                 overwrite=True)
    finally:
        try:
            svc.close(timeout=2.0)
        except BaseException:
            pass
    _emit({"child_error": True, "reason": "worker returned without being killed"})


def _child_crash_storm(spec):
    root = spec["root"]
    alias = spec["alias"]
    token = spec["token"]
    parent = spec["parent"]
    nfiles = spec["files"]
    worker = spec["worker"]
    svc = _build_single_service(root, alias, token)
    i = 0
    try:
        while True:
            body = ("w%d-%d-" % (worker, i)).encode() * 64
            head = hashlib.sha256(body).hexdigest()[:32].encode("ascii")
            data = head + body
            name = "p/%s/s%02d.bin" % (parent, (worker + i) % nfiles)
            try:
                svc.save(token, alias, name, data, overwrite=True)
            except Exception:  # noqa: BLE001
                pass
            i += 1
    finally:
        try:
            svc.close(timeout=1.0)
        except BaseException:
            pass


def _child_recover_probe(spec):
    root = spec["root"]
    alias = spec["alias"]
    token = spec["token"]
    out = {"on_disk_temps": 0, "temp_in_list": False, "temp_in_find": False}
    svc = _build_single_service(root, alias, token)
    try:
        try:
            lst = svc.list(token, alias, "root", limit=100)
            out["list_ok"] = True
            names = [it.get("name") for it in lst.get("items", [])]
            out["temp_in_list"] = any(n and n.startswith(TEMP_PREFIX) for n in names)
        except Exception as exc:  # noqa: BLE001
            out["list_ok"] = False
            out["list_err"] = type(exc).__name__
        try:
            fnd = svc.find(token, alias, "root", name_contains="tmp",
                           limit=100, max_entries=500, max_depth=4)
            out["find_ok"] = True
            fnames = [it.get("name") for it in fnd.get("items", [])]
            out["temp_in_find"] = any(n and n.startswith(TEMP_PREFIX) for n in fnames)
        except Exception as exc:  # noqa: BLE001
            out["find_ok"] = False
            out["find_err"] = type(exc).__name__
        try:
            svc.save(token, alias, "p/savepool/probe_recover.bin", b"ok" * 4,
                     overwrite=True)
            out["save_ok"] = True
        except Exception as exc:  # noqa: BLE001
            out["save_ok"] = False
            out["save_err"] = type(exc).__name__
        try:
            r = svc.read(token, alias, "p/savepool/probe_recover.bin",
                         offset=0, length=8)
            out["read_ok"] = getattr(r, "data", None) == b"ok" * 4
        except Exception as exc:  # noqa: BLE001
            out["read_ok"] = False
            out["read_err"] = type(exc).__name__
    finally:
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
    # count on-disk temps
    n = 0
    for dp, dn, fn in os.walk(root):
        for name in fn:
            if name.startswith(TEMP_PREFIX):
                n += 1
    out["on_disk_temps"] = n
    _emit(out)


def _child_enospc_rlimit(spec):
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    fsize = int(spec["fsize"])
    size = int(spec["size"])
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    root = spec["root"]
    alias = spec["alias"]
    token = spec["token"]
    existing = os.path.join(root, "savepool", "existing.bin")
    if os.path.exists(existing):
        sha_before = hashlib.sha256(open(existing, "rb").read()).hexdigest()
    else:
        sha_before = None
    out = {}
    svc = _build_single_service(root, alias, token)
    try:
        try:
            svc.save(token, alias, "p/savepool/existing.bin", b"X" * size,
                     overwrite=True)
            out["unexpected_success"] = True
        except Exception as exc:  # noqa: BLE001
            from drive_tool.file_service import ServiceError
            if isinstance(exc, ServiceError):
                out["code"] = exc.code
                out["outcome_uncertain"] = exc.outcome_uncertain
                out["retry_safe"] = exc.retry_safe
            else:
                out["unhandled"] = type(exc).__name__
        out["target_preserved"] = (
            sha_before is not None and os.path.exists(existing)
            and hashlib.sha256(open(existing, "rb").read()).hexdigest() == sha_before)
        n = 0
        for dp, dn, fn in os.walk(root):
            for name in fn:
                if name.startswith(TEMP_PREFIX):
                    n += 1
        out["temp_leaks"] = n
    finally:
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
    _emit(out)


def _child_fd(spec):
    root = spec["root"]
    alias = spec["alias"]
    token = spec["token"]
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    cur = _nfd()
    out = {"nofile_soft_before": soft, "nofile_hard": hard, "nfd_before": cur}
    svc = _build_single_service(root, alias, token)
    from drive_tool.file_service import ServiceError
    fillers = []
    unhandled = []
    mapped = 0
    try:
        # lower the soft limit close to the current fd count, then EXHAUST the
        # remaining descriptors so os.open/os.scandir really return EMFILE.
        target = min(soft, (cur or 16) + 8)
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
            out["nofile_soft_lowered"] = target
        except (OSError, ValueError) as exc:
            out["lower_error"] = type(exc).__name__
        while True:
            try:
                fillers.append(os.open("/dev/null", os.O_RDONLY))
            except OSError:
                break
        out["fillers"] = len(fillers)
        for i in range(30):
            for op in ("list", "find", "read", "save"):
                try:
                    if op == "list":
                        svc.list(token, alias, "root", limit=20)
                    elif op == "find":
                        svc.find(token, alias, "root", name_contains="a",
                                 limit=20, max_entries=200, max_depth=3)
                    elif op == "read":
                        svc.read(token, alias, "p/readme.txt", offset=0, length=32)
                    else:
                        svc.save(token, alias, "p/savepool/fd%d.bin" % i,
                                 b"f" * 8, overwrite=True)
                except ServiceError:
                    mapped += 1
                except Exception as exc:  # noqa: BLE001
                    unhandled.append(type(exc).__name__)
        out["mapped_service_errors"] = mapped
        out["unhandled"] = unhandled[:8]
        out["emfile_forced"] = mapped > 0
    finally:
        for fd in fillers:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
        except (OSError, ValueError):
            pass
        try:
            svc.list(token, alias, "root", limit=20)
            svc.save(token, alias, "p/savepool/fd_recover.bin", b"r" * 8,
                     overwrite=True)
            out["recovered"] = True
        except Exception as exc:  # noqa: BLE001
            out["recovered"] = False
            out["recover_err"] = type(exc).__name__
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
    out["nfd_after"] = _nfd()
    _emit(out)


def _child_ram(spec):
    as_mib = int(spec["as_mib"])
    try:
        with open("/proc/self/oom_score_adj", "w") as fh:
            fh.write("1000\n")
    except OSError:
        pass
    limit = as_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    root = spec["root"]
    alias = spec["alias"]
    token = spec["token"]
    out = {"as_mib": as_mib}
    svc = _build_single_service(root, alias, token)
    ballast = None
    try:
        # hold a bounded ballast within the limit
        ballast = bytearray(128 * 1024 * 1024)
        for i in range(0, len(ballast), 4096):
            ballast[i] = 1
        ok = 0
        for i in range(200):
            try:
                svc.read(token, alias, "p/readme.txt", offset=0, length=32)
                svc.save(token, alias, "p/savepool/ram%d.bin" % (i % 16),
                         b"m" * 256, overwrite=True)
                ok += 1
            except Exception:  # noqa: BLE001
                break
        out["ops_ok"] = ok > 0
        out["ops"] = ok
        # intentional MemoryError boundary
        try:
            _ = bytearray(400 * 1024 * 1024)
            out["memoryerror_raised"] = False
        except MemoryError:
            out["memoryerror_raised"] = True
        del ballast
        ballast = None
        # subsequent normal ops must succeed
        svc.save(token, alias, "p/savepool/ram_after.bin", b"a" * 64, overwrite=True)
        r = svc.read(token, alias, "p/savepool/ram_after.bin", offset=0, length=64)
        out["post_ok"] = getattr(r, "data", None) == b"a" * 64
    finally:
        try:
            svc.close(timeout=5.0)
        except BaseException:
            pass
    out["rss_kb"] = _rss_kb()
    _emit(out)


def _child_cpu(spec):
    try:
        os.nice(15)
    except OSError:
        pass
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    except (OSError, ValueError):
        pass
    import hashlib
    h = b"seed"
    end = time.time() + 120
    while time.time() < end:
        h = hashlib.pbkdf2_hmac("sha256", h, b"salt", 2000)
    _emit({"child": "cpu", "done": True})


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def _run_guarded(fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
    except TimeoutError:
        return {"result": "TIMEOUT", "problems": ["stage timed out"]}
    except BaseException as exc:  # noqa: BLE001
        import traceback
        return {"result": "ERROR",
                "problems": ["stage raised %s" % type(exc).__name__],
                "traceback": traceback.format_exc()[-800:]}
    if not isinstance(res, dict):
        return {"result": "ERROR", "problems": ["stage returned non-dict"]}
    return res


def _aggregate(stages):
    problems = []
    for name in REQUIRED_STAGES:
        res = stages.get(name)
        if res is None:
            problems.append("%s: not executed (skipped/missing)" % name)
            continue
        status = res.get("result")
        if status != "PASS":
            problems.append("%s: %s" % (name, "MISSING" if status is None else status))
    return (not problems), problems


_STAGE_FUNCS = {
    "selfcheck": stage_selfcheck,
    "readdir_order": stage_readdir_order,
    "http_hostile": stage_http_hostile,
    "admission": stage_admission,
    "isolation": stage_isolation,
    "concurrency": stage_concurrency,
    "crash_kill": stage_crash_kill,
    "resource_pressure": stage_resource_pressure,
    "enospc": stage_enospc,
}


def run_gate(repo):
    stages = {name: None for name in REQUIRED_STAGES}
    for name in REQUIRED_STAGES:
        fn = _STAGE_FUNCS[name]
        _log("[d110] stage %s ..." % name)
        stages[name] = _run_guarded(fn, repo)
        _log("[d110] stage %s -> %s" % (name, stages[name].get("result")))
    ok, problems = _aggregate(stages)
    return {"harness": "d110-harsh-target-gate",
            "stage": "gate",
            "required_stages": list(REQUIRED_STAGES),
            "executed": [n for n in REQUIRED_STAGES if stages[n] is not None],
            "result": "PASS" if ok else "FAIL",
            "problems": problems,
            "stages": stages}


def main(argv=None):
    ap = argparse.ArgumentParser(description="d110 harsh target gate payload")
    ap.add_argument("--repo", help="path to the drive-tool checkout")
    ap.add_argument("--stage", choices=tuple(_STAGE_FUNCS))
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--selfcheck", action="store_true")
    ap.add_argument("--child-spec", help="internal: run one child role (JSON)")
    ap.add_argument("--json", help="write the result JSON to this path")
    args = ap.parse_args(argv)

    if args.child_spec:
        spec = json.loads(args.child_spec)
        spec["repo"] = args.repo
        child_main(spec)
        return 0

    if args.selfcheck:
        out = _run_guarded(stage_selfcheck, args.repo or ".")
    elif args.gate:
        if not args.repo:
            ap.error("--repo is required for --gate")
        out = run_gate(args.repo)
    elif args.stage:
        if args.stage != "selfcheck" and not args.repo:
            ap.error("--repo is required for stage %s" % args.stage)
        out = _run_guarded(_STAGE_FUNCS[args.stage], args.repo or ".")
    else:
        ap.error("choose --gate, --stage or --selfcheck")

    text = json.dumps(out, indent=2, sort_keys=True, default=str)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0 if out.get("result") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

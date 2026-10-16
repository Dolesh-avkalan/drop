#!/usr/bin/env python3
"""Build the D097 corrected harness from the verified D096/D095 r1 harness.

Only the Track-B saturation function is replaced, with a REAL service-entry
barrier that removes the timing race.  Everything else (schedules, accounting,
smoke/soak tracks, adversarial track, gating helper, selfcheck) is unchanged.
"""
import hashlib
import re

SRC = "/scratch/work/d097/scripts/http_gate_r1.py"
DST = "/scratch/work/d097/scripts/http_gate_d097.py"

with open(SRC, "r", encoding="utf-8") as fh:
    text = fh.read()

start_marker = "def run_saturation(repo, cycles=SAT_CYCLES, budget=STAGE_BUDGET_SECONDS):"
end_marker = "# --------------------------------------------------------------------------\n# Adversarial protocol track"

i = text.index(start_marker)
j = text.index(end_marker)
head = text[:i]
tail = text[j:]

NEW = '''# --------------------------------------------------------------------------
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


'''

out = head + NEW + tail
with open(DST, "w", encoding="utf-8") as fh:
    fh.write(out)

print("wrote", DST)
print("bytes", len(out))
print("sha256", hashlib.sha256(out.encode()).hexdigest())

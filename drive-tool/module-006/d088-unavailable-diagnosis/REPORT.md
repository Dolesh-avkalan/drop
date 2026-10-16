# D088 — bounded diagnosis of the unexpected HTTP `unavailable` responses

**Task:** D088. Diagnose only — no source or test change, no gate relabelling, no new
acceptance criteria. Exact head `7dab4357`, source blob `8cd137f7`.

## 1. Headline finding

The `unavailable` responses seen in the D085 gate workload are **not structured 503
envelopes from the service or the adapter**. They are **client-side transport fallbacks
(`http.client.RemoteDisconnected`) on the admission-busy rejection path**.

The adapter's own error-emission seam (`_safe_send_error`) emitted **only** `403 denied` in
every 1200-call diagnostic run — never `unavailable`. In the same runs the identity

```
server _busy_reject count  ==  client "busy"  +  client "unavailable"
```

held exactly, on both interpreters (e.g. 3.12: `39 == 37 + 2`; 3.11: `31 == 30 + 1`). So
each client `unavailable` is a busy rejection whose 503 envelope the client failed to read,
not a distinct server error.

## 2. Why the gate counters could not see this

`DriveClientError` exposes only `(code, outcome_uncertain, retry_safe)`. In
`drive_tool/service_client.py`, both

- `_parse_error_envelope`'s fallback (unparseable / non-envelope reply), and
- `_wrap_transport` (a socket / HTTP-layer exception)

construct `DriveClientError("unavailable", outcome_uncertain=write_op, retry_safe=not write_op)`
— **identical flags**. A structured 503 `unavailable` from the adapter carries the same
flags too. The gate counter therefore cannot distinguish the three sources, which is exactly
why the 6–7 `unavailable` in the 10,000-call soak looked unexplained.

## 3. Evidence (`logs/combined_1200_*.txt`, `logs/client_seam_*.txt`)

Single-run, same-process instrumentation of the adapter's admission seam (`_busy_reject`),
the adapter's error seam (`_safe_send_error`), and the client's `_wrap_transport` and
`_parse_error_envelope`:

| Run | client codes | server emissions | `_busy_reject` | `_wrap_transport` | envelope fallback | identity |
| --- | --- | --- | --- | --- | --- | --- |
| 3.12 combined | ok 1125, denied 39, busy 35, **unavailable 1** | `403 denied` × 39 only | 36 | `RemoteDisconnected` × 1 | none | `36 == 35 + 1` ✔ |
| 3.11 combined | ok 1130, denied 39, busy 30, **unavailable 1** | `403 denied` × 39 only | 31 | `RemoteDisconnected` × 1 | none | `31 == 30 + 1` ✔ |
| 3.12 combined (earlier) | ok 1123, denied 38, busy 37, **unavailable 2** | `403 denied` × 38 only | 39 | `RemoteDisconnected` × 2 | none | `39 == 37 + 2` ✔ |
| 3.12 server-emissions | ok 1120, denied 39, busy 41 | `403 denied` × 39 only | 41 | — | — | `41 == 41 + 0` ✔ |
| 3.11 server-emissions | ok 1127, denied 37, busy 34, **unavailable 2** | `403 denied` × 37 only | 36 | — | — | `36 == 34 + 2` ✔ |

**Separation, as requested:**

- **Structured 503 `unavailable`**: zero emitted by the adapter in any bounded run.
- **Transport reset / malformed-reply fallback**: every observed `unavailable` is a
  transport `RemoteDisconnected`; the unparseable-envelope fallback fired **zero** times.
- **Teardown**: the small teardown probe (`logs/teardown_unavailable_3.12.txt`) shows that
  closing the adapter *while calls are in flight* does produce a genuine structured 503
  `unavailable` (3 emissions → 3 client `unavailable`, flags `uncertain=False, retry=True`).
  That path is real but **not the source in the gate runs**, because `_run_workload` closes
  only after every worker has joined and all 10,000 calls have already completed.
- **Admission-busy artifacts**: exactly account for the client-side `unavailable`, per the
  identity above.

Per-call detail is recorded in `logs/detail_raw_1200_3.12.txt` (raw-socket mode) and
`logs/detail_client_1200_3.12.txt` with `agent` (agent0..agent5), source alias, op, call id,
expected grant, body length, status, code, uncertainty and retry flags. Token strings are
never printed; agents appear only as `agentN`.

## 4. Actual disk state after the saves

`savepool` file counts after each 1200-call run: `main 16, other 16, small 16, alias_a 16,
alias_b 16, ro 0` → **80 files**. The read-only source has zero files because its agent
holds no write grant. No partial or leaked writes, and no cross-source bleed.

## 5. Two generator issues flagged for adjudication (not relabelled here)

1. **Read-only `denied` is EXPECTED but counted as a failure.** One of the six soak agents
   is the read-only token; its `save` calls are legitimately 403 denied (≈20% of its calls,
   39 per 1200). The gate's "no unrecognized errors" threshold counts that as a failure.
2. **`busy` reflects response-before-slot-free timing.** The gate drives client concurrency
   equal to the six worker slots, so a response that completes before the worker's
   post-response drain frees its slot makes the next arrival a genuine seventh in-flight
   operation and the adapter correctly answers 503 busy (probe: concurrency 4 → 0 busy,
   5 → 0, 6 → 32).

Both are **Gemini D089 gate-adjudication topics**. Nothing was relabelled: the D085 smoke and
soak results remain **FAIL** in `drop/drive-tool/module-006/d085-contract-tests/`, and the
10,000-call soak re-run is a **diagnostic, not a gated pass**.

## 6. Lifecycle / cleanup

`threads: before=1, live=8, after_close=1` on both interpreters — the seven adapter threads
(six workers plus the accept thread) are created and fully reaped, matching
`expected_adapter_threads = 7`. Every bounded run reports `closed=True`, fd `11 → 4`, and RSS
that does not grow.

## 7. Method and budget, stated plainly

Each diagnostic run was bounded at 1200 calls as instructed, mirroring the gate's agent mix,
op mix (index % 10) and concurrency, on both 3.11.2 and 3.12.13. The target event is rare
(≈0.1% of calls), so several bounded runs were needed to catch it: **ten 1200-call runs
(12,000 diagnostic calls in total)**, plus two lifecycle censuses and one three-call teardown
probe. No full soak was executed, and no source or test file was modified — every probe is
runtime-only instrumentation.

## 8. Scope

No fixes, no merge, no deploy, no real roots, no acceptance change. **Gemini D089 designs the
gate correction; DeepSeek implements it after that decision.**

# D091 — close-budget patch assembly and regression

**Task:** D091. From exact base `7dab4357`, apply the DeepSeek D087 diff on a NEW branch,
translate its example regression to the existing unittest harness, prove oldfail/newpass with
actual timing, run the full suite on 3.11/3.12, and show a compile-clean semantic revert.
**No auth, gate or other semantics changed.**

## 1. Source identity

- base `7dab4357ca9a79a6c857ab78bea55805dfa1de89` (tree `26eff85fa3b9945619157632e65d594c41653aac`)
- branch `feature/module-006b-http-close-budget`, head `b962a04df1c5abdb78c37617d3a6adca02d04024`,
  tree `ebcee4f5d1108b678d137da23916ecc8cd9a1999`
- `drive_tool/http_adapter.py` blob `8cd137f7…` → `a28970e29f7aa52373026f2e539206b2de784ccf`
  (40119 bytes, sha256 `9706fdbc9e48fe35e3777116f536a462368ae87080c47934a534fd0d93cdd0ec`)
- `tests/test_http_adapter.py` blob `5419096c…` → `8130d56f4ca04305ec2e9a38ff59c892c6a659b0`
  (70229 bytes, sha256 `88c1e558e093d3017056b0e592b778406ce23043fb2a7a5c090312d560b17e78`)
- **strict two-file scope**; fetched the published branch back, `cmp`-confirmed byte identity,
  and re-ran everything from those bytes.
- patch source: `drop` `ea5b10428c461536b2c9300211d016ee11f63fa7`,
  `drive-tool/module-006/d087-close-lock-budget.md`.

## 2. Patch assembly

The D087 source diff is a context-free diff (bare `@@`), so the single unambiguous hunk was
reconstructed from its anchor text and replaced with the D087 target `close()` body verbatim.
The change is minimal — **12 insertions, 3 deletions** (`logs/patch.diff`): the `try:` body sits
at the same indent as the old `with self._close_lock:`, so no interior line moved.

`close()` now computes `deadline = time.monotonic() + timeout_f`, takes
`self._close_lock.acquire(timeout=remaining)` (non-blocking when the budget is already spent),
returns `False` immediately if it cannot acquire, and releases the lock in a `finally`. A
contended caller therefore honours its **own** budget instead of blocking unboundedly behind a
long first close. Nothing else changed — the once-only listener wake/close, the pending
`slot.conn` handoff closure, and the descriptor-ownership behaviour are all preserved.

## 3. Harness translation

The D087 example was a pytest module building a bare adapter via `__new__`. It is translated
into `CloseBudgetTests` in `tests/test_http_adapter.py` (no pytest, no installs), keeping the
bare-adapter technique and the original assertions, and adding the D091 properties:
descriptor safety, once-only lock release, idempotency, and a no-thread-leak check.

## 4. oldfail / newpass with actual timing

| Run | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| `CloseBudgetTests` vs the pre-patch adapter | FAILED (failures=3), exit 1, **15.01 s** | FAILED (failures=3), exit 1, **15.01 s** |
| `CloseBudgetTests` vs the patched branch | Ran 3, OK, exit 0, **0.16–0.18 s** | Ran 3, OK, exit 0 |

The pre-patch failures are all `AssertionError: True is not False` — the contended close
returned `True` after blocking. The timing probe (`scripts/probe_close_budget_timing.py`,
`logs/timing_*.txt`) states it directly:

```
patched:   contended close(timeout=0.05) -> False in 0.0511s   VERDICT: PASS
pre-patch: contended close(timeout=0.05) -> True  in 5.0007s   VERDICT: FAIL
```

0.0511 s is inside the budget of 0.05 s plus the documented 0.10 s scheduler margin; the
pre-patch figure is the first close's own 5 s service lease, i.e. an unbounded wait. In both
cases `service.close` was called exactly once during the contention, the first close
eventually returned `True`, `adapter._closed` became `True`, and a follow-up
`close(timeout=0.1)` returned `True` — so the fix bounds the wait without changing the
eventual outcome.

**Descriptor safety.** The winner closes the pending handoff *before* it parks in the service
lease (asserted: `slot.conn is None` and `fileno() == -1`); the contended caller, which never
enters the critical section, closes nothing — the `/proc/self/fd` census is unchanged across
its call and a control socketpair stays usable.

## 5. Full suite

| Suite | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| base `7dab4357` | `Ran 573 … OK (skipped=3)`, exit 0 | same, exit 0 |
| patched branch | `Ran 576 … OK (skipped=3)`, exit 0 | same, exit 0 |
| patched branch, fetched bytes | `OK (skipped=3)`, exit 0 | same, exit 0 |

The patch adds 3 passing tests and breaks nothing. The 3 skips are the documented opt-in /
control ones (the adapter-present gate-contract test and the two `D067_RUN_HTTP_SMOKE_SOAK=1`
opt-ins); there are zero adapter-missing skips.

## 6. Semantic-revert guard (compile-clean)

`logs/semantic_revert_guard.txt`: restoring the pre-patch `http_adapter.py`
(sha256 back to `1e185615…`) leaves **both** interpreters compiling clean, and the new
`CloseBudgetTests` then fails (3 failures in 15.03 s) — so the guard is genuinely sensitive to
the semantic change and the revert is clean. Re-applying the patch restores sha256 `9706fdbc…`
and compiles clean.

## 7. Lifecycle

`threads: before=1, live=8, after_close=1` on both interpreters — the seven adapter threads are
created and fully reaped; every run reports `closed=True` and fd `11 → 4`. No leaks.

## 8. Scope and gates

Two files only; no auth, gate or other semantics changed; no fix beyond the D087 patch and the
harness translation. No merge, no deploy, no real roots. **No acceptance stress rerun** — the
smoke/soak remain as reported in D085/D088, and the busy/transport adjudication is pending
**Gemini D092**. **Gemini's final delta review is still required.**

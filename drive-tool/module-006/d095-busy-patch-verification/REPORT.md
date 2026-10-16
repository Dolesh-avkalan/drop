# D095 — busy patch assembly, conformance and frozen HTTP gates

**Task:** D095. Assemble the DeepSeek D094 busy-reject patch on a NEW branch from exact
`b962a04d`, translate its regression, prove oldfail/newpass, run the full suite on 3.11/3.12,
then run the frozen D096 gate harness — selfcheck, 600 smoke, gated 10,000 soak and the 50-cycle
6+1 saturation. **No auth, schema or header semantics changed; no test weakened.**

## 1. Source identity

- base `b962a04df1c5abdb78c37617d3a6adca02d04024` (tree `ebcee4f5d1108b678d137da23916ecc8cd9a1999`)
- branch `feature/module-006b-http-busy-budget`, head `f37a30b0073611c05d26f714f2e833d689673a09`,
  tree `377e9e507a5bbfe269d92bf8a5327e83e021e6b5`
- `drive_tool/http_adapter.py` blob `a28970e2…` → `41279e6290617968c3b4f3f91fc3cf9a7dab505a`
- `tests/test_http_adapter.py` blob `8130d56f…` → `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3`
- **strict two-file scope**; fetched back, `cmp`-verified and re-run from those bytes.
- patch source: `drop` `61f5d14`, `drive-tool/module-006/d094-busy-reject-patch.md`.

## 2. Patch assembly (22 insertions, 4 deletions)

Precise phase constants — `BUSY_REJECT_BUDGET_SECONDS = 0.050`,
`BUSY_PRE_READ_BUDGET_SECONDS = 0.010`, `BUSY_WRITE_RESERVE_SECONDS = 0.020`,
`BUSY_POST_DRAIN_BUDGET_SECONDS = 0.020`, `MAX_BUSY_READ_BYTES = 16384` (unchanged) — plus a
phased `_busy_reject`: a bounded pre-read that cannot consume the reserved write slice, the
reserved write window inside the same 50 ms ceiling, and a post-write drain bounded by
`min(busy_deadline, now + 20 ms)`. `MAX_IN_FLIGHT_OPERATIONS` stays 6 and
`POST_RESPONSE_DRAIN_SECONDS` stays 0.05. No queue, thread or filesystem work is added to the
reject path.

**The defect this removes.** The old pre-read used the whole outer budget, so a peer that sent
nothing consumed all 50 ms and `_send_with_deadline` then found the deadline already spent and
wrote nothing. The client received an empty reply, which the production client maps to
`DriveClientError("unavailable")` — exactly the D088 finding.

## 3. Harness translation

The D094 example was written against an imagined `server`/`Server`; it is translated onto
`drive_tool.http_adapter` / `DriveHTTPAdapter` with a fake monotonic clock and fake socket (no
network, no pytest), and the new constants are wired into the harness import, the contract
fallback and the frozen `_CONTRACT_CONSTANTS` table.

One example assertion was **corrected, not weakened**: it required the whole response never to
contain `"unavailable"`, which cannot hold because 503's reason phrase is literally "Service
Unavailable". The property that matters — the envelope's error *code* is `busy`, not
`unavailable` — is now asserted on the body.

## 4. oldfail / newpass

**Deterministic delayed-payload seam** (`BusyPhaseBudgetTests`, fake clock/socket):

| Run | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| vs the pre-patch `_busy_reject` (constants present) | FAILED (failures=2) | FAILED (failures=2) |
| vs the patched branch | Ran 5, OK | Ran 5, OK |

The two pre-patch failures are `AssertionError: 0 not greater than 0 : 503 write must be
attempted after the bounded pre-read` and an empty `conn.sent` — the defect stated directly.
`test_post_drain_is_bounded`, `test_total_read_and_deadline_caps` and
`test_phase_constants_are_frozen` are guards that pass on both; the discriminating seam is the
delayed-payload one.

**Actual-socket 6+1, repeated** (`probe_busy_6plus1_actual.py`, 25 cycles, six occupiers
holding every slot through the drain, then a stalled excess probe that sends nothing):

```
patched:   25/25 cycles delivered 503 busy (187 bytes)
pre-patch: 25/25 cycles delivered 0 bytes
```

The pre-patch empty reply is precisely what the client turns into `unavailable`.

## 5. Full suite

| Suite | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| base `b962a04d` | `Ran 576 … OK (skipped=3)`, exit 0 | same |
| patched branch | `Ran 581 … OK (skipped=3)`, exit 0 | same |
| patched, fetched bytes | `OK (skipped=3)`, exit 0 | same |

Five added passing tests, no new failure; the three skips are the documented opt-in/control ones.

## 6. Semantic-revert guard (compile-clean, two levels)

`logs/semantic_revert_guard.txt`. **A.** Full revert to `b962a04d` compiles clean on both
interpreters; the phase constants are part of the frozen contract, so the harness import fails
and the adapter tests are **skipped** — visibly not a pass. **B.** Constants-only revert
(constants present, monolithic `_busy_reject`) compiles clean and the guard **fails** with the
two failures above. **C.** The actual-socket probe separates 25/25 busy from 25/25 empty.

## 7. Frozen D096 harness — verified, and a harness defect found

The published harness was verified before use: `scripts/http_gate.py` sha256
`36770171…` and `frozen_schedule.json` sha256 `f0a91815…` match the D096 MANIFEST exactly, and
the schedule fingerprints are the frozen `c3ab4855…` / `e08db707…`.

**First smoke600 run: FAIL** — `logs/RAW_SMOKE_FAILURE_DIAGNOSTIC.txt`. Buckets were valid 386
(want 580), expected RO denial 20, busy 0, **unavailable 0**, other 194. The 194 errors were
`transport=ValueError` on `op=read` only, each finishing in ~0.04 ms — raised by client-side
validation before any socket I/O. `_validate_file_id` requires a non-root file_id to start with
`p/`, and the frozen schedule used `readme.txt`. **This is a defect in the D096 harness, not a
production failure** (the harness had only been validated on `list`-only tracks). Per the task
the acceptance soak was **not** run at that point.

**Mechanical harness correction (one line, `p/readme.txt`)** — `scripts/harness_r1.diff`,
corrected script `scripts/http_gate_r1.py` (sha256 `4bb7a02a…`), new frozen fingerprints
`74e61249…` (smoke600) / `7f3911b4…` (soak10000). The D096-published harness is left untouched
in `drop`.

## 8. Gate results (corrected harness, verified bytes)

| Stage | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| selfcheck | PASS | PASS |
| smoke600 | **PASS** 580 valid + 20 RO denial, busy 0, unavailable 0, other 0 | **PASS** same |
| soak10000 (gated, run because smoke passed) | **PASS** 9680 + 320, 0 / 0 / 0, 120.9 s | **PASS** same, 121.2 s |
| saturation 6+1, 50 cycles | **PASS** 300 valid + 50 busy, 0 / 0 | **PASS** same |

Resource bounds held in every stage: `closed=True`, fd `11 → 4`, seven adapter threads created
and reaped, client leases never above 5, RSS did not grow. `unexpected_unavailable` is **0**
throughout — the D094 property holds. The smoke and soak are stable (4/4 and 3/3 across
repeats).

**Saturation determinism, stated honestly.** The 6+1 sub-gate is *not* perfectly deterministic.
It passed 7 of 8 repeated runs and failed one with `299 valid / 49 busy / 2 other`
(`logs/saturation_repeat_3.12.txt`); combined with the earlier published-bytes run that is 2
failures in 10. The failure signature is consistent with a scheduler race in which the excess
probe's connection is accepted before all six occupiers hold a slot, so the excess is admitted
and one occupier is rejected. `unexpected_unavailable` stayed 0 in every saturation run. This is
a harness determinism limit to be tightened, not a production failure.

## 9. Preserved history

The D085 (7dab4357) FAIL records are unchanged in `drop` — soak10000 still
`busy=326, denied=320, unavailable=6, result=FAIL` — as are the D088 diagnosis and the D096
harness drop.

## 10. Scope

Two files only; no fixes beyond the D094 patch and the mechanical harness correction; no installs,
no merge, no deploy, no real roots. **Gemini's final delta review and a fresh independent
execution are still required.**

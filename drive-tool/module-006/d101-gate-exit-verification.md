# D101 — harness-only aggregate exit/status repair (final HTTP gate)

## Verdict

The D096/D097 HTTP stress-gate harness returned a **nonzero** `--gate` exit code
even though every stage PASSed, because its aggregate result dict had no
top-level `result` key (the D097 report admits this in section 8). D101 repairs
**only** the harness's aggregate exit/status, in a **separate evidence copy**,
and leaves the frozen operations, schedules, intents, budgets, the real
6-service-entry saturation barrier and the candidate source `f37a30b` unchanged.
After the repair, the **actual `--gate` exits 0 on both Python 3.11.2 and
3.12.13** with exact counts 580/20, 9680/320 and 300/50 and zero
unexpected/unavailable outcomes.

- Corrected harness: `d101-final-http-gate/scripts/http_gate_d101.py`
  (sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b`)
- Full evidence bundle: `d101-gate-exit-verification/`
  (`REPORT.md`, `MANIFEST.md`, `HASHES.txt`, `env.txt`, `scripts/`, `logs/`, `schedules/`)

## The defect

`scripts/http_gate_d097.py`: `run_gate()` returned `{"smoke":…, "soak":…}` with
no top-level `result` key, so `main()`'s exit mapping read `None` and returned
`1`. Reproduced on this host: `--gate` on 3.11 exited **1** with
`smoke.result=PASS` and `soak.result=PASS`. Nothing about the stages was wrong;
only the aggregate exit/status was.

## The repair (harness-only)

The gate now orchestrates the four **required** stages — `selfcheck`,
`smoke600`, `soak10000`, `saturation_6plus1` — and returns an aggregate dict that
**carries a top-level `result` key**. It passes **iff every required stage was
executed and reports PASS**; a missing/skipped stage (`None`) or any non-PASS
result (FAIL / ERROR / TIMEOUT / MISSING) is a problem → nonzero. The "no soak
after smoke fail" rule is preserved: if smoke does not pass, soak **and**
saturation are withheld and the gate is nonzero.

The change is confined to the gating helper: `run_gate` (changed) plus the new
`_aggregate_gate`, `_run_guarded` and `REQUIRED_STAGES`. An **AST comparison of
all 54 top-level definitions** shows those four are the *only* differences —
**50 frozen definitions are byte-identical**, including `frozen_schedule`,
`classify`, `verdict`, `run_stage`, `run_saturation`, `selfcheck`, `build_roots`,
`_EntryGate` (the real service-entry barrier) and every frozen constant. The
`main()` exit line is unchanged; it becomes correct because `result` now exists.

## Negative-injection proof — a false pass is impossible

`scripts/test_gate_exit_d101.py` imports the real corrected harness and drives
its real entry point, so the asserted value is the process exit code. Injected
FAIL / SKIPPED / ERROR / TIMEOUT / raising / `TimeoutError` / non-dict stages all
yield a nonzero gate. An **exhaustive truth table** over all `7**4 = 2401`
combinations of `{None, PASS, FAIL, SKIPPED, ERROR, TIMEOUT, MISSING}` across the
four required stages passes for **exactly one** combination (all PASS) with **0
false passes**, and the same sweep through the entry point gives **0 exit-code
mismatches**. Run-order rules verified: `selfcheck FAIL ⇒ smoke not run`;
`smoke FAIL ⇒ no soak and no saturation`. **23/23 checks pass on 3.11.2 and
3.12.13.**

## Actual `--gate` re-run (900 s/stage outer bound)

| stage | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| `selfcheck` | PASS | PASS |
| `smoke600` | PASS **580 + 20**, 0 busy, 0 unavailable, 0 other | PASS same |
| `soak10000` | PASS **9680 + 320**, 0/0/0 | PASS same |
| `saturation_6plus1` | PASS **300 + 50**, 0/0 | PASS same |
| **`--gate` raw exit** | **0** | **0** |

`unexpected_unavailable = 0` and `unexpected_other_error = 0` everywhere.
Resources clean in every stage: `closed=True`, fd `11 → 4`, the seven
`drive-http*` threads reaped (none after close), leases never above 5, RSS
bounded, workspace/fixtures inside the frozen bounds, each stage inside budget.

## Frozen schedules preserved

`--dump-schedule` is **bit-identical on both interpreters**, sha256
`14a6ac33e796dd62d2a1e60415868608c5013c6e2c5bfc39346ec3c3003c0c88` — matching
the D097 recorded full-schedule dump sha256. The published
`schedules/frozen_schedule_manifest.json` is the D097 file byte-for-byte
(sha256 `e08fc4fe…`); smoke/soak fingerprints `74e61249…` / `7f3911b4…`
reproduce.

## Preserved history

The old **nonzero** result is retained, not rewritten:
`logs/old_d097_gate_3.11.json` (D097 `--gate` exit 1, both stages PASS, no
top-level `result`). `logs/comparison_old_vs_new.txt` sets the old nonzero run
beside the new zero run. The D096/D095/D097 published harnesses in `drop` are
untouched.

## Not done

No source fix, no test change, no merge, no deploy, no target/real-root run. The
corrected harness exists only in this evidence copy.

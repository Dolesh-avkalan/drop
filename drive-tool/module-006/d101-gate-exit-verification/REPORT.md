# D101 — harness-only aggregate exit/status repair (final HTTP gate)

**Scope.** D101 corrects **only** the D096/D097 stress-gate harness's aggregate
exit/status so that `--gate` returns **0 iff every required stage was executed
and PASSed**, and **nonzero on any FAIL / missing / skipped / error / timeout**.
It is a harness-only repair in a **separate evidence copy**. The frozen
operations, schedules, intents, budgets, the real 6-service-entry saturation
barrier and the candidate source `f37a30b` are **unchanged** — proven below by
byte-level and AST-level comparison. No source fix, no test change, no merge,
no deploy and no target run were performed.

## 1. The defect

The D097 report (section 8) admits it:

> `--gate` exits non-zero because its result dict has no top-level `result` key —
> a pre-existing harness quirk carried from D096; the stages themselves PASS.

Root cause, in `scripts/http_gate_d097.py`:

- `run_gate()` returned `{"smoke": <stage>, "soak": <stage>}` — **no** top-level
  `result` key.
- `main()`'s exit mapping read `out.get("result")`, got `None`, and returned `1`.

Reproduced on this host (Python 3.11.2, candidate `f37a30b`):

```
OLD scripts/http_gate_d097.py  --gate 3.11
  exit code  : 1
  top-level result key : None
  smoke.result = PASS   soak.result = PASS
  smoke buckets: 580 valid + 20 RO-denied, 0 busy, 0 unavailable, 0 other
  soak  buckets: 9680 valid + 320 RO-denied, 0 busy, 0 unavailable, 0 other
```

Every stage passed; the process still exited nonzero. That is the defect.

## 2. The repair (harness-only, separate copy)

New file: `scripts/http_gate_d101.py`
(sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b`).
It is the D097 harness with **one block** replaced — the gating helper — plus a
single docstring usage line. The gate now:

- orchestrates the **four required stages**: `selfcheck`, `smoke600`,
  `soak10000`, `saturation_6plus1`;
- returns an aggregate dict that **carries a top-level `result` key**;
- passes **iff every required stage was executed and reports PASS**; a
  missing/skipped stage (`None`) or any non-PASS result (FAIL / ERROR / TIMEOUT /
  MISSING / anything) is a problem → nonzero;
- **preserves the "no soak after smoke fail" rule**: if smoke does not pass,
  `soak10000` and `saturation_6plus1` are withheld (recorded as skipped) and the
  gate is nonzero.

New/changed definitions (the whole delta):

- `REQUIRED_STAGES` (new constant)
- `_run_guarded(fn, ...)` (new) — converts any exception to `ERROR`, any
  `TimeoutError` to `TIMEOUT`, any non-dict return to `ERROR`; all non-PASS.
- `_aggregate_gate(stages)` (new) — PASS iff every required stage present & PASS.
- `run_gate(repo, allow_diagnostic_soak=False)` (changed) — the orchestrator.

The `main()` exit line is **unchanged**; it becomes correct because the aggregate
now supplies `result`.

### Scope proof (AST, `logs/d101_scope.txt`)

54 top-level definitions/assignments compared verbatim between D097 and D101:
the **only** differences are the four gate-helper names above; **50 frozen
definitions are byte-identical**, including `frozen_schedule`, `schedule_counts`,
`schedule_fingerprint`, `classify`, `verdict`, `run_stage`, `run_saturation`,
`selfcheck`, `build_roots`, `build_policies`, `_EntryGate` (the real
service-entry barrier), `_make_gated_service`, and every frozen constant
(`SMOKE_*`, `SOAK_*`, `SAT_*`, `CLIENT_LEASES`, `DRAIN_HOLD_SECONDS`,
`STAGE_BUDGET_SECONDS`, `MAX_*`, `PERSONAS`, `_TOKENS`, …). Raw-byte check: the
`# Stage runner … # Gating helper` region and the `# Self-check … EOF` region are
identical in both files.

## 3. Negative-injection unit proof — a false pass is impossible

`scripts/test_gate_exit_d101.py` imports the **real** corrected harness and drives
its **actual** entry point (`main(["--gate", ...])`), so the value asserted *is*
the process exit code. Injected failures: FAIL, SKIPPED, ERROR, TIMEOUT,
raising stages, a raising `TimeoutError`, and a non-dict stage return — each must
yield a nonzero gate.

- **23/23 checks pass on Python 3.11.2 and on 3.12.13** (exit 0 for the suite).
- **Exhaustive truth table**: all `7**4 = 2401` combinations of
  `{None, PASS, FAIL, SKIPPED, ERROR, TIMEOUT, MISSING}` across the four required
  stages. The aggregate passes for **exactly one** combination — all four PASS —
  with **0 false passes**. The same sweep through the real entry point yields
  **0 exit-code mismatches**.
- Run-order rules verified: `selfcheck FAIL ⇒ smoke not run`;
  `smoke FAIL ⇒ soak not run AND saturation not run` (no soak after smoke fail).

## 4. Actual `--gate` re-run (hard outer bound 900 s/stage)

Candidate `Dolesh-avkalan/drive-tool @ f37a30b` (blob `41279e62…`, sha256
`3ed13cfa…` — recomputed on this host and matching D097), base `b962a04d`.

| stage | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| `selfcheck` | PASS | PASS |
| `smoke600` | PASS **580 + 20**, 0 busy, 0 unavailable, 0 other | PASS same |
| `soak10000` | PASS **9680 + 320**, 0/0/0 | PASS same |
| `saturation_6plus1` | PASS **300 + 50**, 0/0 | PASS same |
| **`--gate` raw exit** | **0** | **0** |

`unexpected_unavailable` is **0** everywhere and `unexpected_other_error` is
**0** everywhere. Resources clean in every stage: `closed=True`, fd `11 → 4`,
the seven `drive-http*` threads reaped (none after close), client leases never
above 5, RSS bounded, workspace/fixtures inside the frozen 128 MiB / 32 MiB
bounds, each stage inside its 900 s budget (smoke ≈ 10 s, soak ≈ 156 s wall).

## 5. Frozen schedules preserved

`--dump-schedule` re-generated on both interpreters is **bit-identical**:
sha256 `14a6ac33e796dd62d2a1e60415868608c5013c6e2c5bfc39346ec3c3003c0c88`
on 3.11.2 and on 3.12.13 — matching the D097 recorded full-schedule dump sha256
exactly. The published `schedules/frozen_schedule_manifest.json` is the D097 file
byte-for-byte (sha256 `e08fc4fe…`). Smoke fingerprint
`74e61249…` and soak fingerprint `7f3911b4…` reproduce.

## 6. Preserved history

The old **nonzero** result is preserved, not rewritten:
`logs/old_d097_gate_3.11.json` records the D097 `--gate` returning exit 1 with
both stages PASS and no top-level `result` key. The D097/D096/D095 published
harnesses in `drop` are untouched. `logs/comparison_old_vs_new.txt` sets the old
nonzero run beside the new zero run.

## 7. Reproduction

```sh
fetch_repo owner=Dolesh-avkalan repo=drive-tool ref=f37a30b   # -> /scratch/repos/drive-tool
python3.11 scripts/build_d101_harness.py                      # d097 -> d101 (gate helper only)
python3.11 scripts/scope_check_d101.py                        # delta is exactly the gate helper
python3.11 scripts/test_gate_exit_d101.py                     # 23/23, 2401 combos, 0 false passes
python3.12 scripts/test_gate_exit_d101.py
python3.11 scripts/http_gate_d101.py --repo /scratch/repos/drive-tool --gate --quiet --json logs/d101_gate_3.11.json
python3.12 scripts/http_gate_d101.py --repo /scratch/repos/drive-tool --gate --quiet --json logs/d101_gate_3.12.json
```

## 8. What was NOT done

No source fix, no test change, no merge, no deploy, no target/real-root run. The
corrected harness lives only in the evidence copy
(`d101-final-http-gate/` and `d101-gate-exit-verification/`); the frozen D096/D095
harnesses and all prior evidence are unmodified.

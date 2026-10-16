# D096 — independent HTTP stress-gate harness (preparation)

**Task:** D096. Build a separate, stdlib-runnable gate harness under `drop`, freeze the exact
schedule, accounting and resource bounds **before** any run, and validate only to the extent of
compile / schedule+accounting unit checks / bounded cleanup. **No production or test file is
edited, and no acceptance stress is executed** — that waits on the DeepSeek D094 busy fix and
the Gemini delta. Adopted from Gemini D089 (`drop` `c67c548`): orthogonal
valid-load / expected-denial / saturation accounting, *not* a mathematical occupancy guarantee.

## 1. What this drop contains

Scripts only — nothing on the source branch:

- `scripts/http_gate.py` — the harness (stdlib only; imports the candidate adapter from a
  `--repo` checkout at call time).
- `frozen_schedule.json` — the pinned schedules and their fingerprints, produced before any run.
- `logs/` — the validation runs below, raw.

## 2. Frozen before execution (pinned in `frozen_schedule.json`)

| Item | Frozen value |
| --- | --- |
| schedule seed | `0xD096` (53398) |
| smoke600 | 600 = **580 valid + 20 read-only saves** |
| soak10000 | 10000 = **9680 valid + 320 read-only saves** |
| agents | **6 distinct personas / 6 distinct roots** (main, other, small, ro, alias-a→shared, alias-b→shared) |
| client leases | **5 global**, each held until *response + 55 ms monotonic hold* |
| saturation | **50 cycles × (6 occupiers + 1 excess) = 300 success + 50 busy** |
| workspace / fixtures | ≤128 MiB / ≤32 MiB |
| fd / threads / RSS | fd returns to baseline (+2 slack), **7 adapter threads reaped**, RSS growth ≤64 MiB after warmup |
| outer budget | 900 s per stage |

Schedule fingerprints (identical on 3.11.2 and 3.12.13):

```
smoke600  c3ab4855d8ad0505dd9026dc14395c2dc784ecd8662672ce94cd5db8903dc737
soak10000 e08db707be56fe1324654d95b8bfcdb054fa9116f1188082653ae9e9960f856b
```

## 3. Accounting (D089 buckets)

```
requested = completed + incomplete
completed = valid_below_capacity_success + expected_readonly_denial
          + expected_saturation_busy + unexpected_unavailable + unexpected_other_error
```

A **busy below capacity**, any **unavailable**, any **other unexpected error**, or an expected
bucket that does not match its frozen count is a **gate FAIL**. `denied` counts as valid only
when the intent was a read-only persona running `save`; a denied read/list/find, or an OK on a
read-only save, is an immediate FAIL. There are **no blind retries** and no error budgets. Every
record carries `seq`, agent label (never the token), op, pre-dispatch intent, bucket, status,
code, `outcome_uncertain`, `retry_safe`, transport exception and per-call duration.

## 4. Tracks

- **Track A — below-capacity six-agent stress** (`smoke600`, `soak10000`): five drain-aware
  client leases keep actual occupancy below the six-slot ceiling while all six personas
  interleave. Expected buckets: valid = 580 / 9680, RO denial = 20 / 320, busy = 0,
  unavailable = 0, other = 0.
- **Track B — deterministic 6+1 saturation**: 6 barrier-synchronised occupiers hold every slot
  through the 50 ms post-response drain, and a 7th probe arriving inside that window must be
  busy. 50 cycles ⇒ exactly 300 successes and 50 busy, zero unavailable.
- **Adversarial protocol track**: framing probes recorded for information only. It reports
  `gate_pass: false` and `kind: adversarial-best-effort` and can never be read as a normal
  gate pass.
- **Gating helper** (`--gate`): runs smoke, and runs soak **only if smoke passes**; a soak run
  after a smoke failure is labelled `DIAGNOSTIC-NOT-GATED-PASS`.

## 5. Validation performed (bounded, not acceptance)

| Check | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| compile `http_gate.py` | OK | OK |
| `--selfcheck` (schedule counts, replay fingerprint, accounting truth table, saturation arithmetic) | **PASS**, 0 problems | **PASS**, 0 problems |
| `--stage bounded` (60 calls, full resource accounting) | **PASS** — fd 11→4, 7 threads → 0, closed | **PASS** — same |
| `--stage saturation` (350 requests) | **PASS** — 300 valid + 50 busy, 0 unavailable, 0 other, 2.11 s | **PASS** — same, 2.18 s |
| `--stage adversarial` | — | recorded, `gate_pass: false` |

The self-check pins the schedules as replayable (re-generating each yields the identical
fingerprint) and asserts the 14-row accounting truth table, including that a busy below
capacity and an unavailable are never counted as expected outcomes.

## 6. Not run (deliberately)

**`smoke600` and `soak10000` acceptance runs were not executed.** They are withheld pending the
DeepSeek D094 busy fix and the Gemini delta, per the task. The harness is ready to run them with
`--gate`; until then no acceptance claim is made.

## 7. Preserved history

The D085 (7dab4357) smoke/soak **FAIL** records remain intact and unmodified in
`drop/drive-tool/module-006/d085-contract-tests/` — smoke600 `busy=28..32`, soak10000
`busy=300..326` with `denied=320` and `unavailable=6..7` — together with the D088 diagnosis of
the unavailable responses. Nothing in this drop rewrites or reinterprets them.

## 8. Scope

Scripts only; no adapter or test production file edited, no installs, no merge, no deploy, no
real roots. Synthetic roots are bounded and removed after each stage. **Gemini's final delta
review is still required.**

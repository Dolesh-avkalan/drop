# D097 — fresh independent final HTTP execution

**Task:** D097. Fresh, independent verification of the frozen candidate
`f37a30b0073611c05d26f714f2e833d689673a09` (branch `feature/module-006b-http-busy-budget`)
against base `b962a04df1c5abdb78c37617d3a6adca02d04024` and the accepted reference
`b7f8d17b9dcc4aec68d54b38f994290e05264e67`. This run did **not** trust the D095 builder logs:
every claim below is reproduced from the actual fetched bytes on this host, on Python 3.11.2 and
3.12.13. No source fix, merge, deploy, or real root was touched. Gemini's final source review
remains separate.

Environment: Linux 4.19.0-gvisor x86_64, nproc 2, Python 3.11.2 / 3.12.13.

## 1. Source identity — verified from the actual bytes

`fetch_repo` snapshots, then `git hash-object` on the fetched working trees:

| file | blob SHA | matches |
| --- | --- | --- |
| `drive_tool/http_adapter.py` (candidate) | `41279e6290617968c3b4f3f91fc3cf9a7dab505a` | ✔ production pin |
| `tests/test_http_adapter.py` (candidate) | `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3` | ✔ test pin |
| `drive_tool/http_adapter.py` (base) | `a28970e29f7aa52373026f2e539206b2de784ccf` | ✔ |
| `tests/test_http_adapter.py` (base) | `8130d56f4ca04305ec2e9a38ff59c892c6a659b0` | ✔ |

Working-tree sha256 of the candidate files: `http_adapter.py` = `3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c`,
`test_http_adapter.py` = `b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf` —
identical to the values D095 reported, but here they were **recomputed from the fetched bytes**, not
copied from the report.

## 2. Source delta from accepted `b7f8d17` — exact two-file scope

A recursive diff of the accepted tree against the candidate tree yields **exactly two entries**:
`drive_tool/http_adapter.py` and `tests/test_http_adapter.py`, both *new*. Every other file in the
tree is byte-identical. So the whole HTTP adapter arrives on this branch as exactly two files and
the busy patch itself (`base b962a04d → candidate f37a30b`) touches only those same two files:

- `http_adapter.py`: **22 insertions, 4 deletions** — three new phase constants
  (`BUSY_PRE_READ_BUDGET_SECONDS=0.010`, `BUSY_WRITE_RESERVE_SECONDS=0.020`,
  `BUSY_POST_DRAIN_BUDGET_SECONDS=0.020`), `BUSY_REJECT_BUDGET_SECONDS` re-spelled `0.050`, the
  new names exported in `__all__`, and a phased `_busy_reject` (bounded pre-read → reserved write →
  bounded post-drain). `MAX_IN_FLIGHT_OPERATIONS` stays 6, `MAX_BUSY_READ_BYTES` stays 16384,
  `POST_RESPONSE_DRAIN_SECONDS` stays 0.05. No queue, thread or filesystem work added to the reject
  path.
- `test_http_adapter.py`: +5 tests in a new `BusyPhaseBudgetTests` class plus the constant wiring.

This is a strictly additive, two-file, mechanical patch; nothing outside the reject path changed.

## 3. Full candidate conformance, 3.11 and 3.12

`python -m unittest discover -p "test_*.py"` run from `tests/` with the repo on `PYTHONPATH`:

| tree | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| accepted `b7f8d17` | — | `Ran 506 … OK` |
| base `b962a04d` | `Ran 576 … OK (skipped=3)` | `Ran 576 … OK (skipped=3)` |
| candidate `f37a30b` | `Ran 581 … OK (skipped=3)` | `Ran 581 … OK (skipped=3)` |

Exit 0 everywhere; the candidate adds 5 passing tests and no failure. The three skips are the
documented opt-in/control skips.

## 4. Own real-socket HTTP probes (no builder harness)

`scripts/probe_http_d097.py` drives the adapter over loopback sockets. For the saturation/busy
probes it holds the six admitted operations at a **real service-entry barrier** (a `LocalFileService`
subclass whose `list()` blocks until all six workers confirm entry) and releases them only after the
probe is answered — no socket-open/drain-window timing.

| probe | what it proves | candidate 3.11 | candidate 3.12 |
| --- | --- | --- | --- |
| `busy-6plus1` | 6 held + 1 excess ⇒ 6×200 + 1×503 busy | PASS | PASS |
| `delayed-busy` | 7th socket connects, stalls 60 ms, *then* sends | PASS (503 busy, 187 B) | PASS (503 busy, 187 B) |
| `close-once` | request ok; close/close/close ⇒ True,True,True; new conn refused | PASS | PASS |
| `close-timed` | close(timeout=0.1) ⇒ False within budget, unrelated fd untouched, final close True | PASS | PASS |

**old-fail / new-pass discriminator.** The same `delayed-busy` probe against the **pre-patch base
`b962a04d`** returns **0 bytes** (empty reply — the client's `RemoteDisconnected` → synthesized
`unavailable`), i.e. FAIL. This independently reproduces the D088/D094 defect and shows the patch is
what removes it. (A stall shorter than the 50 ms budget does not discriminate — the pre-patch
monolithic read simply completes in time — so the probe uses a 60 ms stall, past the whole budget.)

## 5. Security mutation battery — every mutant killed, compile-clean

Six surgical mutants of `http_adapter.py` (one per security property), each applied to a private
copy, `py_compile`-checked on both interpreters (no syntax false-positive), then the targeted test
class run. A mutant the tests fail to catch would be a gate FAIL.

| mutant | property | class | compile 3.11/3.12 | killed 3.11 | killed 3.12 |
| --- | --- | --- | --- | --- | --- |
| `m1_framing_nonpost` (accept non-POST) | framing | `FramingRejectionTests` | OK/OK | ✔ | ✔ |
| `m2_auth_missing_allowed` (missing auth proceeds) | auth | `AuthFirstZeroFsTests` | OK/OK | ✔ | ✔ |
| `m3_caps_wire_gate_removed` (drop wire size cap) | caps | `CapabilityBoundaryTests` | OK/OK | ✔ | ✔ |
| `m4_close_not_idempotent` (re-run close) | once-only-close | `CloseBudgetTests` | OK/OK | ✔ | ✔ |
| `m5_close_ignores_deadline` (blow the budget) | timed-close | `CloseBudgetTests` | OK/OK | ✔ | ✔ |
| `m6_busy_monolithic_preread` (revert the patch) | busy-phase | `BusyPhaseBudgetTests` | OK/OK | ✔ | ✔ |

All six classes PASS on the unmutated candidate on both interpreters (new pass) and FAIL under their
mutant (old fail). `m1`,`m2`,`m4`,`m5`,`m6` are clean assertion failures; `m3` surfaces as a test
*error* — with the wire cap removed the server waits on a 5000-digit `Content-Length`, disconnects,
and the test helper receives an empty body — which is a genuine consequence of the mutant, not a
harness artefact (the mutant compiles and the failure traces to the changed behaviour).

## 6. D096/D095 harness and frozen schedules — verified, not assumed

Hashes recomputed from the published `drop` bytes:

| artifact | sha256 | matches |
| --- | --- | --- |
| `d096-http-gate-harness/scripts/http_gate.py` | `36770171d78b2541f5b869d3f1c8ef5573eb61eba55ef26c00cc4b1e629954ed` | ✔ D096 MANIFEST |
| `d095…/scripts/http_gate_d096_original.py` | `36770171…` (same bytes) | ✔ |
| `d095…/scripts/http_gate_r1.py` | `4bb7a02a27db2fe54e6e1232ee7e136ea79bf497a8be96d04f66d981875ba8f2` | ✔ D095 MANIFEST |

The r1 correction is exactly the one-line `file_id = "readme.txt"` → `"p/readme.txt"` (the client
rejects a bare id). Running the r1 harness `--selfcheck` on both interpreters reproduces the frozen
schedule counts (smoke 580+20, soak 9680+320) and the **corrected** fingerprints
`74e61249b9e7d3be0b0f3e31f7e88d1be5368c9ef752991fc21fdd690e9d68ef` (smoke) /
`7f3911b44f9a1dd86671fcfd141b8aa0ac00486deb94f97c37d01cc89105bf4e` (soak), matching D095's
`74e61249…` / `7f3911b4…`. The original D096 (bare-id) fingerprints `c3ab4855…`/`e08db707…` are the
pre-correction ones and are not used. The full schedule manifest is published as
`frozen_schedule_manifest.json` (seed `0xD096` = 53398, 5 leases, 55 ms hold); the full per-intent dump is deterministic from the seed and re-generated bit-identically by `http_gate_d097.py --dump-schedule`.

## 7. The saturation sub-gate is not deterministic — reproduced, then fixed harness-only

The D095 report claimed the 50-cycle 6+1 saturation "passed 7 of 8" with one `299/49/2` flake. On
this host, running the **unmodified r1 saturation** repeatedly gives a much worse and highly
variable result — e.g. a run of 8 gave **8/8 FAIL** (`valid` 288–299, `busy` 38–48, `other` 3–24,
`unavailable` always 0). The failure is the D095 mechanism: the occupiers and the excess probe are
released by a `threading.Barrier` and then race to `connect()`, so the excess can be accepted before
all six occupiers hold a slot, admitting the excess and rejecting an occupier. It is a timing race,
not reproducible, and never a production defect (`unavailable` stayed 0 throughout).

**Fix, harness-only, in a separate evidence copy** (`scripts/http_gate_d097.py`; the D096/D095
harnesses are left untouched in `drop`). Track B now holds the six admitted operations at a **real
service-entry barrier**: the harness service blocks inside `list()` until all six workers have
confirmed entry, the excess probe is sent only then (all six slots provably held in-handler), and the
six are released only after the probe is fully answered. No socket-open or drain-window timing is
used. Everything else in the harness (schedules, accounting, smoke/soak tracks, adversarial track,
gating helper, selfcheck) is byte-for-byte the verified r1 code.

Result: **50 cycles = 300 valid + 50 busy, 0 unavailable, 0 other, every cycle.** Ten repeat runs on
3.12 and ten on 3.11 all PASS.

## 8. Gate results (corrected harness, verified bytes)

| stage | 3.11.2 | 3.12.13 |
| --- | --- | --- |
| `--selfcheck` | PASS | PASS |
| `smoke600` | PASS 580 + 20, busy 0, unavailable 0, other 0 | PASS same |
| `soak10000` (gated, run because smoke passed) | PASS 9680 + 320, 0/0/0 | PASS same, 156 s |
| `saturation` 6+1 × 50 | PASS 300 + 50, 0/0 | PASS same |

Resource accounting held in every stage: `closed=True`, fd `11 → 4`, the seven `drive-http*` threads
created and reaped (none after close), client leases never above 5, RSS did not grow, workspace and
fixtures within the frozen 128 MiB / 32 MiB bounds, each stage inside its 900 s budget. `unexpected_unavailable` is 0 everywhere.

(Note: `--gate` exits non-zero because its result dict has no top-level `result` key — a pre-existing
harness quirk carried from D096; the stages themselves PASS. Run with `--stage` for a per-stage exit
code.)

## 9. Strict semantic-revert guard — compile-clean, two levels

`logs/semantic_revert_guard.txt`.

- **Level A — full revert** of `http_adapter.py` to base `b962a04d`: compiles clean on both
  interpreters; the candidate test module can no longer import the new constants, so the adapter
  tests are **skipped** (`Ran 581 … OK (skipped=73)`) — visibly *not a pass*.
- **Level B — constants present, monolithic `_busy_reject`** (the D092 defect re-introduced):
  compiles clean; `BusyPhaseBudgetTests` **FAILS (failures=2)**, with
  `AssertionError: 0 not greater than 0 : 503 write must be attempted after the bounded pre-read` —
  the defect stated directly.

## 10. Preserved history

The D085 (`7dab4357`) smoke/soak FAIL records and the D088 diagnosis remain unmodified in `drop`,
as does the D096 published harness and the D095 evidence. Nothing here rewrites them. The D095
report's saturation claim is recorded as **not reproducible** on this host, which is a correction,
not a rewrite of that artifact.

## 11. Verdict

The frozen candidate `f37a30b` is **independently confirmed**: two-file additive patch, clean on
3.11.2 and 3.12.13, the busy-phase defect demonstrably fixed at the real-socket level (old fail /
new pass), all six security properties mutation-killed, and the frozen smoke/soak/saturation gates
pass with zero unexpected outcomes and bounded resources. The only outstanding item is the
saturation-harness determinism, which D097 fixes harness-only (real service-entry barrier); with the
correction the 50-cycle gate is exactly 300/50/0/0 on every repeat. **Gemini's final source review
remains separate.** No source fix, merge, deploy, or real root was performed.

# D086 — runner final two-fix (correction / verification summary)

**Status: CORRECTED + VERIFIED IN SANDBOX.** Exactly two files were corrected,
and nothing else. The runner's embedded dual-order reproducer now derives the
test module name correctly (`rsplit(".", 2)` instead of `rsplit(".", 1)`), and
the negative harness's N2/N11 assertions are de-coupled from a rewording of the
`--base-dir` FATAL message while keeping (and, for N11, adding) the fail-closed
behaviour checks. With these two corrections the required outcome is met:
dual-order `asc` = 1 test / 0 skips / PASS, `desc` = 1 test / 0 skips /
FAILED (`AssertionError: 3 != 2`), `confirmed_order_sensitive_defect = True`;
the 18 negative gates pass **18/18** on both Python 3.12 and 3.11; and the
default invocation still fails **strictly** (exit NONZERO) on the known
directory-order-sensitive committed-suite failure, with smoke/soak/edges run
separately for diagnostic evidence only.

Scope honoured: the payload (`stress_checks.py`), the 26 pinned source/test
identities, `COMMIT`, `EXPECTED_BLOBS`, `STRESS_CHECKS_SHA256`, the pinned
archive and the runner README are all unchanged. No target run, no installs, no
credentials, no merge, no deploy, no re-pin, no harsh-extension and no HTTP work.
No fix was applied beyond the two named corrections. **Gemini security delta
acceptance of the D086 correction is still required.**

---

## 1. Pins resolved

| label | resolved full pin | commit message |
| --- | --- | --- |
| D082 bundle being corrected | `Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8` | (D082 bundle drop) |
| D078 patch (source of the pre-fix runner) | `Dolesh-avkalan/drop @ 0aef8e882c0eed2f868832ea4bc07b845c666480` | "relay: d078 (done)" |
| source under test (UNCHANGED) | `Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67` | — |

Pinned archive (independently re-downloaded and hashed in this sandbox):

```
https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/b7f8d17b9dcc4aec68d54b38f994290e05264e67
sha256 93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3
bytes 338575   members 123
```

---

## 2. The two corrections

### Correction 1 — runner dual-order repro module-name extraction (B-D072-2)

D078's `DUAL_ORDER_REPRO` imported the test module with a one-token strip, which
left the **test class** attached to the module path. The runner's own
`ORDER_SENSITIVE_TEST` is

```
tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged
```

so `rsplit(".", 1)[0]` produced
`tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests`, which is not
a module. `importlib.import_module` raised before any test loaded (both legs
`rc=1`, `ran=None`, `confirmed=False`). The fix is a single token:

```diff
- MODNAME = TESTNAME.rsplit(".", 1)[0]
+ MODNAME = TESTNAME.rsplit(".", 2)[0]
```

This is the **only** line changed in `runner/run_cloud_stress.py` (verified by a
byte diff against the D082 runner — see §5). `COMMIT`, `EXPECTED_BLOBS` (26
entries) and `STRESS_CHECKS_SHA256` are byte-identical to the D082 runner.

### Correction 2 — negative harness N2 / N11 message coupling

The D082 harness asserted the exact pre-D078 FATAL substring
`"--base-dir must resolve under /tmp/"`. The D078-corrected runner emits
`"--base-dir must resolve to /tmp or under /tmp/"`, so N2 and N11 reported FAIL
even though the behaviour (rc=1, fail-closed, no artifact) was unchanged. The
correction makes N2/N11 assert the **behaviour** and accept **either** wording:

* a `basedir_rejected(out)` helper accepts the old **or** the new message;
* N2 keeps `rc == 1` **and** "no workspace created outside /tmp";
* N11 keeps `rc == 1`, accepts either message, **and gains** a "no artifact
  created under /mnt" check.

No gate is weakened — the checks are equal or stricter; only the brittle
exact-text coupling is removed. No other gate was touched (byte diff in §5).

---

## 3. Required outcome — dual-order repro

Default invocation of the corrected runner (`python3 run_cloud_stress.py`, no
arguments, downloading the pinned archive), run under a hard outer timeout:

```
dual-order repro: asc rc=0 desc rc=1 confirmed=True
```

| leg | rc | ran | skipped | ok | failed | observed |
| --- | --- | --- | --- | --- | --- | --- |
| asc | 0 | 1 | 0 | True | False | `Ran 1 test … OK` |
| desc | 1 | 1 | 0 | False | True | `Ran 1 test … FAILED (failures=1)`, `AssertionError: 3 != 2` (tests/test_partial_scan_review_fixes.py:406) |

`confirmed_order_sensitive_defect = True`. Raw legs:
`gates/dual_order_asc.out`, `gates/dual_order_desc.out`;
`gates/readdir_order_confirmation.json`.

---

## 4. Negative gates N1–N18 — **18/18 on 3.12 and 18/18 on 3.11**

Harness: the corrected `negatives/run_negatives.py` (py3.12) and the identical
`negatives/run_negatives_311.py` (py3.11 driver), each run under a hard outer
timeout with the harness's own per-invocation hard timeout of 120 s.

| id | scope | 3.12 | 3.11 |
| --- | --- | --- | --- |
| N1 | B3 workspace escape via symlink | PASS | PASS |
| N2 | B3 `--base-dir` outside /tmp | PASS | PASS |
| N3 | B3 workspace mode | PASS | PASS |
| N4 | B2 extra file under tests/ | PASS | PASS |
| N5 | B2 `sitecustomize.py` at root | PASS | PASS |
| N6 | B2 unexpected `.so` | PASS | PASS |
| N7 | B2 symlink inside extracted src | PASS | PASS |
| N8 | B2 symlinked directory | PASS | PASS |
| N9 | B1 suite failure + diagnostic continue | PASS | PASS |
| N10 | B1 dual-order repro | PASS | PASS |
| N11 | B1 no filesystem masking | PASS | PASS |
| N12 | L1 wall-clock download deadline | PASS | PASS |
| N13 | L2 `--deadline-seconds` propagation | PASS | PASS |
| N14 | L3 bounded subprocess capture | PASS | PASS |
| N15 | L3 process-group kill | PASS | PASS |
| N16 | L4 manifest symlink safety | PASS | PASS |
| N17 | L5 apparent vs allocated | PASS | PASS |
| N18 | regression archive guards | PASS | PASS |
| | **TOTAL** | **18/18** | **18/18** |

Raw logs: `gates/negatives_stdout_py312.txt`, `gates/negatives_stdout_py311.txt`,
machine-readable `gates/negatives_results_py312.json`, `gates/negatives_results_py311.json`.

N2/N11 detail on 3.12 (corrected harness): `rc=1 created=[] rejected_msg=True`
and `rc=1 created_under_mnt=[] rejected_msg=True`.

---

## 5. Raw old-fail / new-pass evidence

### Correction 1 (runner) — isolated

| state | asc | desc | confirmed |
| --- | --- | --- | --- |
| OLD (`rsplit(".",1)`, D082 runner) | `rc=1`, `ran=None`, `ModuleNotFoundError` | `rc=1`, `ran=None`, `ModuleNotFoundError` | False |
| NEW (`rsplit(".",2)`, D086 runner) | `rc=0`, `ran=1`, `skipped=0`, `OK` | `rc=1`, `ran=1`, `skipped=0`, `FAILED (failures=1)` `3 != 2` | True |

Raw: `raw/dualorder_oldfail_{asc,desc}.txt` (+ `raw/_dual_order_repro_OLD_rsplit1.py`),
`raw/dualorder_newpass_{asc,desc}.txt` (+ `raw/_dual_order_repro_NEW_rsplit2.py`).

### Correction 2 (harness) — isolated

The brittle D082 harness, run against the **corrected** D086 runner, still fails
N2/N11 purely on the message wording while the runner behaves correctly:

```
[N2]  FAIL  rc=1 created=[] msg=False
[N11] FAIL  rc=1 msg=False
TOTAL: 16/18 passed
```

The corrected harness against the same D086 runner: **18/18** (N2/N11 PASS with
`rejected_msg=True`). This isolates the correction to the assertion coupling, not
the runner behaviour. Raw: `raw/negatives_oldfail_D082harness_D086runner.txt`.

### Byte diffs (nothing else changed)

```
runner/run_cloud_stress.py  vs D082 runner:  1 line  (rsplit 1 -> 2)
negatives/run_negatives.py  vs D082 harness: N2/N11 + basedir_rejected helper only
```

---

## 6. Strict overall suite gate — preserved (diagnostic stages separate)

Default invocation, hard outer timeout, exit **NONZERO**:

```
RESULT: FAIL (fail-closed)
  !! suite failed on python3.12 (exit 1)
  !! suite failed on python3.11 (exit 1)
```

* committed suite: `ran=506 skipped=0 ok=False failed=True exit=1` on **both**
  python3.12 (3.12.13) and python3.11 (3.11.2);
* the single failure is the known directory-order-sensitive test
  `test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged`
  (`AssertionError: 3 != 2`) — no new failure was introduced;
* `suite_diagnostic_continue = True`: smoke (600 calls), soak (10000 calls) and
  edges still run **for diagnostic evidence only** — reported honestly and
  separately, never relabelled as a suite pass;
* the suite failure is never masked by filesystem selection.

Raw: `gates/default_invocation.log`, `gates/workspace_summary.json`.

---

## 7. Compile checks (3.11 / 3.12) — clean

```
python3.11 -m py_compile runner/run_cloud_stress.py   OK
python3.12 -m py_compile runner/run_cloud_stress.py   OK
python3.11 / 3.12  runner/stress_checks.py            OK
python3.11 / 3.12  negatives/run_negatives.py         OK
python3.11 / 3.12  originals/runner/run_cloud_stress.py  OK
```

Raw: `gates/compile_checks.log`.

---

## 8. Exact bytes and hashes of the corrected files

| file | bytes | sha256 |
| --- | --- | --- |
| `runner/run_cloud_stress.py` (corrected) | 43732 | `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` |
| `runner/run_cloud_stress.py` (pre-fix, D082) | 43732 | `318e2100fc3a7da718e97768720cf0b5cb49954edd8e879e5c1851ec041cf2d8` |
| `negatives/run_negatives.py` (corrected) | 26862 | `543de9d42cb856aad456b9fb265b2c4b00dd7427debe51cb67c87278e982d02d` |
| `negatives/run_negatives.py` (pre-fix, D082) | 26115 | `8917b6a1a6056afbae3417b55b6d1a28c4c0ca29f064c0262f984b2156de8b9e` |
| `runner/stress_checks.py` (payload, UNCHANGED) | 21467 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` |
| `runner/README.md` (UNCHANGED) | 10367 | `25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb` |

Exact corrected bytes are published under `exactbytes/`; the full bundle hash
manifest is under `hashes/d086-runner-final-twofix-HASHES.txt` and
`hashes/d086-runner-final-twofix-MANIFEST.md`.

---

## 9. Bundle contents

`drive-tool/module-006/d086-runner-final-twofix/`

```
runner/run_cloud_stress.py         CORRECTED by D086, sha256 f58f61dc… (43732 bytes)
runner/README.md                   unchanged (D069)
runner/stress_checks.py            UNCHANGED payload, sha256 8097d0a3…
originals/runner/*                 D063 originals (preserved)
originals/MANIFEST.md              D063 bundle manifest
originals/tests_test_runner_gates.py   D063 runner gate tests (preserved)
negatives/run_negatives.py         CORRECTED by D086 (N2/N11 only), sha256 543de9d4…
negatives/run_negatives_311.py     identical harness, PY="python3.11" (py3.11 re-run driver)
negatives/logs_stdout.txt          raw 18-gate output (py3.12)
negatives/logs/negatives_results.json    machine-readable results (18/18, py3.12)
negatives/logs_stdout_py311.txt    raw 18-gate output (py3.11)
negatives/logs_py311/negatives_results.json  machine-readable results (18/18, py3.11)
sandbox/default_invocation.log     default invocation (dual-order confirmed=True)
sandbox/compile_checks.log         3.11 / 3.12 py_compile results
sandbox/workspace_logs/*           full-run logs (summary.json, suite_*.out,
                                   stress_*.out, dual_order_*.out,
                                   readdir_order_confirmation.json,
                                   _dual_order_repro.py, identity.txt,
                                   env_*.json, MANIFEST.md)
IDENTITIES.md                      pins, the two corrections, 26 blob sha1
MANIFEST.md                        sha256 + bytes of every file in the bundle
HASHES.txt                         machine-readable hash list
```

Evidence package: `drive-tool/module-006/d086-runner-final-twofix-summary/`
(raw old-fail/new-pass logs, gate logs, scripts, hash manifest, exact corrected
bytes, env, report copy).

---

## 10. Safety / scope confirmation

* No target run, no install, no real credentials, no cloud API, no service change,
  no reboot, no public binding, no merge, no deploy, no re-pin.
* Source under test `b7f8d17…`, its 26 file identities, the payload, `COMMIT`,
  `EXPECTED_BLOBS` and `STRESS_CHECKS_SHA256` are unchanged.
* Only two files were corrected: `runner/run_cloud_stress.py` (one line) and
  `negatives/run_negatives.py` (N2/N11 assertions). No other fix was applied.
* No filesystem selection was used to force the suite to pass; the suite failure
  is recorded and the overall exit is NONZERO. Diagnostic smoke/soak/edges are
  reported separately and honestly.
* Scope kept to the two runner fixes — no harsh-extension and no HTTP work.
* **Gemini security delta acceptance of the D086 correction is still required**
  and is not claimed here.

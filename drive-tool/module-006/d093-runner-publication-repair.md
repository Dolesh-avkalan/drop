# D093 — short missing-artifact publication repair (runner + 18 negative gates)

**Status: REPAIRED AND PUBLISHED — with an explicit honesty boundary.**
D086's summary claimed a *complete corrected bundle* at
`Dolesh-avkalan/drop @ 60b826e2ee52a6bc1f471dede75d50c19b880ae6`; that bundle
**was never published**. D093 re-derives the two documented changes from the
D082 pinned bundle, re-verifies the runner byte-for-byte, re-runs the 18
negative gates honestly on Python 3.12 and 3.11, and publishes a *complete*
bundle under `drive-tool/module-006/d093-complete-runner/` whose every file was
actually produced by this run. No file that does not exist is claimed.

---

## 1. What was actually there (verified against GitHub, not assumed)

`GITHUB_GET_COMMIT_OBJECT(Dolesh-avkalan/drop, 60b826e2…)` →
message `"relay: d086"`, tree `797593a1096dffcff3a993df56cc642fe2a18c3e`.
Listing `drive-tool/module-006/d086-runner-final-twofix` **at that commit**
returns exactly two entries:

* `IDENTITIES.md` (blob `9eb252fb…`, 6949 bytes)
* `sandbox/` (dir `486a5dc0…`) — containing only `compile_checks.log`

The sibling `drive-tool/module-006/d086-runner-final-twofix-summary.md` sits at
the module root. **Nothing else exists at that commit.** The runner bytes, the
18-gate raw logs, the harness scripts, `exactbytes/`, `hashes/…-HASHES.txt`,
`hashes/…-MANIFEST.md`, `MANIFEST.md`, `HASHES.txt` and the `…-summary/`
evidence package described in the D086 summary §9 are **absent from the
repository at every inspected ref**.

The D086 summary therefore over-claimed: it described a bundle that its own
relay did not commit. The missing artifacts are **unrecoverable from the repo**
(they were never pushed), and no D086 chat transcript was available to this run.
The task's fallback was taken: reconstruct the two documented changes from the
D082 pinned bundle and re-execute the gates honestly.

## 2. The two documented changes, reconstructed from D082 @ 783d09d

The D082 bundle (`d082-runner-twofix/`) is the pre-fix bundle; its two files
hash exactly to the "pre-correction" values in D086's `IDENTITIES.md`:

```
runner/run_cloud_stress.py   318e2100…  43732 bytes  (pre-fix, matches D086)
negatives/run_negatives.py   8917b6a1…  26115 bytes  (pre-fix, matches D086)
```

**Change 1 — runner dual-order repro module name (EXACT).**
`MODNAME = TESTNAME.rsplit(".", 1)[0]` → `rsplit(".", 2)[0]` (single token).

```
runner/run_cloud_stress.py   bytes=43732
sha256 = f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2
```

This **equals the D086-documented hash exactly.** Verified: `COMMIT`,
`EXPECTED_BLOBS` (26 entries) and `STRESS_CHECKS_SHA256` are untouched.

**Change 2 — negative-harness N2/N11 message coupling (BEHAVIOURAL reconstruction).**
A `basedir_rejected(out)` helper accepts the pre-D078 **or** the D078 FATAL
wording; N2 keeps `rc == 1` and "no workspace created outside `/tmp`"; N11 keeps
`rc == 1`, accepts either wording, and gains a no-artifact-under-`/mnt` check.

```
negatives/run_negatives.py   reconstructed bytes=26576
sha256 = 96a34f07d3e14ca315a64a62243ed5c37acd9da37a6a41d2d7246ac1aa3670bc
```

**Honesty boundary.** The D086-documented harness hash is `543de9d4…` (26862
bytes). Those exact bytes were never published and cannot be reconstructed
byte-for-byte from a prose specification. This file is a *behaviourally
equivalent* reconstruction — it is **not** byte-identical to the never-published
D086 original, and this bundle **does not claim it is**. Behaviour is verified
equivalent (§4).

## 3. Required outcome — dual-order repro (re-executed)

Default invocation of the corrected runner (no arguments, downloads the pinned
archive), run under a hard outer timeout:

```
dual-order repro: asc rc=0 desc rc=1 confirmed=True
RESULT: FAIL (fail-closed)   exit 1
```

| leg | rc | ran | skipped | ok | failed | observed |
| --- | --- | --- | --- | --- | --- | --- |
| asc | 0 | 1 | 0 | True | False | `Ran 1 test … OK` |
| desc | 1 | 1 | 0 | False | True | `Ran 1 test … FAILED (failures=1)`, `AssertionError: 3 != 2` (tests/test_partial_scan_review_fixes.py:406) |

Raw legs: `gates/dual_order_asc.out` (**asc 1 test / 0 skip / PASS**),
`gates/dual_order_desc.out` (**desc 1 test / 0 skip / FAIL**),
`gates/readdir_order_confirmation.json`.

## 4. Negative gates N1–N18 — 18/18 on 3.12 and 18/18 on 3.11 (re-executed)

Reconstructed `negatives/run_negatives.py` (py3.12) and the identical
`negatives/run_negatives_311.py` (py3.11 driver), each under a hard outer
timeout with the harness's own 120 s per-invocation cap.

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

N2/N11 detail on 3.12: `rc=1 created=[] rejected_msg=True` and
`rc=1 created_under_mnt=[] rejected_msg=True` — identical to the
D086-documented detail strings.

Raw logs: `negatives/logs_stdout.txt` + `negatives/logs/negatives_results.json`
(3.12); `negatives/logs_stdout_py311.txt` +
`negatives/logs_py311/negatives_results.json` (3.11).

## 5. Strict overall suite gate — preserved (diagnostic stages separate)

Default invocation, hard outer timeout, exit **NONZERO**:

```
RESULT: FAIL (fail-closed)
  !! suite failed on python3.12 (exit 1)
  !! suite failed on python3.11 (exit 1)
```

* committed suite `ran=506 skipped=0 ok=False failed=True exit=1` on **both**
  python3.12 (3.12.13) and python3.11 (3.11.2);
* the single failure is the known directory-order-sensitive test
  `…PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged`
  (`AssertionError: 3 != 2`) — no new failure introduced;
* `suite_diagnostic_continue = True`: smoke (600 calls), soak (10000 calls) and
  edges still run **for diagnostic evidence only**, never relabelled as a pass;
* the failure is never masked by filesystem selection.

Raw: `sandbox/default_invocation.log`, `sandbox/workspace_logs/summary.json`.

## 6. Compile checks (3.11 / 3.12) — clean

```
python3.11 / 3.12  runner/run_cloud_stress.py      OK
python3.11 / 3.12  runner/stress_checks.py         OK
python3.11 / 3.12  negatives/run_negatives.py      OK
python3.11 / 3.12  originals/runner/run_cloud_stress.py  OK
```

Raw: `sandbox/compile_checks.log`.

## 7. Exact bytes and hashes of the corrected files

| file | bytes | sha256 | vs D086 doc |
| --- | --- | --- | --- |
| `runner/run_cloud_stress.py` (corrected) | 43732 | `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` | **MATCH** |
| `negatives/run_negatives.py` (reconstructed) | 26576 | `96a34f07d3e14ca315a64a62243ed5c37acd9da37a6a41d2d7246ac1aa3670bc` | reconstruction (D086 doc `543de9d4…` / 26862 — not byte-reproducible) |
| `runner/stress_checks.py` (payload, UNCHANGED) | 21467 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` | UNCHANGED |
| `runner/README.md` (UNCHANGED) | 10367 | `25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb` | UNCHANGED |

Exact corrected bytes: `exactbytes/`. Full manifest:
`hashes/d093-complete-runner-HASHES.txt`, `hashes/d093-complete-runner-MANIFEST.md`
(root copies `HASHES.txt`, `MANIFEST.md`).

## 8. Bundle contents

`drive-tool/module-006/d093-complete-runner/`

```
runner/run_cloud_stress.py         CORRECTED (change 1), sha256 f58f61dc… (43732 B)
runner/README.md                   unchanged (D069)
runner/stress_checks.py            UNCHANGED payload, sha256 8097d0a3…
originals/                         D063 originals + MANIFEST + gate tests
negatives/run_negatives.py         RECONSTRUCTED (change 2), sha256 96a34f07…
negatives/run_negatives_311.py     identical harness, PY="python3.11"
negatives/logs_stdout.txt          raw 18-gate output (py3.12)
negatives/logs/negatives_results.json      machine-readable (18/18, py3.12)
negatives/logs_stdout_py311.txt    raw 18-gate output (py3.11)
negatives/logs_py311/negatives_results.json  machine-readable (18/18, py3.11)
sandbox/default_invocation.log     default invocation (dual-order confirmed=True)
sandbox/compile_checks.log         3.11 / 3.12 py_compile
sandbox/workspace_logs/*           full-run logs (summary.json, suite_*.out,
                                   stress_*.out, dual_order_*.out,
                                   readdir_order_confirmation.json, identity.txt, …)
gates/dual_order_asc.out           asc 1 test / 0 skip / PASS
gates/dual_order_desc.out          desc 1 test / 0 skip / FAIL (3 != 2)
gates/readdir_order_confirmation.json
exactbytes/                        exact corrected bytes (runner + harness)
hashes/                            HASHES.txt + MANIFEST.md
IDENTITIES.md                      pins, the two changes, hashes, 26 blob sha1
MANIFEST.md / HASHES.txt           sha256 + bytes of every file
RECONSTRUCTION-NOTES.md            what is real vs reconstructed
```

## 9. Safety / scope confirmation

* No target run, no install, no real credentials, no cloud API, no service
  change, no reboot, no public binding, no merge, no deploy, no re-pin.
* Source under test `b7f8d17b…`, its 26 file identities, the payload, `COMMIT`,
  `EXPECTED_BLOBS` and `STRESS_CHECKS_SHA256` are unchanged.
* Only the two documented files were changed: `runner/run_cloud_stress.py` (one
  line) and `negatives/run_negatives.py` (N2/N11 assertions). No new fix.
* The suite failure is recorded; overall exit is NONZERO; smoke/soak/edges are
  reported separately and honestly.
* **Gemini security delta acceptance is still required and is not claimed here**
  — it waits on the actual source, which this run did not alter.

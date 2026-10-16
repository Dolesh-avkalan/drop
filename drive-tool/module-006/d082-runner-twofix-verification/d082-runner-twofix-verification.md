# D082 — runner two-fix patch assembly and verification (summary)

**Status: ASSEMBLED + VERIFIED IN SANDBOX. The D078 patch was applied exactly to `runner/run_cloud_stress.py` only. One of its two fixes (B-D072-1) works; the other (B-D072-2) is broken, and the patch additionally breaks two previously-passing negative gates (N2, N11) through a message reword. Net negative-gate result: 15/18 (was 17/18). No fix was applied beyond the patch. No target run. Gemini delta acceptance still required.**

Scope honoured: only `runner/run_cloud_stress.py` was changed; the payload, the 26 pinned source/test identities, `COMMIT`, `EXPECTED_BLOBS`, `STRESS_CHECKS_SHA256` and the pinned archive are unchanged. Nothing was fixed beyond the supplied patch, no source under test was touched, no target was run, nothing was installed, no credentials used, no merge/deploy, no re-pin, and no harsh-extension or HTTP work was done.

---

## 0. Pins resolved ("resolvefullpin")

| label in the task | resolved full pin | commit message |
| --- | --- | --- |
| `drop0aef8e8e` (D078 patch) | `0aef8e882c0eed2f868832ea4bc07b845c666480` | "relay: d078 (done)" |
| `drop6f62174` (D072 corrected bundle) | `6f621741327aaddac5b385e6cf5bb2a9da69c541` | "relay: d072" |

D078 itself records its input as `Dolesh-avkalan/drive-tool:tasks/d078-runner-two-fixes.txt@eab4935bd73c6017a47267ae43e08284b44ea0d7`, and states **TESTS_NOT_RUN** (the author executed nothing).

---

## 1. What was assembled

The exact D078 unified diff was applied to the D072 corrected runner. It has four hunks, all inside `runner/run_cloud_stress.py`:

1. the `--base-dir` help string,
2. the `--base-dir` containment condition + FATAL message,
3. the embedded `DUAL_ORDER_REPRO` subprocess script,
4. the `run_dual_order_repro()` loop / confirmation predicate.

| item | pin / hash |
| --- | --- |
| source under test (UNCHANGED) | `Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67` |
| pinned archive sha256 | `93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3` (338575 bytes, 123 members) |
| payload `stress_checks.py` sha256 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` (unchanged) |
| pre-patch runner (D072/D069) sha256 | `49ce02f378e98dd55aa18c1328a61fa81dea249fcd7010c1d0a717b872c804a5` (42651 bytes) |
| **patched runner (D082) sha256** | **`318e2100fc3a7da718e97768720cf0b5cb49954edd8e879e5c1851ec041cf2d8`** (43732 bytes) |
| `runner/README.md` (unchanged) | `25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb` |
| D063 originals | `originals/` (see `IDENTITIES.md`) |

The applied diff was compared back to the D078 text: every added/removed line matches D078's hunks exactly, and the surrounding context (including the `fh.write(f"$ {' '.join(...)}…")` line) is byte-identical to the pre-patch file. `COMMIT`, `EXPECTED_BLOBS` (all 26) and `STRESS_CHECKS_SHA256` are unchanged. Full identity table: `IDENTITIES.md`.

---

## 2. Compile checks (3.11 / 3.12) — clean

```
$ python3.11 -m py_compile runner/run_cloud_stress.py   # OK  (Python 3.11.2)
$ python3.12 -m py_compile runner/run_cloud_stress.py   # OK  (Python 3.12.13)
$ python3.11 -m py_compile runner/stress_checks.py      # OK
$ python3.12 -m py_compile runner/stress_checks.py      # OK
$ python3.11 -m py_compile originals/runner/run_cloud_stress.py  # OK
$ python3.12 -m py_compile originals/runner/run_cloud_stress.py  # OK
```

Raw log: `sandbox/compile_checks.log`. The embedded `DUAL_ORDER_REPRO` also compiles on both interpreters.

---

## 3. Fix B-D072-1 (`--base-dir` default) — **WORKS**

The patch changes the containment test from `real_base == "/tmp" or not real_base.startswith("/tmp/")` to `real_base != "/tmp" and not real_base.startswith("/tmp/")`.

Default invocation (`python3 run_cloud_stress.py`, no arguments, no `--base-dir`):

```
workspace: /tmp/d063-b7f8d17b-jzxewynq (mode 0700)
payload stress_checks.py sha256 OK: 8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9
...
native readdir probe order: ['b.txt', 'a.txt'] (created a.txt before b.txt)
interpreters found: ['python3.12=3.12.13', 'python3.11=3.11.2']
...
RESULT: FAIL (fail-closed)
  !! suite failed on python3.12 (exit 1)
  !! suite failed on python3.11 (exit 1)
```

- The former `FATAL: --base-dir must resolve under /tmp/ (got '/tmp')` (D072's B-D072-1) is gone: **default invocation is now allowed**, and the unique workspace is created under `/tmp` with mode `0700` (`drwx------`).
- The **final-workspace** gate is unchanged and still strict: `real_ws == "/tmp" or not real_ws.startswith("/tmp/")` → FATAL. `/tmp` is a valid *base*, never a final workspace.
- Containment still fails closed for non-descendants: `--base-dir /var/tmp`, `/tmpfoo`, `/etc`, `/mnt` all → `FATAL: --base-dir must resolve to /tmp or under /tmp/ (got …)`, rc=1, no workspace created.
- `--base-dir /tmp/d082base` (a `/tmp` descendant) is accepted.

Raw log: `sandbox/default_invocation.log`.

### 3a. Side effect of the fix — the reword breaks gates N2 and N11

The patch also rewords the FATAL message from `--base-dir must resolve under /tmp/` to `--base-dir must resolve to /tmp or under /tmp/`. The pinned negative harness asserts the **exact old substring** `"--base-dir must resolve under /tmp/"` in N2 and N11. The new message does not contain it, so both gates now report FAIL even though the behaviour (rc=1, fail-closed, no workspace created) is unchanged. This is a message/assertion coupling, not a behavioural regression — but it does mean the patch does **not** preserve all 17 gates as D078 claims.

---

## 4. Fix B-D072-2 (dual-order repro) — **BROKEN**

D078 replaces the embedded repro so that the test module is imported **before** any order override (so `LocalAdapter` feature detection sees the real `os.scandir` and the test is not skipped), then overrides only the `LocalAdapter._os_scandir` seam. The approach is sound, but the module-name derivation is wrong.

The repro computes the module name as:

```python
MODNAME = TESTNAME.rsplit(".", 1)[0]
importlib.import_module(MODNAME)
```

With the runner's own `ORDER_SENSITIVE_TEST` value:

```
tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged
```

`rsplit(".", 1)[0]` strips only the *method* name and leaves the **test class** attached, giving
`tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests` — which is not a module. `importlib.import_module` therefore raises before any test is loaded.

Observed from the full runner run (`sandbox/workspace_logs/dual_order_asc.out`, `…desc.out`):

```
ModuleNotFoundError: No module named
  'tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests';
  'tests.test_partial_scan_review_fixes' is not a package
EXIT=1 timed_out=False seconds=0.35
ran=None skipped=None ok=False failed=False
```

Result: **both legs exit 1 with no test executed** (`ran=None`). The runner therefore logs `dual-order repro: asc rc=1 desc rc=1 confirmed=False`, and `confirmed_order_sensitive_defect` stays `false`. This is the same observable N10 failure the patch was meant to fix (the D072 legs reported `rc=0 skipped=1`; the patched legs report `rc=1 ran=None`) — the fix does not achieve "Ran 1 test, skipped=0".

Reproduced on **both** interpreters (`python3.12` and `python3.11`): identical `ModuleNotFoundError`.

### 4a. Minimal reproducer (patch broken — no broad rewrite applied)

```
$ SRC=/…/drive-tool-b7f8d17b9dcc4aec68d54b38f994290e05264e67
$ python3.12 <repro> asc  "$SRC" "tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged"
ModuleNotFoundError: No module named 'tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests';
  'tests.test_partial_scan_review_fixes' is not a package   # exit 1
```

### 4b. Characterisation — the only defect is the one-token module extraction

Holding the rest of the D078 repro exactly as written and changing **only** `rsplit(".", 1)` → `rsplit(".", 2)` (yielding the real module `tests.test_partial_scan_review_fixes`) produces precisely the behaviour D078 intended:

```
# asc
test_metadata_failure_below_root_is_skipped_and_charged (...) ... ok
Ran 1 test in 0.004s
OK                                        # exit 0  (skipped=0)

# desc
test_metadata_failure_below_root_is_skipped_and_charged (...) ... FAIL
AssertionError: 3 != 2                    # tests/test_partial_scan_review_fixes.py:406
Ran 1 test in 0.005s
FAILED (failures=1)                       # exit 1
```

So the seam-override design works and genuinely captures the known directory-order bug (asc OK / desc FAILED), and the `LocalAdapter._os_scandir` seam does exist (`drive_tool/local.py:535`, used at lines 1097/1262). The sole defect is the module-name computation. **Per the task ("do not fix beyond the patch"), this is reported, not applied.** Raw: `rawlogs/repro_corrected_modname_py312_{asc,desc}.out`.

---

## 5. Negative gates N1–N18 re-run — **15/18** (was 17/18)

Harness: the pinned D072 `negatives/run_negatives.py` (unchanged), run against the patched bundle. Every gate runs against both the pre-D069 (D063) runner and the patched runner, so old-fail/new-pass contrasts are real. Raw: `negatives/logs_stdout.txt` (py3.12), and the same gates re-run with the runner-under-test forced to py3.11 (`raw_logs/negatives_stdout_py311.txt`) — **identical 15/18**.

| id | scope | D082 result | note |
| --- | --- | --- | --- |
| N1 | B3 workspace escape via symlink | PASS | |
| N2 | B3 `--base-dir` outside /tmp | **FAIL** | rc=1 & no workspace created, but message reworded → exact-string assertion fails |
| N3 | B3 workspace mode | PASS | |
| N4 | B2 extra file under tests/ | PASS | |
| N5 | B2 `sitecustomize.py` at root | PASS | |
| N6 | B2 unexpected `.so` | PASS | |
| N7 | B2 symlink inside src | PASS | |
| N8 | B2 symlinked directory | PASS | |
| N9 | B1 suite failure + diagnostic continue | PASS | |
| N10 | B1 dual-order repro | **FAIL** | fix B-D072-2 broken (see §4) |
| N11 | B1 no filesystem masking | **FAIL** | same message-reword cause as N2 |
| N12 | L1 wall-clock download deadline | PASS | |
| N13 | L2 `--deadline-seconds` propagation | PASS | |
| N14 | L3 bounded subprocess capture | PASS | |
| N15 | L3 process-group kill | PASS | |
| N16 | L4 manifest symlink safety | PASS | |
| N17 | L5 apparent vs allocated | PASS | |
| N18 | regression archive guards | PASS | |

- **N10** is a genuine defect of the D078 patch (not a harness artefact).
- **N2 / N11** fail only because the patch reworded the FATAL message the harness asserts verbatim; their behaviour is still fail-closed. Both are direct consequences of the D078 diff.

---

## 6. Strict overall suite gate — preserved

The committed 506-test suite still fails on this pinned revision (known directory-order-sensitive test), and the runner still behaves strictly:

- `suite_diagnostic_continue = True`, `result = "FAIL"`, exit **1**;
- smoke (600 calls), soak (10000 calls) and edges still run for diagnostic evidence;
- no relabelling of a known failure as a pass; no filesystem selection used to mask it.

Suite: `ran=506 skipped=0 ok=False` on both python3.12 and python3.11. This part of the D078 "Preserved" claim holds.

---

## 7. Old-fail / new-pass for the two fixes — specified vs observed

| check | D072 observed | D078 predicted | D082 observed |
| --- | --- | --- | --- |
| py_compile 3.11 / 3.12 | OK | OK | **OK** |
| default invocation `python3 run_cloud_stress.py` | FATAL rc=1 | no FATAL; `/tmp/d063-*` 0700 | **no FATAL; `/tmp/d063-…` 0700** |
| dual-order asc | rc=0 (skipped=1) | Ran 1, skipped=0, OK, rc=0 | **rc=1, ran=None (ModuleNotFoundError)** |
| dual-order desc | rc=0 (skipped=1) | Ran 1, skipped=0, FAILED, rc=1 | **rc=1, ran=None (ModuleNotFoundError)** |
| `confirmed_order_sensitive_defect` | False | True | **False** |
| N10 | FAIL | PASS | **FAIL** |
| N1–N9, N11–N18 | 17 PASS | 17 PASS | **15 PASS (N2, N11 FAIL)** |
| overall suite gate | strict FAIL | strict FAIL preserved | **strict FAIL preserved** |

Fix B-D072-1 works behaviourally but costs gates N2/N11; fix B-D072-2 does not work at all.

---

## 8. Independent corroboration

A separate, bounded sub-agent (independent sandbox, own tools) re-derived the two facts from scratch using only the public pinned archive:

- **Fact 1 confirmed:** `TESTNAME.rsplit(".", 1)[0]` = `tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests`; `importlib.import_module` raises `ModuleNotFoundError` ("…'tests.test_partial_scan_review_fixes' is not a package").
- **Fact 2 confirmed:** with `rsplit(".", 2)[0]`, asc = `Ran 1 test … OK` exit 0; desc = `Ran 1 test … FAILED (failures=1)` with `AssertionError: 3 != 2`, exit 1.

Its report and scripts are bundled at `external_verification_report.json`, `external_repro.py`, `external_fact1.py`. These match my own runs exactly.

---

## 9. Bundle contents

`drive-tool/module-006/d082-runner-twofix/`

```
runner/run_cloud_stress.py         PATCHED by D078, sha256 318e2100… (43732 bytes)
runner/README.md                   unchanged (D069), sha256 25b3f5a7…
runner/stress_checks.py            UNCHANGED payload, sha256 8097d0a3…
originals/runner/run_cloud_stress.py   D063 original, sha256 66c9079f…
originals/runner/README.md             D063 original, sha256 bb3fe881…
originals/runner/stress_checks.py      D063 original (identical to payload)
originals/MANIFEST.md                  D063 bundle manifest
originals/tests_test_runner_gates.py   D063 runner gate tests (preserved)
negatives/run_negatives.py         pinned N1–N18 harness (unchanged)
negatives/logs_stdout.txt          raw harness output (py3.12)
negatives/logs/negatives_results.json   machine-readable results (15/18)
sandbox/compile_checks.log         3.11 / 3.12 py_compile results
sandbox/default_invocation.log     default-invocation run (B-D072-1 fixed)
sandbox/workspace_logs/*           full-run logs (summary.json, suite_*.out,
                                   stress_*.out, dual_order_*.out,
                                   readdir_order_confirmation.json,
                                   _dual_order_repro.py, identity.txt, env_*.json, MANIFEST.md)
IDENTITIES.md                      pins + hashes + 26 blob sha1
MANIFEST.md                        sha256 + bytes of every file in the bundle
HASHES.txt                         machine-readable hash list
```

Evidence package: `drive-tool/module-006/d082-runner-twofix-verification/`
(raw logs, scripts, env, hash manifest, report copy, exact patched runner bytes,
external corroboration).

---

## 10. Safety / scope confirmation

- No target run, no target install, no real credentials, no cloud API, no service/reboot/public binding, no merge, no deploy, no re-pin.
- Source under test `b7f8d17…`, its 26 file identities, the payload, `COMMIT`, `EXPECTED_BLOBS` and `STRESS_CHECKS_SHA256` are unchanged; **only `runner/run_cloud_stress.py` was patched**.
- No fix was applied beyond the supplied D078 patch; both defects are reported with minimal reproducers.
- No filesystem selection was used to force the suite to pass; the suite failure is recorded and the overall exit is NONZERO.
- Scope kept to the two runner fixes — no harsh-extension and no HTTP work.
- **Gemini delta acceptance of the D078 runner patch is still required.** On the evidence here, the delta is not acceptable as-is: fix B-D072-2 does not function, and fix B-D072-1 breaks gates N2/N11 via its message reword.

# D072 — corrected-runner assembly and negative verification (summary)

**Status: ASSEMBLED + VERIFIED IN SANDBOX. Two blockers found (B-D072-1, B-D072-2). No target run performed. Gemini security-delta review still required before target bootstrap.**

Scope honoured: this task assembled the D069 runner correction and verified it. Nothing was fixed, no source under test was touched, no target was run, nothing was installed, no credentials used, no merge/deploy, and no HTTP / harsh-extension work was done.

---

## 1. What was assembled

The D069 correction was extracted from its published source and assembled into a separate bundle, preserving the D063 originals. **Only `runner/run_cloud_stress.py` and `runner/README.md` are corrected**; the payload `runner/stress_checks.py` is byte-identical to the D063 original and was **not** edited.

| item | pin / hash |
| --- | --- |
| D069 source (resolved full pin) | `Dolesh-avkalan/drop @ cb20c7c0443817f8714c0c0ce2a43b42f4a1865e`, `drive-tool/module-006/d069-runner-fixes.md` |
| D063 payload source | `Dolesh-avkalan/drop @ a0f5368d62623c5ed939915275f7732cda74011b` |
| Source under test (UNCHANGED) | `Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67` |
| pinned archive sha256 | `93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3` (338575 bytes, 123 members) |
| payload `stress_checks.py` sha256 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` (unchanged) |
| corrected `run_cloud_stress.py` sha256 | `49ce02f378e98dd55aa18c1328a61fa81dea249fcd7010c1d0a717b872c804a5` (42651 bytes) |
| corrected `README.md` sha256 | `25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb` (10367 bytes) |
| original `run_cloud_stress.py` sha256 | `66c9079ff7bb757256bb0a5f70b16293bfb85f3264520d8acbeccce95a81587e` |
| original `README.md` sha256 | `bb3fe881c699fc8bceb26f0c0ffaf1e3e657cbba5d66efdfb89eedbcbdc7c67f` |

The 26 `EXPECTED_BLOBS`, `STRESS_CHECKS_SHA256` and `COMMIT` in the corrected runner are unchanged. All 26 pinned files were independently recomputed from the extracted archive and matched exactly (0 mismatches). Full identity table: `IDENTITIES.md`.

### Assembly note — the D069 README "diff" block is partly mangled

The `runner/README.md — diff` block in `d069-runner-fixes.md` embeds fenced code blocks inside its own ```` ```diff ```` fence, which truncates the diff, and it contains ten literal `@@ options` placeholder lines where a hunk failed to render. Per the D069 note ("README is otherwise unchanged: options block already lists --base-dir and --workdir … enforced in code and documented by the paragraph above rather than by an edit to the options table"), the corrected README was reconstructed by applying the clearly-specified hunks to the exact original D063 README; the **options table is unchanged**, exactly as D069 states. Every other hunk (title, `## The command` paragraph, identity item 5, new item 6, renumbering, the L1–L5 limits paragraph, Outputs, and the Provenance directory-order paragraph) was applied verbatim.

---

## 2. Compile checks (3.11 / 3.12)

```
$ python3.11 -m py_compile runner/run_cloud_stress.py   # OK  (Python 3.11.2)
$ python3.12 -m py_compile runner/run_cloud_stress.py   # OK  (Python 3.12.13)
$ python3.11 -m py_compile runner/stress_checks.py      # OK
$ python3.12 -m py_compile runner/stress_checks.py      # OK
$ python3.11 -m py_compile originals/runner/run_cloud_stress.py  # OK
$ python3.12 -m py_compile originals/runner/run_cloud_stress.py  # OK
```

Raw log: `sandbox/compile_checks.log`.

---

## 3. Negative gates N1–N18 — result: 17/18 PASS

Harness: `negatives/run_negatives.py` (raw output `negatives/logs_stdout.txt`, machine-readable `negatives/logs/negatives_results.json`). Every test has a concrete fixture and a precise assertion; each is run against **both** the pre-D069 (D063) runner and the D069-corrected runner so the old-fail / new-pass contrast is real, not claimed. E2E tests invoke the runner as a subprocess under a hard 120 s outer timeout; unit tests import the runner module and drive the exact function (symlink detection, wall-clock download deadline, output cap, process-group kill, manifest symlink safety, archive guards). Syntax/import failures in the runner under test are recorded as real failures, never masked.

| id | scope | result | observed (D069 corrected) | observed (pre-D069) |
| --- | --- | --- | --- | --- |
| N1 | B3 workspace escape via symlink | PASS | rc=1, `must resolve under /tmp/`, no dir created | rc=1 but created `/var/tmp/ws` (escape) |
| N2 | B3 `--base-dir` outside /tmp | PASS | rc=1, no workspace created | created `/var/tmp/d063-…` |
| N3 | B3 workspace mode | PASS | workdir mode `0o700` | `0o775` |
| N4 | B2 extra file under tests/ | PASS | `FAIL-CLOSED (identity): UNEXPECTED tests/rogue.py`, rc=1 | noted extra, continued past identity |
| N5 | B2 `sitecustomize.py` at root | PASS | `EXECUTABLE_UNEXPECTED sitecustomize.py`, rc=1 | noted extra, continued |
| N6 | B2 unexpected `.so` | PASS | `UNEXPECTED drive_tool/_evil.so`, rc=1 | noted extra, continued |
| N7 | B2 symlink inside src | PASS | `MISSING_OR_LINK drive_tool/listing.py` | symlink to byte-identical copy **accepted** (empty problems) |
| N8 | B2 symlinked directory | PASS | `SYMLINK_DIR escape` | not flagged |
| N9 | B1 suite failure + diagnostic continue | PASS | `suite_diagnostic_continue=True`, `result=FAIL`, smoke+soak+edges ran | aborts before stages on suite failure |
| N10 | B1 dual-order repro | **FAIL** | `asc rc=0 desc rc=0 confirmed=False` — see B-D072-2 | no repro |
| N11 | B1 no filesystem masking | PASS | `--base-dir /mnt` → rc=1 | created workspace under /mnt |
| N12 | L1 wall-clock download deadline | PASS | `RuntimeError: download exceeded wall-clock deadline (1s)` | per-socket timeout only |
| N13 | L2 `--deadline-seconds` propagation | PASS | smoke invoked with `--deadline-seconds 170` | never passed |
| N14 | L3 bounded subprocess capture | PASS | `truncated=True`, captured exactly 8388608 bytes (cap) | unbounded `capture_output=True` |
| N15 | L3 process-group kill | PASS | orphan sentinel **absent**, child state `Z` | orphan sentinel **present** (child survived) |
| N16 | L4 manifest symlink safety | PASS | symlink listed `link -> /etc/passwd`, not hashed, excluded from size | followed the symlink |
| N17 | L5 apparent vs allocated | PASS | both totals in summary; block-based measure matches | apparent only |
| N18 | regression — archive guards | PASS | all 6 malicious archives rejected | already rejected (unchanged) |

N10 is the only failing gate. It is a genuine defect in the D069 correction, not a harness artefact — see blocker B-D072-2.

---

## 4. Full runner sandbox run (baseline + 600 smoke + 10000 soak + edges)

Command (hard outer timeout 280 s):

```
$ python3 run_cloud_stress.py --base-dir /tmp/d072base \
      --archive /scratch/work/archive-b7f8d17.tar.gz
```

Raw stdout: `sandbox/full_run.stdout.log`. Workspace logs: `sandbox/workspace_logs/`.

Environment: Debian 12 (bookworm), gVisor kernel, Python 3.12.13 + 3.11.2, `/tmp` fstype `9p`. Workspace created at `/tmp/d072base/d063-b7f8d17b-nhqnaiw3`, mode `0700`.

| stage | result | detail |
| --- | --- | --- |
| payload identity | PASS | sha256 = pinned |
| archive identity | PASS | 123 members, archive sha256 recorded |
| source identity | PASS | all 26 pinned blobs match; 88 unexpected **non-executable** files (docs/tasks/session `.md`/`.txt`) noted, correctly not fail-closed |
| committed 506 suite (py3.12) | **FAIL** | ran=506 skipped=0 ok=False exit=1 (6.57 s) |
| committed 506 suite (py3.11) | **FAIL** | ran=506 skipped=0 ok=False exit=1 (6.25 s) |
| smoke (600 calls) | PASS | 600 completed, exit 0 |
| soak (10000 calls) | PASS | 10000 completed, exit 0 (23.9 s) |
| edges | PASS | all 19 edge checks true, exit 0 |
| workspace size | recorded | apparent 15972442 B, allocated 16053248 B |
| **overall** | **FAIL (exit 1)** | `suite failed on python3.12`, `suite failed on python3.11` |

The single committed suite failure is the known directory-order-sensitive test; the runner records it as a **FAIL**, sets `suite_diagnostic_continue=True`, still runs smoke/soak/edges for diagnostic evidence, and exits **NONZERO**. It does **not** relabel the failure a pass. This matches the D069 policy.

### Directory-order observations (recorded separately, not used to force a pass)

- Native `/tmp` (9p) readdir order of a probe created `a.txt` before `b.txt`: `['b.txt', 'a.txt']`.
- Failing committed test: `tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged` — `AssertionError: 3 != 2`.
- Dual-order repro: `asc rc=0`, `desc rc=0`, `confirmed_order_sensitive_defect=False` (**see B-D072-2**).
- Full detail: `sandbox/workspace_logs/readdir_order_confirmation.json`, `dual_order_asc.out`, `dual_order_desc.out`, `suite_python3.11.out`, `suite_python3.12.out`.

No filesystem selection was used to mask the failure. On this host `/tmp` returns `b.txt` first, so the suite failure is the expected NONZERO outcome for the pinned `b7f8d17…` revision.

---

## 5. Blockers (no source fixed; minimal reproducers)

### B-D072-1 — the documented default invocation fails on its own containment check

The corrected runner rejects `--base-dir` values whose realpath is exactly `/tmp`, but the default of `--base-dir` **is** `/tmp`:

```python
ap.add_argument("--base-dir", default="/tmp", ...)
...
real_base = os.path.realpath(args.base_dir)
if real_base == "/tmp" or not real_base.startswith("/tmp/"):
    log(f"FATAL: --base-dir must resolve under /tmp/ (got {real_base!r})")
    return 1
```

Minimal reproducer (raw log `sandbox/default_invocation_FATAL.log`):

```
$ python3 run_cloud_stress.py
FATAL: --base-dir must resolve under /tmp/ (got '/tmp')
# exit 1 — no workspace, no stages
```

This contradicts both the README ("That is the whole invocation … creates a fresh unique workspace under `/tmp`") and the runner's own printed "Exact target invocation: `python3 run_cloud_stress.py`". The D065 B3 requirement was to fail-closed on the **workspace** path, not on the base directory. To exercise the pipeline for this task, `--base-dir /tmp/d072base` was used; that workaround is not a fix and is labelled as such. **Suggested correction for review (not applied):** allow `real_base == "/tmp"` for `--base-dir` (keep the `!= "/tmp"` guard only for the final workspace path).

### B-D072-2 — the D069 dual-order repro is a false negative (N10)

The D069 `DUAL_ORDER_REPRO` subprocess shims `os.scandir`/`os.listdir` globally *before* the test module is imported. Importing `tests.test_partial_scan_review_fixes` evaluates `_LOCAL_SUPPORTED = _local_supported()`, which constructs a `LocalAdapter`; the shim replaces `os.scandir` with an object lacking file-descriptor support, so `LocalAdapter` raises `UnsupportedPlatformError` ("LocalAdapter requires file descriptor support for os.scandir") and every test in the module is skipped. The repro therefore reports `asc rc=0, desc rc=0, confirmed=False` even on a host (`/tmp` = 9p) that genuinely returns `b.txt` first.

Evidence:

```
# sandbox/workspace_logs/dual_order_desc.out
test_metadata_failure_below_root_is_skipped_and_charged ... skipped
  'LocalAdapter unsupported on this platform'
Ran 1 test ... OK (skipped=1)          # EXIT=0  -> looks like "desc passes"

# isolated confirmation
LocalAdapter supported WITHOUT shim: True
LocalAdapter supported WITH shim:    False -> LocalAdapter requires file descriptor support for os.scandir
```

So the confirmation flag `confirmed_order_sensitive_defect` can never be set to `true` by the repro as written, and the repro's `desc` leg silently skips instead of failing. **Suggested correction for review (not applied):** shim only the `drive_tool` scan path (or patch `LocalAdapter._os_scandir`) rather than replacing global `os.scandir`, so `_local_supported()` still succeeds; alternatively detect the skip and treat it as an inconclusive/error outcome rather than a pass.

No further defects were found in N1–N18; L1–L5 behave as specified except as noted.

---

## 6. Bundle contents (`drive-tool/module-006/d072-corrected-runner/`)

```
runner/run_cloud_stress.py         corrected (D069), sha256 49ce02f3…
runner/README.md                   corrected (D069), sha256 25b3f5a7…
runner/stress_checks.py            UNCHANGED payload, sha256 8097d0a3…
originals/runner/run_cloud_stress.py   D063 original, sha256 66c9079f…
originals/runner/README.md             D063 original, sha256 bb3fe881…
originals/runner/stress_checks.py      D063 original (identical to payload)
originals/MANIFEST.md                  D063 bundle manifest
originals/tests_test_runner_gates.py   D063 runner gate tests (preserved)
negatives/run_negatives.py         N1–N18 harness
negatives/logs_stdout.txt          raw harness output
negatives/logs/negatives_results.json   machine-readable results
sandbox/compile_checks.log         3.11 / 3.12 py_compile results
sandbox/default_invocation_FATAL.log   B-D072-1 reproducer
sandbox/full_run.stdout.log        full runner run stdout
sandbox/workspace_logs/*           full-run logs (summary.json, suite_*.out,
                                   stress_*.out, readdir_order_confirmation.json,
                                   dual_order_*.out, identity.txt, env_*.json, MANIFEST.md)
IDENTITIES.md                      pins + all hashes + 26 blob sha1
MANIFEST.md                        sha256 + bytes of every file in the bundle
HASHES.txt                         machine-readable hash list
```

---

## 7. Safety / scope confirmation

- No target run, no target install, no real credentials, no cloud API, no service/reboot/public binding, no merge, no deploy.
- Source under test `b7f8d17…` and its 26 file identities are unchanged; the payload is unchanged; only the runner and its README are corrected (D069).
- No filesystem selection was used to force the suite to pass; the suite failure is recorded and the overall exit is NONZERO.
- No fixes were applied to the runner; both blockers are reported with minimal reproducers for review.
- Scope kept to runner assembly/verification — no harsh-extension and no HTTP work.
- **Gemini security-delta review of the D069 runner correction is still required before any target bootstrap.**

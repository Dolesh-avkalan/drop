# D086 identities — runner final two-fix (payload/pins preserved; two files corrected)

## Task

Short mechanical runner correction/verification, following the D082 verification
of the D078 patch. Exactly **two** corrections were applied, and nothing else:

1. **Runner fix (B-D072-2, the one D078 got wrong).** In the embedded
   `DUAL_ORDER_REPRO` script inside `runner/run_cloud_stress.py`, the test
   module name was derived with a one-token strip:

       MODNAME = TESTNAME.rsplit(".", 1)[0]        # BEFORE  (broken)

   With the runner's own `ORDER_SENSITIVE_TEST` value

       tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests.test_metadata_failure_below_root_is_skipped_and_charged

   this yields `tests.test_partial_scan_review_fixes.PostYieldStorageErrorTests`,
   which is not a module, so `importlib.import_module` raised
   `ModuleNotFoundError` before any test ran (both legs `rc=1`, `ran=None`,
   `confirmed=False`). The fix strips two tokens:

       MODNAME = TESTNAME.rsplit(".", 2)[0]        # AFTER   (correct)

   yielding the real module `tests.test_partial_scan_review_fixes`. No other
   line of the runner was touched.

2. **Negative-harness fix (N2 / N11).** The D082 harness asserted the exact
   pre-D078 FATAL substring `"--base-dir must resolve under /tmp/"`. The
   D078-corrected runner emits `"--base-dir must resolve to /tmp or under /tmp/"`,
   so N2 and N11 reported FAIL even though the behaviour (rc=1, fail-closed, no
   artifact) was unchanged. N2 and N11 now assert the **behaviour**
   (`rc == 1` and no workspace created outside `/tmp`) and accept **either**
   wording via a `basedir_rejected()` helper; N11 additionally gained the
   no-artifact check. Behaviour is not weakened — the checks are equal or
   stricter, only the message coupling is removed. No other gate was touched.

## Pins

### Source under test (UNCHANGED)

    Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67

  codeload archive sha256: 93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3
  archive bytes:           338575
  members:                 123

### Bundle being corrected (resolved full pin)

    Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8
      drive-tool/module-006/d082-runner-twofix/

### Patch source of the pre-fix runner (D078, resolved full pin)

    Dolesh-avkalan/drop @ 0aef8e882c0eed2f868832ea4bc07b845c666480  ("relay: d078 (done)")
      drive-tool/module-006/d078-runner-two-fixes.md

## Payload (UNCHANGED, exact D063 / drop@a0f5368)

    runner/stress_checks.py sha256: 8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9
    == STRESS_CHECKS_SHA256 in the runner; identical in originals/ and runner/

## Files in this bundle

    runner/run_cloud_stress.py   CORRECTED by D086   bytes=43732 sha256=f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2
    runner/README.md             unchanged (D069)    bytes=10367 sha256=25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb
    runner/stress_checks.py      unchanged payload    sha256=8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9
    negatives/run_negatives.py   CORRECTED by D086 (N2/N11 only) bytes=26862 sha256=543de9d42cb856aad456b9fb265b2c4b00dd7427debe51cb67c87278e982d02d
    negatives/run_negatives_311.py  identical to run_negatives.py except PY="python3.11" (py3.11 re-run driver)

## Pre-correction runner (D082/D078) — replaced by this correction

    runner/run_cloud_stress.py   bytes=43732 sha256=318e2100fc3a7da718e97768720cf0b5cb49954edd8e879e5c1851ec041cf2d8

## Pre-correction harness (D082) — N2/N11 corrected here

    negatives/run_negatives.py   bytes=26115 sha256=8917b6a1a6056afbae3417b55b6d1a28c4c0ca29f064c0262f984b2156de8b9e

## Preserved originals (D063, drop@a0f5368)

    originals/runner/run_cloud_stress.py sha256=66c9079ff7bb757256bb0a5f70b16293bfb85f3264520d8acbeccce95a81587e
    originals/runner/README.md           sha256=bb3fe881c699fc8bceb26f0c0ffaf1e3e657cbba5d66efdfb89eedbcbdc7c67f
    originals/runner/stress_checks.py    sha256=8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9
    originals/MANIFEST.md                sha256=91132258576c7d27e485e07c5ed97b76ccdef7916a40699c1b58aae87660a121
    originals/tests_test_runner_gates.py sha256=7592d46e1278a855cda9bda7da9e065c1b1a6916bd8aa6c9587dd85eb97e8387

## Runner constants unchanged by the D086 correction

  `COMMIT` = `b7f8d17b9dcc4aec68d54b38f994290e05264e67`
  `STRESS_CHECKS_SHA256` = `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9`
  `EXPECTED_BLOBS` — 26 entries, byte-identical to the D082 runner (verified by
  extracting the block and comparing; `COMMIT`, `EXPECTED_BLOBS` and
  `STRESS_CHECKS_SHA256` are untouched by the one-line `rsplit` fix).

## 26 pinned executable source/test git blob sha1 (UNCHANGED)

| file | git blob sha1 |
| --- | --- |
| `drive_tool/__init__.py` | `9be841b5749acb36c5e362c84b986d98292bae8d` |
| `drive_tool/file_service.py` | `b7e18c606f45066cd54ec66016e70e797486ef50` |
| `drive_tool/listing.py` | `28dddd549c068b00b149a16ad9820445b8af7946` |
| `drive_tool/local.py` | `74a45c61d3ea9c6e64005b1d92834fed17323d62` |
| `drive_tool/local_write.py` | `9824052f349e94f87ee65215ab96e979b4d2a021` |
| `drive_tool/search.py` | `f2d8407df8a98bb92972eecb7e43e653246d4b1a` |
| `drive_tool/service_client.py` | `d04c637de7b7ed2b9be78d5b18fde60519f71579` |
| `drive_tool/service_policy.py` | `3e58f99ab4ad0286838743b25cef138638131305` |
| `drive_tool/storage.py` | `3f4f8dcf50bbf68e97cd807fe40db1ee1bec4576` |
| `tests/test_enumeration.py` | `f7e1eef00de1d82fca7001b64a6af9cfc6d1e667` |
| `tests/test_enumeration_proofs.py` | `e18e02c2252c52a46ef97e733f50ecbcec422878` |
| `tests/test_file_service.py` | `8b5248f9365d8cac6e1331bb4677dea48a1778ff` |
| `tests/test_listing.py` | `8287db88a4b7ff8d956c082e8150c8d169f0f4f7` |
| `tests/test_local.py` | `b3319752edaf92a02993981fcc62d63f63ebb408` |
| `tests/test_local_range.py` | `7fa3f80e97e84d8c8e7ff57c9cf2a950d5534fa9` |
| `tests/test_local_range_proofs.py` | `d217e66b72a40de3bbc042f199db1ab25da341ba` |
| `tests/test_local_write.py` | `85e7bf06357c16ebf499294de9b116fb909e07db` |
| `tests/test_local_write_proofs.py` | `6abf5f1b4bceae58877cb29182f685f71cd4343c` |
| `tests/test_partial_scan.py` | `ca73b0704a13d03e09f28a44c86f52ee76478dec` |
| `tests/test_partial_scan_proofs.py` | `51c990bc26661d98498086371be47cd08764be56` |
| `tests/test_partial_scan_review_fixes.py` | `f110f83c95b846bc853069194ff7759b690ebfca` |
| `tests/test_readonly_core.py` | `1b0f746fd8162a9d27691abf7f5a90492548c4d8` |
| `tests/test_search.py` | `2ef9c5b8f97a9aa1ff912d250612b8fdb53cad29` |
| `tests/test_service_client.py` | `41d94d6ba0a184943ff6c80e1acc3d920ce18034` |
| `tests/test_service_policy.py` | `97bbf75bd967c29a9558514332e12bd3c908e7b9` |
| `tests/test_storage.py` | `2126dde7f32b7c0cd4d1e737ff990ab10954caf5` |

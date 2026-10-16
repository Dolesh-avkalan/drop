# D093 identities — complete-runner publication repair

## Task

Repair the **short, missing artifact publication** left by D086. The D086
summary (`drive-tool/module-006/d086-runner-final-twofix-summary.md`) claimed a
*complete corrected bundle* at `Dolesh-avkalan/drop @
60b826e2ee52a6bc1f471dede75d50c19b880ae6` ("relay: d086"), but the **actual git
tree at that commit never contained it**: only `IDENTITIES.md` and
`sandbox/compile_checks.log` (plus the sibling `…-summary.md`) were published.
The runner bytes, the 18 negative-gate raw logs, the harness scripts, the
`HASHES`/`MANIFEST` and `exactbytes/` were all absent.

D093 reconstructs the **two documented changes** from the D082 bundle
(`Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8`) and
republishes a *complete* bundle whose contents are the ones actually verified in
this run — no file is claimed that was not produced.

## Pins

### Source under test (UNCHANGED — no re-pin, no payload change)

    Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67
    codeload archive sha256 93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3
    archive bytes 338575   members 123

### Bundle reconstructed from (resolved full pin)

    Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8
      drive-tool/module-006/d082-runner-twofix/

### Patch source of the pre-fix runner (D078)

    Dolesh-avkalan/drop @ 0aef8e882c0eed2f868832ea4bc07b845c666480  ("relay: d078 (done)")

### D086 over-claiming commit (inspected, incomplete)

    Dolesh-avkalan/drop @ 60b826e2ee52a6bc1f471dede75d50c19b880ae6  ("relay: d086")
      drive-tool/module-006/d086-runner-final-twofix/  ->  IDENTITIES.md + sandbox/ only

## The two documented changes (reconstructed)

### Change 1 — runner dual-order repro module-name extraction  (EXACT)

    MODNAME = TESTNAME.rsplit(".", 1)[0]   # BEFORE (D082/D078, broken)
    MODNAME = TESTNAME.rsplit(".", 2)[0]   # AFTER  (correct)

Single token; the runner stays 43732 bytes. Reconstructed runner hash
**matches the D086-documented hash exactly**:

    runner/run_cloud_stress.py  bytes=43732  sha256=f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2   (== D086 IDENTITIES)

### Change 2 — negative-harness N2 / N11 message coupling  (BEHAVIOURAL reconstruction)

N2/N11 asserted the exact pre-D078 FATAL substring
`"--base-dir must resolve under /tmp/"`; the D078 runner emits
`"--base-dir must resolve to /tmp or under /tmp/"`. The correction asserts the
**behaviour** via a `basedir_rejected(out)` helper that accepts **either**
wording; N2 keeps `rc == 1` and no workspace created outside `/tmp`; N11 keeps
`rc == 1`, accepts either wording, and gains a no-artifact-under-`/mnt` check.

    negatives/run_negatives.py  reconstructed bytes=26576  sha256=96a34f07d3e14ca315a64a62243ed5c37acd9da37a6a41d2d7246ac1aa3670bc

**HONEST NOTE.** The D086-documented harness hash is
`543de9d42cb856aad456b9fb265b2c4b00dd7427debe51cb67c87278e982d02d` (26862 bytes).
Those exact bytes were **never published** and are not recoverable from any
commit, so this file is a *behavioural reconstruction* from the documented
spec. It is **not** byte-identical to the never-published D086 original and
**this bundle does not claim it is**. Its behaviour is verified equivalent
(18/18 gates on 3.11 and 3.12; N2 detail `rc=1 created=[] rejected_msg=True`,
N11 detail `rc=1 created_under_mnt=[] rejected_msg=True` — identical to the
D086-documented detail strings).

## Unchanged / preserved

    runner/stress_checks.py (payload)  sha256=8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9  (UNCHANGED)
    runner/README.md                   sha256=25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb  (UNCHANGED)
    originals/runner/run_cloud_stress.py  sha256=66c9079ff7bb757256bb0a5f70b16293bfb85f3264520d8acbeccce95a81587e  (D063)
    originals/runner/README.md            sha256=bb3fe881c699fc8bceb26f0c0ffaf1e3e657cbba5d66efdfb89eedbcbdc7c67f  (D063)
    originals/runner/stress_checks.py     sha256=8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9  (D063)
    originals/MANIFEST.md                 sha256=91132258576c7d27e485e07c5ed97b76ccdef7916a40699c1b58aae87660a121
    originals/tests_test_runner_gates.py  sha256=7592d46e1278a855cda9bda7da9e065c1b1a6916bd8aa6c9587dd85eb97e8387

    COMMIT                = b7f8d17b9dcc4aec68d54b38f994290e05264e67   (unchanged)
    STRESS_CHECKS_SHA256  = 8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9  (unchanged)
    EXPECTED_BLOBS        = 26 entries, byte-identical to the D082 runner    (unchanged)

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

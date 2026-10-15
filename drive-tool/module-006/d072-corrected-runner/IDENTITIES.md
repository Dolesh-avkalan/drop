# D072 identities (unchanged pins + corrected-file hashes)

## Source under test (UNCHANGED)

    Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67

  codeload archive sha256: 93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3
  archive bytes:           338575
  members:                 123

## Payload (UNCHANGED, exact D063 / drop@a0f5368)

  runner/stress_checks.py sha256: 8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9
  == STRESS_CHECKS_SHA256 in the runner; identical in originals/ and runner/

## Corrected files (D069)

  runner/run_cloud_stress.py  bytes=42651 sha256=49ce02f378e98dd55aa18c1328a61fa81dea249fcd7010c1d0a717b872c804a5
  runner/README.md            bytes=10367 sha256=25b3f5a7d629bf9d5bae639841bc29286d0b9657166a1dfc6a55f7c5339a6dcb

## Preserved originals (D063, drop@a0f5368)

  originals/runner/run_cloud_stress.py sha256=66c9079ff7bb757256bb0a5f70b16293bfb85f3264520d8acbeccce95a81587e
  originals/runner/README.md           sha256=bb3fe881c699fc8bceb26f0c0ffaf1e3e657cbba5d66efdfb89eedbcbdc7c67f
  originals/runner/stress_checks.py    sha256=8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9

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

All 26 were independently recomputed from the extracted pinned archive and matched
exactly (0 mismatches).


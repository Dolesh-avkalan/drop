# D073 — first actual HTTP integration execution (report)

**Task:** D073. Overlay the exact generated D068 production adapter and the exact
D067 test blob on a NEW integration branch from base `b7f8d17`, execute the real
combined conformance with ZERO adapter-missing skips, report every failure raw,
and run the gated 600/10,000 smoke/soak ONLY if conformance passes.

## 1. Result summary (honest state)

| Item | State |
| --- | --- |
| Integration branch published | **DONE** |
| Exactly two additions vs base (adapter + test) | **DONE** |
| Byte identity of both files to their sources | **DONE** |
| Compile + import on 3.11 and 3.12 | **DONE** |
| Adapter-missing skips | **ZERO** (the 3 remaining skips are gate-by-design) |
| Combined conformance execution | **EXECUTED — FAILED (11 failures, 3 skipped)** on both interpreters |
| 600-call HTTP smoke | **NOT RUN — conformance did not pass; gate holds** |
| 10,000-call six-agent soak | **NOT RUN — gated on a passing smoke** |
| Cloud D071 source-only branch | **untouched** |
| Merge / deploy / installs / real roots | **none** |

No fixes and no weakened assertions were applied. Every failure below is raw.

## 2. Exact source identity and scope

- repo `Dolesh-avkalan/drive-tool`, new branch `feature/module-006b-http-integration`
- base commit `b7f8d17b9dcc4aec68d54b38f994290e05264e67`
- head commit `cc9c994e64a52793949b58699f707c53f47c4369`, tree `e6d4af27b14694d3aad698a1b37fb99b248219ab`
- `drive_tool/http_adapter.py` — blob `02576d59d555afc7afde89fd8e2e63a1c1c43e24`, 37502 bytes,
  sha256 `191ad2be919fabdd2f4ec9edb0820165c2c4358ce05c93574514b5ee30a30ff3`.
  Source: verbatim production FILE block from drop `d068-deepseek-http-adapter.md`
  (resolved pin `a01a8576b7bb34e8a4c8e7e89beee6cb0840405c`). Byte-identical to the
  already-published `feature/module-006b-http-source` blob.
- `tests/test_http_adapter.py` — blob `b571032c3e938abfb2a17f1dde44bb370469e4c4`, 50785 bytes,
  sha256 `de3c67d3405a176ee4ccfcab253083fb0fd7115b7174b569b352fdc747f90272`.
  Source: exact D067 test blob (branch `feature/module-006b-http-tests`, head `e47587a`).
- Scope vs base: exactly two additions (`A drive_tool/http_adapter.py`,
  `A tests/test_http_adapter.py`); no other path changed.

Both files were confirmed byte-identical after fetching the published branch back
and the suite was re-run from those fetched bytes.

## 3. Execution results

| Run | Command | Result |
| --- | --- | --- |
| Focused 57 | `python3.X -m unittest tests.test_http_adapter` | Ran 57, **FAILED (failures=11, skipped=3)** |
| Full suite | `python3.X -m unittest discover -s tests` | Ran 563, **FAILED (failures=11, skipped=3)** |

Identical failures on CPython 3.11.2 and 3.12.13. The prior 506 baseline is
preserved (563 = 506 + 57). The 3 skips are the two opt-in smoke/soak stages plus
one gate-contract test that self-skips when the adapter is present — there are
**no adapter-missing skips**.

## 4. Failures, raw and classified

11 failures, identical on both interpreters. Raw tracebacks are in `logs/focused_*.txt`.

**Group A — 9 failures: malformed payload delegation returns 403 `denied` where the
contract error matrix expects 400 `invalid`.**
`AuthFirstZeroFsTests.test_valid_token_valid_source_bad_payload_invalid_before_lease`;
`FramingRejectionTests.test_all_framing_cases_rejected_400_invalid (case='save_duplicate_key')`;
`PayloadParsingTests.test_deeply_nested_json_does_not_kill_worker`;
`PayloadParsingTests.test_payload_cases_rejected_400_invalid` (cases
`duplicate_keys`, `nan`, `infinity`, `bom`, `invalid_utf8`, `non_object`).
Expected `(400, 'invalid')`, actual `(403, 'denied')`.

Root cause (not fixed): the adapter faithfully implements the adopted auth-first
delegation — for a body that cannot be parsed, `candidate_source_id` is `None` and
the frozen `LocalFileService` maps a non-`str` source_id to `PolicyDeniedError`,
which the adapter surfaces as `403 denied`. When the source_id *is* extractable
from valid JSON (the `missing_key` / `extra_key` cases) the same delegation yields
`400 invalid` and those cases pass. This is a tension between the contract's
delegation rule (delegate with `file_id=None`) and its error matrix (JSON error →
`400 invalid`), i.e. a production/spec divergence — not a test defect and not an
adapter deviation from the delegation rule. Reported, not altered.

**Group B — 1 failure: over-digit-count Content-Length status choice.**
`FramingRejectionTests.test_all_framing_cases_rejected_400_invalid (case='huge_digit_content_length')`:
expected `400`, actual `413`. The adapter rejects an over-long digit count as
`too_large`; the test asserts the matrix `400 invalid`. Reported, not altered.

**Group C — 1 failure: save-uncertainty fault injection.**
`SaveUncertaintyTests.test_post_lease_save_failure_is_uncertain`: `DriveClientError not raised`.
Classified **harness probe-seam mismatch, not a production defect**. The committed
test patches `local_write.LocalWriter._os_link`, but it saves with `overwrite=True`;
`LocalWriter.write_bytes` uses `_os_rename` on the overwrite path and `_os_link`
only on the no-overwrite path, so the injected fault never fires and the save
legitimately succeeds. The scratch diagnostic `scripts/diagnostic_save_seam.py`
(not a test edit) shows:
`patch _os_link overwrite=False -> DriveClientError(unavailable, uncertain=True, retry_safe=False)`;
`patch _os_link overwrite=True -> SAVE SUCCEEDED (no error)` (the failing case);
`patch _os_rename overwrite=True -> DriveClientError(unavailable, uncertain=True, retry_safe=False)`.

## 5. Gates and pending work

- Conformance did not pass, so the 600-call smoke and 10,000-call soak **remain BLOCKED**.
  The D064 fixed thresholds are preserved and the helpers fail closed; the hard outer
  per-stage bound is 15 minutes and teardown runs even on assertion failure.
- No production or test file was edited to change any of the above outcomes.
- Independent Gemini security review remains mandatory and was not performed here.
- Cloud D071 source-only branch was not altered.

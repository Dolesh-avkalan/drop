# D076 — one-test fault-injection correction (report)

**Task:** D076. On a NEW branch from exact `cc9c994e`, correct the single proven-wrong
post-publish save seam in `tests/test_http_adapter.py`, preserve production and the
auth/digit tests unchanged, show targeted oldfail/newpass on both interpreters, verify
the guard is sensitive to a genuinely post-publish failure and that cleanup holds, and
record the full-suite result honestly without claiming a conformance pass.

## 1. Result

| Item | State |
| --- | --- |
| New branch published | **DONE** |
| ONLY `tests/test_http_adapter.py` changed | **DONE** (one file, one test) |
| Production / auth / digit tests untouched | **DONE** |
| Targeted oldfail → newpass, 3.11 and 3.12 | **DONE** |
| Guard sensitive to actual post-publish failure | **DONE** (probe) |
| Cleanup verified (no stale temp file) | **DONE** (probe + in-test assert) |
| Full 563 suite recorded | **DONE** — 10 failures / 3 skipped (still-known, not a pass) |
| Merge / deploy / real roots | **none** |

## 2. Source identity and scope

- repo `Dolesh-avkalan/drive-tool`, branch `feature/module-006b-http-save-test`
- base `cc9c994e64a52793949b58699f707c53f47c4369` (tree `e6d4af27b14694d3aad698a1b37fb99b248219ab`)
- head `f304425ab774158090edd69f1b605bcc3b03096d` (tree `87569b2b8a82c821497d9e784c568d5f75f3e5d7`)
- `tests/test_http_adapter.py` — base blob `b571032c…`, head blob `80798e3200064a09e4c84a2b264c4f764b64599c`,
  51582 bytes, sha256 `23dfe5ddbca815759ac26d378b4c70b84eb9c7374f52131cf328dc687e56f467`
- scope vs base: exactly one modification (`M tests/test_http_adapter.py`); no other path changed.
- verified byte-identical after fetching the published branch back.

## 3. The correction (single test)

`SaveUncertaintyTests.test_post_lease_save_failure_is_uncertain` previously injected its
fault on `LocalWriter._os_link` while saving with `overwrite=True`. The overwrite path
publishes through `_os_rename`, so no fault ever fired and the save legitimately
succeeded. The correction keeps `overwrite=True`, injects on `_os_rename`, performs the
real atomic rename first (so the failure is genuinely post-publish), then raises. The
original assertions (`code == "unavailable"`, `outcome_uncertain` true, `retry_safe`
false) are preserved, and two post-publish assertions are added: the committed bytes are
on disk, and no stale `.drive-tool-tmp-*` file is left behind.

Full unified diff: `logs/patch.diff` (+16/−4, one hunk).

## 4. Targeted oldfail / newpass

One test, both interpreters:

| Run | 3.11 | 3.12 |
| --- | --- | --- |
| base `cc9c994e` (old seam) | FAILED (failures=1) — `DriveClientError not raised` | FAILED (failures=1) |
| head `f304425a` (corrected) | OK | OK |

## 5. Guard sensitivity and cleanup (probe)

`scripts/diagnostic_save_seam_rename.py` (a scratch probe, not a test) runs three
injections against the real adapter over synthetic roots:

```
_os_link (old test seam)   overwrite=True -> SAVE SUCCEEDED (no error) | published=True  bytes=b'FAULT-PAYLOAD' | temp_leftovers=0
_os_rename post-publish    overwrite=True -> DriveClientError(code=unavailable, uncertain=True, retry_safe=False) | published=True bytes=b'FAULT-PAYLOAD' | temp_leftovers=0
_os_rename pre-publish     overwrite=True -> DriveClientError(code=unavailable, uncertain=True, retry_safe=False) | published=False bytes=None | temp_leftovers=0
```

The guard is sensitive to the *actual* publish primitive: only a post-publish failure
leaves the committed bytes on disk, which is exactly what the corrected test asserts.
Cleanup holds in every case (zero stale temp files).

## 6. Full suite (honest)

`python3.X -m unittest discover -s tests` → `Ran 563 tests ... FAILED (failures=10, skipped=3)`
on both 3.11.2 and 3.12.13. This is one fewer failure than the D073 integration run (the
save-uncertain test now passes). The remaining 10 are the still-known auth/digit
divergences (403-vs-400 malformed-payload delegation and 413-vs-400 huge-digit
Content-Length) that D076 does not touch; they are for Gemini to adjudicate separately.
**No conformance pass is claimed.**

## 7. Gates

The 600-call smoke and 10,000-call soak remain BLOCKED (they are opt-in and gated on a
clean conformance). No merge, no deploy, no real roots, no installs.

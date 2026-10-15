# D053 — narrow client transport correction: summary

**Builder/assembler evidence only — not independent acceptance.** No broader source edits, no main
merge, no deployment, no installs, no real credentials/roots.

**Access/pins:** GitHub read + publish confirmed. D053 brief `40c320a6`; contract `tasks/d047-agent-client.md`
`d14b1b7f`; D051 review `drop@ba4029f168d531be52a37155131003ab3b3e8b95`
`drive-tool/module-006/d051-deepseek-client-review.md`; base candidate `81a6485c300f0a9cecc9c902c90360379c17e946`
(left untouched for local D052).

**Branch `feature/module-006a-client-review-fixes`** from `81a6485`, head
`53450a4cb71f555addd94eb5a700c777e7f5b1e6`, tree `48ab4ef31a36ed2d36c8d6dfc5bd75bb90fd0b27`. Only
`drive_tool/service_client.py` and `tests/test_service_client.py` changed; committed files match the
tested tree byte-for-byte.

**Old failure reproduced (before change):** with tiny raw servers, the pinned old client leaked
`TimeoutError` (stalled body) and `http.client.IncompleteRead` (malformed chunk) — `_dispatch` wrapped
only `conn.request()`/`getresponse()`, not the body read in `_read_capped`.

**Fix (narrow):** added `_TRANSPORT_ERRORS = (TimeoutError, http.client.HTTPException, OSError)` and, in
`_dispatch`, mapped those body-read failures through the existing `_wrap_transport` (timeout → `timeout`,
else `unavailable`; write → uncertain True/retry False, read-only → uncertain False/retry True); a parsed
`DriveClientError` propagates unchanged. Cap+1 bounds, close ownership and no-retry preserved. After the
fix the repro returns safe `DriveClientError`s.

**Duplicate-header nits — DISCONFIRMED, no fix.** Probing actual http.client (3.11.2 and 3.12.13) shows
`getheader` **combines** duplicates (`'2, 5'`, `'application/octet-stream, text/plain'`), so the strict
decimal and exact-MIME checks already reject duplicate `Content-Length` and `Content-Type` fail-closed.
Client-level probe on the old tree confirms all duplicate cases → `unavailable`; the single valid control
is accepted. No speculative fix.

**Regressions:** +11 deterministic tests (seam tests via a raising-response fake + tiny raw-socket
stalled / malformed-chunk / truncated-chunk servers). Pure append (216 added, **0 deleted**); the existing
61 client tests are byte-identical.

**Results:** NEW full suite **423 tests OK** on 3.11.2 and 3.12.13; client module 72 tests OK; baseline
`81a6485` 412 OK. **Final tests vs OLD client: 11 errors** on both interpreters (raw leaks, not import
errors).

**Mutations (isolated copies, both interpreters): 7/7 caught, 0 survived**, all real assertion failures —
the six D047-equivalent mutants (unbounded read, lost close, automatic save retry, raw error leak,
cross-request reuse, wrong EOF) plus a precise revert of the new fix (caught by exactly the 11 new tests).
No syntax/import fake positives.

**Evidence bundle:** `drive-tool/module-006/d053-client-review-fixes/` — `D053-REPORT.md`,
`MANIFEST.sha256.txt`, `scripts/`, `logs/`, `env.txt`. Source/tests live on the isolated branch only.

**Blockers:** none. Independent delta review/recheck and integration are the director's to arrange.

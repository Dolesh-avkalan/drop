# d037 — independently verify the MODULE-005A corrections

Exact candidate: e88c9c79fdc27057622d44ba51e008f2e4ea4f4f, feature/module-005a-review-fixes; base 593759a40645386427bad35d53e8b856aeaa68d5. Builder evidence is drop 9e388701dc0786d8df9f46e57a36753868cc26c4 under drive-tool/module-005a/d035-review-fixes/.

Sarvam, continue your independent d034 testing context. Use ONLY the exact correction SHA supplied in my accompanying short message, not a moving branch. Read tasks/d035-partial-scan-review-fixes.md and d034's report/probes. No implementation/test changes on candidate branches, merge or deployment.

Verify scope against 593759a40645386427bad35d53e8b856aeaa68d5: only search.py/local.py, two old completeness test expectations, the new regression file and evidence. Read the final committed regression file, not an earlier in-chat copy. Run the full suite on installed Python 3.11/3.12, zero hidden skips, save exact raw output/counts/exits/tree/source hashes.

Independently run that FINAL regression file against old 593759a in a separate scratch copy and against the exact corrected candidate. Show genuine old-fail/new-pass, explaining each old failure; do not claim old-fail evidence from a preliminary version before its fd-measurement bug was corrected. No source edits to make the result pass.

Re-run your 40 d034 contract checks and convert the six former finding scenarios into positive regression assertions: skipped => incomplete (specific bound reasons retain precedence), invalid ScanFailure.error rejected at every depth, post-yield StorageError count charged with original error/cause preserved. Verify no double wrapping, no sibling after exhaustion, and primary storage failure wins when cleanup also fails. Keep meaningful fd measurements within the same adapter lifetime; distinguish OS fd-number reuse/adapter closure from leaks. Verify old list/read/write behavior remains unchanged.

Independently mutate each of the three new protections in scratch copies and prove the FINAL committed tests detect them; confirm original seven regression protections still detect their mutations if source matching permits, otherwise report precisely why not. Interpret positive fixes as fixes, not as tests that must preserve the original bad flags. Describe mocked extension/seam robustness separately from normal-kernel behavior.

Publish one small review, probe scripts and raw logs under Dolesh-avkalan/drop/drive-tool/module-005a/d037-independent-corrections/, preferably one atomic evidence commit when supported; honest direct-file fallback is fine if connector restrictions block batching. Return ACCEPT/CHANGES REQUIRED with exact findings, commands, counts, source/evidence SHAs. These are sandbox checks, not target-cloud execution. No new installs/private data/service changes; bounded fixtures/probe timeouts. A frontier static review is separate; do not claim it has run.

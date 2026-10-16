# D093 reconstruction notes — what is real, what is recovered, what is not

This bundle exists to repair a **publication gap**, not a code defect. No source
under test was re-pinned, no payload changed, and no new fix was invented.

## 1. What D086 actually published (verified against GitHub)

`GITHUB_GET_COMMIT_OBJECT` for `60b826e2ee52a6bc1f471dede75d50c19b880ae6`
returns message `"relay: d086"`, tree `797593a1…`. Listing
`drive-tool/module-006/d086-runner-final-twofix` at that commit returns **two
entries**: `IDENTITIES.md` and the `sandbox/` directory (which holds only
`compile_checks.log`). The sibling `…-summary.md` is at the module root.

The D086 summary's §9 "Bundle contents" block (runner, originals, negatives,
sandbox/workspace_logs, exactbytes, hashes, MANIFEST, HASHES) was **never
committed**. The claimed `hashes/d086-runner-final-twofix-HASHES.txt`,
`…-MANIFEST.md` and `exactbytes/` do not exist in the repository at any
inspected ref.

**Conclusion:** the missing artifacts are genuinely unrecoverable from the
repository — they were not published. There is no D086 chat transcript available
to this run. The fallback documented in the task was therefore taken:
*reconstruct the two documented changes from the D082 pinned bundle and
re-execute the gates honestly.*

## 2. What D093 recovered exactly

* **Runner change 1** — `rsplit(".", 1)[0]` → `rsplit(".", 2)[0]`. Applied to
  the D082 runner. Resulting sha256 `f58f61dc…` **equals** the D086-documented
  value, byte-for-byte (43732 bytes). This one is exact.

## 3. What D093 reconstructed behaviourally (NOT byte-exact)

* **Harness change 2** — the `basedir_rejected()` de-coupling of N2/N11. The
  original corrected bytes were never published, so they cannot be reproduced
  byte-for-byte from a prose spec. The reconstructed harness is verified
  *behaviourally equivalent*:
  * 18/18 gates PASS on python3.12 and 18/18 on python3.11;
  * N2 detail `rc=1 created=[] rejected_msg=True` and N11 detail
    `rc=1 created_under_mnt=[] rejected_msg=True` — identical to the
    D086-documented detail strings;
  * the gates are equal-or-stricter, never weakened.

  Its sha256 is `96a34f07…` (26576 bytes). The D086-documented value is
  `543de9d4…` (26862 bytes). **These do not match, and this bundle does not
  claim they do.** If a future run locates the original D086 sandbox bytes, the
  harness should be replaced with them and the manifest regenerated.

## 4. Raw evidence regenerated in this run (honest new run)

All logs in this bundle are **new** outputs of this D093 run — none are
inherited from D086 (which published none) and none are the stale D082
pre-fix logs.

* `sandbox/default_invocation.log` — full default runner invocation. Suite
  `ran=506 skipped=0 ok=False` on 3.12 and 3.11 (the known directory-order
  sensitive failure), dual-order `asc rc=0 / desc rc=1 confirmed=True`,
  smoke/soak/edges PASS (diagnostic only), overall `RESULT: FAIL (fail-closed)`
  exit 1.
* `gates/dual_order_asc.out` — `Ran 1 test … OK` (rc 0, 1 test, 0 skips).
* `gates/dual_order_desc.out` — `Ran 1 test … FAILED (failures=1)`,
  `AssertionError: 3 != 2` (rc 1, 1 test, 0 skips).
* `negatives/logs_stdout.txt` / `logs/negatives_results.json` — 18/18 on 3.12.
* `negatives/logs_stdout_py311.txt` / `logs_py311/negatives_results.json` —
  18/18 on 3.11.
* `sandbox/compile_checks.log` — py_compile clean on 3.11 and 3.12.

## 5. Scope honoured

No target run, no deploy, no credentials, no installs, no merge, no re-pin, no
payload change, no HTTP work, no new fix. Source under test
`b7f8d17b…` and its 26 pinned identities are unchanged. Gemini security delta
acceptance remains required and is **not** claimed here.

# d038 — updated bounded target-cloud validation runner (prepared)

**Status: preparation complete. No target execution. No acceptance claimed.**

This bundle prepares a small, runnable validation runner for the exact
drive-tool candidate. It was authored and sandbox-tested by the author; it has
**not** been run on the target. Independent candidate execution (D037) is still
finishing on the local host, and D036 is a static review — neither is a target
run. Nothing here asserts that the candidate passes on the target.

## Pinned candidate

- Repo: `Dolesh-avkalan/drive-tool`
- Commit: `e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`
  ("Apply d035 review corrections: honest completeness, per-depth ScanFailure
  validation, post-yield StorageError charging")
- Tree: `abc0ffb2f561b375cd5166a6bf223d45e3b834c2`
- Archive URL:
  `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`
- Archive SHA-256 (downloaded in sandbox): `97a5035b8775795766c161d5eec240de7f954523894f6c29803b49f8669d7f24`
  (181071 bytes)

## What was adapted

Adapted from the proven d014 runner design
(`drop/drive-tool/readonly-core/d014-cloud-validation/runner/`,
`run_cloud_validation.py`, `kernel_checks.py`, `README.md`), not a new
framework:

1. **Exact archive pin** updated from the d014 commit
   `99e102522da4f0eeee465fe231ad62f0cc4ecad8` to the d038 candidate
   `e88c9c79fdc27057622d44ba51e008f2e4ea4f4f`.
2. **Executable source/test identity list regenerated from GitHub.** The d014
   `EXPECTED_BLOBS` are **not** reused. The list is now **every Python file**
   `unittest` can execute — the `drive_tool/*.py` source and all `tests/*.py`
   modules, including the newly added enumeration / partial-scan / search /
   local-write tests (18 files).
3. **New coverage gate.** After the identity check, the runner walks the
   extracted tree and fails closed if any `*.py` file present is *not* in the
   pinned identity list — so a newly added test can never be silently
   un-verified.
4. **Four new tiny real-filesystem checks** added (see below); the six d014
   real-kernel checks are retained where compatible with the candidate API.
5. **Overall runner invocation timeout guidance** added (recommended 5580 s),
   printed at start and recorded in `summary.json`.
6. Workspace prefix, user-agent and manifest header moved to `d038`.

Nothing in the candidate implementation was changed. No implementation branch
was touched. The runner lives outside the drive-tool implementation, under
`drop/drive-tool/module-005a/d038-cloud-runner/`.

## Executable source/test identity list (git blob sha1)

Verified fail-closed before any execution.

| file | git blob sha1 |
| --- | --- |
| `drive_tool/__init__.py` | `9be841b5749acb36c5e362c84b986d98292bae8d` |
| `drive_tool/listing.py` | `28dddd549c068b00b149a16ad9820445b8af7946` |
| `drive_tool/local.py` | `a0e43e17e60ad72536acea4ca9cfedfd058b9c2b` |
| `drive_tool/local_write.py` | `9824052f349e94f87ee65215ab96e979b4d2a021` |
| `drive_tool/search.py` | `f2d8407df8a98bb92972eecb7e43e653246d4b1a` |
| `drive_tool/storage.py` | `3f4f8dcf50bbf68e97cd807fe40db1ee1bec4576` |
| `tests/test_enumeration.py` | `f7e1eef00de1d82fca7001b64a6af9cfc6d1e667` |
| `tests/test_enumeration_proofs.py` | `e18e02c2252c52a46ef97e733f50ecbcec422878` |
| `tests/test_listing.py` | `8287db88a4b7ff8d956c082e8150c8d169f0f4f7` |
| `tests/test_local.py` | `b3319752edaf92a02993981fcc62d63f63ebb408` |
| `tests/test_local_write.py` | `85e7bf06357c16ebf499294de9b116fb909e07db` |
| `tests/test_local_write_proofs.py` | `6abf5f1b4bceae58877cb29182f685f71cd4343c` |
| `tests/test_partial_scan.py` | `ca73b0704a13d03e09f28a44c86f52ee76478dec` |
| `tests/test_partial_scan_proofs.py` | `51c990bc26661d98498086371be47cd08764be56` |
| `tests/test_partial_scan_review_fixes.py` | `f110f83c95b846bc853069194ff7759b690ebfca` |
| `tests/test_readonly_core.py` | `1b0f746fd8162a9d27691abf7f5a90492548c4d8` |
| `tests/test_search.py` | `2ef9c5b8f97a9aa1ff912d250612b8fdb53cad29` |
| `tests/test_storage.py` | `2126dde7f32b7c0cd4d1e737ff990ab10954caf5` |

## Kernel checks (6 retained + 4 new)

Retained d014 checks (compatible with the candidate API): `nofollow`,
`bounded_read`, `root_anchor`, `dir_symlink_swap`, `fifo`, `fd_lifetime`.

New d038 checks — tiny, real filesystem operations; each prints **REAL** vs
**SIMULATED** so an observational seam is never confused with fault injection:

- **`strict_b_scanner`** (REAL) — wraps the real `os.scandir` iterator in an
  observational seam that counts raw yields and stat calls. Asserts the scan
  pulls exactly `B` raw entries, never probes `B+1`, and stats at most `B`
  entries; a writer-temp-prefixed entry is counted as a yield but never stat'ed.
- **`partial_search`** (REAL + SIMULATED) — a directory of exactly `B` entries
  scanned with budget `B` never observes EOF, so `find` keeps its matches and
  returns `truncated=True, reason="max_entries"`; and (SIMULATED) a
  subdirectory scan that fails mid-iteration is charged, recorded in `skipped`,
  and the pre-fault match is retained (`reason="skipped"`).
- **`write_collision`** (REAL) — a no-overwrite write of an existing name
  raises `AlreadyExistsError`, the original bytes survive, and no temp file is
  left behind.
- **`concurrent_writers`** (REAL) — a bounded set of threads race a no-overwrite
  write of the same name with distinct full payloads: exactly one winner, every
  loser raises `AlreadyExistsError`, and the published file holds the winner's
  exact full payload with no truncation or mixing.

## Operator commands (director, on directortemp)

Preferred (egress available):

```
timeout 5580 python3 run_cloud_validation.py
```

No egress on the target (pre-stage the pinned archive first):

```
timeout 5580 python3 run_cloud_validation.py --archive /path/to/drive-tool-e88c9c79.tar.gz
```

See `OPERATOR-COMMANDS.md` for full detail. The runner creates a fresh unique
workspace `/tmp/d038-e88c9c79-<uniq>`, prints `RESULT: PASS`/`RESULT: FAIL
(fail-closed)`, exits `0` only on pass, keeps the workspace, and prints the exact
`rm -rf <workspace>` cleanup line.

## Sandbox evidence (author-side, not the target)

Environment: Debian 12 sandbox, Python 3.12.13 and 3.11.2. Python 3.14 was
**unavailable in the sandbox and is not claimed**; the target's 3.14 is picked
up automatically when the director runs it.

Happy-path run (pinned archive supplied locally), bundled at
`sandbox/sandbox_happy_run.log`:

- identity OK: all 18 files match pinned blobs
- python coverage OK: all 18 executable `.py` files are pinned
- suite `python3.12`: ran=274, skipped=0, OK
- suite `python3.11`: ran=274, skipped=0, OK
- all 10 kernel checks: PASS on both interpreters
- `RESULT: PASS`

Negative gates (each fails closed, exit non-zero), bundled as
`sandbox/neg_*.log`:

| gate | input | observed |
| --- | --- | --- |
| `neg_tampered_archive` | pinned file mutated | `FAIL-CLOSED (identity): MISMATCH drive_tool/local.py` |
| `neg_path_traversal` | archive member `top/../evil.txt` | `FAIL-CLOSED (extract): unsafe path in archive` |
| `neg_symlink_member` | archive symlink member | `FAIL-CLOSED (extract): link member in archive` |
| `neg_missing_archive` | non-existent archive path | `FAIL-CLOSED (archive): FileNotFoundError` |
| `neg_unpinned_python` | extra `tests/test_extra_unpinned.py` | `FAIL-CLOSED (python coverage): UNPINNED tests/test_extra_unpinned.py` |
| `neg_workdir_reuse` | pre-existing `--workdir` | `FATAL: workspace ... already exists; refusing to reuse` |

Full per-interpreter suite output, per-check output, environment captures and
the workspace manifest are bundled under `sandbox/workspace_logs/`.

## Script SHA-256 / length manifest

| script | bytes | sha256 |
| --- | --- | --- |
| `run_cloud_validation.py` | 26489 | `b2c0cd3ae6177f240f8ccee90e3203e65a039283c8a38e7d06119d5108b5053f` |
| `kernel_checks.py` | 29207 | `b86e09b3a2e4386883445db2afccce6c2cded9d7666c0dc903e0db8b004e476d` |

The full bundle manifest (all files, bytes, sha256) is `MANIFEST.md` in the
bundle folder.

## Honest limitations

- The runner has **not** executed on `directortemp`. No target result exists or
  is claimed. Independent candidate execution is still running on the local
  host.
- Python 3.14 is not available in the author's sandbox; the sandbox run covers
  3.11 and 3.12 only. The runner will exercise 3.14 on the target.
- No acceptance is claimed (D036 is a static review; D037 is not complete).
- No merge, no deploy, no service change, no reboot, no package installation,
  and no changes to existing evidence.

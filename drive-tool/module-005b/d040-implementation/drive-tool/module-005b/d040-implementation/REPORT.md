# D040 / MODULE-005B — Bounded Local Range Reads — Implementation Drop (Sarvam)

Builder drop for the MODULE-005B task. It contains the published feature-branch
source/tests, the raw test and mutation logs, the mutation runner, and this
report. It is the assembler's own builder run and makes **no independent
acceptance claim**; review and merge approval are owned by the director.

## 1. Task and authorization

- Task: `Dolesh-avkalan/drive-tool` `tasks/MODULE-005B.md`
  @ `18cc50f613e582e8bcaa9f282bd61b6ea48f1143`.
- Scope: implement an optional `LocalAdapter.read_range` capability plus the
  frozen `RangeReadResult` value object; change only four allowed paths; run the
  committed full suite; supply a focused mutation check; publish on an isolated
  feature branch with no merge or deployment.

## 2. Base and branch

| Role | Value |
| --- | --- |
| Base commit | `03a8250a5d02823812533290356cf375b7d2c33e` — "Record approved partial-scan integration" |
| Base tree | `3332be94c547e606a31456bb0deb5c6a5c8fbbc2` |
| Base commit parent | `0d9aa8f593e460e3e016114fcde0dc8fc7160951` (approved MODULE-005A PR #4 merge, per `session/DECISIONS.md` D023) |
| Feature branch | `feature/module-005b-range-read` (created from the base commit) |
| Branch head | `121faf848b2f33f80721239fc7716adba7a9ba62` |
| Assembler | Sarvam |

`main` (`drive-tool`) was not modified, nothing was merged and nothing was
deployed.

## 3. Changed paths (exactly the four allowed)

| Path | Change | Blob SHA |
| --- | --- | --- |
| `drive_tool/local.py` | modified | `74a45c61d3ea9c6e64005b1d92834fed17323d62` |
| `tests/test_local_range.py` | added | `7fa3f80e97e84d8c8e7ff57c9cf2a950d5534fa9` |
| `tests/test_local_range_proofs.py` | added | `d217e66b72a40de3bbc042f199db1ab25da341ba` |
| `docs/evidence/MODULE-005B.md` | added | `4292b6903ef072b48116437b0cd3e14868e678a8` |

A base→head compare reports `ahead_by: 4`, `behind_by: 0`, with exactly these
four files changed. The source/test blobs were re-fetched from the branch and
their SHA-256 matched the local candidate byte-for-byte.

## 4. Commits on the feature branch

| # | Commit | Message |
| --- | --- | --- |
| 1 | `2fe70a904e39d6f39b5648ffedbf10d6d9d35873` | Add LocalAdapter.read_range and RangeReadResult (MODULE-005B) |
| 2 | `433765cd5a6306a1a4612bec827397309714ca8a` | Add MODULE-005B read_range contract/boundary/cleanup tests |
| 3 | `ecda94e22f73f5082f06ed1200383181a2f0fee9` | Add MODULE-005B read_range adversarial proofs |
| 4 | `121faf848b2f33f80721239fc7716adba7a9ba62` | Add MODULE-005B evidence report (Sarvam) |

## 5. Test results

Command (both interpreters, from the repository root):

```
python3.11 -m unittest discover -s tests -v
python3.12 -m unittest discover -s tests -v
```

| Interpreter | Count | Final line | Exit | Skips |
| --- | --- | --- | --- | --- |
| Python 3.11.2 | `Ran 351 tests in 2.504s` | `OK` | 0 | 0 |
| Python 3.12.13 | `Ran 351 tests in 2.774s` | `OK` | 0 | 0 |

351 = 274 pre-existing tests + 77 new (`test_local_range.py` 62,
`test_local_range_proofs.py` 15). Every pre-existing test passes unchanged.
Raw logs: `raw/full_suite_python3.11.log`, `raw/full_suite_python3.12.log`.

## 6. Mutation check

Each mutant was applied to an isolated copy of the candidate tree, the full
351-test suite was run, and the copy was discarded. Results are identical on
Python 3.11.2 and 3.12.13. **7 mutants, 7 caught, 0 survivors.**

| # | Mutation | Caught by (count) |
| --- | --- | --- |
| M1 | read_bytes-and-slice (whole read + slice; inherits whole-size rejection) | 25 tests |
| M2 | unbounded `pread` request | 18 tests |
| M3 | early stop on a short nonempty read | 9 tests |
| M4 | EOF derived from `observed_size` | 3 tests |
| M5 | file open flags drop `O_NOFOLLOW` | 7 tests |
| M6a | `read_range` does not release its descriptors | 5 tests |
| M6b | cleanup close failure masks the primary read error | 2 tests |

Raw per-mutant logs: `raw/mutation_*.log`; summaries:
`raw/mutation_summary_python3.11.log`, `raw/mutation_summary_python3.12.log`.
Runner: `scripts/mutation_runner.py`
(SHA-256 `e9e4ed5db6a671093a4fe0f21dca671621bf8afc6bfa97861040e4df5118e14b`).
Mutants are never committed to the implementation.

## 7. Environment

- OS: Debian GNU/Linux 12 (bookworm), x86_64, non-root uid 1000.
- Python 3.11.2 and Python 3.12.13 (stdlib only; no new dependency).
- No 3.13/3.14 interpreter installed; none installed or claimed.
- No real roots, credentials, services or network targets were touched.

## 8. Artifact manifest

`MANIFEST.txt` lists every artifact in this drop (path, byte size, SHA-256),
except itself. It was generated over the exact bytes published here.

## 9. Limitations (honest)

- This is a builder run only. There is no independent reviewer execution and no
  target-cloud result in this drop; the branch is not merged and nothing is
  deployed.
- Validation-order judgement: source/state checks and `file_id` parsing keep the
  same relative precedence as `read_bytes`, then option validation and the
  `os.pread` capability gate run before any filesystem syscall. This is stated
  in the evidence report for review.
- `eof_observed` is a per-call observation, never a snapshot/version/content-hash
  promise; repeated calls may see different file versions.
- `max_read_bytes` bounds each range call; `read_bytes` still rejects whole files
  larger than its cap.
- The capability requires a callable `os.pread`; absent it, `read_range` raises
  `UnsupportedPlatformError` while construction and `read_bytes` keep working.
- Infinite repeated `EINTR`/blocked kernel I/O is not hard-cancelled; no global
  lock or hard syscall deadline is claimed.

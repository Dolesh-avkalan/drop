# D071 — HTTP source assembly (report)

Short mechanical assembly only. Extract the complete production Python block from the
D068 DeepSeek source verbatim, publish it on an isolated single-file branch, compile and
import it, and rerun the accepted baseline suite. No production fixes, no new tests, no
merge, no deploy, no real roots, and no HTTP execution.

## 1. Exact pins

| Role | Repository | Commit | Notes |
|---|---|---|---|
| Source artefact | `Dolesh-avkalan/drop` | `a01a8576b7bb34e8a4c8e7e89beee6cb0840405c` | short `a01a857`, message `relay: d068 (done)` |
| Source file | `Dolesh-avkalan/drop` | same | `drive-tool/module-006/d068-deepseek-http-adapter.md` |
| Accepted base | `Dolesh-avkalan/drive-tool` | `b7f8d17b9dcc4aec68d54b38f994290e05264e67` | merge of PR #8 (`feature/module-006a-service-client-int`) |
| Accepted base tree | `Dolesh-avkalan/drive-tool` | `4a4e27b9d3f75ffd7c841aa547eacef82734596e` | tree of the base commit |

Source file pin resolved: the short ref `a01a857` resolves to the full commit
`a01a8576b7bb34e8a4c8e7e89beee6cb0840405c`. The source file was fetched at that exact
commit and is byte-identical to the copy on `drop` `main`:

- size `38250` bytes
- sha256 `7a62b94c3b1d58163a34b7b8fe2b50c3ba172c4d30ab7e8b91187beb5b4673b6`

## 2. Verbatim extraction

The source markdown contains exactly one fenced Python block (opening fence ```` ```python ````
at markdown line 16, closing fence at line 1116). The block body — markdown lines 17..1115 —
was taken verbatim; nothing was rewritten, reformatted, or repaired.

| Property | Value |
|---|---|
| Extracted bytes | `37502` |
| Extracted lines | `1099` |
| sha256 | `191ad2be919fabdd2f4ec9edb0820165c2c4358ce05c93574514b5ee30a30ff3` |
| git blob sha | `02576d59d555afc7afde89fd8e2e63a1c1c43e24` |

The git blob sha returned by the publish API equals the sha computed locally over
`b"blob <len>\0" + bytes`, which confirms the published content round-tripped byte-exact.

## 3. Continuation completeness

The D068 answer is a single, complete response (one `## Answer` with one code fence; the file
ends at the closing fence with no trailing prose). Checks on the extracted artefact:

- `ast.parse` succeeds.
- Exactly one public top-level class `DriveHTTPAdapter` (32 methods), plus the five internal
  helpers (`_ReqErrorSignal`, `_TimeoutSignal`, `_DisconnectSignal`, `_ParsedRequest`,
  `_WorkerSlot`) and four module helpers (`_no_dup_keys`, `_no_nan_inf`, `_parse_json_strict`,
  `_parse_header_line`).
- `tokenize` completes with no unterminated string or bracket — no truncated middle.
- `__all__` (17 names) is fully defined at module level; all 16 contract constants present.
- Final source line is a complete statement: `self._safe_write(conn, head + data)`.

No missing or truncated middle was found. Raw output: `logs/completeness_ast.txt`.

## 4. Compile / import

| Interpreter | py_compile | import | exports |
|---|---|---|---|
| CPython 3.11.2 | OK | OK | 17 |
| CPython 3.12.13 | OK | OK | 17 |

Raw output: `logs/compile_import_3.11.txt`, `logs/compile_import_3.12.txt`.

## 5. Baseline506 rerun

The accepted baseline suite was run before and after adding the adapter, on both
interpreters. Adding `drive_tool/http_adapter.py` adds no test module, so the collected
count is unchanged.

| Run | Interpreter | Collected | Result | Exit |
|---|---|---|---|---|
| pre (no adapter) | 3.12.13 | — | 506 passed, 135 subtests passed | 0 |
| pre (no adapter) | 3.11.2 | — | 506 passed, 135 subtests passed | 0 |
| post (adapter added) | 3.12.13 | 506 | 506 passed, 135 subtests passed | 0 |
| post (adapter added) | 3.11.2 | 506 | 506 passed, 135 subtests passed | 0 |

Raw output: `logs/pytest_baseline_{311,312}_{pre,post}.txt`, `logs/collect_{311,312}.txt`.
Discovery method: `pytest tests/ --collect-only -q` (506 tests collected).

**The 506 baseline tests do not exercise the adapter.** There is no `tests/test_http_adapter.py`
on this branch; the D067 conformance tests live separately on
`feature/module-006b-http-tests`. This run therefore only confirms the accepted suite is
unaffected by the added module.

## 6. Publication

Branch `feature/module-006b-http-source` created from the exact accepted base
`b7f8d17b9dcc4aec68d54b38f994290e05264e67`, carrying one new file:

| Item | Value |
|---|---|
| Branch | `feature/module-006b-http-source` |
| Head commit | `d59bef9e343816c6d266cfbffa6b4c4d8200e3c4` |
| Commit tree | `0e962bcd6cc25e3615cee938e42f38ace9d22857` |
| File blob | `02576d59d555afc7afde89fd8e2e63a1c1c43e24` |
| Path | `drive_tool/http_adapter.py` (mode `100644`) |
| Parent | `b7f8d17b9dcc4aec68d54b38f994290e05264e67` |

Diff base..head: `ahead_by 1`, `behind_by 0`, files changed = `1 added`,
`drive_tool/http_adapter.py`, `+1099 / -0`. Nothing else changed.

Published file read back from the branch: `37502` bytes, sha256
`191ad2be919fabdd2f4ec9edb0820165c2c4358ce05c93574514b5ee30a30ff3` — byte-identical to the
extracted artefact.

## 7. Scope compliance

- Only `drive_tool/http_adapter.py` was added; no client/backend/policy/storage edits.
- No test files added or edited; no production fixes; source kept verbatim.
- No merge, no deploy, no real roots, no public binding.
- The adapter was never executed: no server was started and no socket/HTTP request was made.
  No HTTP behaviour is claimed tested or accepted.

## 8. Limitations

- No HTTP request/response path was exercised (as instructed). Compile/import and the
  unchanged baseline suite are the only execution evidence.
- The adapter is not covered by the 506 baseline tests.
- pytest 9.1.1 was installed in-session for 3.12; for 3.11 pytest was supplied via
  `PYTHONPATH`. Interpreter patch levels: 3.11.2 and 3.12.13 (see `environment.txt`).

## 9. Files in this bundle

- `http_adapter.py` — the extracted verbatim artefact (the published blob content).
- `REPORT.md` — this report.
- `MANIFEST.md` — sha256 + size of every file here.
- `environment.txt` — interpreter/OS/pytest versions and UTC timestamp.
- `logs/` — raw compile/import, completeness, collection and pytest output.

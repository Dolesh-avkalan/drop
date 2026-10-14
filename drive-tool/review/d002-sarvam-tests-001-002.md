# Independent test run — drive-tool MODULE-001 & MODULE-002

**Task:** Independent test run for the drive-tool project (repository `Dolesh-avkalan/drive-tool`).
**Constraint honoured:** no branch of `Dolesh-avkalan/drive-tool` was modified and nothing was pushed to it. The clone was used read-only; all four test runs were executed on detached-HEAD checkouts of the exact commits named below.

- Date of run: 2026-10-14
- Runner environment: Debian 12 (bookworm), x86_64, non-root sandbox
- git version: `git version 2.39.5`
- Clone source: `https://github.com/Dolesh-avkalan/drive-tool.git`

## Python interpreters actually used

| Label used in this report | Interpreter binary | `--version` output |
|---|---|---|
| Python 3.11 | `python3.11` | `Python 3.11.2` |
| Python 3.12 | `python3.12` | `Python 3.12.13` |

Both interpreters were already installed in the environment; nothing needed to be installed. The bare `python3` on this machine resolves to 3.12.13, so the version-specific binaries `python3.11` and `python3.12` were invoked explicitly to guarantee each version was exercised. The `--version` outputs above are the exact strings printed.

## Commits checked out

| Module | Branch named in task | Commit SHA | Subject | Author date |
|---|---|---|---|---|
| MODULE-001 | `feature/module-001-storage-contract` | `194d4ad57de6dd895c6eaaf7faf4d08583eab02b` | Implement MODULE-001 storage contract and in-memory adapter | Tue Oct 6 22:25:24 2026 +0530 |
| MODULE-002 | `feature/module-002-listing` | `bfbae511a538cff22b642fcd771b7a189029f7e8` | Implement MODULE-002 paginated listing helper | Tue Oct 6 22:42:34 2026 +0530 |

Each commit was verified to exist in the clone (`git cat-file -t` returned `commit`) before checking it out.

## Results summary

| Commit | Python | Command | Tests run | Passed | Failed | Skipped | Errors | Result |
|---|---|---|---|---|---|---|---|---|
| MODULE-001 `194d4ad` | 3.11.2 | `python3.11 -m unittest discover -s tests -v` | 36 | 36 | 0 | 0 | 0 | OK |
| MODULE-001 `194d4ad` | 3.12.13 | `python3.12 -m unittest discover -s tests -v` | 36 | 36 | 0 | 0 | 0 | OK |
| MODULE-002 `bfbae51` | 3.11.2 | `python3.11 -m unittest discover -s tests -v` | 71 | 71 | 0 | 0 | 0 | OK |
| MODULE-002 `bfbae51` | 3.12.13 | `python3.12 -m unittest discover -s tests -v` | 71 | 71 | 0 | 0 | 0 | OK |

Passed counts are the number of `... ok` lines; there were no `FAIL`, `ERROR`, or `skipped` lines in any run. Every run exited with status code 0. No test failed, so there are no tracebacks to paste.

## MODULE-001 — `194d4ad57de6dd895c6eaaf7faf4d08583eab02b`

Working tree at this commit: `README.md`, `docs/evidence/MODULE-001.md`, `drive_tool/__init__.py`, `drive_tool/storage.py`, `tasks/MODULE-001.md`, `tests/test_storage.py`.

### Python 3.11 — `python3.11 -m unittest discover -s tests -v`

`python3.11 --version` → `Python 3.11.2`

Ran 36 tests. 36 passed, 0 failed, 0 skipped, 0 errors. Exit code 0.

Final lines verbatim:

```
----------------------------------------------------------------------
Ran 36 tests in 0.007s

OK
```

### Python 3.12 — `python3.12 -m unittest discover -s tests -v`

`python3.12 --version` → `Python 3.12.13`

Ran 36 tests. 36 passed, 0 failed, 0 skipped, 0 errors. Exit code 0.

Final lines verbatim:

```
----------------------------------------------------------------------
Ran 36 tests in 0.006s

OK
```

## MODULE-002 — `bfbae511a538cff22b642fcd771b7a189029f7e8`

Working tree at this commit adds `docs/evidence/MODULE-002.md`, `drive_tool/listing.py`, and `tests/test_listing.py` on top of MODULE-001.

### Python 3.11 — `python3.11 -m unittest discover -s tests -v`

`python3.11 --version` → `Python 3.11.2`

Ran 71 tests. 71 passed, 0 failed, 0 skipped, 0 errors. Exit code 0.

Final lines verbatim:

```
----------------------------------------------------------------------
Ran 71 tests in 0.055s

OK
```

### Python 3.12 — `python3.12 -m unittest discover -s tests -v`

`python3.12 --version` → `Python 3.12.13`

Ran 71 tests. 71 passed, 0 failed, 0 skipped, 0 errors. Exit code 0.

Final lines verbatim:

```
----------------------------------------------------------------------
Ran 71 tests in 0.026s

OK
```

## Raw output files

Full verbatim stdout+stderr for each of the four runs is included alongside this report:

- `d002-sarvam-tests-001-002/m001-py311.txt` — MODULE-001, Python 3.11.2
- `d002-sarvam-tests-001-002/m001-py312.txt` — MODULE-001, Python 3.12.13
- `d002-sarvam-tests-001-002/m002-py311.txt` — MODULE-002, Python 3.11.2
- `d002-sarvam-tests-001-002/m002-py312.txt` — MODULE-002, Python 3.12.13

Each file contains the complete per-test line output and the summary footer exactly as produced.

## Notes and limitations

- Nothing in this task could not be run. All four required runs executed successfully; no result here is summarised from anything I did not directly observe.
- Only `python3 -m unittest discover -s tests -v` was run, as instructed. No other test runner, linter, or coverage tool was invoked.
- Test execution times vary slightly between runs; the values quoted above are those recorded in the saved raw output files for the final run of each combination.

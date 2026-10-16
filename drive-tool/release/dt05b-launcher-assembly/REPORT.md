# dt05b-sarvam — drive-tool `serve` launcher: assembly & test

**Report lines (from the captured outputs):**

```
BRANCH: feature/serve-launcher @ aedde796fc690214b9d2d8a93b05d2113d712bda
SUITE: FAIL (603 tests run, 1 failure, 3 skipped)
LIVE: FAIL (token "secret123" rejected by DriveClient before any request: ValueError "token length must be in 32..256")
```

---

## Summary

I assembled the reviewed launcher change into `drive-tool` on branch
`feature/serve-launcher`, ran the test suite and the live check as the
non-root user (uid 1000), and report exactly what the outputs showed.

Both checks FAIL. Neither failure is in the launcher's own logic — both are
caused by defects in the material under test:

1. **The suite fails on the change's own new end-to-end test.** The new
   `tests/test_serve.py::test_run_end_to_end` asserts `"entries" in listing`,
   but the drive-tool wire contract returns the key **`items`** (see
   `drive_tool/file_service.py`, and every pre-existing test, which all use
   `items`). 1 of the 603 discovered tests therefore fails. The review
   (`dt04-launcher-review.md`) states VERDICT: ACCEPT and says the e2e test
   "lists/saves/reads ... and confirms return code 0"; it does not — it fails
   on the very first assertion.
2. **The live check as specified cannot complete**, because the token it names,
   `secret123`, is 9 characters, below the **32–256 character minimum**
   enforced by both `DriveClient.__init__` and the server's policy/auth layer.
   The launcher passes the *identical* check when given a spec-compliant
   (≥32-char) token, so the launcher itself is fine; the check's token is not.

The two new files were copied **verbatim** (byte-identical, SHA-256 verified)
from `dt02-serve-launcher.md` into `drive_tool/serve.py` and
`tests/test_serve.py`; no other changes were made.

---

## Inputs

- `Dolesh-avkalan/drop@main: drive-tool/release/dt02-serve-launcher.md`
  (implementation — the two `FILE:` blocks).
- `Dolesh-avkalan/drop@main: drive-tool/release/dt04-launcher-review.md`
  (review — VERDICT: ACCEPT, no blockers).

Both were read directly from GitHub before starting.

## 1. Branch

- Cloned `https://github.com/Dolesh-avkalan/drive-tool` (default branch `main`).
- Created branch `feature/serve-launcher` from `main`.
- Copied the two `FILE:` blocks verbatim into `drive_tool/serve.py` and
  `tests/test_serve.py` (verified byte-identical with `cmp` against the
  extracted blocks; SHA-256 of the pushed files matches the local files).
- No other changes.

**Pushed branch head commit:**
`aedde796fc690214b9d2d8a93b05d2113d712bda`
(`feat: add serve launcher and tests`).

Note on method: the sandbox has no git credentials, so the branch was created
and the single commit was pushed through the GitHub API (`commit_multiple_files`,
`base_branch=main`). The result is a normal branch containing exactly the two
files, verified by re-fetching both files from
`raw.githubusercontent.com/.../feature/serve-launcher/...` and comparing
SHA-256 hashes — they match the local copies exactly.

## 2. Test suite (non-root, uid 1000)

Command (exactly as requested):

```
python3 -m unittest discover -s tests
```

Captured output (`suite.txt`, run as uid 1000):

```
......................................................................../scratch/work/drive-tool/tests/test_http_adapter.py:363: ResourceWarning: unclosed file <_io.TextIOWrapper name='/scratch/work/drive-tool/drive_tool/http_adapter.py' mode='r' encoding='utf-8'>
  src = open(m.__file__, encoding="utf-8").read()
ResourceWarning: Enable tracemalloc to get the object allocation traceback
....................................s.ss...........................................................................................................................................................................................................................................................................................................................F...............................................................................................................................................................................
======================================================================
FAIL: test_run_end_to_end (test_serve.ServeEndToEndTests.test_run_end_to_end)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/scratch/work/drive-tool/tests/test_serve.py", line 243, in test_run_end_to_end
    self.assertIn("entries", listing)
AssertionError: 'entries' not found in {'items': [{'ref': {'source_id': 'work', 'file_id': 'p/hello.txt'}, 'name': 'hello.txt', 'parent_id': 'root', 'kind': 'file', 'size_bytes': 11}], 'next_offset': None}

----------------------------------------------------------------------
Ran 603 tests in 12.435s

FAILED (failures=1, skipped=3)
```

**Result: FAIL — 603 tests run, 1 failure, 3 skipped.** The 3 skips are
pre-existing; the only failure is the new `test_run_end_to_end`.

Secondary observation: the `discover` process **prints the summary and then
does not terminate**. The failing e2e test never reaches `stop.set()`, so
`run()` stays blocked in `stop.wait()` and the `DriveHTTPAdapter` it started
keeps its non-daemon accept/worker threads alive, which prevents the
interpreter from exiting. I had to bound the run with `timeout` (exit code 124
after the summary was already printed). A green suite would not have this
problem; the hang is a direct consequence of the same failing test.

## 3. Live check (non-root, uid 1000)

Procedure followed as specified: temp root dir with a file; a config with port
`18765` and one agent whose `token_sha256` comes from
`echo -n secret123 | python3 -m drive_tool.serve --hash-token`; `chmod 600`;
the launcher started (as a child process of the foreground harness, since the
sandbox forbids shell background jobs); then `DriveClient(port=18765,
token="secret123")` to list and read; then SIGTERM.

- `--hash-token` printed
  `fcf730b6d95236ecd3c9fc2d92d7b6b2bb061514961aec041d6c7a7192f592e4`, which
  **equals `sha256("secret123")`** — the hash function is correct.
- The launcher started and printed
  `drive-tool listening on 127.0.0.1:18765 (1 agents)`.
- `DriveClient(port=18765, token="secret123")` raised
  **`ValueError: token length must be in 32..256`** before any request was
  sent, so the root was never listed and the file never read.
- SIGTERM was sent; the launcher **exited with code 0**.

So the live check as specified is **FAIL** (the list/read never happened). The
exit-code requirement (0) did hold.

Because the failure is purely the token length, I also ran the *identical*
procedure with a compliant 40-character token (`"A"*40`, hash
`f0a2fb80ac0699075fb6c7b0ee2bcc204a1d909ee3149571216ec9cc1d4b9f8e`):

```
list('work','root') -> keys=['items', 'next_offset'] items=1
read('work','p/hello.txt') -> data=b'hello from live check' eof=True
SIGTERM sent; process exit code = 0
```

That variant **PASSES**: the launcher serves on loopback, the client lists and
reads through it, and shutdown on SIGTERM returns 0. The launcher works; the
check's token does not.

## Findings

1. **BLOCKER (in the change's test, not the launcher):** `tests/test_serve.py`
   line 243 asserts `"entries"` but the service returns `"items"`. The new e2e
   test fails; the suite is not green. Fixing it would mean editing the code,
   which this task forbids.
2. **BLOCKER (in the check spec):** the live check's token `secret123` (9 chars)
   violates the 32–256 char minimum enforced by `DriveClient` and the
   policy/auth layer, so the check cannot run as written.
3. **NIT:** the `discover` command hangs after printing its summary, because the
   failing e2e test leaks the adapter's non-daemon threads.

Neither finding is about the launcher's config validation, hashing, startup,
or shutdown — those all behave as the review described. The review's ACCEPT
verdict is nonetheless not reproducible: its claimed passing e2e test does not
pass.

## Reproduction

```
git clone https://github.com/Dolesh-avkalan/drive-tool
cd drive-tool && git checkout feature/serve-launcher
python3 -m unittest discover -s tests        # 603 tests, 1 failure, 3 skipped
python3 live_check.py                        # see REPORT/live_check.py
```

# dt05 — drive-tool serve launcher: assembly and test

Assembled the reviewed launcher change (dt02, accepted by dt04) onto branch
`feature/serve-launcher` and ran the test suite plus a live loopback check as
the non-root `sandbox` user. Nothing in `drive-tool` was edited beyond copying
the two `FILE` blocks verbatim.

## Report lines

```
BRANCH: feature/serve-launcher @ aedde796fc690214b9d2d8a93b05d2113d712bda
SUITE: FAIL (603 tests, 1 failure, 3 skipped)
LIVE: FAIL (as specified — DriveClient(port=18765, token="secret123") raised ValueError: token length must be in 32..256, so list/read could not run; the server started and exited 0 on SIGTERM)
```

## What was assembled

Both files were extracted directly from the markdown in
`drive-tool/release/dt02-serve-launcher.md` (the text between each ```python
fence, byte-for-byte):

| file | sha256 |
| --- | --- |
| `drive_tool/serve.py` | `5b07b09eec799aa0791a785483a923410cba2f8abea64f8c7b54ed22afaf0c3b` |
| `tests/test_serve.py` | `95c782e4009d1cca52fa50ddab301e76b0e4670178c6529b35327b842817583e` |

No other changes to the repository.

## Branch

`feature/serve-launcher` off `main` (`321ccaef4c33d5f98727aa32995c0d9bcf893660`).
The branch tip is commit `aedde796fc690214b9d2d8a93b05d2113d712bda`
(parent `321ccae`, message "feat: add serve launcher and tests"), whose tree is
`15d562ecc5ec8b4c61f8254d8ae2754b9be9a723`.

Two points of note:

- `git push` from the sandbox cannot authenticate (no credentials are available
  to the pod), so publishing was done through the authenticated GitHub API.
- When I went to create the branch it **already existed** on the remote,
  pointing at that same tree. Because Git trees are content-addressed, that
  tree SHA is identical to the tree I built independently from `main` + the two
  files, so the remote content is the same as my assembly. I confirmed this by
  downloading both files from the branch and hashing them — both match the
  local files byte-for-byte. I therefore left the existing ref untouched rather
  than overwriting it.

## 1. Test suite — FAIL

Command, as the non-root user (`uid=1000`, `gid=1000`):

```
python3 -m unittest discover -s tests
```

Result (verbatim tail of `suite.txt`):

```
Ran 603 tests in 14.897s

FAILED (failures=1, skipped=3)
```

The one failure is the new end-to-end test:

```
FAIL: test_run_end_to_end (test_serve.ServeEndToEndTests.test_run_end_to_end)
Traceback (most recent call last):
  File ".../tests/test_serve.py", line 243, in test_run_end_to_end
    self.assertIn("entries", listing)
AssertionError: 'entries' not found in
  {'items': [{'ref': {'source_id': 'work', 'file_id': 'p/hello.txt'},
              'name': 'hello.txt', 'parent_id': 'root', 'kind': 'file',
              'size_bytes': 11}], 'next_offset': None}
```

The frozen wire contract keys the listing as `items`
(`drive_tool/file_service.py` returns `{"items": [...], "next_offset": ...}`),
but the new test asserts `entries`. dt04 reviewed this file and returned
`VERDICT: ACCEPT (no blockers)`, so this is a defect the review missed: the
added end-to-end test cannot pass against the service it exercises.

The other 21 new tests (config validation and `hash_token`) pass. The 3 skips
are the pre-existing `test_http_adapter` skips.

**The command also does not exit.** After printing its result the interpreter
hangs. The failing end-to-end test aborts at the assertion *before*
`stop.set()`, so the `run()` thread never closes the adapter, and
`DriveHTTPAdapter`'s accept/worker threads are created with `daemon=False`, so
they keep the process alive. My run had to be killed by a 60 s timeout
(`SUITE_EXIT=124` recorded in `suite.txt`). The pre-existing suite alone (581
tests, as run for dt03) exits cleanly, so the hang is introduced by this change.

## 2. Live check — FAIL (as specified)

Procedure, as the non-root user:

1. Temp root directory containing `hello.txt`.
2. Config on port 18765 with one agent whose `token_sha256` came from
   `echo -n secret123 | python3 -m drive_tool.serve --hash-token`.
3. Verify the printed hash equals `sha256("secret123")`.
4. `chmod 600` the config.
5. Start `python3 -m drive_tool.serve --config cfg.json`.
6. `DriveClient(port=18765, token="secret123")` to list the root and read the file.
7. SIGTERM the server and record the exit code.

Observed:

- `--hash-token` printed `fcf730b6d95236ecd3c9fc2d92d7b6b2bb061514961aec041d6c7a7192f592e4`,
  equal to `sha256("secret123")`. OK.
- Server started: `drive-tool listening on 127.0.0.1:18765 (1 agents)`.
- `DriveClient(port=18765, token="secret123")` raised
  `ValueError: token length must be in 32..256`. The existing client requires a
  32–256 character visible-ASCII token, so the specified 9-character token
  `secret123` is rejected and `list`/`read` never run.
- SIGTERM → server exit code **0**.

So the specified live check fails at the client step. The launcher itself, the
`--hash-token` path, and the clean SIGTERM shutdown are fine.

### Supplementary diagnostic (not the specified check)

Repeating the identical procedure with a 40-character token
(`secret123secret123secret123secret1234567`, hashed by the same `--hash-token`
command), the whole path works:

```
DriveClient constructed OK
list('work','root') -> {"items": [{"ref": {"source_id": "work",
  "file_id": "p/hello.txt"}, "name": "hello.txt", ...}], "next_offset": null}
read('work','p/hello.txt', offset=0, length=64) -> data=b'live-check-payload\n'
server exit code after SIGTERM: 0
```

See `live-supplementary.txt`. This isolates the specified failure to the token
length rather than the launcher.

One environment note: the adapter's listener does not set `SO_REUSEADDR`, so
port 18765 is unusable for a short while after a prior connection closes
(`TIME_WAIT`); the supplementary run waited for the port to become bindable.

## Raw evidence files

Committed next to this report (and, per the relay's filing convention, also
under `REPORT/`):

| file | content |
| --- | --- |
| `suite.txt` | full `unittest` output (603 tests, 1 failure, 3 skipped; killed after timeout) |
| `live.txt` | the specified live check (FAIL) |
| `live-supplementary.txt` | the 40-character-token diagnostic (PASS) |
| `env.txt` | commit / python / user and provenance |

## Verdict

As specified, the change does not pass: the suite has 1 failure and the live
check cannot run with the specified token. Both trace to the delivered change
and the check definition rather than to my assembly — the two files are
byte-identical to dt02, the launcher works end-to-end with a valid token, and
it shuts down cleanly on SIGTERM.

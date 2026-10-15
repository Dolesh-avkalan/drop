# d063 — bounded six-agent cloud stress runner (GitHub-delivered, D069 corrected)

Self-contained, **stdlib-only** runner for the director to execute on the
separate target instance `instance-20261015-210506` through the existing Cloud
Shell SSH. It validates the **pinned** accepted candidate

```
Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67
```

by downloading its GitHub archive, verifying identities **before** executing,
and running the committed 506 suite plus a bounded six-agent backend smoke,
a bounded six-agent backend soak (gated on the smoke) and raw edge checks.

It does **not** run on the target from the author's side. **No target result is
claimed or fabricated here.** This is *library* stress against real POSIX
fixtures — it is **not** an HTTP client/service acceptance test (there is no
HTTP adapter in this pinned revision; an HTTP smoke/soak will need a separately
pinned revision after the HTTP transport is accepted).

## The command

```
python3 run_cloud_stress.py
```

That is the whole invocation. It creates a fresh unique workspace under `/tmp`
(`/tmp/d063-b7f8d17b-<uniq>`, mode `0700`, realpath-verified), runs
everything, prints `RESULT: PASS` or `RESULT: FAIL (fail-closed)`, and exits
`0` only on success. The workspace is **kept** for retrieval; the exact
packaging and cleanup commands are printed at the end.

`--base-dir` and `--workdir` are **rejected** unless the canonical
(`os.path.realpath`) path resolves under `/tmp/` and is not `/tmp` itself.
This is a D069 containment change: no filesystem selection can be used to
mask the directory-order-sensitive committed test.

## Requirements / assumptions

- A POSIX host with Python 3 (the runner itself is stdlib-only; it then runs the
  suite on every interpreter it finds: `python3.14`, `3.13`, `3.12`, `3.11`,
  `3.10`, `3`). The target's Python 3.13.5 is picked up automatically.
- Outbound HTTPS to `codeload.github.com` for the pinned archive, **or** a
  pre-staged archive via `--archive <path>` (e.g. if the VM has no egress).
- Nothing is installed, cloned, mounted or written outside the workspace. No
  credentials, no cloud API, no reboot, no service change and no public binding.
  Real storage roots are never touched; fixtures are synthetic.

## What it checks, in order

1. **Workspace + payload identity** — creates a new unique dir; verifies the
   fixed payload `stress_checks.py` SHA-256 before anything runs; requires free
   space (default ≥ 20 MiB).
2. **Environment (before)** — hostname, `uname`, OS release, interpreter, free
   space, memory, `nproc`.
3. **Pinned archive** — downloads the codeload tar.gz of the pinned commit with
   a 50 MiB byte cap and a wall-clock timeout (default 120 s).
4. **Guarded extraction** — rejects absolute paths, `..` components, symlink/
   hardlink members, non-regular members; caps member count (2000), per-file
   size (5 MiB) and total uncompressed size (50 MiB).
5. **Identity** — recomputes the git blob sha1 of all **26** pinned executable
   source/test files and compares to the commit's known hashes **before**
   executing anything. **D069 fail-closed additions:** any unexpected file
   under `drive_tool/` or `tests/`, any unexpected importable/executable file
   anywhere in the extracted source (`.py`, `.pyc`, `.pyo`, `.pth`, `.so`,
   `.sh`, `.bash`, `.pyw`), `sitecustomize.py` / `usercustomize.py` at any
   path, or any symlink inside the extracted tree aborts with the offending
   path.
6. **Readdir order confirmation + dual-order repro (D069)** — records the
   `/tmp` filesystem type / options and the native `readdir` order of a probe
   directory created with `a.txt` before `b.txt` into
   `logs/readdir_order_confirmation.json`. Then reproduces the known
   directory-order-sensitive test in **two isolated subprocesses**, shimming
   `os.scandir` / `os.listdir` to sort ascending (`asc`) vs descending
   (`desc`). The confirmation flag `confirmed_order_sensitive_defect` is set
   only if `asc` passes and `desc` fails.
7. **Committed 506 suite** — `python -m unittest discover -s tests` on each
   available interpreter, under a wall-clock timeout. Records full
   stdout/stderr, exit, count and skips; fails closed if the count ≠ 506.
   **D069 policy:** a failing suite is never relabelled a pass. If the suite
   fails, the runner continues to smoke/soak/edges for diagnostic evidence
   but the overall exit remains **NONZERO**.
8. **Six-agent backend SMOKE** — 600 backend calls across 6 authenticated
   agents with real rooted adapters and grant policies.
9. **Six-agent backend SOAK** — 10000 backend calls, run **only if the smoke
   passes**.
10. **Raw edge checks** — grants, races, refusal, caps, EOF, leases and a
    clearly-labelled simulated post-publish fault.
11. **Environment (after)**, a **workspace-size gate** (≤ 128 MiB) and a
    **SHA-256/length manifest** of the whole workspace, plus `summary.json`.
    Symlinks are enumerated explicitly and **never followed** by the manifest
    or size accounting.

## Fixed allow-listed actions only

The runner executes exactly one payload (`stress_checks.py`, identity-pinned)
with a fixed action token — `smoke`, `soak` or `edges` — plus the extracted
source dir. There is **no arbitrary shell/job payload**, no command string from
config, no credential and no cloud API call.

## Pass / fail / resource thresholds (defined before execution)

| threshold | value |
| --- | --- |
| concurrent operations | ≤ 6 |
| workspace size | ≤ 128 MiB |
| new fixture data | ≤ 32 MiB |
| archive / uncompressed / per-file | 50 / 50 / 5 MiB |
| archive members | ≤ 2000 |
| smoke / soak calls | exactly 600 / exactly 10000 completed |
| committed suite | exactly 506 tests, `OK`, exit 0, every interpreter |
| FD table after close | returns to baseline (+2 slack) |
| leaked temp files | none (`TEMP_PREFIX` scan of every root) |
| thread peak | ≤ baseline + 6 (+2 slack) |
| RSS growth (per stage) | ≤ 96 MiB |
| per-stage wall limits | download 120 s, suite 240 s, smoke 180 s, soak 420 s, edges 120 s |
| overall runner deadline | 900 s (< 20 min hard outer operator timeout) |

Recognized error codes counted exactly: `denied`, `exists`, `too_large`,
`invalid`, `not_found`, `unavailable`, `busy`, `timeout`. Any unexpected
exception fails the stage.

**D069 limits enforced on the runner side:** wall-clock download deadline
(L1), `--deadline-seconds` propagated to the stress payload (L2), byte-capped
subprocess output and process-group kill on timeout (L3), nofollow manifest /
size accounting (L4), apparent + allocated workspace bytes recorded (L5).

## Raw edge checks (stage `edges`)

alias isolation · readonly denial · path-traversal refusal · symlink-component
refusal (+ symlink omitted from listing) · grant-specific read/write caps ·
service read cap · exact-window / at-EOF / past-EOF / short / empty reads ·
large sparse range · empty-data save round-trip · concurrent no-overwrite with
exactly one winner and exact full payload · active-lease drain with idempotent
`close()` and post-close `unavailable` · **simulated** post-publish fault
injection (documented `LocalWriter._os_link` seam) asserting
`outcome_uncertain=True`, `retry_safe=False`, and that the file *was* published
before the error · FD baseline · no temp leaks.

## Options

```
--base-dir DIR         where to create the unique workspace (default /tmp)
--workdir PATH         explicit workspace path (must not already exist)
--archive PATH         use a local .tar.gz instead of downloading
--python NAME          restrict to one interpreter (repeatable)
--download-timeout N   archive download timeout seconds (default 120)
--suite-timeout N      per-interpreter suite timeout seconds (default 240)
--smoke-timeout N      smoke stage timeout seconds (default 180)
--soak-timeout N       soak stage timeout seconds (default 420)
--edge-timeout N       edge stage timeout seconds (default 120)
--overall-deadline N   whole-runner deadline seconds (default 900)
--min-free-bytes N     required free space in the workspace fs (default 20 MiB)
```

## Outputs

Under `<workspace>/logs/`: `env_before.json`, `env_after.json`, `identity.txt`,
`readdir_order_confirmation.json`, `dual_order_asc.out`, `dual_order_desc.out`,
`suite_<py>.out`, `stress_<action>.out`, `summary.json`, `MANIFEST.md`. The
downloaded archive (`archive.tar.gz`) and the extracted tree are kept too.

## Packaging the evidence (exact commands)

The runner prints these at the end; they are:

```
tar -czf d063-evidence-b7f8d17b.tar.gz -C /tmp d063-b7f8d17b-<uniq>
# cleanup ONLY when evidence is no longer needed:
rm -rf /tmp/d063-b7f8d17b-<uniq>
```

## Safety and limits

- Only the created workspace is touched; no broad cleanup or deletion is done.
- Fixtures are real synthetic files; one large **sparse** probe has a large
  apparent size but ≈0 real disk. Total new data stays under 32 MiB.
- No destructive memory/disk exhaustion: payloads and the saved-file pool are
  bounded, reads are windowed, and the soak reuses a bounded file pool.
- No private paths are inspected, no browser profiles enumerated, no user data
  read.

## Provenance of this runner

Authored for d063 by reusing the proven d014/d038 GitHub-delivered pattern
(`Dolesh-avkalan/drop` `drive-tool/readonly-core/d014-cloud-validation/runner/`).
Exercised end-to-end in the author's sandbox against the same pinned archive —
see the bundled `../sandbox/` logs (happy run + five fail-closed negatives).
Negative tests (tampered identity, path-traversal archive, symlink member,
oversized member, missing archive, workspace reuse) all failed closed.

**Directory-order observation (D069).** One committed test
(`test_partial_scan_review_fixes.PostYieldStorageErrorTests.
test_metadata_failure_below_root_is_skipped_and_charged`) is directory-order-
sensitive. The runner records the native `/tmp` filesystem and readdir order
and reproduces the defect deterministically in `asc` / `desc` subprocesses.
It does **not** select a filesystem to make the suite pass: on the pinned
`b7f8d17…` revision the committed suite is expected to fail on any host whose
`/tmp` returns `b.txt` before `a.txt`, and the overall exit stays NONZERO.
The test-side fix lives in D066; do not re-pin before D066 is reviewed.

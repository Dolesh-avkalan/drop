# D063 — Sarvam-owned GitHub-delivered target stress runner

**Status: runner + tests + evidence published, sandbox-tested, no target execution claimed.**
Prepared for director orchestration on the separate target `instance-20261015-210506`
through the existing Cloud Shell SSH. I do not have the target shell; **no target
result is asserted here.**

- Pinned accepted candidate under test: `Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67`
  (contains the accepted client/backend 506 suite; **no HTTP adapter** in this revision).
- Published bundle: `drive-tool/module-006/d063-cloud-stress-runner/`
  (`runner/`, `tests/`, `sandbox/`, `MANIFEST.md`).
- Method reused: the proven D014/D038 GitHub-delivered runner pattern
  (`drop @ a017f66f` → `drive-tool/readonly-core/d014-cloud-validation/runner/`),
  adapted — not a new generic remote shell.

## What this delivers

A compact, **stdlib-only** runner that the director runs with a single command on
the target. It downloads the pinned GitHub archive, verifies every executable
source/test identity **before** executing, then runs a fixed allow-list of
actions and fails closed at every gate.

### Exact target invocation (single command, from the runner directory)

```
python3 run_cloud_stress.py
```

### Result packaging command (evidence is retained; run to collect it)

```
tar -czf d063-evidence-b7f8d17b.tar.gz -C /tmp d063-b7f8d17b-<uniq>
# cleanup ONLY when evidence is no longer needed:
rm -rf /tmp/d063-b7f8d17b-<uniq>
```

The runner prints both the exact packaging line (with the real `<uniq>`) and the
precise cleanup line at the end of its run.

## What the runner does, in order (each gate fails closed)

1. Creates a **fresh unique** workspace `/tmp/d063-b7f8d17b-<uniq>`; verifies the
   fixed payload `stress_checks.py` SHA-256 (`8097d0a3…5be9`) before anything runs;
   requires ≥ 20 MiB free.
2. Captures host/OS/interpreter/resources **before**.
3. Downloads the pinned codeload archive with a 50 MiB byte cap and a wall-clock
   timeout (or uses `--archive`).
4. **Guarded extraction**: rejects absolute paths, `..` components, symlink/hardlink
   members and non-regular members; caps members (2000), per-file (5 MiB) and total
   uncompressed (50 MiB) size.
5. **Identity**: recomputes the git blob sha1 of all **26** pinned executable
   source/test files and compares to the commit's known hashes **before executing**.
   Any mismatch/missing file aborts naming the path.
6. Runs the committed **506** suite on every available interpreter.
7. Runs a bounded **600-call six-agent backend smoke**.
8. Runs a bounded **10000-call six-agent backend soak** — **only if the smoke passes**.
9. Runs **raw edge checks**.
10. Captures resources **after**, gates workspace size (≤ 128 MiB), writes a
    SHA-256/length manifest and `summary.json`.

## Fixed allow-listed actions only

The runner executes exactly one payload (`stress_checks.py`, identity-pinned) with
a fixed action token — `smoke`, `soak`, `edges` — plus the extracted source dir.
There is **no arbitrary shell/job payload**, no credential, no cloud API, no
install/reboot/service change, no public binding and no real storage root. Only a
fresh unique `/tmp` workspace is touched; `TMPDIR` lives inside it and bytecode
writing is disabled. **A GitHub push of this bundle does not itself cause any
remote execution** — it only publishes inert scripts.

## Pass / fail / resource thresholds (defined before execution)

| threshold | value |
| --- | --- |
| concurrent operations | ≤ 6 |
| workspace size | ≤ 128 MiB |
| new fixture data | ≤ 32 MiB |
| archive / uncompressed / per-file | 50 / 50 / 5 MiB |
| archive members | ≤ 2000 |
| smoke / soak | exactly 600 / exactly 10000 completed calls |
| committed suite | exactly 506 tests, `OK`, exit 0, every interpreter |
| FD table after close | returns to baseline (+2 slack) |
| leaked temp files | none (`TEMP_DIR`/`TEMP_PREFIX` scan of every root) |
| thread peak | ≤ baseline + 6 (+2 slack) |
| RSS growth per stage | ≤ 96 MiB |
| per-stage wall limits | download 120 s · suite 240 s · smoke 180 s · soak 420 s · edges 120 s |
| overall runner deadline | 900 s (< 20 min hard outer operator timeout) |

Recognized error codes counted exactly: `denied`, `exists`, `too_large`, `invalid`,
`not_found`, `unavailable`, `busy`, `timeout`. Any unexpected exception fails the stage.

## Edge cases covered (stage `edges`)

Six-agent grant policies with real rooted `LocalAdapter`s; **alias isolation**;
**readonly denial**; **path-traversal refusal**; **symlink-component refusal**
(+ symlink omitted from listing); **grant-specific read/write caps**; service read
cap; exact-window / at-EOF / past-EOF / **short** / **empty** reads; **large sparse
range**; **empty-data save** round-trip; **concurrent no-overwrite with exactly one
winner and exact full payload**; **active-lease drain with idempotent `close()`**
and post-close `unavailable`; **simulated post-publish uncertainty** via the
documented `LocalWriter._os_link` seam, asserting `outcome_uncertain=True`,
`retry_safe=False`, and that the file *was* published before the error (clearly
labelled as injected, not a real crash); FD baseline; no temp leaks.

## Sandbox provenance (author side — not a target claim)

Ran the full runner in my sandbox against the same pinned archive. Sandbox had
Python **3.11.2** and **3.12.13** (no 3.13/3.14 here — I did **not** install them;
the target's 3.13.5 is picked up automatically there).

- **Happy run: `RESULT: PASS`**, exit 0. Committed suite **506 tests, 0 skips, OK**
  on both 3.11 and 3.12. Smoke **600/600** calls; soak **10000/10000** calls. All
  edge checks passed.
- Soak resources: FD `4 → 4` (baseline), RSS `+5.5 MiB` (budget 96 MiB), no leaked
  temp files, fixture data `14.2 MiB` (≤ 32 MiB), workspace `15.97 MiB` (≤ 128 MiB),
  ~22 s.
- **Negatives all failed closed** (logs in `sandbox/`): tampered identity
  (`MISMATCH`), path-traversal archive, symlink member, oversized member, missing
  archive, workspace reuse, and a **payload-tamper** negative (mutated
  `stress_checks.py` rejected by the pinned SHA-256).
- Runner self-tests: **16 tests, OK** (`sandbox/test_runner_gates.log`), including
  the required identity-tamper negative.

### One honest sandbox finding (not a target claim)

One committed test —
`test_partial_scan_review_fixes.PostYieldStorageErrorTests.
test_metadata_failure_below_root_is_skipped_and_charged` — depends on physical
`readdir` order and asserts `inspected == 2`. It passes when the directory yields
`a.txt` before `b.txt` (creation order, as on a disk-backed filesystem) and fails
(`inspected == 3`) when `b.txt` is yielded first. My sandbox's `/tmp` is a gVisor
tmpfs that reverses that order, so the sandbox happy run used a **disk-backed
`--base-dir`**; the target's disk-backed `/tmp` needs no override. If the target's
`/tmp` is a tmpfs with reversed order, this single test could fail there — the
runner will report it honestly (fail-closed) rather than hide it. This is a
property of the committed suite, not of the runner; I did not and will not modify
candidate code.

## Explicit non-claims

- **No target execution** has occurred from my side; nothing here is a target result.
- **No HTTP client/service acceptance** is claimed or possible here — this pinned
  revision has no HTTP adapter. An HTTP smoke/soak will require a **separately
  pinned revision** after the HTTP transport is accepted.
- No implementation change, merge, deployment, real root, credential or cloud API.

## What I need back, and next bounded rounds

The director bootstraps the approved pinned invocation through the existing SSH and
returns the **raw, sanitized evidence** (the `logs/` tree and the packaged tarball)
through GitHub. On receipt I will: verify the workspace manifest and identity
lines, analyse the suite/smoke/soak/edge results and resource counters, and propose
further **bounded** reproductions/corrections — e.g. re-running a single stage with
tighter bounds, or a narrower six-agent soak — until acceptance. No unbounded work
and no target execution claim until the actual returned logs are in hand.

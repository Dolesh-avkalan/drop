# D054 — file-service assembly summary (final answer)

Deliverable for "assemble and execute D054 generated file-service backend per
pinned brief". All supporting artifacts (final tested source, raw initial/final
suite logs, probe, mutation scripts/logs, environment, byte-SHA256 manifest and
the full report) are in the sibling folder
`drive-tool/module-006/d054-file-service-assembly-summary/`.

Status: assembled and executed; all demonstrated failures fixed within the two
allowed files; full suite green on Python 3.11.2 and 3.12.13. **No acceptance
claim** — independent review/execution and merge remain with the director.

---

# D054 — assemble/test the generated file-service backend (report)

## Provenance and pins

| Item | Value |
|---|---|
| Base (accepted policy main) | `Dolesh-avkalan/drive-tool` @ `e55c9f741a528ce9298b5041012373195e878eaf` |
| Working branch (isolated) | `feature/module-006a-file-service` (local; no merge, no push to drive-tool) |
| Director contract | `tasks/d050-file-service-implementation.md` @ `8eac68b98481b86e7ae164a5835063584c15fdcb` — sha256 `7632d4868bba9025167f21aa0f3c1e579141a59638bf7f0e38b17126ff79f267` (identical at base and at the pinned contract commit) |
| Generated answer | `Dolesh-avkalan/drop` @ `2b980155e82e985a08d3a9eb7d517bf6a69603db`, `drive-tool/module-006/d050-gemini-file-service.md` — sha256 `ea0c018390ffe127299161b9006f2aef6b2a353659e18262f5b811d82c7b88b8` |
| Verbatim FILE-block extraction | `drive_tool/file_service.py` = lines 37–653; `tests/test_file_service.py` = lines 659–1377 of the generated answer |

The extraction reproduced the two FILE blocks byte-for-byte: the extracted
sha256 values (`f9724404…` for the service, `452c9d7f…` for the tests) are the
exact blobs committed in the verbatim commit.

## Scope compliance

Only the two allowed new paths were created or edited:
`drive_tool/file_service.py` and `tests/test_file_service.py`. No edits to
`service_policy`, `local`, `local_write`, `storage`, `search`, `listing`, or any
client. No HTTP server/socket, no package installs, no real roots or
credentials, no main merge, no deployment. The service is a synchronous facade
only; no HTTP deadline/cancellation claim is made.

## Commit sequence on `feature/module-006a-file-service`

```
e2f0efa  base: accepted policy main e55c9f741a528ce9298b5041012373195e878eaf
fed9d8b  D050: add the two FILE blocks VERBATIM (as generated)
894558a  fix(file_service): rebuild canonical p/ FileRef ids from parsed parts
9effd25  fix(test_file_service): conform harness to accepted service_policy/local contracts
```

Initial head/tree: `fed9d8b` / tree `024ef45c68cf24783ec71c0cf281872b449466e3`. Final head/tree:
`9effd25e08a8de9c2d319c2acae15a0cd2c9689b` / tree
`3482dc4325afb5adf4b7ecfcbfe1e76a1ad0356c`.

## Initial full-suite execution (before any fix)

Baseline (base tree, existing tests only) on Python 3.11.2 and 3.12.13:
**413 tests, 0 failures, 0 errors, 0 skips, exit 0** — matches the brief's stated
baseline of 413.

As delivered (verbatim commit, full suite): **429 tests, 16 errors, exit 1** on
both interpreters. All 16 errors were the same cause:
`TypeError: token_sha256 must be bytes` (the generated harness stored a hex
string where `AgentPolicy` requires the raw 32-byte digest). Raw logs:
`logs/01_baseline_existing_3.11.log`, `logs/01_baseline_existing_3.12.log`,
`logs/02_initial_full_3.11.log`, `logs/02_initial_full_3.12.log`.

## Demonstrated failures and attributed fixes

Fixes were applied only inside the two allowed paths and only to failures the
runs actually demonstrated. Each fix is in its own attributed commit.

### Commit `894558a` — `drive_tool/file_service.py`

**Demonstrated failure.** After the harness could reach the storage layer, every
`read`, nested `list`, nested `find`, and `save` returned `denied`. The service
built `FileRef` ids by joining bare path parts (e.g. `sample.txt`), dropping the
canonical `p/` prefix that `local._parse_file_id` requires; the adapter re-parsed
each ref and raised `UnsafePathError`. **Fix:** add `_canonical_id()` and use it
for the list/find/read parent refs and the save parent-chain refs.

### Commit `9effd25` — `tests/test_file_service.py`

Each item below was demonstrated by a run, not assumed:

1. `token_sha256` hex string → raw 32-byte digest (`_token_digest`).
2. Bearer tokens were all shorter than the policy's 32-char minimum, so
   `PolicyTable.authenticate` denied before any adapter call; reads/lists/saves
   returned `denied`. Tokens are now ≥32 visible-ASCII chars (`_pad_token`).
3. Wire `file_id`s were bare relative names; canonical ids are `root` or
   `p/relative`. Tests now pass canonical `p/…` ids.
4. `RangeReadResult` exposes `eof_observed`, not `eof`.
5. The save read-back used a real `p/` directory; `p/` is a virtual prefix, so
   the on-disk path is `root/a/b.txt`.
6. `find` does not report an omitted symlink as a skipped subtree — `skipped`
   holds unscannable subtrees. The test now induces a genuine permission-denied
   subtree (`chmod 000`) and asserts `skipped`/`truncated`/`reason`.
7. The startup-rollback count included a never-opened adapter that also invokes
   `close` via `LocalAdapter.__del__`. The test now records successfully-opened
   adapters and asserts each is closed exactly once.

Note: item 6 also means the original redaction test was passing vacuously
(auth denied first). After the token fix it exercises the storage-error path.

## Final full-suite execution (after fixes)

Full suite on Python 3.11.2: **429 tests, 0 failures, 0 errors, 0 skips, exit 0**.
Full suite on Python 3.12.13: **429 tests, 0 failures, 0 errors, 0 skips, exit 0**.
Focused file-service module: **16 tests, OK** on both. Raw logs:
`logs/03_final_full_3.11.log`, `logs/03_final_full_3.12.log`,
`logs/04_final_file_service_verbose_3.11.log`,
`logs/04_final_file_service_verbose_3.12.log`.

Command used (from the repo root): `PYTHONPATH=. <python> -m unittest discover -s tests`.

## Meaningful actual tests (mapped to the brief)

Real POSIX synthetic roots, accepted `LocalAdapter`:

- six synthetic identities and startup cap enforcement (≤6 agents / ≤32 grants,
  rejected before any adapter opens);
- two agents, identical alias, different roots — no cross-root bleed;
- read-only/unauthenticated denial with zero metadata leakage and identical
  messages; auth/authorize strictly before id-parse/options/IO;
- startup rollback when a later root is invalid (each opened adapter closed once);
- invalid options/caps perform no IO (adapter/writer spies never called);
- list/find metadata shape and the partial/skip contract, including a real
  permission-denied subtree reported in `skipped`;
- large sparse range reads and exact-EOF semantics (`eof_observed` false on an
  exact-fill window, true only on an observed EOF);
- save no-overwrite collision (`exists`) and explicit overwrite;
- missing-parent one-call creation, and the `create_parents=False` refusal;
- symlink parent refusal with the outside target untouched;
- post-publish fsync fault injection → `unavailable`, `outcome_uncertain=True`,
  with the real published bytes verified on disk;
- static error redaction (no root/token/name/bytes; `__cause__` None);
- concurrent blocked read + `close(timeout)` keeps the active fd alive and denies
  new leases (`unavailable`); a later close drains;
- concurrent close callers never double-close; fd stability after drain.

Fault-injection seams are clearly labelled in the test comments.

## Isolated semantic mutations (raw)

`scripts/mutation_runner.py` copies the committed tree per mutation, applies one
semantic edit to `file_service.py`, and runs the focused module under a bounded
timeout (a timeout is recorded as failure, never a pass). All seven mutations
were CAUGHT (the focused tests fail):

| Mutation | Result | Failing tests |
|---|---|---|
| M1 skip per-(agent,alias,op) grant lookup | CAUGHT | auth-before-parse, readonly-denial |
| M2 alias-only binding key (collision) | CAUGHT | two-agents-same-alias + 6 others |
| M3 bool accepted as offset/limit (invalid option reaches IO) | CAUGHT | invalid-options-no-io |
| M4 dropped save uncertainty (`is_write_in_flight=False`) | CAUGHT | fsync/symlink/parents/overwrite |
| M5 close ignores active leases (close active fd) | CAUGHT | concurrent-blocked-read-close-timeout |
| M6 always create parents (ignore flag) | CAUGHT | save-creates-missing-parents |
| M7 no in-progress/already-closed guard (double close) | CAUGHT | concurrent-closes-close-once |

Raw per-mutation logs: `mutations/M1…M7.log`; summary `mutations/mutation-summary.txt`.

## Raw probe (independent of the suite)

`scripts/probe_d054.py` prints raw observations (Python 3.11 and 3.12, both exit
0), confirming on the actual filesystem:

```
[perm]  find skipped: ['p/locked'] truncated: True reason: skipped   (chmod 000 subtree)
[alias] alpha reads p/a.txt: b'AAA' ; alpha reads p/b.txt -> not_found
[drain] timed-out close -> False ; binding.closed: False
[drain] post-drain list -> unavailable retry_safe: True
[drain] in-flight read data: b'payload' ; draining close -> True ; binding.closed: True
[fd]    before=4 after-open=5 after-drain=4
[save]  code: unavailable uncertain: True retry_safe: False ; bytes on disk: b'published-bytes'
[save]  rendered error: unavailable: service or storage is unavailable | cause: None
```

Logs: `logs/05_probe_3.11.log`, `logs/05_probe_3.12.log`.

## Final published bytes vs tested source

The tested files are the committed blobs:

- `drive_tool/file_service.py` — git blob `b7e18c606f45066cd54ec66016e70e797486ef50`, sha256 `befe20bba64252d5595ac68e4af8459f4d8686dd31d14f5bfbf5159fa8b56f8c`
- `tests/test_file_service.py` — git blob `8b5248f9365d8cac6e1331bb4677dea48a1778ff`, sha256 `855df6ef02139f003cf7cfd26ccd1c43bce52b14e332c774f23a6de2917ad8dc`

The copies published alongside this report are byte-identical to those tested
files (see `MANIFEST.sha256.txt`).

## Honest caveats / blockers

- Only Python 3.11.2 and 3.12.13 were available; both are reported. Python 3.14
  was not available in this sandbox.
- The generated code contained a latent, non-runtime annotation defect
  (`Never` used without import; `from __future__ import annotations` keeps it
  inert). It was left unchanged because it is not a demonstrated runtime
  contract failure and changing it would exceed the "demonstrated failures only"
  scope.
- The service remains a synchronous facade with no HTTP transport, deadline,
  cancellation or idempotency guarantee, per the contract.
- The branch is local: the brief's final publication target is the `drop`
  repository; no push to `drive-tool` and no main merge was performed.
- This is **not an acceptance claim**. Independent review/execution and the merge
  decision remain with the director.

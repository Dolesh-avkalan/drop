# d110 harsh target extension — core package

Pinned, stdlib-only **harsh-fault** extension for the accepted final Drive Tool
HTTP candidate. It is authored and sandbox-tested here; it does **not** run on
the target from here and **no target result is fabricated**. The operator runs
it on the disposable instance.

This package is separate from the D101/D104 reliability gate. It reuses the
**exact D104 runner containment / identity / archive / resource patterns**
(drop `c29e3a2b23161602ec331a49ff8edb774dfebcb2`,
`drive-tool/module-006/d104-target-http-runner-summary/{run_target_http.py,http_gate_d101.py,README.md}`)
and drives the accepted final HTTP adapter with hostile-fault stages. It is a
*break-it* extension: adverse diagnostics are never relabelled as normal
success, and an unsupported capability is reported as `SKIP`/problem, never as
a pass.

## Files (core — everything needed to run)

| file | bytes | sha256 |
| --- | --- | --- |
| `run_harsh_target.py` | 28881 | `0e76f066ff16a0e5594a6da6a161aa2b297c2b9e8e34be96be92dc8d5ac75987` |
| `harsh_gate_d110.py` | 78388 | `b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e` |

`harsh_gate_d110.py` is the pinned harsh payload. Its sha256 is embedded in
`run_harsh_target.py` and verified before execution; the runner fails closed on
any mismatch. The runner also re-verifies the candidate archive sha256 and every
executable/importable candidate file before executing anything.

## Pins

- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
- archive: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  (sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`)
- accepted D101 final HTTP gate (reference): sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b`
- accepted order fix preserved: `tests/test_partial_scan_review_fixes.py`
  blob `c01003e7015915db3dcac15a168ff7aae3d423db`
- composite sourcehash (adapter‖test): `b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c`
- pinned candidate manifest: 28 files (identical to the accepted D104 `EXPECTED_BLOBS`)

No Drive Tool source, tests, acceptance spec or old evidence is modified. New
scripts only. No PR/merge.

## Exact operator command (target: Debian / CPython 3.13)

    cd d110-harsh-target && \
    timeout 1200 python3 run_harsh_target.py \
        --confirm-disposable-host=instance-20261015-210506 \
        --json d110_summary.json

`timeout 1200` is the hard 20-minute outer operator bound; the runner's internal
overall deadline defaults to 1080 s. `--confirm-disposable-host` is fail-closed:
if `socket.gethostname()` does not equal the value, the runner aborts before
doing any work. A nonzero exit means the aggregate gate failed — read
`d110_summary.json` and the retained raw logs under the workspace.

To reproduce a single stage: add `--stage <name>` (repeatable). To run offline
against a pre-downloaded archive: add `--archive /path/to/candidate.tar.gz`.

## Behaviour

Order, failing closed at every preflight gate:

1. host identity (when `--confirm-disposable-host` is given) and free-disk floor;
2. acquire the pinned archive (download, or `--archive` a local tar.gz) and
   verify its sha256 against the pin;
3. extract with path/size/count/link guards (no symlinks, no traversal, no
   special files, bounded sizes/totals);
4. re-hash **every** executable/importable candidate file against the embedded
   pinned blob-sha1 + sha256; reject unexpected importable/executable files,
   unexpected `drive_tool/` or `tests/` files, symlinks, traversal, oversize;
5. verify the harsh payload sha256;
6. run the fixed allow-list of harsh stages, each in its own process group with
   a per-stage deadline and byte-capped output; stop the aggregate on the first
   FAIL;
7. gate the retained workspace at <= 192 MiB and write a symlink-safe manifest.

Acceptance is PASS only if **every** required stage reports PASS. A `SKIP`,
`ERROR`, `TIMEOUT`, `MISSING` or any non-PASS result makes the aggregate nonzero.

## Case / invariant matrix

| stage | mechanism | invariant gates (all must hold) |
| --- | --- | --- |
| `selfcheck` | capability probes + frozen arithmetic, no adapter | product bounds match (`MAX_IN_FLIGHT_OPERATIONS=6`, `TEMP_PREFIX`, `PATH_PREFIX`); host `MemAvailable` and free-disk floors; RLIMIT_FSIZE/AS/NOFILE settable; `os.link` supported; SIGXFSZ ignorable; concurrency harness <= `MAX_IN_FLIGHT` |
| `readdir_order` | dual-order run of `test_metadata_failure_below_root_is_skipped_and_charged` (native + forced-inverted `os.scandir`/`os.listdir`) + `/tmp` fstype/native-order telemetry | the order-explicit accepted test PASSES under **both** host readdir orders (no filesystem masking) |
| `http_hostile` | raw-socket malformed/oversize/slow-partial requests: overlong request line, overlong/too-many headers, huge/non-digit/duplicate Content-Length, bare-LF headers, buffered trailing bytes, bad method, unknown endpoint, oversize JSON/save bodies, slow partial body | every case terminates in a typed 4xx/5xx envelope or a clean close — never a 2xx success, never a hang, never an unhandled worker death; the adapter still serves a valid request afterwards; `close()` returns True; 7 threads reaped; fd back to baseline |
| `admission` | deterministic 6+1: six occupiers held at a **real service-entry barrier**, excess probe sent while all six slots are provably held | each cycle: 6/6 occupiers admitted, excess gets `busy` (503), zero unexpected; recovery request returns 200 after exhaustion; `close()` True; threads reaped; fd baseline |
| `isolation` | cross-agent read/list, path traversal (`..`, `%2e%2e`), symlink read/list/save escaping the root, shared-alias access, read-only save | every escape attempt is a typed denial (`denied`/`invalid`/`not_found`/client-side reject), never an unhandled exception; the outside secret is never returned; the outside directory is byte-unchanged and gains no file; shared-alias agents both succeed |
| `concurrency` | simultaneous create (`overwrite=False`), overwrite race with concurrent range readers, concurrent `create_parents`; total concurrency <= 6 | create race: exactly 1 winner, all others `exists`; overwrite race: all succeed; readers never observe torn/partial data (a transient `busy` is admission, not corruption); no temp residue; final file equals exactly one complete payload |
| `crash_kill` | pipe-synchronized child SIGKILL at mid-write and post-fsync/pre-publish, plus a 4-child uninstrumented SIGKILL storm | each kill terminates the child by SIGKILL; >= 1 orphan `TEMP_PREFIX` temp on disk (staging genuinely interrupted); nothing partially published; a **fresh process** then succeeds on list/read/find/save with no lock wedge; orphan temps are NOT exposed by `list()`/`find()`; storm: every file equals its seed or a complete valid write (0 torn) |
| `resource_pressure` | CHILD-only: 4 `nice 15` + RLIMIT_CPU CPU children; child `RLIMIT_AS=384 MiB` + `oom_score_adj=1000`; child `RLIMIT_NOFILE` exhaustion (fillers to EMFILE) | CPU: 200/200 calls succeed; RAM: reads/saves succeed, host `MemAvailable` stays above the floor, child exits clean; FD: EMFILE is genuinely forced (mapped ServiceErrors > 0), zero unhandled OSError escapes the service, recovery succeeds and fd returns to baseline. If EMFILE cannot be forced the stage is reported as a problem, not a pass |
| `enospc` | injected `OSError(ENOSPC)` at four save phases (temp create, mid-write, fsync, publish incl. link+rename), plus a real child `RLIMIT_FSIZE=8192` kernel EFBIG mid-write | each failure maps to `code == "unavailable"`; a write-in-flight failure never claims `retry_safe=True` with `outcome_uncertain=False`; the pre-existing overwrite target stays byte-identical; no partial new file is published; zero temp/FD leak; full recovery after the fault is removed |

## Observed contract notes (accepted candidate)

These are recorded as **observed product behaviour**, not defects:

- A write that fails in-flight (ENOSPC / EFBIG / OSError) is mapped to
  `ServiceError(code="unavailable", outcome_uncertain=True, retry_safe=False)`.
  This is deliberately conservative and satisfies the "no retry of uncertain
  writes" requirement. (It differs from the older Gemini draft, which expected
  `outcome_uncertain=False, retry_safe=True` for pre-publish faults; the
  accepted adapter is stricter, and the gate asserts the stricter safety
  property, never the weaker one.)
- `TEMP_PREFIX` (`.drive-tool-tmp-`) staging files are hidden from `list()` and
  `find()`. Orphan temps left by SIGKILL remain on disk (one per killed child)
  but are not exposed by the service surface.
- A malformed/oversize request never kills a worker: it returns a typed
  envelope (`invalid` 400 / `too_large` 413 / `timeout` 504) or a clean close,
  and the adapter recovers immediately.

## Containment / safety

stdlib only; no credential, cloud API, install, reboot, service/public binding,
real root or deploy; no generic remote shell; loopback only. Execution is
confined to a new unique `/tmp/d110-<commit8>-<uniq>` workspace (0700, strict
descendant of the base, never the base itself); `TMPDIR` lives inside it and
bytecode writing is disabled. `<= 192 MiB` retained workspace; `>= 1 GiB`
free-disk floor (overridable only via `--min-free-bytes` for sandbox validation).
Host `MemAvailable >= 1 GiB` is required before the RAM stage and pressure aborts
below 512 MiB. Child `RLIMIT_AS <= 512 MiB`; CPU stress is `<= 4` low-priority
children; service concurrency `<= 6` plus one rejected admission probe. Only the
runner's own child process groups are killed; SSH/parent are preserved. Per-case
deadlines, overall `<= 20 min`, operator `timeout 1200`, bounded output, reaping
and retained logs on failure. No physical-power-loss durability claim is made.

## Sandbox evidence (this package, not the target)

Executed locally against the pinned candidate on the two available interpreters:

| interpreter | result | notes |
| --- | --- | --- |
| CPython 3.12.13 | PASS (all 9 stages) | full orchestrator run, local archive, 19.5 s |
| CPython 3.11.2 | PASS (all 9 stages) | full orchestrator run, local archive |

Guard negatives (fail-closed, verified):

- tampered payload -> `payload sha256 mismatch`, exit 1, nothing executed;
- tampered archive -> `archive sha256 ... != pin ...`, exit 1;
- content tamper of `drive_tool/http_adapter.py` -> size/blob/sha256 mismatch;
  an unexpected importable file (`__pycache__/*.pyc`) is also rejected.

Raw per-stage JSON, captured logs and the source manifest are retained under
`evidence/py312/` and `evidence/py311/`.

## Explicit non-guarantees

1. SIGKILL proves **process-crash atomicity**, not physical power-loss
   durability across hypervisor disk write-back caches.
2. Orphan `TEMP_PREFIX` files left by SIGKILL are not auto-reaped unless the
   product implements a startup/periodic janitor sweep; the gate only proves
   they are not exposed by `list()`/`find()`.
3. Real mount-full ENOSPC via a private tmpfs/loopback mount is not attempted
   here (no mounts/sudo/installs); ENOSPC is exercised by syscall injection plus
   the kernel `RLIMIT_FSIZE` EFBIG path, which is the meaningful unprivileged
   equivalent.
4. Exact timing of the uninstrumented SIGKILL storm and the CPU-saturation race
   is scheduler-dependent; determinism for mid-write crash invariants comes from
   the pipe-synchronized cases.

## Unresolved limits

- Not executed on the target `instance-20261015-210506`; target numbers are for
  the operator to produce. The D104 suite/gate were only re-confirmed locally
  (581 tests, OK, skipped=3 on 3.12.13) and are not re-run by this package.
- CPython 3.13 was not available in the sandbox; validated on 3.11 and 3.12.
- `--min-free-bytes` is a sandbox-validation override; the default (1 GiB) is
  the target contract and must be left at default on the disposable instance.

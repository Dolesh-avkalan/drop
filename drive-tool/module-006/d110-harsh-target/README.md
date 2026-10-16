# D110 harsh-fault package — compact core

Bounded adversarial "break-it" extension for the accepted D102 final HTTP
candidate. This package is authored and **sandbox-tested here**; it does **not**
run on the target from here and **no target result is fabricated**. The
operator runs it on the designated disposable instance after Gemini security
review.

It is strictly separate from the D104 baseline HTTP runner and does **not**
duplicate the active baseline cloud run. It modifies **no** Drive Tool source,
test, acceptance spec or old evidence.

## Files (core — everything needed to run)

| file | bytes | sha256 |
| --- | --- | --- |
| `run_harsh_d110.py` | 32554 | `f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87` |
| `harsh_checks_d110.py` | 75545 | `5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43` |

`harsh_checks_d110.py` is the pinned payload; its sha256 is embedded in the
runner and verified **before** execution.

## Pins

- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
- archive: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  (sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`, verified in-sandbox)
- identity manifest: the same 26 pinned `drive_tool/` + `tests/` blob-sha1/sha256
  set used by D104, re-hashed fail-closed before any execution.

## Exact operator command (disposable target: Debian / CPython 3.13)

    cd d110-harsh-target && \
    timeout 1200 python3 run_harsh_d110.py \
        --confirm-disposable-host=instance-20261015-210506 \
        --json d110_summary.json

`timeout 1200` is the hard 20-minute outer operator bound. The runner defaults
to the interpreter it is launched with; add `--python python3.13` to pin it.
A nonzero exit means the package did not fully pass — read `d110_summary.json`
and the retained raw logs under `<workspace>/logs/`. The runner fails closed
unless the live hostname equals `instance-20261015-210506` **and**
`--confirm-disposable-host` matches it.

## Sandbox validation command (harness validation only — never a target pass)

    python3 run_harsh_d110.py --sandbox --base-dir /scratch/d110ws \
        --archive <local candidate tar.gz> --json d110_summary.json

`--sandbox` runs the identical package locally, marks
`disposable_host_verified=false` and `mode=sandbox`, and records any relaxed
containment in `sandbox_relaxations`. It is **never** reported as a target pass.

## Fixed allow-list of stages (execution order)

1. `selfcheck` — frozen arithmetic / accounting / temp-scan truth, no adapter.
2. `http_hostile` — malformed / oversize / slow-partial HTTP framing.
3. `admission_exhaustion` — deterministic 6+1 admission + recovery.
4. `isolation` — cross-agent / path / symlink containment.
5. `concurrent_ops` — simultaneous create / overwrite / range operations.
6. `crash_kill` — synchronized child SIGKILL + fresh recovery + orphan audit.
7. `resource_pressure` — CHILD-only CPU / RAM / FD pressure.
8. `enospc` — RLIMIT_FSIZE EFBIG + injected 4-phase ENOSPC.

Each stage prints one `HARSH_JSON: {...}` line; the runner aggregates and
retains per-stage logs, `summary.json` and `logs/MANIFEST.md`.

## Case / invariant matrix

| stage | cases | invariants / gate | sandbox result |
| --- | --- | --- | --- |
| selfcheck | frozen consts; temp-scan; fixture bound | no drift; scan finds exactly the prefixed files | PASS |
| http_hostile | 14 framing probes + slow-partial | server survives every probe; a valid request succeeds afterwards; bounded response; threads reaped; fd baseline | PASS |
| admission_exhaustion | 50 × (6 occupiers + 1 excess) + recovery | real service-entry barrier; 300 success / 50 busy / 0 unexpected; 60/60 recovery; threads reaped; fd baseline | PASS |
| isolation | cross-agent; 10 hostile file_ids at client **and** server boundary; symlink escape; outside sentinel | every hostile id denied (403/404/503), never 200-ok; symlinks denied; sentinel byte-identical and unexposed | PASS |
| concurrent_ops | 6-way no-overwrite create race; 2 writers × 3 readers overwrite/range; 6-way multi-agent create | exactly 1 create winner; zero torn reads; zero temp residue; fd baseline | PASS |
| crash_kill | C1 pre-fsync kill, C2 post-fsync pre-publish kill, each overwrite=False/True | child SIGKILLed; ≥1 orphan temp; overwrite target preserved / non-overwrite target absent; fresh-service recovery ok; orphan visibility recorded | PASS |
| resource_pressure | R1 4 low-priority CPU children + 300-op workload; R2 RLIMIT_AS memory; R3 EMFILE | R1 300/300; R3 EMFILE mapped to ServiceError, 0 raw escapes, recovery ok; R2 skipped below the VM-headroom floor | PARTIAL (R2 SKIPPED) |
| enospc | RLIMIT_FSIZE EFBIG; injected ENOSPC at temp-create / mid-write / fsync / publish × overwrite False/True | every failure → `ServiceError` code `unavailable`; overwrite target preserved; no partial publication; 0 orphan temps; fd baseline; full recovery | PASS |

## Distinguishing expected faults from defects

The package never relabels an adverse diagnostic as a normal success. It
separates:

- **expected denial** (`denied` 403 / `not_found` 404 / `too_large` 413) — the
  isolation and size guards working;
- **expected busy** (`busy` 503) — deterministic admission exhaustion working;
- **expected resource fault** (`unavailable` 503 from ENOSPC/EFBIG/EMFILE) —
  storage/descriptor faults correctly mapped;
- **corruption / escape / unhandled exception / deadlock / leak** — a genuine
  FAIL. None were observed.

## Safety boundaries

- stdlib only; no credential, cloud API, install, reboot, service/public
  binding, real root, deploy, or remote shell.
- workspace: new unique `/tmp` dir, mode `0700`, strict descendant of the base,
  ≤ 192 MiB; ≥ 1 GiB free-disk floor; 16 MiB emergency ballast file.
- `TMPDIR` inside the workspace; bytecode writing disabled.
- every executable/importable file re-hashed fail-closed before execution;
  unexpected files, symlinks, traversal and oversize rejected.
- per-stage deadlines + an overall deadline < 20 min; each stage in its own
  process group, killed as a group on timeout; byte-capped capture.
- the runner only ever kills its own child process groups; SSH/parent preserved.
- child pressure is bounded: `RLIMIT_AS ≤ 512 MiB`, ≤ 4 CPU children at
  `nice(15)` + `RLIMIT_CPU`, `RLIMIT_NOFILE` lowered only inside a child; host
  `MemAvailable ≥ 1 GiB` before the RAM stage, abort below 512 MiB.

## Explicit non-guarantees

- **No physical-power-loss durability.** SIGKILL proves process-crash atomicity,
  not durability across a hypervisor disk write-back cache.
- **SIGKILL-orphaned temp files are not swept.** A process killed between
  `mkstemp` and `unlink` cannot run its `finally:`; the package *audits* orphans
  rather than claiming they are cleaned up.
- **R2 memory pressure may be skipped.** If the interpreter's baseline `VmSize`
  leaves less than 192 MiB headroom under the 512 MiB `RLIMIT_AS`, R2 is
  reported `SKIPPED` (never PASS).
- **Unprivileged mount/tmpfs ENOSPC is not attempted.** The package never fills
  the host filesystem; it relies on kernel `RLIMIT_FSIZE` EFBIG and injected
  syscall ENOSPC instead.
- **Hardware timing of uninstrumented races is statistical.** C1/C2 are
  pipe-synchronized and deterministic; C3-style storms and R1 are statistical.

## Sandbox evidence (actual, retained under `evidence/`)

Executed in-sandbox on the pinned archive under CPython 3.11.2 and 3.12.13
(CPython 3.13 was **not available** in the sandbox; the target is 3.13). Both
interpreters produced identical verdicts: seven stages PASS, `resource_pressure`
PARTIAL because R2 was honestly skipped (baseline `VmSize` ≈ 520 MiB exceeds the
512 MiB child `RLIMIT_AS` budget). No genuine product defect was observed. The
aggregate is therefore PARTIAL, not PASS — a skipped capability is never
reported as a pass. Raw per-stage logs, the two run summaries, the guard-negative
controls and the environment capture are in `evidence/`.

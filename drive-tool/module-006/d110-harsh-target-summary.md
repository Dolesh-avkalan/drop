# D110 — Sarvam adversarial break-it package (final answer)

**Status:** authored and **sandbox-tested**; **NOT run on the target** and **no
target result is fabricated**. Gemini security review is required before the
Director launches it on the designated disposable instance.

**Scope honoured:** separate bounded harsh-test package; no Drive Tool source,
test, acceptance spec or old evidence was modified; no credentials, no cloud
API, no production edits, no remote execution; the active baseline cloud run
was **not** duplicated.

---

## 1. What was built

A compact, stdlib-only, two-file harness plus a README and checksums, reusing
the accepted D104 runner containment / identity / archive / resource patterns
and adapting the approved D065/Gemini harsh design to the **accepted final HTTP
adapter** (`drive_tool/http_adapter.py` over `drive_tool/file_service.py`).

| file | bytes | sha256 |
| --- | --- | --- |
| `run_harsh_d110.py` (outer runner) | 32554 | `f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87` |
| `harsh_checks_d110.py` (pinned payload) | 75545 | `5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43` |
| `README.md` | 8128 | `9301351c8b4b701c783f8f68dfb73aa6441e3e4d4ccb3dac9ff285a08bdf9248` |

The payload sha256 is embedded in the runner and verified before execution.

### Source pin
- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
- archive: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  — sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`
  (**re-verified in-sandbox**, matches the D104-documented value)
- identity manifest: the same 26 pinned `drive_tool/` + `tests/` blob-sha1/sha256
  set as D104, re-hashed fail-closed before any execution.

### Exact operator command (disposable target: Debian / CPython 3.13)
```
cd d110-harsh-target && \
timeout 1200 python3 run_harsh_d110.py \
    --confirm-disposable-host=instance-20261015-210506 \
    --json d110_summary.json
```
The runner fails closed unless the live hostname equals
`instance-20261015-210506` **and** `--confirm-disposable-host` matches it. A
nonzero exit means the package did not fully pass; read `d110_summary.json` and
the retained logs under `<workspace>/logs/`.

---

## 2. Fixed allow-list of stages and case/invariant matrix

| stage | cases | invariants / gate |
| --- | --- | --- |
| `selfcheck` | frozen consts; temp-scan truth; fixture bound; meminfo | no drift; scan finds exactly the prefixed files |
| `http_hostile` | 14 framing probes (overlong line/header, too-many-headers, huge/duplicate/non-digit content-length, bare-LF, trailing bytes, unknown endpoint, oversize JSON/save body, truncated body, empty/immediate-close) + slow-partial | server survives every probe; a valid request succeeds afterwards; bounded response; threads reaped; fd back to baseline |
| `admission_exhaustion` | 50 × (6 occupiers + 1 excess) + recovery | real service-entry barrier; 300 success / 50 busy / 0 unexpected; 60/60 recovery; threads reaped; fd baseline |
| `isolation` | cross-agent; 10 hostile file_ids probed at the **client** and the **server** boundary; symlink escape; outside sentinel | every hostile id denied (403/404/503), never 200-ok; symlinks denied; sentinel byte-identical and unexposed |
| `concurrent_ops` | 6-way no-overwrite create race; 2 writers × 3 readers overwrite/range; 6-way multi-agent create | exactly 1 create winner; zero torn reads; zero temp residue; fd baseline |
| `crash_kill` | C1 pre-fsync kill, C2 post-fsync pre-publish kill, each overwrite=False/True | child SIGKILLed; ≥1 orphan temp; overwrite target preserved / non-overwrite target absent; fresh-service recovery; orphan visibility recorded |
| `resource_pressure` | R1 four `nice(15)` CPU children + 300-op workload; R2 `RLIMIT_AS` memory; R3 `EMFILE` | R1 300/300; R3 EMFILE mapped to `ServiceError`, 0 raw escapes, recovery ok; R2 skipped below the VM-headroom floor |
| `enospc` | `RLIMIT_FSIZE` EFBIG; injected ENOSPC at temp-create / mid-write / fsync / publish × overwrite False/True | every failure → `ServiceError` code `unavailable`; overwrite target preserved; no partial publication; 0 orphan temps; fd baseline; full recovery |

The harness separates **expected denial** (403/404/413), **expected busy**
(503), and **expected resource fault** (503 `unavailable`) from genuine
**corruption / escape / unhandled exception / deadlock / leak**. No genuine
defect class was observed.

---

## 3. Actual sandbox results (raw evidence retained)

Executed in-sandbox against the pinned archive under **CPython 3.11.2** and
**3.12.13**. CPython 3.13 was **not available** in the sandbox (the target is
3.13) — stated plainly rather than claimed.

Both interpreters produced identical verdicts:

| stage | result |
| --- | --- |
| selfcheck | PASS |
| http_hostile | PASS |
| admission_exhaustion | PASS |
| isolation | PASS |
| concurrent_ops | PASS |
| crash_kill | PASS |
| resource_pressure | **PARTIAL** (R1 PASS, R3 PASS, R2 SKIPPED) |
| enospc | PASS |

Aggregate: **PARTIAL** (exit 1) — seven PASS, one PARTIAL, because R2 was
honestly skipped. A skipped capability is **never** reported as a pass.

Representative raw observations (full logs in `evidence/run_logs_*`):

- **http_hostile** — every malformed probe answered with a bounded, well-formed
  envelope (400 `invalid`, 413 `too_large`, or 504 `timeout`), max response 191
  bytes; the server recovered (valid op succeeded); 7 adapter threads reaped on
  close.
- **admission_exhaustion** — 300 occupier successes, 50 excess `busy`, 0
  unexpected, 60/60 post-overload recovery.
- **isolation** — all 10 hostile ids denied at the server (403/404/503); the
  two symlink probes and the cross-agent read/write denied; outside sentinel
  byte-identical and absent from listings.
- **crash_kill** — all four cases SIGKILLed at the synchronization point; 1
  orphan temp each; overwrite targets preserved, non-overwrite targets absent;
  fresh-service recovery ok; orphan temps **not** visible in `list()`/`find()`.
- **enospc** — EFBIG and all eight injected phases raised `ServiceError`
  code `unavailable` with `outcome_uncertain=True`, `retry_safe=False`;
  overwrite targets preserved, no partial publication, 0 orphan temps, fd
  stable, full recovery.

### Guard-negative controls (prove the guards are not no-ops)
`evidence/negative_controls.txt` — all PASS: clean payload/source accepted;
tampered payload rejected; tampered source rejected (size+blob+sha mismatch);
extra importable file rejected; extra `tests/` file rejected; symlink in source
rejected; missing expected file rejected.

---

## 4. Product findings

**No genuine product defect was found.** Two behaviours are worth flagging for
Gemini's security review (recorded, not relabelled):

1. **Save-phase error classification differs from the historical design.** The
   approved D065/Gemini design expected a pre-publish ENOSPC/EFBIG to surface as
   `ServiceError(code="unavailable", outcome_uncertain=False, retry_safe=True)`.
   The accepted implementation maps **every** save-phase failure through
   `is_write_in_flight=True`, so the observed result is
   `code="unavailable", outcome_uncertain=True, retry_safe=False`
   (`drive_tool/file_service.py`, `_translate_storage_exception` /
   `save()`). The package records the **actual** behaviour and does not assume
   the historical expectation. Smallest reproduction: `enospc` stage,
   `injected_phases` — inject `OSError(ENOSPC)` at any write phase and call
   `LocalFileService.save(...)`; expected (historical) `uncertain=False,
   retry_safe=True`, actual `uncertain=True, retry_safe=False`. Whether the
   actual semantics are correct is a contract decision for the Director/Gemini,
   not a defect this package asserts.

2. **Client-side id validation is the first line of containment.** Malformed
   file_ids (`..`, absolute, NUL, `//`, over-long names) raise a raw
   `ValueError` inside `DriveClient` **before** any request is sent; the same
   ids sent as raw HTTP are denied by the server (403/404/503). Recorded as
   informational — the server boundary was probed separately to confirm it also
   denies.

---

## 5. Unresolved limits / non-guarantees

- **Not run on the target.** The Director launches the reviewed package; this
  document is not a target result.
- **CPython 3.13 not exercised in-sandbox** (3.11/3.12 only). The target is
  3.13; the runner defaults to its launching interpreter and accepts
  `--python python3.13`.
- **R2 (RAM pressure) SKIPPED in-sandbox.** The interpreter's baseline
  `VmSize` (≈ 520 MiB) exceeds the 512 MiB child `RLIMIT_AS` budget, so the
  memory sub-stage cannot run there without violating the child limit. R2 is
  reported `SKIPPED` and the stage is `PARTIAL`, never PASS. On a target where
  the interpreter baseline is smaller, R2 runs.
- **Sandbox containment relaxation.** The sandbox `/tmp` is a ~64 MiB tmpfs
  below the 1 GiB floor, so local validation used `--sandbox --base-dir` on a
  larger filesystem; this is flagged in `sandbox_relaxations`. The **target
  run does not relax containment**: base must resolve under `/tmp` with a
  ≥ 1 GiB floor.
- **No physical-power-loss durability claim.** SIGKILL proves process-crash
  atomicity, not durability across a hypervisor disk write-back cache.
- **SIGKILL-orphaned temps are audited, not swept.** A process killed between
  `mkstemp` and `unlink` cannot run its `finally:`; the package reports the
  orphans rather than claiming cleanup.
- **Unprivileged mount/tmpfs ENOSPC is not attempted** — the host filesystem is
  never filled; kernel `RLIMIT_FSIZE` EFBIG and injected syscall ENOSPC are
  used instead.
- **Uninstrumented race timing is statistical.** C1/C2 are pipe-synchronized
  and deterministic; storms and R1 are statistical.

---

## 6. Publication (this relay)

- final answer: `drive-tool/module-006/d110-harsh-target-summary.md`
- created files: `drive-tool/module-006/d110-harsh-target-summary/`
  (package: `run_harsh_d110.py`, `harsh_checks_d110.py`, `README.md`,
  `SHA256SUMS`, `negative_controls.py`; plus `evidence/`)
- compact core also published to `drive-tool/module-006/d110-harsh-target/`
  (the task's "publish compact core first" location)

Repo: `Dolesh-avkalan/drop`, branch `main`.

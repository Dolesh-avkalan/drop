# D119 — first-D110 harsh package: narrow diagnosis + minimal patch

Scope: diagnosis/correction of the **first D110 package** only. No product fix,
no target run, no rewrite. The original D110 package and the D112 package are
preserved untouched. No third package is created.

## Verdict

- **`concurrent_ops` FAIL** on the target (`concurrent overwrite errors:
  ['DriveClientError']`) is a **harness over-subscription**, not a product
  fault. The stage runs 2 writers + 3 readers, each in a *tight reconnect loop
  with no drain-aware lease*; the harness transiently holds **>6 backend
  requests** and the 7th is (correctly) rejected `busy` → `DriveClientError`.
  The product's admission (6 slots) is working as designed.
- **`resource_pressure` R2 SKIP** is a **harness child-spawn defect**: the RAM
  child is `os.fork()`ed from the (previously threaded) process and inherits
  ~512 MiB `VmSize`, so the 192 MiB ballast cannot fit under the 512 MiB
  `RLIMIT_AS` cap.
- **No product bug found.** No corruption or escape is proven (consistent with
  the target result).

## Pins (exact)

| item | value |
| --- | --- |
| source | `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528` |
| archive sha256 | `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3` |
| first-D110 runner `run_harsh_d110.py` | sha256 `f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87` |
| first-D110 payload `harsh_checks_d110.py` | sha256 `5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43` |
| D101 gate | sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` |

The original package was located by **path + content hash** at
`drop/drive-tool/module-006/d110-harsh-target/` (relay commits
`974ba86e`/`7b89673d`/`052b47dd`/`7b650630`).

## Root cause 1 — `concurrent_ops` (admission lease timing)

The D101 gate deliberately used **K = 5 client leases, each held until response
+ 55 ms** (`CLIENT_LEASES=5`, `DRAIN_HOLD_SECONDS=0.055`) so a client does not
open a new connection while the server is still draining the previous one. The
first-D110 `concurrent_ops` stage kept the count at 5 (2 writers + 3 readers)
but **dropped the 55 ms hold and the lease cap**. Under CPU contention the
reconnect loops overlap the server's post-response drain window; the harness
then holds >6 backend requests and the 7th gets `busy`.

Evidence (sandbox, 2 vCPU + 4 low-priority CPU hogs — `evidence/repro_a_run.txt`):

```
stock stage under contention: 9/12 FAIL
every FAIL: busy=1  served_max=6   (a transient 7th connection rejected busy)
every PASS: busy=0  served_max=6
```

Rich diagnostics (`evidence/repro_b_run.txt`) — the failing op reports:

```json
{"op": "save", "kind": "DriveClientError", "code": "busy",
 "message": "drive service error: busy",
 "outcome_uncertain": false, "retry_safe": true}
```

`served_max == 6` proves the service never served more than 6 concurrently —
the product is correct; the harness over-subscribed.

## Root cause 2 — `resource_pressure` R2 (`VmSize` inheritance)

`_r2_child` is `os.fork()`ed (not exec'ed) after the adapter's 7 threads have
run. Thread stacks + arenas are retained, so the process `VmSize` stays ~512 MiB
even after `adapter.close()`. The forked child inherits it.

Evidence (`evidence/repro_c_run.txt`):

```
parent single-threaded VmSize_kb = 29160
parent after adapter (7 threads) VmSize_kb = 548744
forked child VmSize_kb = 548744   -> fits 192 MiB under 512 MiB: false  -> SKIP
```

and after `adapter.close()`: `VmSize 548576 -> 523876 KiB` (still cannot fit).
The target's `529312 KiB` is the same mechanism.

**Fix (proposed):** spawn the RAM child as a **clean exec'ed interpreter**
(`subprocess.Popen([sys.executable, "-c", _R2_CHILD_SRC, ...], pass_fds=(wfd,))`)
so its `VmSize` starts small. Cap unchanged at **512 MiB**.

Evidence (`evidence/repro_c_run.txt`, Part 2):

```
fresh child VmSize_kb = 26840 ; after 192 MiB ballast = 228552 (< 512 MiB)
ops_ok=50  mem_error=MemoryError  recovery_ops=20
```

(`fork-before-thread` — forking R2 before the adapter exists — is an acceptable
alternative; the clean exec is preferred because it is immune to inherited
state.)

## Minimal patch

`patch/d119_concurrent_lease_and_r2.patch` — a unified diff against
`harsh_checks_d110.py` (sha256 `5599d32f…`). It is **surgical**:

1. `concurrent_ops`: add `_LeaseLimiter` (K=5, hold 55 ms) around every client
   op (create/write/read/multi) and `_exc_detail` rich diagnostics
   (`code`/`message`/`outcome_uncertain`/`retry_safe`/`op`). A `busy` is **still
   an error** — never forgiven.
2. `resource_pressure` R2: replace the `os.fork()` spawn with the clean-exec
   child above.

Strict counts and integrity checks are unchanged.

## old-fail → new-pass (sandbox, same contention)

| harness | concurrent_ops | R2 |
| --- | --- | --- |
| first-D110 (stock) | FAIL (busy) — `evidence/repro_a_run.txt`, `repro_b_run.txt` | SKIPPED — `evidence/repro_c_run.txt` |
| D119 patched | **0/12 FAIL**, `lease_max_held=5` — `evidence/repro_d_conc.txt` | **PASS** — `evidence/repro_d_res.txt` |

Patched `resource_pressure`: `result=PASS`, `R2={ok:50, mem_error:MemoryError,
vm_kb:40200, recovery_ok:20}`, `R1 ok=300`, `R3={result:PASS, mapped:128,
raw:0, recovery_ok:20}`.

## Semantic mutant (the fix does not blind the oracle)

`evidence/repro_e_run.txt`: with a runtime **non-atomic-publish mutant**
(`_os_rename` replaced by a truncate-and-write-in-place), the *patched* stage
still **FAILs 6/6** with torn/inconsistent reads (e.g. `len=2048`,
`len=0`). So the lease fix prevents over-subscription without forgiving real
corruption.

## Gemini review required

The patch changes **admission lease timing** (`concurrent_ops`) and the **R2
child spawn** — both are safety/oracle semantics. **Gemini review is required
before the patched package is used as a target candidate.** This package is a
diagnosis + proposal only; it is not a target pass.

## Missing identity evidence

- The operator's `drop e96136c9` short ref is **not resolvable** via the API
  (40-hex required); the original package was identified by path + content hash
  (`f55f1ca2` / `5599d32f`) instead.
- No target-instance execution by us; the target numbers are the operator's.
- No CPython 3.13 in the authoring sandbox (validated on 3.12.13; 2 vCPU).

## Files

```
README.md
patch/d119_concurrent_lease_and_r2.patch
repro/repro_a.py  repro_b.py  repro_c.py  repro_d.py  repro_e.py
evidence/repro_a_run.txt  repro_b_run.txt  repro_c_run.txt
         repro_d_conc.txt  repro_d_res.txt  repro_e_run.txt
SHA256SUMS
```

The repro scripts are read-only diagnostics; `repro_e.py` applies a runtime
product mutant in-process only (no file on disk is changed).

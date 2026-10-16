# D122 — corrected D110 harsh package (fixes the four Gemini blockers in the D119 delta)

Targeted correction of the **D119 patch only**. No product/source change, no
whole-package rewrite. Immutable source `337e4c7…` and the original D110
evidence are untouched. No third package.

## Pins (exact)

| item | value |
| --- | --- |
| immutable source | `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528` |
| archive sha256 | `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3` |
| original D110 runner `run_harsh_d110.py` | sha256 `f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87` |
| original D110 payload `harsh_checks_d110.py` | sha256 `5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43` |
| reviewed D119 patch | `d119_concurrent_lease_and_r2.patch` @ drop `248d1f9def06746a7947d814ff1f76a0a63906a1` |
| **corrected payload** `harsh_checks_d110.py` | sha256 `3e13cddebb3306563b238354dc528f9a4833316c17261fa6251cd44abd215bd7` (81318 B) |
| **corrected runner** `run_harsh_d110.py` | sha256 `39192ffeba131725e1605ade73b69881539ae71ed9f61de92111debb2dede93b` (32554 B) |
| corrected patch `d122_corrected.patch` | sha256 `2a1e09f3dbb0a7428607fea4490f31f4e89885395eefaff6277cf82a65b20aa4` (21803 B) |

`d122_corrected.patch` is a unified diff from the **original** payload
(`5599d32f…`) to the corrected payload — it supersedes the D119 patch.

## The four blocker fixes

1. **Unhashable-dict crash on any writer failure.** `_exc_detail()` returns a
   dict; `sorted(set(write_err))` raised `TypeError: unhashable type: 'dict'`,
   turning the exact failure case into an unhandled `ERROR`. Now `write_err`
   is bounded (`write_err[:5]` + `overwrite_error_count`), guarded by a lock,
   and the writer breaks on first error — no `set()` on dicts, so a writer
   failure yields a clean `FAIL` with diagnostics and resource checks.
2. **6-way one-shot races restored.** `CONC_LEASES=5` no longer caps sub-tests
   (a) and (c); those keep the full `MAX_CONCURRENT` (=6) way race with **no**
   slot cap and a real `threading.Barrier(6)` entry barrier (recorded as
   `create_entered` / `multi_entered`). The `_LeaseLimiter(K=5, 55 ms)` now
   applies **only** to the looping sub-test (b) (2 writers + 3 readers = 5
   threads). `>=55 ms` drain pauses sit between phases (a) → seed → (b) → (c).
   Documented as a normal-scheduling mitigation, not a universal OS guarantee.
3. **R2 ballast/oracle drift.** Ballast is now the documented **192 MiB**
   (`192*1024*1024`, touched across pages); the child reports `vm_kb_before`,
   `vm_kb_ballast` and `vm_kb_peak`; and the parent oracle now requires
   `mem_error == "MemoryError"` **and** `ok == 50` **and** `recovery_ok == 20`
   for R2 `PASS`. Child cap unchanged at **512 MiB**.
4. **R2 child lifecycle / dead code.** The clean-exec R2 child now runs with
   `start_new_session=True` (own process group) and is reaped via `proc.wait()`
   (never a raw `os.waitpid` behind `Popen`); `_collect_child` kills a timed-out
   child's process group **before** any blocking wait; the dead `_r2_child`
   function is removed.

## What is NOT changed

- `selfcheck`, `http_hostile`, `admission_exhaustion`, `isolation`,
  `crash_kill`, `enospc` — byte-identical to the original payload.
- The R2 workload counts (50 pre-MemoryError ops, 20 recovery ops) and the R1
  (300) / R3 counts — unchanged. No workload is lowered.
- No `busy` is forgiven and no uncertain write is retried.
- The outer runner changed in exactly **two lines**: `PAYLOAD_SHA256` and
  `PAYLOAD_BYTES`. The target host guard (`--confirm-disposable-host`,
  hostname match) is preserved; sandbox relaxations remain documented in the
  runner's `--sandbox` path.

## Operator command (disposable target)

    cd d122-harsh-corrected && \
    timeout 1200 python3 run_harsh_d110.py \
        --confirm-disposable-host=instance-20261015-210506 \
        --json d122_summary.json

## Files

```
README.md
harsh_checks_d110.py     # corrected payload (3e13cdde…)
run_harsh_d110.py        # corrected outer runner (39192ffe…)
d122_corrected.patch     # diff vs original payload 5599d32f…
SHA256SUMS
```

## Status

- Sandbox validation (full runner + focused negatives) is recorded in
  `evidence/` (published progressively).
- **Gemini delta acceptance is required before any target re-run.** This is a
  corrected candidate, not a target pass.
- Unfinished checks and exact inventory are listed in the D122 summary.

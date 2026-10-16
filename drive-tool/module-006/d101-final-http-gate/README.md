# d101-final-http-gate — corrected harness copy

This is the **separate evidence copy** of the corrected HTTP stress-gate harness
required by D101. It contains the harness with **only** the aggregate
exit/status (the gating helper) repaired; the frozen operations, schedules,
intents, budgets, the real 6-service-entry saturation barrier and the candidate
source `f37a30b` are unchanged.

| file | note |
| --- | --- |
| `scripts/http_gate_d101.py` | the corrected harness — sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` |
| `scripts/build_d101_harness.py` | reproducible d097 → d101 builder (gate helper only) |
| `scripts/test_gate_exit_d101.py` | negative-injection + exhaustive truth-table unit suite |
| `scripts/scope_check_d101.py` | AST proof that only the gating helper differs |

The **full evidence bundle**, the raw logs, the manifest and the report are in
the sibling folder `../d101-gate-exit-verification/`; the summary answer is
`../d101-gate-exit-verification.md`.

Gate contract: exit **0** iff `selfcheck`, `smoke600`, `soak10000` and
`saturation_6plus1` were all executed and PASSed; **nonzero** on any FAIL,
missing, skipped, error or timeout. **No soak (nor saturation) after a smoke
failure.** Verified `--gate` exit 0 on Python 3.11.2 and 3.12.13 against
`Dolesh-avkalan/drive-tool @ f37a30b`.

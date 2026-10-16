# D101 evidence manifest

Task: D101 — harness-only aggregate exit/status repair of the D096/D097 HTTP
stress-gate harness. Separate evidence copy; frozen ops/schedules/intents/budgets/
real 6-service-entry saturation barrier/source `f37a30b` unchanged.

Candidate source verified on this host (recomputed from fetched bytes):
`Dolesh-avkalan/drive-tool @ f37a30b0073611c05d26f714f2e833d689673a09`,
`drive_tool/http_adapter.py` blob `41279e6290617968c3b4f3f91fc3cf9a7dab505a`
sha256 `3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c`,
`tests/test_http_adapter.py` blob `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3`
sha256 `b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf`.
Base `b962a04df1c5abdb78c37617d3a6adca02d04024`.

Environment: see `env.txt` (Linux 4.19.0-gvisor x86_64, nproc 2,
Python 3.11.2 / 3.12.13).

## Contents

| path | what |
| --- | --- |
| `scripts/http_gate_d101.py` | corrected harness (gate helper only changed) |
| `scripts/http_gate_d097.py` | the verified D097 harness, included read-only for the diff |
| `scripts/build_d101_harness.py` | surgical d097 → d101 builder (reproducible) |
| `scripts/test_gate_exit_d101.py` | negative-injection + exhaustive truth-table unit suite |
| `scripts/scope_check_d101.py` | AST scope proof (only the gate helper differs) |
| `logs/harness_d097_to_d101.diff` | the full unified diff (2 hunks) |
| `logs/d101_scope.txt`, `logs/d101_scope.json` | scope proof output |
| `logs/d101_gate_exit_unit_3.11.txt/.json`, `…_3.12.txt/.json` | unit-suite results (23/23, 2401 combos, 0 false passes) |
| `logs/d101_gate_3.11.json`, `logs/d101_gate_3.12.json` | corrected `--gate` aggregate results (compact) |
| `logs/d101_gate_3.11.stdout.compact.json`, `…_3.12…` | stdout aggregate (compact) |
| `logs/d101_selfcheck_3.11.json`, `…_3.12.json` | selfcheck re-runs |
| `logs/old_d097_gate_3.11.json` | **preserved old nonzero history** (D097 `--gate` exit 1) |
| `logs/comparison_old_vs_new.txt` | old exit 1 vs new exit 0 proof |
| `logs/raw_exit_codes.txt` | raw exit codes for every run |
| `schedules/frozen_schedule_manifest.json` | D097 frozen schedule manifest (byte-identical) |
| `schedules/d101_schedule_dump.json` | re-generated dump, sha256 `14a6ac33…` (== D097) |
| `env.txt` | host/interpreters/source identity |
| `HASHES.txt` | sha256 + size of every file in this bundle |
| `REPORT.md` | the D101 report |

`HASHES.txt` lists the sha256 and byte size of every published file; those are
the hashes of the exact published bytes.

Preserved, unmodified: the D096 published harness, the D095 evidence and the D097
evidence in `drop`; the old nonzero D097 `--gate` result is retained here as
`logs/old_d097_gate_3.11.json`.

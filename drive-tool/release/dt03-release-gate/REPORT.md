# dt03 — drive-tool release gate (raw evidence)

Independent run of the drive-tool release gate against the frozen candidate,
executed as a non-root user, with the raw outputs committed alongside this
report. No source in `drive-tool` was modified.

## Report lines

```
SUITE: OK (581 tests, 3 skipped, 0 failures, 0 errors)   [exit 0]
GATE_EXIT: 0
STAGE selfcheck: PASS
STAGE smoke600: PASS
STAGE soak10000: PASS
STAGE saturation_6plus1: PASS
GATE (aggregate): PASS
```

## Environment

| item | value |
| --- | --- |
| repo | `Dolesh-avkalan/drive-tool` |
| commit | `321ccaef4c33d5f98727aa32995c0d9bcf893660` (`321ccae`, main) |
| python | `Python 3.12.13` |
| user | `sandbox` (uid=1000, gid=1000) — **non-root** |
| harness | `Dolesh-avkalan/drop @ drive-tool/module-006/d101-final-http-gate/scripts/http_gate_d101.py` |
| harness sha256 | `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` — **matches the expected digest** |

The suite was run as the non-root `sandbox` user (uid 1000) so the
file-permission check is actually exercised (root ignores permission bits).

## 1. Test suite

Command:

```
python3 -m unittest discover -s tests
```

Result (verbatim tail of `suite.txt`):

```
Ran 581 tests in 15.083s

OK (skipped=3)
```

Exit code 0. Full output: `REPORT/suite.txt`.

## 2. Gate harness

Command:

```
python3 http_gate_d101.py --repo <checkout> --gate --json gate.json --quiet
```

The `--gate` path runs, in order: `selfcheck` → `smoke600` (600 calls,
6 concurrent agent personas) → `soak10000` (10,000 calls) → `saturation_6plus1`
(50 cycles × 7 = 300 success + 50 busy). The soak and saturation are withheld
if smoke does not pass; here smoke passed, so all four stages executed.

### Per-stage results (from `gate.json`)

| stage | result | detail |
| --- | --- | --- |
| `selfcheck` | PASS | schedule/accounting checks only, no adapter; `problems: []` |
| `smoke600` | PASS | 600 intents = 580 valid + 20 read-only saves; `problems: []` |
| `soak10000` | PASS | 10,000 intents = 9,680 valid + 320 read-only saves; `problems: []` |
| `saturation_6plus1` | PASS | 300 valid + 50 busy; `problems: []` |
| **gate (aggregate)** | **PASS** | `problems: []`, `note: null`, all four required stages executed |

Exit code **0**.

### D089 accounting buckets (every scheduled intent accounted for)

| bucket | smoke600 | soak10000 | saturation |
| --- | --- | --- | --- |
| `valid_below_capacity_success` | 580 | 9680 | 300 |
| `expected_readonly_denial` | 20 | 320 | 0 |
| `expected_saturation_busy` | 0 | 0 | 50 |
| `unexpected_unavailable` | 0 | 0 | 0 |
| `unexpected_other_error` | 0 | 0 | 0 |

Every bucket matches its frozen count; there are zero unexpected buckets.

### Resource / cleanup checks

All resource checks passed in every stage: `within_budget: true`,
`adapter_threads_ok: true`, `closed: true`, `fd_ok: true`, `rss_ok: true`.
The 7 adapter threads were present live and fully reaped after close
(`adapter_threads_after_close: []`) in each stage; file descriptors returned to
baseline (11 → 4) and RSS growth stayed within the frozen 64 MiB bound (smoke
−8.8 MiB, soak −0.09 MiB). Saturation elapsed 2.33 s; soak elapsed 146.5 s;
smoke elapsed 7.75 s. Fixture bytes 25,128 (limit 32 MiB); workspace 25,384 B
(limit 128 MiB).

### Schedule fingerprints (frozen, unchanged)

| schedule | fingerprint |
| --- | --- |
| smoke600 | `74e61249b9e7d3be0b0f3e31f7e88d1be5368c9ef752991fc21fdd690e9d68ef` |
| soak10000 | `7f3911b44f9a1dd86671fcfd141b8aa0ac00486deb94f97c37d01cc89105bf4e` |

Both match the frozen fingerprints emitted by `--selfcheck`.

## Unexpected / noteworthy

- **Nothing failed.** No `unexpected_unavailable`, no `unexpected_other_error`,
  no gate `problems`.
- The test suite emitted `ResourceWarning: unclosed file` messages from
  `tests/test_http_adapter.py` (it opens the adapter source without closing the
  handle). These are warnings only — the suite still reports `OK`. Noted for
  completeness; not a failure.
- The suite skips 3 tests (reported as `skipped=3`); the harness does not
  report the skip reasons.
- `--quiet` omits the per-call `records`/`cycles` arrays; the gate JSON still
  carries every stage's aggregate buckets, counts, fingerprints and resource
  figures.

## Raw evidence files

Committed next to this report (and, per the relay's filing convention, also
under `REPORT/`):

| file | content |
| --- | --- |
| `suite.txt` | full `unittest` output (581 tests, OK, exit 0) |
| `gate.txt` | full stdout of the `--gate` run |
| `gate.json` | the gate's `--json` result document |
| `env.txt` | commit / python / user and provenance |

Gate exit code: **0**. Suite exit code: **0**.

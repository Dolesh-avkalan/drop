# d104 target HTTP runner — run report

All results below are the **parent's own sandbox runs** on the authoring side,
from the published/pinned bytes. No target execution, credential, install,
deploy, service/public binding or real-root access was performed.

## Environment (authoring sandbox)

- Linux 4.19.0-gvisor x86_64 (glibc 2.3), CPython **3.11.2** and **3.12.13**
  present. **CPython 3.13 is NOT available in this sandbox** — the target's
  3.13.5 could not be exercised here and no 3.13 result is claimed.
- candidate archive sha256 (download and local copy identical):
  `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`

## Acceptance results (full runner)

| run | interpreter | suite | gate raw exit | gate result | runner exit |
| --- | --- | --- | --- | --- | --- |
| `logs/run_3.11.json` | CPython 3.11.2 | 581 ran, skipped=3, exit 0 | 0 | PASS | **0** |
| `logs/run_3.12.json` | CPython 3.12.13 | 581 ran, skipped=3, exit 0 | 0 | PASS | **0** |
| `logs/run_download_3.12.json` | CPython 3.12.13 (network fetch path) | 581 ran, skipped=3, exit 0 | 0 | PASS | **0** |

Gate stages executed and PASS on both interpreters:
`selfcheck`, `smoke600`, `soak10000`, `saturation_6plus1`.

Gate buckets (identical on 3.11.2 and 3.12.13):

| stage | valid success | expected readonly denial | expected busy | unexpected other | unexpected unavailable |
| --- | --- | --- | --- | --- | --- |
| smoke600 | 580 | 20 | 0 | 0 | 0 |
| soak10000 | 9680 | 320 | 0 | 0 | 0 |
| saturation_6plus1 | 300 | 0 | 50 | 0 | 0 |

Suite skips audited — exactly the three documented control/opt-in skips, no
platform/adapter-missing skip:
1. `test_http_adapter.SmokeSoakGateContractTests.test_helper_raises_without_production_adapter`
2. `test_http_adapter.SmokeSoakGateTests.test_stage_smoke_600`
3. `test_http_adapter.SmokeSoakGateTests.test_stage_soak_10000`

Resources: workspace ≈ 9.34 MB allocated (≤ 128 MiB bound), max concurrent ops
6, whole run ≈ 145–146 s (suite ≈ 12 s, gate ≈ 133 s), inside the 20-minute
outer bound.

## Identity verification

All 28 executable/importable files under `drive_tool/` and `tests/` were
re-hashed and matched the embedded pinned git-blob sha1 + sha256, including the
two accepted overlay files:

- `drive_tool/http_adapter.py` — blob `41279e6290617968c3b4f3f91fc3cf9a7dab505a`,
  sha256 `3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c`
- `tests/test_http_adapter.py` — blob `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3`,
  sha256 `b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf`

and the preserved accepted order fix `tests/test_partial_scan_review_fixes.py`
(blob `c01003e7015915db3dcac15a168ff7aae3d423db`). Composite sourcehash
`b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c` reproduced.

## Negative checks (must fail closed)

See `logs/negatives.txt`. All five failed closed (runner exit 1), and none
reached the gate:

- **N1 identity tamper** — one pinned source file altered → `identity` size/
  blob/sha256 mismatch → FAIL.
- **N2 gate-payload tamper** — `http_gate_d101.py` altered → gate payload
  sha256 mismatch → FAIL before execution.
- **N3 workspace escape** — `--base-dir` outside `/tmp` → refused.
- **N4 workspace escape** — `--workdir` equal to the base (`/tmp` itself) →
  refused.
- **N5 stray importable file** — `docs/rogue_module.py` added → FAIL
  (`unexpected importable/executable file`).

## Packaging method

Core files were published first (`run_target_http.py`, `http_gate_d101.py`,
`README.md`, `MANIFEST.sha256`), then fetched back and byte/hash-verified
against the live GitHub file inventory, and only then were the raw logs and
this report added.

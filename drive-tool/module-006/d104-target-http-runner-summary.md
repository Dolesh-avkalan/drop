# D104 — target runner for the exact final HTTP candidate

## Verdict

A stdlib-only, pinned **target runner** for the accepted D102 final HTTP
candidate is built, sandbox-tested and packaged. It reuses the D098 runner
containment/identity/archive/resource patterns, adds no generic remote shell and
no unrelated framework, and drives the **exact** D101 corrected gate harness.
On the authoring sandbox the full runner returns **raw exit 0 on both CPython
3.11.2 and 3.12.13**, and every negative check fails closed. The disposable
target (Debian / CPython 3.13.5, `instance-20261015-210506`) is **not** run from
here and **no target result is fabricated**; CPython 3.13 is not available in
this sandbox, so the 3.13 result is explicitly not claimed.

## 1. Pins (frozen)

- **Candidate**: `Dolesh-avkalan/drive-tool` @
  `337e4c713829af76615472eb47b81244ff399528`
  (branch `feature/module-006b-final-service-candidate`).
- **Source archive**: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  — sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`
  (identical for the network fetch and the local copy).
- **Accepted overlay (unchanged, byte-identical to source `f37a30b`)**:
  - `drive_tool/http_adapter.py` — git blob `41279e6290617968c3b4f3f91fc3cf9a7dab505a`,
    sha256 `3ed13cfa7960854382577c9e0982d3ba116833793a6430d141732ccac89c020c`, 40881 B
  - `tests/test_http_adapter.py` — git blob `7a7be06d5ef0e25d0ac54e11bc5909cda27500d3`,
    sha256 `b678744759bd53c3dc992e215fc7e98cd5df869c381addbaaa2bfb15e2b87dbf`, 76436 B
- **Composite sourcehash** (adapter‖test): `b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c`.
- **Preserved accepted order fix**: `tests/test_partial_scan_review_fixes.py`,
  blob `c01003e7015915db3dcac15a168ff7aae3d423db`.
- **Gate payload**: exact D101 corrected harness
  (`drop@15192ab6f818cae9d74e94a7833a74a3d0826914`,
  `drive-tool/module-006/d101-final-http-gate/scripts/http_gate_d101.py`),
  sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b`,
  45668 B.

Every pinned blob/sha256 above was **recomputed from the actual archive bytes**
and matched the D102 `PINS.md`; the accepted order fix is present, so the suite
must pass strictly (no old known-failure excuse).

## 2. Core package (published first)

| file | bytes | sha256 |
| --- | --- | --- |
| `run_target_http.py` | 32795 | `4eaf7f530bb25646e2c58e61d05eded952fdf53172f2db212c4e43945d72fdbf` |
| `http_gate_d101.py` | 45668 | `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` |
| `README.md` | 3549 | `3bb404eb0ea3bdcced2f3313d4fcd89a814d624b2718e0f82227f30767e5ed33` |
| `MANIFEST.sha256` | — | (hash manifest of the whole package) |

The runner is one self-contained stdlib-only file. It embeds the pinned
git-blob-sha1 + sha256 for **all 28** executable/importable files under
`drive_tool/` and `tests/`, the gate-payload sha256, and the frozen gate
expectations. Nothing else is needed to run; the huge evidence bundle is
deliberately **not** included.

## 3. Exact short operator command

On the target (Debian / CPython 3.13.5), from the package directory:

    timeout 1200 python3 run_target_http.py --json d104_summary.json

`timeout 1200` is the hard 20-minute outer operator bound. Default interpreter
is the one launching the runner; pin it with `--python python3.13` if desired.
Nonzero exit = acceptance failed; read `d104_summary.json` and the retained
raw logs in the workspace.

## 4. What the runner does (fails closed at every gate)

1. **environment/identity** capture;
2. acquire the pinned archive (download, or `--archive <tar.gz>`) and extract it
   with absolute-path / traversal / link / per-file / count / total guards;
3. **re-hash every executable source/test/importable file** against the embedded
   pinned blob-sha1 + sha256; reject any unexpected importable/executable file
   anywhere, any unexpected `drive_tool/` or `tests/` file, symlinks and
   oversize;
4. verify the **gate payload sha256** before execution;
5. run the committed suite (`python -m unittest discover -s tests -v`) and
   **audit skips** — only the three documented control/opt-in skips are allowed;
   any platform/adapter-missing skip is a FAIL (no skip masking);
6. **only if the suite passes**, run the exact D101 gate
   (`http_gate_d101.py --repo <src> --gate --json <ws>/gate.json`) and require
   raw exit 0 with `selfcheck` + `smoke600` + `soak10000` + `saturation_6plus1`
   all executed and PASS and buckets **580+20 / 9680+320 / 300+50**, zero
   unexpected/unavailable;
7. gate workspace size and write a symlink-safe manifest; **retain raw
   evidence** (no cleanup).

Acceptance stages stop on the first failure; overall exit is strictly nonzero on
any FAIL/missing/skip/error/timeout. Execution is confined to a **new unique
`/tmp` workspace, mode 0700**, a strict descendant of the base (never the base
itself); `TMPDIR` lives inside it and bytecode writing is disabled. Bounds:
≤128 MiB workspace / 32 MiB fixtures / ≤6 concurrent ops, byte-capped subprocess
output and process-group kill on timeout, finite per-stage timeouts plus an
overall deadline under the 20-minute outer bound. No credential, cloud API,
install, reboot, service/public binding, real root or deploy.

## 5. Sandbox results (parent-run, from the pinned bytes)

| run | interpreter | suite | gate raw exit | gate | runner exit |
| --- | --- | --- | --- | --- | --- |
| `logs/run_3.11.json` | CPython 3.11.2 | 581 ran, skipped=3, exit 0 | 0 | PASS (all 4 stages) | **0** |
| `logs/run_3.12.json` | CPython 3.12.13 | 581 ran, skipped=3, exit 0 | 0 | PASS (all 4 stages) | **0** |
| `logs/run_download_3.12.json` | CPython 3.12.13, network fetch | 581 ran, skipped=3, exit 0 | 0 | PASS (all 4 stages) | **0** |

Buckets identical on 3.11.2 and 3.12.13: smoke **580+20**, soak **9680+320**,
saturation **300+50**; zero unexpected_other_error / unexpected_unavailable in
every stage. The three audited skips are exactly the adapter-present control and
the two smoke/soak opt-ins. Workspace ≈9.34 MB (≤128 MiB); whole run ≈145 s.

**Truthful exit counts**: the three full runs above each exited **0**; the five
negative runs below each exited **1**.

### Negative checks (all fail closed)

`logs/negatives.txt`:

- **N1 identity tamper** (one pinned source file altered) → FAIL, identity
  size/blob/sha256 mismatch, gate not reached, exit 1.
- **N2 gate-payload tamper** (`http_gate_d101.py` altered) → FAIL, payload
  sha256 mismatch before execution, exit 1.
- **N3 workspace escape** (`--base-dir` outside `/tmp`) → refused, exit 1.
- **N4 workspace escape** (`--workdir` == base `/tmp`) → refused, exit 1.
- **N5 stray importable file** (`docs/rogue_module.py`) → FAIL,
  `unexpected importable/executable file`, exit 1.

## 6. Packaging method

Core files were published **first** (`run_target_http.py`, `http_gate_d101.py`,
`README.md`, `MANIFEST.sha256`), then **fetched back** and byte/hash-verified
against the live GitHub file inventory; only after that were the small raw logs
and the report added under
`drive-tool/module-006/d104-target-http-runner-summary/`. The large gate
per-call record arrays were stripped from the published gate JSON (records-free,
still raw on results/buckets) to keep the package small; the full raw evidence
is retained by the runner on the target workspace.

## 7. Not done (scope guards)

No target execution, no credential, no install/deploy/service/public binding, no
real root, no merge, and no change to the candidate source or tests. The
separate Gemini security review is required **before bootstrap** on the target
and is not attempted here. No target (3.13.5) result is claimed.

## 8. Provenance

- Candidate: `Dolesh-avkalan/drive-tool @ feature/module-006b-final-service-candidate`
  (head `337e4c71…`, tree `169855e4…`).
- Prior evidence reused: D102 final-candidate pins/manifest
  (`drop/drive-tool/module-006/d102-final-candidate-summary/`), D101 gate
  (`drop@15192ab6…/drive-tool/module-006/d101-final-http-gate/`), D098 runner
  patterns (`drop/drive-tool/module-006/d098-runner-core/runner/`).
- All results are the parent's own sandbox run output; the published bytes were
  fetched back and re-hashed.

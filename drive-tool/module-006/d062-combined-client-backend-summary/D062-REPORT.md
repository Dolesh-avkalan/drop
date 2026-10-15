# D062 — combined accepted client/backend candidate (assembly + execution report)

Verdict: **PASS** — the combined candidate assembles exactly as specified (two
additions, base unchanged), and the full combined suite, the D058 probe harness
and the seven D058 semantic mutants all behave as on the standalone backend, on
both Python 3.11 and 3.12. Nothing was fixed, merged or deployed.

This is routine assembly/execution. It tests **coexisting library modules**
(client `drive_tool/service_client.py` + backend `drive_tool/file_service.py` in
one tree); it is **not** a real HTTP service. HTTP design/security remains with
Gemini; no HTTP implementation is present or added here.

## Pins

| What | Value |
|---|---|
| Accepted client/main source base | `Dolesh-avkalan/drive-tool` @ `cbf60867a0ca6e10206d540aed93f40e24b44a5d` |
| Accepted base tree | `b96c2807f0c8bd6adb09ba4678a43482e876bf41` |
| Backend source | `Dolesh-avkalan/drive-tool` @ `14729120c0f32ee5d64c1daf93b27fa1b3270d6b` (`feature/module-006a-file-service-independent`) |
| Backend tree | `3482dc4325afb5adf4b7ecfcbfe1e76a1ad0356c` |
| D058 independent report | `Dolesh-avkalan/drop` @ `main` `drive-tool/module-006/d058-independent-backend-summary/D058-REPORT.md` |
| Expected blobs | `drive_tool/file_service.py` = `b7e18c606f45066cd54ec66016e70e797486ef50`; `tests/test_file_service.py` = `8b5248f9365d8cac6e1331bb4677dea48a1778ff` |

## Published source (assembly output)

- Branch **`feature/module-006a-service-client-integration`** in `Dolesh-avkalan/drive-tool`
  (created from the exact accepted client base `cbf60867`).
- Head commit `67d37b2bba1e2676d12c99eff0559c04df6174c8`, tree
  `d6b5e87cd37e459bb8c3b1c85f97700dc2225ca7`, parent `cbf60867a0ca6e10206d540aed93f40e24b44a5d`.
- Scope: **exactly two additions** — `drive_tool/file_service.py`,
  `tests/test_file_service.py` — overlaid byte-identically from the accepted
  backend. No removals, no modifications to any base file.
- The tree SHA computed independently in a local git repository from the
  extracted base + overlay equals the SHA the GitHub Git-Data API returned for
  the created tree (`d6b5e87…`), and the locally reconstructed base tree equals
  the base commit's tree (`b96c2807…`). Assembly is content-exact.

### Assembly verification (`scripts/assemble_candidate.py`, `scripts/verify_published.py`)

```
added  : ['drive_tool/file_service.py', 'tests/test_file_service.py']
removed: []
changed: []
[OK] drive_tool/file_service.py gitblob=b7e18c606f45066cd54ec66016e70e797486ef50 expected=b7e18c606f45066cd54ec66016e70e797486ef50
[OK] tests/test_file_service.py  gitblob=8b5248f9365d8cac6e1331bb4677dea48a1778ff expected=8b5248f9365d8cac6e1331bb4677dea48a1778ff
RESULT: PASS
```

All execution below was performed on the **published bytes**, re-fetched from
the branch head via pinned codeload (`drive-tool` @ `67d37b2…`) and re-hashed to
the expected blobs before running.

## Execution environment

- Debian GNU/Linux 12 (bookworm), x86_64.
- `python3.11` = Python 3.11.2 (`/usr/bin/python3.11`).
- `python3.12` = Python 3.12.13 (`/usr/local/bin/python3.12`).
- `git` 2.39.5. Runner: `PYTHONPATH=. <python> -m unittest -v <tests.test_*>`.
- `tests/` is an implicit namespace package (no `__init__.py`), so modules are
  enumerated explicitly; `unittest discover` cannot be used here (recorded as a
  note, not a defect).

## Execution matrix (raw logs in `logs/`)

| Run | Python 3.11.2 | Python 3.12.13 |
|---|---|---|
| **Full combined suite** (all 17 test modules) | **506 OK**, exit 0 | **506 OK**, exit 0 |
| Baseline (base `cbf60867`, no backend files) | 490 OK, exit 0 | 490 OK, exit 0 |
| Focused (`tests.test_file_service`) | 16 OK, exit 0 | 16 OK, exit 0 |
| Probes (D058 harness) | **54/54 PASS**, exit 0 | **54/54 PASS**, exit 0 |
| Mutations (7 D058 semantic mutants) | **7/7 CAUGHT** | **7/7 CAUGHT** |

No skips, no errors, no failures in any run. The suite result is **measured, not
assumed**: the accepted client tests are preserved and re-run in place
(`tests.test_service_client` 77 OK, `tests.test_service_policy` 62 OK), and the
integrated total is the sum of the per-module runs
(490 baseline + 16 backend = 506), each module independently green.

Per-module counts on the integrated tree (both interpreters identical) are in
`logs/per_module_counts.txt`.

## Mutations (`scripts/reproduce_mutations.py`; `logs/mutations.txt`)

The seven D058 semantic mutants, applied to the **integrated** `file_service.py`
(the file is byte-identical to the standalone backend, so the same edits apply
exactly once), focused suite under a 120s timeout:

| Mutation | 3.11.2 | 3.12.13 | Representative failing test |
|---|---|---|---|
| M1 skip per-(agent,alias,op) grant lookup | CAUGHT | CAUGHT | auth-before-parse; readonly-denial |
| M2 alias-only binding key | CAUGHT | CAUGHT | two-agents-same-alias (+6) |
| M3 bool accepted as offset/limit | CAUGHT | CAUGHT | invalid-options-no-io |
| M4 dropped save uncertainty | CAUGHT | CAUGHT | 4 save tests |
| M5 close ignores active leases | CAUGHT | CAUGHT | concurrent-blocked-read-close-timeout |
| M6 always create parents | CAUGHT | CAUGHT | save-creates-missing-parents |
| M7 double close | CAUGHT | CAUGHT | concurrent-closes-close-once (`AssertionError: 4 != 1`) |

14/14 (7 mutants × 2 interpreters) CAUGHT.

## Probes (`scripts/reproduce_probes.py`; `logs/probes_*.txt`)

54/54 checks PASS on both interpreters, covering alias isolation and cross-grant
matrix; traversal/malformed-id rejection (`denied`); `root` forbidden
(`invalid`); wrong-kind errors (`invalid`); symlink read and symlinked-parent
save refused (`denied`) with the outside tree untouched; exact cap boundaries
(`too_large` at cap+1); exact-EOF semantics; 8-way concurrent no-overwrite
publish (1 winner, 7 `exists`); fd stability; timeout-close keeps the active fd
and denies new leases; 6-way concurrent close closes once; redaction with
`__cause__` None. The two non-blocking INFO observations match D058
(`find(whitespace-only)` → `invalid`, `list(offset=10000)` → `invalid`).

## Blocker(s)

None blocking. Notes / limitations:

1. **`unittest discover` unusable** on this tree (namespace-package `tests/`);
   handled by explicit module enumeration. Not a candidate defect.
2. **`chmod` not permitted** on the evidence workspace, so the copied shell/py
   scripts carry default modes (no exec bit). Cosmetic; scripts run via their
   interpreter.
3. **No merge / deploy / HTTP work** was performed, per instruction. The branch
   is published unmerged; default branch untouched.

## Provenance / reproduction

- `scripts/assemble_candidate.py` reconstructs the candidate from the two pinned
  codeload snapshots and asserts the two-additions / blob-hash invariants.
- `scripts/verify_published.py` re-fetches the published head and re-checks the
  same invariants against the published bytes.
- `scripts/run_combined_suite.sh` runs the full suite + probes + mutations.
- `scripts/indep_*.py` and `scripts/reproduce_*.py` are the D058 harness
  originals, reused byte-identically (sha256 recorded in `MANIFEST.sha256.txt`).
- `MANIFEST.sha256.txt` — pins, candidate hashes (sha256 + git blob), harness and
  log hashes. `TREE-MANIFEST.sha256.txt` — every file under the published
  `drive_tool/` and `tests/`.

Independent verification only; integration/merge remains with the director.

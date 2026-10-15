# D062 — combined accepted client/backend candidate (summary)

**Verdict: PASS.** Routine assembly + execution only. The combined candidate was
assembled exactly as specified, published as a branch, and the full combined
suite, the D058 probe harness and the seven D058 semantic mutants were executed
against the published bytes on Python 3.11 and 3.12 — all green. No code/test
fixes, no merge, no deploy, no HTTP work.

## What was done

1. **Assembly.** Created branch **`feature/module-006a-service-client-integration`**
   in `Dolesh-avkalan/drive-tool` from the exact accepted client/main base
   `cbf60867a0ca6e10206d540aed93f40e24b44a5d`, overlaying **only** the two accepted
   backend files byte-identically from `14729120c0f32ee5d64c1daf93b27fa1b3270d6b`:
   `drive_tool/file_service.py` and `tests/test_file_service.py`.
2. **Verified** exactly two additions, no removals, no modifications; blobs match
   the expected `b7e18c606f45066cd54ec66016e70e797486ef50` and
   `8b5248f9365d8cac6e1331bb4677dea48a1778ff`.
3. **Published** the branch and re-fetched its head to run everything against the
   published bytes.
4. **Executed** the full combined suite, the 54-probe D058 harness and the 7 D058
   semantic mutants on Python 3.11.2 and 3.12.13.
5. **Published** all raw evidence to the drop repository (this folder).

## Published source (drive-tool)

| Field | Value |
|---|---|
| Branch | `feature/module-006a-service-client-integration` |
| Head commit | `67d37b2bba1e2676d12c99eff0559c04df6174c8` |
| Tree | `d6b5e87cd37e459bb8c3b1c85f97700dc2225ca7` |
| Parent / base | `cbf60867a0ca6e10206d540aed93f40e24b44a5d` |
| Change | exactly 2 additions (`drive_tool/file_service.py`, `tests/test_file_service.py`) |
| Base source | unchanged (0 removals, 0 modifications) |

The integrated tree SHA computed independently in a local git repo from the
extracted base + overlay equals the SHA the GitHub Git-Data API returned
(`d6b5e87…`), and the locally reconstructed base tree equals the base commit's
tree (`b96c2807…`) — the assembly is content-exact.

## Measured results (published bytes; logs in `d062-combined-client-backend-summary/logs/`)

| Run | Python 3.11.2 | Python 3.12.13 |
|---|---|---|
| **Full combined suite** (17 modules) | **506 OK**, exit 0 | **506 OK**, exit 0 |
| Baseline (base, no backend files) | 490 OK, exit 0 | 490 OK, exit 0 |
| Focused (`tests.test_file_service`) | 16 OK, exit 0 | 16 OK, exit 0 |
| Probes (D058, 54 checks) | **54/54 PASS**, exit 0 | **54/54 PASS**, exit 0 |
| Mutations (D058, 7 mutants) | **7/7 CAUGHT** | **7/7 CAUGHT** |

No skips, no errors, no failures. Counts are measured, not assumed: accepted
client tests are preserved and re-run (`tests.test_service_client` 77 OK,
`tests.test_service_policy` 62 OK), and the integrated total is the sum of
independently-run modules (490 + 16 = 506).

## Blockers

None blocking. Notes: (1) `unittest discover` is unusable on this tree because
`tests/` is an implicit namespace package — modules are enumerated explicitly;
(2) `chmod` is not permitted on the evidence workspace, so the copied scripts
carry no exec bit (cosmetic); (3) per instruction, nothing was merged or
deployed and no HTTP implementation was added — the branch is published
unmerged and the default branch is untouched.

## Scope statement

This validates that the accepted client library module and the accepted backend
library module **coexist and pass together** in one tree. It is **not** a real
HTTP service test. HTTP design/security ownership remains with Gemini.

## Evidence index (this folder)

- `D062-REPORT.md` — full report.
- `MANIFEST.sha256.txt` — pins, candidate sha256/git-blob, harness and log hashes.
- `TREE-MANIFEST.sha256.txt` — per-file hashes of the published `drive_tool/` and `tests/`.
- `environment.txt` — interpreters, OS, runner.
- `candidate/` — the two published files, verbatim.
- `logs/` — raw suite / baseline / focused / probes / mutations / assembly-verify logs.
- `scripts/` — assembly, verification, runner, and the byte-identical D058 harnesses.

Raw evidence is mirrored at `drive-tool/module-006/d062-combined-client-backend/`.

Independent verification only; integration/merge remains with the director.

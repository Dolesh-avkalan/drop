# D049 — independent policy execution and adversarial review (summary)

**Verdict: ACCEPT WITH NITS. No blocker.**
Fresh independent run — not the D044/D046 builder chat. No source edits, branch edits,
installs, merge or deployment. All results below were produced by executing the pinned
candidate myself; D046 logs were read only to compare claims.

Full evidence bundle (report, scripts, raw logs, env, mutation outputs, byte manifest):
`drive-tool/module-006/d049-independent-policy/` and mirrored at
`drive-tool/module-006/d049-independent-policy-summary/`. Report: `D049-REPORT.md`.

## Pins

- Candidate: `Dolesh-avkalan/drive-tool` `feature/module-006a-policy` @ `dc3c2af7a83055903708b2622ef05c735ebb1210`, tree `3f096eddbc5b509e2f0f8e67892f918b522eaa52`.
- Base: `232fd03a3f50013adf62937e042d30c495aeb840` (tree `09a207fb1376c1db9c7242a4b9ddbb62acb2de1a`); branch commits `dae2ca04…` (verbatim import), `945016b2…` (`_by_id` fix), `dc3c2af7…` (test fix).
- Contract: `tasks/d045-service-policy-implementation.md` @ `0a1c8bf20b197c3c06bd54820a0957772ff3d940`.
- Generated answer: `drop` @ `1aa5ba7645526cf3d19238ccee84c8caa082c5ec` `drive-tool/module-006/d045-deepseek-service-policy.md`.
- Builder drop reviewed: `drop` @ `3e030403b9c9882a10cee38b0b1d551697a25971` `drive-tool/module-006/d046-policy-assembly/`.

## Evidence (independently reproduced)

- **Scope:** compare `232fd03a…...dc3c2af7…` → `ahead_by=3`, exactly **two** files changed, both *added* (`drive_tool/service_policy.py`, `tests/test_service_policy.py`). No existing file touched.
- **Byte identity / provenance:** committed files SHA-256 `8feedd94…` / `ada2c59e…` (match D046 manifest); generated answer `820c9b43…`; extracted verbatim blocks `537837dd…` / `d8d77768…`. Chain verified end to end.
- **Execution (CPython 3.11.2 and 3.12.13 only):** full suite **413 OK** on both, **zero skips**; policy module **62 OK** on both; base tree **351 OK** on both (original 351 preserved). Pre-fix verbatim tree reproduces the claimed **413 / errors=1** (`test_visible_ascii_bounds_accepted`).
- **Fixes verified by diff:** only `_by_id` → `MappingProxyType` and the `test_visible_ascii_bounds_accepted` strengthening. No assertion removed; authentication **not** weakened.
- **Mutations:** own re-runner, isolated copies, **6/6 CAUGHT** on both interpreters, each a real `AssertionError` (compiles+imports, no syntax/import fake catch).
- **Fresh adversarial probes:** own 103-check suite, **103/103 pass** on both interpreters (real NUL/backslash/dot/empty roots; nonbool bounds; duplicate ids/digests; mappingproxy immutability; same-alias isolation; caps vs ops; uniform denial for malformed/unhashable fields; exact object identity; visible-ASCII bounds/lengths; full digest scan with no early return; no secrets in repr/errors; no fs/network).

## Findings

- **NIT-1 (cosmetic):** `service_policy.py:164` annotates a *local* variable `Mapping[...]` without importing `Mapping`. Inert at runtime (`from __future__ import annotations` and Python not evaluating local annotations), but a static type checker would flag it. Not a blocker.
- **Out-of-scope note:** `PolicyTable.__slots__` slots are writable by trusted in-process code — not reachable from the JSON/HTTP surface; the contract's named mutable-dict exposure *was* fixed.
- **Blockers: none.** No CHANGES REQUIRED.

## Honesty notes

- Only Python 3.11.2 and 3.12.13 were run; **no 3.13/3.14 or cloud/kernel run is claimed**.
- Synthetic tokens/roots only; no real paths opened; no installs, merges or deployments.
- Independent acceptance is based on my own execution, not on builder logs.

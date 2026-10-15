# D046 — policy assembly & execution: summary

**Builder/assembler evidence — not independent acceptance.** Actual assembly and test execution of the
D045 DeepSeek service-policy candidate. No range/storage/HTTP changes, no main merge, no deployment, no
installs, synthetic tokens/roots only.

**Access:** GitHub read + publish confirmed. Pins read from source: D046 brief `b0f5d8d7`; assembly base
main `232fd03a3f50013adf62937e042d30c495aeb840`; D045 contract `0a1c8bf`; DeepSeek answer
`drop@1aa5ba7645526cf3d19238ccee84c8caa082c5ec` (file SHA-256 `820c9b43…`, re-fetched byte-identical).
The two FILE blocks were extracted byte-for-byte (no reconstruction).

**Branch `feature/module-006a-policy`** (from `232fd03a`), head `dc3c2af7a83055903708b2622ef05c735ebb1210`,
tree `3f096eddbc5b509e2f0f8e67892f918b522eaa52`. Commits:
1. `dae2ca04` — **verbatim** import of the generated files (provenance preserved).
2. `945016b2` — fix confirmed contract violation: `PolicyTable._by_id` immutable lookup.
3. `dc3c2af7` — fix the generated test that could never pass.

The committed files were re-fetched and match the tested tree **byte-for-byte**.

**Initial run (verbatim):** full suite **413 tests, errors=1** on 3.11.2 and 3.12.13 (351 baseline + 62
new); policy module 62 tests, errors=1. The one error is in the generated **test**
`test_visible_ascii_bounds_accepted` (calls `authenticate('!'*32)` with no `assertRaises` → uncaught
`PolicyDeniedError`).

**Codex flags, checked at byte level:**
- **NUL / single-backslash root checks — NOT a violation.** The source lines are `if '\x00' in value:`
  and `if '\\' in value:` — correct Python. Probe with actual characters: a real NUL → rejected, a real
  single backslash → rejected, `/srv/data` and `/` → accepted. **No change made.**
- **`PolicyTable._by_id` — CONFIRMED violation, fixed.** It was a plain dict copy (private but mutable,
  externally reachable; the probe mutated it and changed authorization). Minimal fix:
  `MappingProxyType(dict(by_id))`. Semantics preserved; assignment now raises `TypeError`.
- **Test fixtures — correct**, using a real NUL and a real single backslash.

**Second confirmed defect, fixed:** `test_visible_ascii_bounds_accepted` now configures tokens of `'!'*32`
(cp 33) and `'~'*32` (cp 126) and asserts identity — strengthened, not weakened; test count unchanged.

**Final run:** full suite **413 tests, OK** on 3.11.2 and 3.12.13; policy module 62 tests OK; zero skips.

**Mutation evidence (isolated copies, both interpreters): 6 mutants, 6 caught, 0 survived**, all real
assertion failures: early auth return; duplicate digest acceptance; cross-agent alias fallback;
read-only save bypass; malformed root acceptance; cap upper-bound bypass.

**Evidence bundle:** `drive-tool/module-006/d046-policy-assembly/` — `D046-REPORT.md`,
`MANIFEST.sha256.txt` (byte-SHA256 manifest), `scripts/`, `logs/` (raw initial+final + per-mutant),
`probe/`. Source/tests live on the isolated branch only.

**Blockers:** none. One non-blocking boundary: private immutable state is not a process-isolation
boundary (arbitrary hostile in-process mutation is out of scope, per contract). Independent
review/execution and merge are the director's to arrange.

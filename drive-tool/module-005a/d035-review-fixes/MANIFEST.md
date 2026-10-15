# MODULE-005A — d035 review-fixes raw evidence (Sarvam)

Assembler: Sarvam. Task: d035 narrow corrections from the independent d034 review.

- Candidate branch: `Dolesh-avkalan/drive-tool`, `feature/module-005a-review-fixes`.
- Base commit: `593759a40645386427bad35d53e8b856aeaa68d5` (original branch preserved).
- Authoritative brief: `Dolesh-avkalan/drop`, `drive-tool/module-005a/d035-input/TASK.md` @ `652c41e8091ce122da8b20e364a7ad59f5dfe0cd`.
- Independent report: `Dolesh-avkalan/drop`, `drive-tool/module-005a/d034-independent-tests/d034-sarvam-independent-tests.md` @ `b19c564bda5093d3691d0c3d156c44608cc41a87` (verdict CHANGES REQUIRED).
- Report: `Dolesh-avkalan/drive-tool`, `docs/evidence/MODULE-005A.md` §10.

## Files

| File | What it is |
| --- | --- |
| `00_env.txt` | Platform, OS, interpreter versions. |
| `tests-fixed-python3.11.txt` | Full suite after the fixes, Python 3.11 (verbose). |
| `tests-fixed-python3.12.txt` | Full suite after the fixes, Python 3.12 (verbose). |
| `review-fixes-oldfail-python3.11.txt` | New regression file against the pinned `593759a` code, Python 3.11. |
| `review-fixes-oldfail-python3.12.txt` | New regression file against the pinned `593759a` code, Python 3.12. |
| `mutations-d035.txt` | Three focused mutation checks, both interpreters. |
| `mutants_d035.py` | The mutation runner used. |

## Result

- Old-fail: the 18 new regression tests give **9 failures (5 failures, 4 errors)** against `593759a`, identical on both interpreters, for the intended F-A / F-B / F-C reasons.
- New-pass: **274 tests, OK, exit 0** on Python 3.11.2 and 3.12.13.
- Mutations: **3 mutations, 3 caught, 0 survivors.**

No interpreter was installed and no private data was touched. These logs are
local assembler execution only — the new independent rerun and the frontier
static review have not occurred.

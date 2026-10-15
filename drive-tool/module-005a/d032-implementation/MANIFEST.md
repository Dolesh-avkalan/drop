# MODULE-005A — raw synthetic evidence (Sarvam, d032)

Assembler: Sarvam. Task: MODULE-005A partial bounded enumeration and honest
search accounting.

- Candidate branch: `Dolesh-avkalan/drive-tool`, `feature/module-005a-partial-scan`.
- Base commit: `356a4d8a71d0e57a57e7c82dbfce50be145a0bdb` (parent `a84f6b3`, the MODULE-005 merge).
- Report: `Dolesh-avkalan/drive-tool`, `docs/evidence/MODULE-005A.md`.

## Files

| File | What it is |
| --- | --- |
| `00_env.txt` | Platform, OS, interpreter versions. |
| `tests-python311.txt` | `python3.11 -m unittest discover -s tests -v` (full, verbose). |
| `tests-python312.txt` | `python3.12 -m unittest discover -s tests -v` (full, verbose). |
| `mutation-python311.txt` | Mutation check output, Python 3.11. |
| `mutation-python312.txt` | Mutation check output, Python 3.12. |

## Result

- 256 tests, `OK`, exit 0, on both Python 3.11.2 and 3.12.13.
- 7 mutations, 7 caught, 0 survivors.

No interpreter newer than 3.12 is present in this environment; none was
installed. These logs are local assembler execution only — no independent or
target-cloud result is claimed.

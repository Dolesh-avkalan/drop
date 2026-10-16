# D115 — d112 independent package isolation

Status: **done**. Artifact isolation only — no implementation, fixes, tests or
re-execution; no target run. No decision needed from Dolesh.

## What was done

Copied **only** the independently authored D112 package (which had been
published into the earlier D110 namespace and collided with it) into its own
namespace:

    drop/drive-tool/module-006/d112-independent-harsh/

This is a **copy, not a move**. No existing path was removed or modified. No
third package was created.

## Exact source pin

- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
- archive sha256: `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`

## Inventory — `d112-independent-harsh/` (bytes / git-blob-sha1 / sha256)

| path | bytes | blob (sha1) | sha256 |
| --- | --- | --- | --- |
| `README.md` | 12027 | `1e975041f386` | `8220022537fafb9d315c3e000b07d8bd218c0e513754353cd5a20b79f940185c` |
| `PROVENANCE.md` | 2551 | `acc3007df076` | `09be99800a86c1c3785ba2b8cfa26402808a08acf2525f37e8d0b7554a8d7dea` |
| `SHA256SUMS` | 606 | `553c1f9324a6` | `9883bdfbf94d3461ca8a8c2f85d861d702d6be2cd79a9e1e6526c62a8b7d4d8e` |
| `run_harsh_target.py` | 28881 | `9b0c81ff3f30` | `0e76f066ff16a0e5594a6da6a161aa2b297c2b9e8e34be96be92dc8d5ac75987` |
| `harsh_gate_d110.py` | 78388 | `5ce2fb599785` | `b94eb09ad329abe669633834fe21b67139b43c0fe666645cde263e2139f53e0e` |
| `evidence/RAW_EVIDENCE.md` | 26698 | `2ea70fc28bb6` | `1ed5ed601a1fcfb3b6729454f03bedb53ce9b10f8c86963d08282e6939a54a2c` |
| `evidence/py311/summary.json` | 21949 | `6e5ee24e2578` | `4be7ee65af91a0785522c970c477edc7ac268e23125acb3d21524842a05c5533` |
| `evidence/py312/summary.json` | 21987 | `aadcb8c4d0f7` | `43c5089bbfaca050cecf2c6b93d2effb638d561d148b267ec2f51b85e2d1dcd1` |

`SHA256SUMS` covers every file above except itself and self-checks clean.

## Fetch-back verification (copied bytes vs original Git blobs)

Every copied file was fetched back from `main` and byte-compared to the original
Git blob already present in `d110-harsh-target/`:

- `run_harsh_target.py`, `harsh_gate_d110.py`, `README.md`, `evidence/**` —
  **byte-identical**; both the git-blob sha1 and sha256 match the originals.
- `PROVENANCE.md`, `SHA256SUMS` — new artifacts of this isolation; no prior blob
  to compare (listed above for completeness).

## D110 namespace untouched (verified)

- `d110-harsh-target/run_harsh_d110.py` sha256 `f55f1ca20d79f576…` — **unchanged**
- `d110-harsh-target/harsh_checks_d110.py` sha256 `5599d32fa9df7918…` — **unchanged**
- `d110-harsh-target/README.md` sha256 `9301351c8b4b701c…` (git blob
  `60e91a7e462b`) — **unchanged**, byte-identical to the pre-existing version at
  `974ba86e`

## Provenance / status

- The D112 package is an **independent historical comparison. UNREVIEWED. NOT
  the target candidate.**
- The first D110 package remains under Gemini review and remains the target
  candidate. The two are kept strictly separate and are not mixed.
- Isolation commits on `drop@main`:
  - `README.md` → `ab0e69224257a5e173c73fc7c68b2ce3e43b259a`
  - `PROVENANCE.md` → `22aaa5a6ec7d3b7e035f525f1faf2fc4a63289a6`
  - `SHA256SUMS` → `ae8568360ab750a532c50377339f93e4d98c818b`
  - `run_harsh_target.py` → `b972aa8345cea05c0359fc21fab2681be7db8bb2`
  - `harsh_gate_d110.py` → `3840949bc793ac17af2ef6e860589723d2ebb7fe`
  - `evidence/RAW_EVIDENCE.md` → `1f8caec0b1912602dddb7da37ca29cebe2a41f1f`
  - `evidence/py311/summary.json` → `b8167f216761aaf42edb24e89cc7c4e99ef473e8`
  - `evidence/py312/summary.json` → `7c1529a5ec042e35c82a6b7ceb481c258b01e1f7`

## Identity evidence NOT available

- No Gemini (or other) security review for the D112 package.
- No target-instance execution: `instance-20261015-210506` was never contacted.
- No CPython 3.13 run: 3.13 was absent in the authoring sandbox; validated on
  CPython 3.11.2 and 3.12.13 only.
- Provenance is author-asserted; the isolation commits above are the only
  cryptographic anchor for the copied bytes.

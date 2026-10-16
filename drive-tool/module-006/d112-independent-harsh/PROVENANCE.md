# Provenance — d112-independent-harsh

Status: **independent historical comparison package. UNREVIEWED. NOT the target
candidate.** Kept strictly separate from the first D110 package (which is under
Gemini review and remains the target candidate). Do not mix the two.

## Identity

- Author: Sarvam (D110/D112 turn, 2026-10-16).
- Origin: this package was first published into
  `drive-tool/module-006/d110-harsh-target/`, where it collided with the earlier
  D110 namespace. Per D115 it is isolated here, byte-for-byte, unchanged. No
  package file was edited during isolation.
- Isolation date: 2026-10-16 (D115). Isolation is a copy, not a move: the
  original paths are left untouched.

## Exact source pin

- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
- archive: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  (sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`)
- accepted D101 final HTTP gate (reference): sha256 `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b`

## Contents (copied unchanged)

- `run_harsh_target.py`  — orchestrator
- `harsh_gate_d110.py`   — pinned harsh payload
- `README.md`            — package README (identical to the d110-harsh-target copy)
- `evidence/`            — raw sandbox evidence (CPython 3.12.13 and 3.11.2)

## Relationship to the first D110 package (kept separate)

The first D110 package in `drive-tool/module-006/d110-harsh-target/` is a
different, independently authored implementation and is **not** part of this
package:

- first D110 runner  `run_harsh_d110.py`     sha256 `f55f1ca20d79f576b32006e7a9745fd9baa4b2af8cf55e6b77cf62e541712c87`
- first D110 payload `harsh_checks_d110.py`  sha256 `5599d32fa9df7918a8809098492284cebbce42b9141c61844c18c069fc17db43`
- first D110 restored `README.md`            git blob `9301351c8b4b701c…`

Those files are unmodified by this isolation and must not be conflated with the
files here.

## Identity evidence NOT available for this package

- No Gemini (or other) security review.
- No target-instance execution: `instance-20261015-210506` was never contacted.
- No CPython 3.13 run: 3.13 was not present in the authoring sandbox; the
  package was validated on CPython 3.11.2 and 3.12.13 only.
- Provenance is author-asserted; the only cryptographic anchor for the copied
  bytes is the D115 isolation commit, verified by fetch-back against the
  original Git blobs (see `SHA256SUMS` and the D115 summary).

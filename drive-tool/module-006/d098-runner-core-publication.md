# D098 — runner-core short publication (publication-only)

**Status:** published, byte-identical. **Commit:** `relay: d098` on
`Dolesh-avkalan/drop` (`main`). **Scope:** publication only — no target run,
no installs, no credentials, no merge, no deploy, no new fix, no payload change.

## What was asked

D093 timed out without publishing the source, and the actual D093 drop lacked
the runner bytes. Publish **only the two core files** — not the ~666 KB bundle.
Retrieve the D086 runner and the unchanged payload, or reconstruct the
documented one-token change from the exact D082 source drop; verify the runner
hash against the D086 IDENTITIES; publish a small manifest with hashes / bytes /
pins. Two files, ~60 KB total.

## What was published

Under `drive-tool/module-006/d098-runner-core/runner/`:

| file | bytes | sha256 | git blob sha1 |
| --- | --- | --- | --- |
| `run_cloud_stress.py` | 43732 | `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` | `60c6b8280f20a1916d6e8c6ba735338b4d49149a` |
| `stress_checks.py` | 21467 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` | `d3496d9638a99d11d221268e1bacf09c86feabdb` |

Plus a small manifest (`d098-runner-core/MANIFEST.md`, `d098-runner-core/HASHES.txt`).
Total published payload ≈ 65 KB — the two files only, no large logs.

Both files were published **by reference to their existing Git blob SHAs**
(`60c6b828…`, `d3496d96…`). Those blob objects were already stored in this
repository, so the published bytes are the *same objects* — nothing was
re-encoded, re-typed or re-uploaded. This is the strongest possible guarantee of
byte-identity.

## Identity and pin verification (parent verifies D086 identity)

* **D086 commit** `Dolesh-avkalan/drop @ 60b826e2ee52a6bc1f471dede75d50c19b880ae6`
  returns message **"relay: d086"**, tree `797593a1096dffcff3a993df56cc642fe2a18c3e`. ✔
* **D086 `IDENTITIES.md`** at that commit: sha256
  `27491391c99b133f4c0ecf46e88419559c91aadffea1829fef956e8ca5960880` — byte-identical
  to the copy on `main`; it documents the corrected runner sha256 `f58f61dc…`. ✔
* **D082 source drop** `Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8`
  returns message **"relay: d082"**, tree `5211951c3bd22d09e50fd1eb9aab17c013687136`. ✔
* **Reconstruction (exact):** D082 `runner/run_cloud_stress.py`
  sha256 `318e2100fc3a7da718e97768720cf0b5cb49954edd8e879e5c1851ec041cf2d8` (43732 B)
  contains **exactly one** occurrence of `rsplit(".", 1)[0]`; replacing it with
  `rsplit(".", 2)[0]` yields sha256
  `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` (43732 B) —
  equal to the D086 pin **and** byte-identical to the D093 runner. ✔
* **Payload (unchanged):** `runner/stress_checks.py` sha256
  `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` (21467 B),
  equal to `STRESS_CHECKS_SHA256` embedded in the runner. ✔
* **Git blob verification:** the two repo blobs (`60c6b828…`, `d3496d96…`) were
  fetched and their sha256 recomputed — `f58f61dc…` / `8097d0a3…` respectively,
  sizes 43732 / 21467. ✔

## Publication mechanism

The authenticated GitHub tool was used via **direct MCP calls** (the program
session is restricted for the `github` toolkit, so `run_program` could not carry
them). No `git push`, no credentials, no shell git. The commit tree references
the two existing blobs by SHA and carries the small text files inline.

## What was NOT done (scope honoured)

No target run, no installs, no credentials, no merge, no deploy, no re-pin, no
payload change, no HTTP work, no new fix, no large logs. Source under test
`b7f8d17b…` and its 26 pinned identities are unchanged. D086 published no
bundle (only `IDENTITIES.md` + `sandbox/compile_checks.log`); D093 reconstructed
and re-verified it; D098 republishes only the two core files requested.

## Files in this publication

* `drive-tool/module-006/d098-runner-core/runner/run_cloud_stress.py`
* `drive-tool/module-006/d098-runner-core/runner/stress_checks.py`
* `drive-tool/module-006/d098-runner-core/MANIFEST.md`
* `drive-tool/module-006/d098-runner-core/HASHES.txt`
* `drive-tool/module-006/d098-runner-core-publication/` (relay copies: the two
  runner files + `MANIFEST.md` + `HASHES.txt`)

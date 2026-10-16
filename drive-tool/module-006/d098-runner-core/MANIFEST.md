# d098-runner-core — short publication manifest (hashes / bytes / pins)

Publication-only drop. **Two** files are published, byte-identical to their
pinned sources. No code was changed, no new fix invented, no payload altered.

## Files published (under this folder)

| path | bytes | sha256 | git blob sha1 |
| --- | --- | --- | --- |
| `runner/run_cloud_stress.py` | 43732 | `f58f61dced9b8df2d92e710bc654190dc32f92f0e426d0f499386e5b84cf57f2` | `60c6b8280f20a1916d6e8c6ba735338b4d49149a` |
| `runner/stress_checks.py` | 21467 | `8097d0a3074c37e5b891f78101f95d24f5bfb73d818cd8a0278c9fe61fa85be9` | `d3496d9638a99d11d221268e1bacf09c86feabdb` |

Both blobs were published by reference to their **existing** Git blob SHAs
(the same objects already stored in this repository), so the published bytes
are identical objects — nothing was re-encoded or re-typed.

## Pins

### Runner (D086 corrected) — sha256 `f58f61dc…`, 43732 bytes

* Source of truth: `Dolesh-avkalan/drop @ 60b826e2ee52a6bc1f471dede75d50c19b880ae6`
  ("relay: d086"), tree `797593a1096dffcff3a993df56cc642fe2a18c3e`,
  `drive-tool/module-006/d086-runner-final-twofix/IDENTITIES.md`
  (sha256 `27491391c99b133f4c0ecf46e88419559c91aadffea1829fef956e8ca5960880`).
* Reconstructed **byte-exactly** from the D082 source drop
  `Dolesh-avkalan/drop @ 783d09d83cbf91d172d8a0b723a5a6a9550b70d8` ("relay: d082"),
  tree `5211951c3bd22d09e50fd1eb9aab17c013687136`,
  `drive-tool/module-006/d082-runner-twofix/runner/run_cloud_stress.py`
  (sha256 `318e2100fc3a7da718e97768720cf0b5cb49954edd8e879e5c1851ec041cf2d8`, 43732 B),
  by the documented **one-token** change `rsplit(".", 1)[0]` → `rsplit(".", 2)[0]`
  (exactly 1 occurrence). Result equals the D086 pin and the D093 runner byte-for-byte.

### Payload (unchanged) — sha256 `8097d0a3…`, 21467 bytes

* `runner/stress_checks.py`; equals `STRESS_CHECKS_SHA256` embedded in the runner;
  identical in `d082-runner-twofix/runner/` and `d082-runner-twofix/originals/runner/`.

### Source under test (unchanged)

* `Dolesh-avkalan/drive-tool @ b7f8d17b9dcc4aec68d54b38f994290e05264e67`
  (codeload archive sha256 `93af95d9e711ec8d44d4901d39b48d0387ce78c2b1c48dd8f55539905bf61db3`,
  338575 bytes, 123 members).
* 26 pinned `EXPECTED_BLOBS` unchanged; runner constants `COMMIT` and
  `STRESS_CHECKS_SHA256` untouched.

## Scope

Publication-only. No target run, no installs, no credentials, no merge, no
deploy, no re-pin, no payload change, no new fix. D086 published no bundle;
D093 reconstructed and re-verified it; D098 republishes only the two core
files requested — byte-identical.

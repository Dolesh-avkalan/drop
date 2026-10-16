# d104 target HTTP runner — core package

Pinned, stdlib-only runner that reproduces the accepted D102 final HTTP
candidate and gates acceptance on the full committed suite and the exact D101
final HTTP gate. It is authored and sandbox-tested here; it does **not** run on
the target from here and **no target result is fabricated**. The operator runs
it on the disposable target instance.

## Files (core — everything needed to run)

| file | bytes | sha256 |
| --- | --- | --- |
| `run_target_http.py` | 32795 | `4eaf7f530bb25646e2c58e61d05eded952fdf53172f2db212c4e43945d72fdbf` |
| `http_gate_d101.py` | 45668 | `3754ca19b4a72797ac16a1e32300ddf399e7117e2dec63def6693d2512db8d7b` |

`http_gate_d101.py` is the exact D101 corrected gate harness (drop
`15192ab6f818cae9d74e94a7833a74a3d0826914`,
`drive-tool/module-006/d101-final-http-gate/scripts/http_gate_d101.py`,
sha256 `3754ca19…`). Its sha256 is embedded in the runner and verified before
execution.

## Pins

- candidate: `Dolesh-avkalan/drive-tool` @ `337e4c713829af76615472eb47b81244ff399528`
  (branch `feature/module-006b-final-service-candidate`)
- archive: `https://codeload.github.com/Dolesh-avkalan/drive-tool/tar.gz/337e4c713829af76615472eb47b81244ff399528`
  (sha256 `191d6f2bd985be51f1b6092472beeec25b267a4c6e89de7817b4d6538c61c6c3`)
- accepted order fix preserved: `tests/test_partial_scan_review_fixes.py`
  blob `c01003e7015915db3dcac15a168ff7aae3d423db`
- composite sourcehash (adapter‖test): `b8b44c4c056e1925957445cc9b532c53194920124a469df54e49053a7dcbb71c`

## Exact operator command (target: Debian / CPython 3.13.5)

    cd d104-target-http-runner-summary && \
    timeout 1200 python3 run_target_http.py --json d104_summary.json

`timeout 1200` is the hard 20-minute outer operator bound. The runner defaults
to the interpreter it is launched with; add `--python python3.13` to pin it
explicitly. A nonzero exit means acceptance failed — read `d104_summary.json`
and the retained raw logs under the workspace.

## Behaviour

Order, failing closed at every preflight gate:

1. environment/identity capture;
2. acquire the pinned archive (download, or `--archive` a local tar.gz) and
   extract it with path/size/count/link guards;
3. re-hash **every** executable source/test/importable file against the
   embedded pinned blob-sha1 + sha256, and reject unexpected importable/
   executable files anywhere, any unexpected `drive_tool/` or `tests/` file,
   symlinks, traversal and oversize;
4. verify the gate payload sha256;
5. run the committed suite (`python -m unittest discover -s tests -v`) and
   audit skips — exactly the three documented control/opt-in skips are allowed;
   any other (platform/adapter-missing) skip is a FAIL;
6. only if the suite passes, run the D101 gate (`http_gate_d101.py --repo <src>
   --gate --json <ws>/gate.json`) and require raw exit 0 with selfcheck +
   smoke600 + soak10000 + saturation_6plus1 all PASS and buckets
   580+20 / 9680+320 / 300+50, zero unexpected/unavailable;
7. gate workspace size and write a symlink-safe manifest; retain all evidence.

Acceptance stages stop on the first failure; the overall exit is strictly
nonzero on any FAIL/missing/skip/error/timeout. Execution is confined to a new
unique `/tmp` workspace (0700, descendant of the base, never the base itself);
`TMPDIR` lives inside it and bytecode writing is disabled. No cleanup.

Safety: stdlib only; no credential, cloud API, install, reboot, service/public
binding, real root or deploy; no generic remote shell and no unrelated
framework.

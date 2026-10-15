#!/usr/bin/env python3
"""D067 bounded HTTP smoke/soak runner (stdlib only).

Runs the FIXED 600-call mixed-call HTTP smoke, then (only if the smoke passes)
the FIXED 10,000-call six-agent HTTP soak, using the helpers in
``tests/test_http_adapter.py``. Reuses that module's pre-committed D064
resource thresholds and FAILS CLOSED when the production adapter (D068) is
absent -- it can never fabricate a passing stage.

Usage (repo root, production adapter present):
    python3 scripts/run_d067_smoke_soak.py [--calls-smoke N] [--calls-soak N] [--skip-soak]

Exit: 0 PASS, 1 FAIL, 2 gated (production adapter absent).
Touches only synthetic temporary roots; no non-loopback socket, no install,
no real root or credential.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile


def main() -> int:
    ap = argparse.ArgumentParser(description="D067 bounded HTTP smoke/soak runner")
    ap.add_argument("--calls-smoke", type=int, default=None)
    ap.add_argument("--calls-soak", type=int, default=None)
    ap.add_argument("--skip-soak", action="store_true")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from tests import test_http_adapter as mod  # type: ignore
    except Exception as exc:  # noqa: BLE001
        print("cannot import tests.test_http_adapter: %s: %s"
              % (type(exc).__name__, exc))
        return 1
    if not mod._ADAPTER_AVAILABLE:
        print("GATED: production drive_tool.http_adapter (D068) is absent; "
              "smoke/soak cannot run. Import error: %s" % (mod._ADAPTER_IMPORT_ERROR,))
        return 2
    if args.calls_smoke is not None:
        mod.SMOKE_CALLS = args.calls_smoke
    if args.calls_soak is not None:
        mod.SOAK_CALLS = args.calls_soak

    base = tempfile.mkdtemp(prefix="d067-smoke-soak-")
    try:
        policies, _roots = mod._standard_policies(base)
        print("thresholds: " + json.dumps(mod.THRESHOLDS, sort_keys=True))
        print("=== smoke (%d calls) ===" % mod.SMOKE_CALLS)
        smoke = mod.run_smoke(policies)
        print("SMOKE_JSON: " + json.dumps(smoke, sort_keys=True))
        if smoke["result"] != "PASS":
            print("RESULT: FAIL (smoke)")
            return 1
        if args.skip_soak:
            print("RESULT: PASS (smoke only)")
            return 0
        print("=== soak (%d calls, six agents) ===" % mod.SOAK_CALLS)
        soak = mod.run_soak(policies)
        print("SOAK_JSON: " + json.dumps(soak, sort_keys=True))
        if soak["result"] != "PASS":
            print("RESULT: FAIL (soak)")
            return 1
        print("RESULT: PASS")
        return 0
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

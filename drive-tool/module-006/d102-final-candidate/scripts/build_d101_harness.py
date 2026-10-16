#!/usr/bin/env python3
"""Build the D101 corrected harness from the D097 verified harness.

Harness-only repair: the ONLY functional change is the gating helper
(run_gate) plus the aggregate exit/status it feeds.  Every stage runner
(run_stage, run_saturation, selfcheck, run_bounded, run_adversarial), the
frozen schedules/intents, the D089 accounting, the budgets and the real
service-entry saturation barrier are copied byte-for-byte from D097.

The defect being repaired (admitted in the D097 report, section 8):
  ``--gate`` exits non-zero even though every stage PASSes, because its
  result dict has no top-level ``result`` key -- so the exit mapping in
  ``main()`` reads ``None`` and returns 1.

The D101 gate:
  * orchestrates the four REQUIRED stages -- selfcheck, smoke600,
    soak10000, saturation_6plus1;
  * returns an aggregate dict WITH a top-level ``result`` key;
  * exits 0 iff EVERY required stage was executed and its own result is
    PASS; any FAIL / missing / skipped / error / timeout stage -> nonzero;
  * preserves the D096/D097 rule: NO soak (nor saturation) after a smoke
    failure.
"""
import hashlib
import sys

SRC = "/scratch/work/d101/scripts/http_gate_d097.py"
DST = "/scratch/work/d101/scripts/http_gate_d101.py"

with open(SRC, "r", encoding="utf-8") as fh:
    text = fh.read()

# --- one docstring line, to describe the corrected gate ---------------------
OLD_USAGE = ("  python3 http_gate.py --repo <repo> --gate          "
             "# smoke, then soak only if smoke passes")
NEW_USAGE = ("  python3 http_gate.py --repo <repo> --gate          "
             "# selfcheck, smoke, then soak + saturation if smoke passes")
if OLD_USAGE not in text:
    sys.exit("usage line not found")
text = text.replace(OLD_USAGE, NEW_USAGE, 1)

# --- replace ONLY the gating helper ----------------------------------------
start_marker = ("# --------------------------------------------------------------------------\n"
                "# Gating helper: smoke, then soak only if smoke passes")
end_marker = ("# --------------------------------------------------------------------------\n"
              "# Self-check (schedule + accounting), no adapter required")

i = text.index(start_marker)
j = text.index(end_marker)

NEW = '''# --------------------------------------------------------------------------
# Gating helper: selfcheck, then smoke, then soak + saturation if smoke passes
#
# D101 correction -- HARNESS-ONLY AGGREGATE EXIT/STATUS.
#
# D096/D097 ``--gate`` returned ``{"smoke": ..., "soak": ...}`` with no
# top-level ``result`` key, so the exit mapping in ``main()`` read ``None``
# and returned a NONZERO code even when every stage PASSed (the quirk the
# D097 report records in section 8).  Nothing about the stages was wrong;
# only the aggregate exit/status was.
#
# The corrected gate now:
#   * orchestrates the four REQUIRED stages -- selfcheck, smoke600,
#     soak10000 and saturation_6plus1;
#   * returns an aggregate dict that CARRIES a top-level ``result`` key;
#   * exits 0 iff EVERY required stage was executed AND its own result is
#     PASS; any FAIL, missing, skipped, error or timeout stage makes the
#     gate nonzero;
#   * preserves the D096/D097 rule: NO soak (nor saturation) after a smoke
#     failure -- both are recorded as skipped and the gate is nonzero.
#
# Only this helper and the exit mapping that reads its ``result`` changed.
# The stage runners, the frozen schedules/intents, the D089 accounting
# buckets, the budgets and the real service-entry saturation barrier are
# byte-for-byte the D097 code.
# --------------------------------------------------------------------------
REQUIRED_STAGES = ("selfcheck", "smoke600", "soak10000", "saturation_6plus1")


def _run_guarded(fn, *args, **kwargs):
    """Run a stage, turning any exception/timeout into an explicit non-PASS.

    A stage that raises must never be able to look like a pass, so a
    TimeoutError becomes ``TIMEOUT`` and any other exception becomes
    ``ERROR``; a non-dict return becomes ``ERROR``.  All three are non-PASS
    and therefore fail the aggregate.
    """
    try:
        res = fn(*args, **kwargs)
    except TimeoutError:
        return {"result": "TIMEOUT", "problems": ["stage timed out"]}
    except BaseException as exc:      # noqa: BLE001
        return {"result": "ERROR",
                "problems": ["stage raised %s" % type(exc).__name__]}
    if not isinstance(res, dict):
        return {"result": "ERROR", "problems": ["stage returned non-dict"]}
    return res


def _aggregate_gate(stages):
    """PASS iff every REQUIRED stage was executed and reports PASS.

    A missing/skipped stage (``None``), or any result other than ``PASS``
    (FAIL / ERROR / TIMEOUT / MISSING / anything), is a problem, so a false
    pass is impossible by construction.
    """
    problems = []
    for name in REQUIRED_STAGES:
        res = stages.get(name)
        if res is None:
            problems.append("%s: not executed (skipped/missing)" % name)
            continue
        status = res.get("result")
        if status != "PASS":
            problems.append("%s: %s" % (name, "MISSING" if status is None else status))
    return (not problems), problems


def run_gate(repo, allow_diagnostic_soak=False):
    """Run the four required stages and return an aggregate verdict.

    ``allow_diagnostic_soak`` is accepted for CLI compatibility but is
    intentionally inert: D101 forbids a soak after a smoke failure, so the
    soak is always withheld when smoke does not pass.
    """
    stages = {name: None for name in REQUIRED_STAGES}

    stages["selfcheck"] = _run_guarded(selfcheck)
    if stages["selfcheck"].get("result") == "PASS":
        stages["smoke600"] = _run_guarded(
            run_stage, repo, SMOKE_TOTAL, SMOKE_VALID, SMOKE_RO_SAVE, "smoke600")

    smoke = stages["smoke600"]
    if smoke is not None and smoke.get("result") == "PASS":
        stages["soak10000"] = _run_guarded(
            run_stage, repo, SOAK_TOTAL, SOAK_VALID, SOAK_RO_SAVE, "soak10000")
        stages["saturation_6plus1"] = _run_guarded(run_saturation, repo)
    # else: smoke skipped or failed -> soak and saturation are withheld.

    ok, problems = _aggregate_gate(stages)
    note = None
    if stages["soak10000"] is None:
        note = "soak withheld: smoke did not pass (no soak after smoke fail)"

    return {
        "harness": "d101-http-gate-harness",
        "stage": "gate",
        "required_stages": list(REQUIRED_STAGES),
        "executed": [n for n in REQUIRED_STAGES if stages[n] is not None],
        "result": "PASS" if ok else "FAIL",
        "problems": problems,
        "note": note,
        "selfcheck": stages["selfcheck"],
        "smoke": stages["smoke600"],
        "soak": stages["soak10000"],
        "saturation": stages["saturation_6plus1"],
    }


'''

out = text[:i] + NEW + text[j:]

with open(DST, "w", encoding="utf-8") as fh:
    fh.write(out)

print("wrote", DST)
print("bytes", len(out))
print("sha256", hashlib.sha256(out.encode()).hexdigest())

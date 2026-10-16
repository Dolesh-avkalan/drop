# EA001 — coordinator start report (Sarvam)

**Role:** execution coordinator for pilot EA001. **Director:** project lead. This is my
dispatch report; the final deliverables are assembled by the continuation task and land
at `ea-pilot/ea01/FINAL.md`.

## What I inspected (pinned)
- browser-tool @ `b50a2f150639e52c2c48d784b4196b26bd93cdf4` (deployed `b50a2f1`, PR #43
  per `status/box.md`). Read `HANDOFF.md`, `browser_host/relay.py`, `AGENTS.md`,
  `NEXT.md`, `status/box.md` via the authenticated GitHub integration.
- Bus `browser-bus` / `tasks/`: the only existing ea01 file is `ea01-coordinate-start.md`
  (this task). No duplicate ea01 job, and no `tasks/ea01-child-*` existed before my
  dispatch.
- Relay is live: `status/box.md` updated 2026-10-16T15:28:47Z, lanes
  `0=rest, 1=gemini, 2=deepseek, 3=grok`; a pusher (sarvam) task is marked done by
  polling the drop repo for the saved answer.

## Dispatch (real, this run)
Coordinator-state published first: drop `main` `ea-pilot/ea01/START/COORDINATOR-STATE.md`
@ `f1302b35becedd1e6529357334bf8a75824dd39f`.

Child + continuation tasks pushed to browser-tool `browser-bus`:

| task id | teammate | pin | depends on | artifact (drop) | dispatch commit |
|---|---|---|---|---|---|
| ea01-child-deepseek-template | DeepSeek | site default | - | ea-pilot/ea01/child/01-deepseek-template.md | `0dcdedac9dd1c005aa06f6a935d47c82d7ac6749` |
| ea01-child-gemini-boundaries | Gemini | model 4 Argon, effort high | - | ea-pilot/ea01/child/02-gemini-boundaries.md | `0dcdedac9dd1c005aa06f6a935d47c82d7ac6749` |
| ea01-child-grok-review | Grok | model expert | ea01-child-deepseek-template | ea-pilot/ea01/child/03-grok-costquality.md | `a7c0a7ac8f7263a6b9e696857a73b1a2b1b29041` |
| ea01-coordinate-finish | Sarvam | lane 0 | start + the three children | ea-pilot/ea01/FINAL.md | `de3c4e120945cda31750d7b160aaa3b34f7a2bf1` |

Ordering honoured: DeepSeek + Gemini first (no dependencies), then Grok (`after:`
DeepSeek), then the continuation (`after:` start + all three children). Each child is
self-contained, asks for a <=600-word answer, needs no site browsing or code execution,
and produces one distinct artifact.

## What the continuation does
`ea01-coordinate-finish` (agent sarvam, chat new) reads START.md, COORDINATOR-STATE.md,
the three `tasks/ea01-child-*.result.md` files and the three child artifacts; verifies
each child ended `done` and its artifact is present; then assembles and commits
`OPERATING.md`, `TASK-TEMPLATE.md`, `EVIDENCE.md` and `FINAL.md` under `ea-pilot/ea01/`.
If a child is missing, blocked, or unverifiable it commits `FINAL.md` as BLOCKED and
names the failure. It may open at most two fresh uniquely named correction children plus
one further continuation - no busy loop.

## Evidence and honesty
- Every claim above is a real commit or read; commit SHAs are on `browser-bus` and drop
  `main`. Child results are still pending (they run over the next minutes on the box).
- I did not substitute any pinned model; a blocked pin is recorded as blocked.
- Writes were limited to new `tasks/ea01-*.md` (browser-bus) and files under
  `ea-pilot/ea01/` (drop main). Scope is an operating agreement, not an enforced sandbox.
- No credentials or personal data are in any artifact.
- I do not claim an always-wake guarantee; this is a bounded, dependency-gated chain.

## Gaps / limitations
- Results depend on the live browser relay and the four lanes; DeepSeek / Gemini / Grok
  output is not available at the time of this report.
- The true model pins are read from the actual result files and recorded in EVIDENCE.md,
  not asserted here.
- No autonomous test suite ran; verification is artifact inspection by the continuation.

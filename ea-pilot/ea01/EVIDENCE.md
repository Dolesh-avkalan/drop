# EA001 — Evidence manifest (audit trail)

Assembled by the continuation task `ea01-coordinate-finish` (agent sarvam, lane 0).
Everything below is what **I** personally read, fetched, and checked in this run; it is
not a restatement of a teammate's claim.

## Task IDs (exact)
- `ea01-coordinate-start` — coordinator start report.
- `ea01-child-deepseek-template` — child 1 (DeepSeek).
- `ea01-child-gemini-boundaries` — child 2 (Gemini).
- `ea01-child-grok-review` — child 3 (Grok).
- `ea01-coordinate-finish` — this continuation (Sarvam).

## Dispatch commits I can see
Read from drop `main` `ea-pilot/ea01/START.md` and confirmed in the browser-bus commit
log (browser-tool @ `browser-bus`):
- `0dcdedac9dd1c005aa06f6a935d47c82d7ac6749` — "ea01 dispatch child jobs — deepseek (template) + gemini (boundaries, 4 Argon/high)".
- `a7c0a7ac8f7263a6b9e696857a73b1a2b1b29041` — "ea01 dispatch child job — grok cost/quality review (expert), after deepseek".
- `de3c4e120945cda31750d7b160aaa3b34f7a2bf1` — "ea01 dispatch coordinator-continuation (sarvam) — assemble FINAL deliverables, after start + children".
- Coordinator-state publish (drop `main`): `f1302b35becedd1e6529357334bf8a75824dd39f`.

## Child results (status + chat/model pin as recorded)
Each result file is `tasks/ea01-child-*.result.md` on browser-tool `browser-bus`.

| task id | status | chat | model pin (verbatim) | finished |
|---|---|---|---|---|
| ea01-child-deepseek-template | done | https://chat.deepseek.com/a/chat/s/f461f5e2-bcc2-42f8-bf17-2633c88b385f | deepseek (deepthink off, search off) | 2026-10-16T15:34:26Z |
| ea01-child-gemini-boundaries | done | https://gemini.google.com/app/19cb57aecbd32cb1 | 4 argon (thinking: high) | 2026-10-16T15:35:58Z |
| ea01-child-grok-review | done | https://grok.com/c/596bb6c5-0fe6-4f21-b032-67fd6d77e698?rid=6959af8f-8334-4f7f-b25a-ff147bcc8bbb | expert (thinking: -) | 2026-10-16T15:36:52Z |

No pinned model was blocked, and none was substituted. The DeepSeek pin is the site
default; Gemini ran 4 Argon at high effort; Grok ran expert — all as dispatched.

## Artifacts (path, commit, sha256)
All three artifacts are on drop `main` under `ea-pilot/ea01/child/`. sha256 was computed
over the fetched artifact bytes; the fetched bytes were cross-checked against the repo's
Git blob SHA and matched exactly, so each hash is the true artifact hash.

| artifact path | artifact commit | sha256 |
|---|---|---|
| ea-pilot/ea01/child/01-deepseek-template.md | `518912af18bccfdec8a01122fd5d513ef8984f9a` | d4d20ce80dc94f5da09fa1f0a1ee68bb4f40996d80a1996dec00440dd31e914d |
| ea-pilot/ea01/child/02-gemini-boundaries.md | `208ef5dc95b1b1a70ab375fd5e719c3d26412f78` | ecc2dde3080dd3500204ef36db3b1a57cd69f2978cc158d768724a6786a62165 |
| ea-pilot/ea01/child/03-grok-costquality.md | `792daf0a71d11bddd234d344bf36b3b4addc7688` | d48b0dbda88bd035f7916cedb9084907985edb49a9d3d113e6cafcd5e98b1e52 |

The latest child-artifact commit (and current drop `main` head before this commit) is
`792daf0a71d11bddd234d344bf36b3b4addc7688`.

## What I personally verified
- Read all 8 inputs myself: START.md, COORDINATOR-STATE.md, the three `*.result.md` files, and the three child artifacts.
- Each child's result file status is `done`; each chat URL and model pin is recorded verbatim above.
- Each artifact exists at the stated path, is non-empty, and its Git blob SHA matches the fetched bytes.
- Each artifact contains the section its task asked for: 01 has `# TASK-TEMPLATE` + `# CORRECTION-AND-EVIDENCE-WORKFLOW`; 02 has `# BOUNDARIES` with its four sections; 03 has `# COST-QUALITY REVIEW` with verdict, defects, gaps, and the cost-overrun line.
- The three dispatch commits and the coordinator-state commit are real commits visible in the repository commit logs.

## Gaps
- The child result files are self-reports produced by the browser relay; I verified the artifacts they point to, but I did not independently reproduce the relay runs or the screenshot files (`shots/lane*-*.png`).
- The dispatch commits are visible on `browser-bus`; I did not re-derive them from a raw git object walk.
- No autonomous test suite ran; verification is artifact inspection only.
- This is a bounded pilot, not a product; nothing here is an enforced sandbox.

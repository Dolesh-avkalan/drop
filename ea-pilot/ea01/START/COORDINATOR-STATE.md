# EA001 — coordinator state (pinned)

**Pilot:** EA001, Sarvam execution-coordinator pilot. **Director:** project lead (owns
direction and final acceptance). **Coordinator / EA:** Sarvam.

## Pins (read-only reference)
- browser-tool @ `b50a2f150639e52c2c48d784b4196b26bd93cdf4` (deployed code per
  `status/box.md`: `b50a2f1`, PR #43). Read at that pin: `HANDOFF.md`,
  `browser_host/relay.py`, `AGENTS.md`, `NEXT.md`, `status/box.md`.
- Relay: git task bus on `browser-bus`. Tasks run in name order; `after:` / `expect:`
  chain; four lanes `0=rest (Sarvam), 1=gemini, 2=deepseek, 3=grok`.
- Coordinator start task: `ea01-coordinate-start` (agent sarvam) -> `ea-pilot/ea01/START.md`.

## Allowed writes (this pilot only)
- browser-tool branch `browser-bus`: NEW `tasks/ea01-*.md` only.
- drop branch `main`: files under `ea-pilot/ea01/` only.
- Nothing else: no existing tasks/results/status/endpoint, no browser-tool `main`, no
  source / services / secrets / permissions / real user files. **This is an operating
  agreement, not an enforced security sandbox.**

## Intended job IDs and allowed outputs
| id | teammate | pin | artifact (drop) |
|---|---|---|---|
| ea01-child-deepseek-template | DeepSeek | site default | ea-pilot/ea01/child/01-deepseek-template.md |
| ea01-child-gemini-boundaries | Gemini | model 4 Argon, effort high | ea-pilot/ea01/child/02-gemini-boundaries.md |
| ea01-child-grok-review | Grok | model expert; after deepseek | ea-pilot/ea01/child/03-grok-costquality.md |
| ea01-coordinate-finish | Sarvam | lane 0 | ea-pilot/ea01/FINAL.md (+ OPERATING.md, TASK-TEMPLATE.md, EVIDENCE.md) |

## Rules carried into the run
- Each child: self-contained, <=600-word answer, no site browsing or code execution,
  one distinct artifact.
- Model/effort pins are recorded from the actual relay results; a blocked pinned model
  is reported, never silently substituted.
- Budget: <=8 child jobs, <=2 correction rounds. A limit / access / missing-artifact is
  a BLOCKED report, not success. Never auto-retry an uncertain write.
- Escalation: anything outside the allowed writes, or any blocked / limit / access gap,
  is reported to the director ("I will bring this to the director").

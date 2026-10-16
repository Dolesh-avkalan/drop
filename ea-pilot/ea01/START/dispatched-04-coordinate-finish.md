agent: sarvam
chat: new
project: ea-pilot
timeout_min: 20
save_to: ea-pilot/ea01/FINAL.md
after: ea01-coordinate-start, ea01-child-deepseek-template, ea01-child-gemini-boundaries, ea01-child-grok-review
read: Dolesh-avkalan/drop:ea-pilot/ea01/START.md@main, Dolesh-avkalan/drop:ea-pilot/ea01/START/COORDINATOR-STATE.md@main, Dolesh-avkalan/browser-tool:tasks/ea01-child-deepseek-template.result.md@browser-bus, Dolesh-avkalan/browser-tool:tasks/ea01-child-gemini-boundaries.result.md@browser-bus, Dolesh-avkalan/browser-tool:tasks/ea01-child-grok-review.result.md@browser-bus, Dolesh-avkalan/drop:ea-pilot/ea01/child/01-deepseek-template.md@main, Dolesh-avkalan/drop:ea-pilot/ea01/child/02-gemini-boundaries.md@main, Dolesh-avkalan/drop:ea-pilot/ea01/child/03-grok-costquality.md@main
---
You are the execution-coordinator (EA) finishing pilot EA001. The input files above
are: the coordinator start report, the pinned coordinator state, the three child
result files (each with status, model pin, ANSWER verbatim and evidence), and the
three child artifacts. Assemble the pilot's final deliverables and commit them
yourself to Dolesh-avkalan/drop, branch main.

Verify before you trust. For each child: confirm its result status is `done`, that
its artifact exists at the stated path, and that the artifact actually contains the
section its task asked for. Do not accept a reviewer's verdict without checking the
artifact it references. Record each model pin exactly as it appears in the result
files; if a pinned model was blocked, report that - never substitute.

Commit these files:
1. `ea-pilot/ea01/OPERATING.md` (<=700 words) - sections: Director responsibilities;
   EA/coordinator responsibilities; teammate routing; routine decisions the EA owns;
   consequential decisions escalated to the director; evidence/pin rules; task limits;
   continuation/recovery; read-only/default scope. Base it on the child artifacts and
   say plainly that the scope is an operating agreement, not an enforced sandbox.
2. `ea-pilot/ea01/TASK-TEMPLATE.md` - the compact director-to-EA brief (the DeepSeek
   draft, incorporating Grok's fixes).
3. `ea-pilot/ea01/EVIDENCE.md` - exact task IDs; the dispatch commit(s) you can see;
   each child's result status and chat/model pin as recorded; artifact paths; a
   sha256 per artifact if you can compute one, else say hashes were not computed;
   what YOU personally verified; and the gaps.
4. `ea-pilot/ea01/FINAL.md` (<=250 words) - verdict READY_FOR_DIRECTOR_REVIEW or
   BLOCKED; the exact artifact commit; the useful outcome; actual limitations. No
   claimed autonomous tests that did not run; no product-quality claims beyond the
   pilot.

Rules: write only under `ea-pilot/ea01/`. If any child is missing, blocked, or its
artifact is absent or unverifiable, still commit FINAL.md as BLOCKED and name exactly
what failed and why. You may create at most TWO fresh uniquely named correction
children (`tasks/ea01-fix-*.md` on browser-bus) plus one further continuation, but do
not wait in a busy loop. Keep it small and finish.

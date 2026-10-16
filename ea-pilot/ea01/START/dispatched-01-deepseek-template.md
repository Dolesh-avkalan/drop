agent: deepseek
chat: new
project: ea-pilot
timeout_min: 25
save_to: ea-pilot/ea01/child/01-deepseek-template.md
---
Draft two reusable artifacts for a director who delegates scoped work to an
execution-coordinator (EA). Answer from your own reasoning; no browsing, no code.
Keep the whole answer under 600 words.

Context: the director writes ONE brief. The EA runs the middle of the job - it
dispatches scoped child tasks to AI teammates over a git-based task bus, collects
their results, verifies evidence, assembles deliverables, and does bounded
corrections. Consequential decisions go back to the director. The EA may write only
new task files and one output folder; the default is read-only.

Produce exactly two Markdown artifacts, in this order:

1. `# TASK-TEMPLATE`
A compact, copy-paste brief a director hands the EA for one job. Include these fields:
objective; allowed paths/actions; acceptance criteria; budget (max child jobs /
answer words / time); evidence required; escalation rule. Keep it under ~180 words,
generic and fill-in-the-blank.

2. `# CORRECTION-AND-EVIDENCE-WORKFLOW`
The routine loop the EA runs: (a) how it verifies a teammate's artifact before
trusting any verdict; (b) how it fixes ordinary defects - bounded rounds, fresh
uniquely named child jobs, never auto-retry an uncertain write; (c) what belongs in
an evidence manifest (task id, dispatch commit, status, model pin, artifact
path/hash, what was personally verified, gaps); (d) a stop rule that ends the loop.

Plain Markdown only, no preamble.

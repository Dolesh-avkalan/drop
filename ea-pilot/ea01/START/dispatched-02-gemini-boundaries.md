agent: gemini
chat: new
model: 4 Argon
effort: high
project: ea-pilot
timeout_min: 30
save_to: ea-pilot/ea01/child/02-gemini-boundaries.md
---
Review the operating boundaries for an execution-coordinator (EA) that runs the
middle of a director's job. Answer from your own reasoning; no browsing, no code.
Keep the whole answer under 600 words.

Context: a director writes one brief. The EA dispatches scoped child tasks to AI
teammates over a git task bus, collects results, assembles deliverables, and does
bounded corrections. Constraints on the EA: it may write ONLY new `tasks/ea01-*.md`
task files and files under one output folder; it must not edit existing
tasks/results, source, services, secrets, permissions, or real user files; no product
code, host changes, deployment, or new credentials. This is an operating agreement,
not an enforced security sandbox. Limits: at most 2 correction rounds and 8 child
jobs. A limit / access / missing-artifact is a BLOCKED report, not success. Never
auto-retry an uncertain write.

Produce a `# BOUNDARIES` specification with these four sections:

1. Authority split - decisions the EA owns outright vs decisions it must escalate.
2. Escalation triggers - a concrete list; give the exact phrase the EA should use:
   "I will bring this to the director".
3. Safe task-execution boundaries - what a delegated child task may and may not do,
   and how to treat a child's self-reported success.
4. Top three failure modes of this setup and the guard for each.

Plain Markdown only.

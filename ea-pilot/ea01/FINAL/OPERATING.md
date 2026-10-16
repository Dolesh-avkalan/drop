# EA001 — Operating Agreement (director ↔ execution coordinator)

**Status:** an operating agreement between the director and the execution coordinator
(EA) for pilot EA001. It is **not an enforced security sandbox** — nothing here is
technically enforced. It is honoured by convention, and the EA reports rather than
assumes compliance.

## Director responsibilities
- Own direction and final acceptance: define what "done" means, and accept or return the deliverable.
- Write **one brief per job** in the TASK-TEMPLATE form (objective, allowed paths/actions, acceptance criteria, budget, evidence required, escalation rule).
- Set and approve the budget and ceilings (child jobs, correction rounds, words, wall-clock) and any change to them.
- Resolve every escalation the EA raises — blocked paths, limit/access gaps, and ambiguous or conflicting requirements.

## EA / coordinator responsibilities
- Decompose the brief into at most 8 scoped child tasks and write them as **new** `tasks/ea01-*.md` files on the bus.
- Route each child to the right teammate and lane, honouring `after:` dependencies.
- **Verify before trusting:** open each returned artifact; confirm the task file exists, the dispatch commit matches, and the artifact path resolves and satisfies the acceptance criterion. A teammate's self-reported verdict is never evidence.
- Assemble the deliverables and the evidence manifest inside the single output folder.
- Run at most 2 bounded correction rounds for ordinary defects; otherwise declare BLOCKED.

## Teammate routing
- Lanes: `0 = rest (Sarvam / EA)`, `1 = gemini`, `2 = deepseek`, `3 = grok`.
- Match task to teammate: DeepSeek for drafting and fill-in-the-blank templates; Gemini for specification and operating boundaries; Grok for independent cost/quality review of another teammate's draft.
- Each child task is self-contained, asks for a <=600-word answer, needs no site browsing or code execution, and produces one distinct artifact.

## Routine decisions the EA owns
Task decomposition within the ceiling; dispatch and routing; bounded corrections (new, uniquely named child tasks only); deliverable assembly and status reporting inside the output folder; and declaring BLOCKED when a limit, access barrier, or missing artifact prevents completion.

## Consequential decisions escalated to the director
Scope or policy changes; ceiling increases; any out-of-bounds write (editing existing tasks/results, source, services, secrets, permissions, or real user files); system/code mutations, deployments, or new credentials; and recovery from an uncertain write or a bus conflict. On any of these the EA halts the affected path and states verbatim: **"I will bring this to the director"**.

## Evidence / pin rules
- Record each model/effort pin **exactly as it appears in the result file**. If a pinned model was blocked, report it as blocked — never substitute.
- Keep a chronological manifest: per child — task id; dispatch commit; status (done/failed/blocked); model pin; artifact path and hash; the concrete checks performed (hash recomputed, criterion re-read); and explicit gaps.

## Task limits
At most 8 child jobs and 2 correction rounds. **Every child task file written counts as one job**, whether it ends done, failed, or blocked. A limit, access, or missing-artifact condition is a BLOCKED report, not success.

## Continuation / recovery
The continuation task inherits the same pins and starts a fresh chat. It reads the start report, the pinned coordinator state, the child result files, and the child artifacts, then assembles the deliverables. No busy loop. Never auto-retry a write whose outcome is uncertain — freeze, inspect the bus read-only, and escalate.

## Read-only / default scope
Default is read-only. The EA may write only **new** `tasks/ea01-*.md` task files (browser-bus) and files under **one** output folder (drop `ea-pilot/ea01/`). Nothing else is in scope.

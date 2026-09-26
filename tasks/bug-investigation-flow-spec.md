# Spec: Existing-bug investigation and fix handoff

## Objective

After Astakos offers to investigate a suspected bug in an existing ability,
the owner can authorize diagnosis without accidentally authorizing code or
runtime changes. A later, separate owner instruction may authorize a fix.
This flow applies to Web, Telegram, and Matrix through the shared graph; it
does not turn bugs into `cannot_do` records or new-tool drafts.

## User-visible contract

1. The existing localized bug offer remains a proposal, not a finding of
   proven root cause or permission to change anything.
2. A natural affirmative response to the current bug offer starts a
   diagnosis-only Dev_Agent turn. A refusal, question, unrelated request, or
   stale reply does not start diagnosis. Do not add phrase/keyword lists for
   ordinary user intent.
3. Diagnosis may read approved project files and use bounded, non-mutating
   checks. It reports what was observed, what is still uncertain, and a
   proposed fix with verification steps. If access or evidence is missing,
   it says so rather than fabricating a cause.
4. Diagnosis-only mode excludes source/config/database writes, publishing,
   messages, code-generation tools, and mutating terminal commands. The
   backend approval gate enforces this even if the LLM requests such a tool.
5. The diagnosis ends with a request for a separate, explicit fix instruction.
   A vague assent or the earlier investigation consent is not fix authority.
   After explicit fix authorization, normal project-access and tool-approval
   gates still apply. Commit, push, PR, merge, and runtime changes remain
   separate actions under existing project policy.
6. A genuine missing capability continues through the existing skill-draft
   flow. A transient failure or uncertain classification does not create a
   bug-fix workflow.

## Implementation boundaries

- Reuse the canonical bug proposal renderer and shared Supervisor/Dev_Agent
  graph. Keep the diagnosis state specific to the current graph turn; no new
  persistent database table or broad global mode.
- Use structured semantic routing for the owner's intent, with deterministic
  provenance and authorization checks at the tool boundary.
- Protect the first diagnosis turn even if a tool call is injected, the graph
  loops after a read, or the response arrives from another enabled channel.
- Do not edit `.env`, credentials, `config.py`, Docker, watchdogs, live data,
  or unrelated agent behavior for this slice.

## Code and tests

- Python 3.11+, typed new helpers, existing project docstring/style patterns.
- Likely source: `core/capability_draft.py`, `core/agents.py`, `core/utils.py`,
  `core/approval.py`, and localized Dev_Agent guidance only if needed.
- Focused offline pytest: exact bug-offer acceptance; refusal/question/stale
  reply; missing-capability and unrelated-turn isolation; mutating tool calls
  blocked even if LLM-generated; read-only project inspection allowed; normal
  explicit fix request retains its existing approval gates.
- Run the relevant routing/approval/Matrix background suites and
  `git diff --check`; no live cloud calls or user data in tests.

## Open verification

- A live owner test in Element/Web remains separate from offline completion.
- This spec does not authorize autonomous code edits or PR creation when a
  bug is merely detected or investigated.

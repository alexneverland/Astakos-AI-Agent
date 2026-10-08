# Spec: Daily context inference before routine questions

Status: owner-approved and implemented locally, 2026-10-08. Extends the shared-context work
in PR #233; this document does not authorize merging that PR or changing runtime.

## Objective and assumptions

Combine explicitly reported daily plans with newer completed events across Web,
Telegram and Matrix so Astakos can infer a routine's context instead of asking an
already answered question. Use semantic interpretation, not phrase matching.

An explicit day-scoped plan is distinct from a current-location observation.
"Not working today" alone does not locate a person. "Will remain home today"
is a plan; a newer actual departure by someone else can ground separation when
there is no contrary evidence. Plans must never be promoted to completed travel.
No routine is completed, reminder replayed or external action approved by this
context inference itself.

## Existing architecture and proposed boundary

- `memory/conversation_history.py`: canonical shared owner history and provenance.
- `services/context_extractor.py`: semantic interpretation and guarded flag writes.
- `services/routine_context_evidence.py`: current evidence validity and conflicts.
- `services/routine_context_clarification*`: existing eligibility/question lifecycle.
- `tests/`: isolated history, flag and question stores; no live owner data.

Reuse these paths. Do not introduce a second flag writer or parallel scheduler.
Build a bounded day-context view from canonical owner records, retaining source
identity, event time, subject and the distinction between a plan and an observed
event. Supply valid canonical evidence with the temporal references to semantic
interpretation. The one-hour conversational reference is not sufficient for
explicit all-day plans; merely raising the history limit is not the solution.

On a new trusted owner message, combine applicable daily context with the new
event and commit only supported flags through the existing conditional writer.
Before asking about unknown routine context, permit bounded semantic resolution
through that same path, then reload authoritative evidence and eligibility.
Unchanged evidence must not cause repeated model calls or renew stale presence.
Final persistence must reject newer user/GPS evidence arriving during inference.

Daily plans expire at their stated boundary (today means Europe/Athens today).
Current observations retain the existing freshness policy; this feature does not
turn an old observation into an all-day fact. New contradictory information wins
when temporally clear; otherwise leave the disputed state unknown and ask.
GPS proves only the owner's supported location, not other household members.
Truncated, malformed or unavailable context is not permission to guess.

## Success criteria

1. Exact reported lifecycle: 08:39 Web says Sofia is not working and will be home
   today; 10:09 Matrix reports departure for work. Persist
   `partner_with_user=false` before the 10:46 question opportunity and send no
   redundant co-presence question. Do not claim arrival at work or remote work
   for Sofia. Preserve the source times rather than pretending the plan was
   newly observed at 10:09.
2. Nearby safety cases: not-working alone, future departure, a newer report of
   travelling together, other-day plans, stale observations, external-derived
   content, unavailable model and a new user/GPS update during inference must
   not manufacture separation or overwrite newer state.
3. Web, Telegram and Matrix consume one shared inference path. Existing question
   budgets, refusals, cooldowns, completion ledger, approval gates and no-late-replay
   behavior remain intact. Unknown context still gets one legitimate question.

## Commands and testing strategy

Use pytest from the repository venv. Start with a failing reproduction of the
actual lifecycle and a nearby negative case; test final persisted flags and the
question-delivery boundary using real isolated stores. Replace model/transport
boundaries, and fail accidental outbound calls. No Android UI work is required.

Focused verification (add the new regression module when named):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_context_extractor.py tests/test_context_extractor_presence.py tests/test_routine_context_evidence.py tests/test_routine_context_clarification_poll.py -q --tb=short --basetemp=C:\Users\PC\.pytest_temp\daily_context
git diff --check
```

Compile changed Python sources and review the complete focused diff. Do not run
the full suite. Live semantic accuracy remains an explicitly separate observation,
not something mocked tests can prove.

## Code style

Use typed, small functions and structured return values, matching canonical
context/evidence code. For example, a helper accepts an aware `now: datetime`
and validated source records, not a free-form string whose words grant authority.
Deterministic logic validates identity, dates, provenance and concurrency only;
the LLM interprets human meaning.

## Boundaries

- Always: retain evidence provenance/time, distinguish plan/event, preserve
  unrelated tasks and use canonical conditional persistence.
- Ask first: schema migrations, new dependencies, separate durable stores,
  global freshness changes, expanding scope to draft wording or remote-work rules.
- Never: touch credentials/config, real databases or Chroma, runtime/watchdog,
  rewrite history, add natural-language keyword lists, auto-approve tools or infer
  household locations from owner GPS alone.

## Open questions

No product decision is unresolved. Implementation planning must establish how the
bounded day view retains relevant plans without reviving stale observations, and
how its source version participates in the existing final freshness checks.
The owner subsequently approved including the erroneous `partner_work_mode=remote`
fallback repair in this same PR: retire only the lexical rule and retain semantic
extraction, with persisted-state tests for all three channels.

## Verification status

204 focused offline tests passed with two existing dependency warnings. Provider
outputs are mocked; isolated stores verify persistence and question suppression,
not the real model's semantic accuracy. A source-age mutation was caught by its
regression test. Subsequent PR review fixes cover offset-aware midnight references
and eligibility-before-cap history scanning. The combined focused run passed
288 tests with one existing dependency warning. Live observation remains pending.

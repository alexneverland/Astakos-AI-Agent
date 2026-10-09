# Spec: Daily context inference before routine questions

Status: owner-approved and implemented locally, 2026-10-08. Extends the shared-context work
in PR #233; this document does not authorize merging that PR or changing runtime.

## Objective and assumptions

### General related-state reassessment (2026-10-09)

Owner approved this repair with "ΠΑΜΕ" after the live report: 08:59 Web reports
returning home and sorting toys with Sofia; 09:31 reports preparing to leave;
10:04 Matrix reports "Έφυγα, φίλε, πάω να πάρω το λεωφορείο". The extractor
changed owner whereabouts but retained `partner_with_user=true`, blocking
routine #4 at 10:45/10:55. Owner confirmed departure was alone.

Reassess co-presence semantically when a completed personal movement supersedes
a fresh shared activity. A separate owner journey can establish separation from
that activity without requiring the owner to spell out every resulting flag.
First-person grammar or not-working alone does not prove separation. Joint
travel, future preparation and unresolved accompaniment must remain distinct.

Owner clarified scope during implementation: reassess all related canonical
flags after every ordinary report, including child presence and other current
or later schema flags. Do not specialize interpretation to departure or Sofia.
The validated schema is supplied to the model; semantic consequences are stored
together. Future intentions still do not become current facts. Source-grounded
explicit co-presence must survive default assumptions about work or travel.

One slice: extend the ordinary extraction contract to accept source-grounded
updates through the existing daily source validator and conditional writer;
preserve legacy direct reports, clarification and pre-question resolution.
Use the current trusted source as the event and retain its time. Validate model
schema, source IDs and races; do not interpret words deterministically.

Acceptance: the exact lifecycle persists false and allows the Messenger routine
condition; joint travel retains true and blocks that condition. Future/ambiguous
events, invalid sources, malformed flags, and newer history/state cannot clear
presence. Provider/transport boundaries stay offline and stores temporary.
Also verify child/household/work consequences, explicit companions at work,
return/join events, and a new typed schema flag using the same writer. An empty
state result must retain unrelated durable routine request handling.

Tasks: write failing persisted-outcome regression and safety tests, extend the
shared validator/ordinary contract, then run focused context/routine checks and
compile changed Python. No live-state writes, sending, runtime restart or Git
publication. Live provider interpretation remains a separate observation.

Verify:
`venv\Scripts\python.exe -m pytest tests/test_context_presence_transitions.py tests/test_context_extractor.py tests/test_context_extractor_presence.py tests/test_daily_context_inference.py tests/test_routine_context_evidence.py tests/test_routine_conditions.py -q --tb=short --basetemp=C:\Users\PC\.pytest_temp\presence_transition`

Verification: 25 new offline cases cover persisted flags and the routine gate.
The initial grounded-transition regression failed before the implementation.
177 focused context/condition/poll cases passed; 22 clarification-answer cases
passed separately after correcting their stale reader patch. That fixture setup
error was reproduced against the unchanged HEAD extractor first. These two
successful runs cover disjoint sets, 199 cases total, with one existing provider
dependency warning per run. An in-memory removal of the shared source-age guard
was caught by the stale-event regression; workspace source was not mutated.
Python compilation and whitespace checks passed. No live provider interpretation,
runtime restart, live flag rewrite, message sending or Git publication performed.

Subsequent live observation: owner's 2026-10-09 12:12:02 work-arrival report
persisted `user_at_work=true`, `user_out_of_home=true`, `partner_with_user=false`,
`family_at_home=false`, `kid1_with_user=false` with the source timestamp. This
does not replay the original departure. Owner authorized PR publication on
2026-10-09. Existing `run_web.py` and `run_matrix.py` supervisors gracefully
restart for Python changes in the modified source directories; individual
prompt files are read on demand and are not separately watched.

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

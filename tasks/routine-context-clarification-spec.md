# Spec: bounded routine context clarification

Module: routine-context-clarification, from
[routine-context-refresh-map.md](routine-context-refresh-map.md).
Status: contract and ordered plan approved by the owner on 2026-10-06;
foundation, injected delivery, canonical answer persistence and initial plain-text
channel arbitration verified offline. Evidence-based resolution, complete
authority/Reply coverage and scheduler integration remain; no live question
dispatcher is active and no production question ledger has been created.
Date: 2026-10-06, Europe/Athens.
Dependency: context-evidence foundation implemented with 74 passing focused tests.

## Objective

Ask a single useful context question only when uncertainty affects an otherwise
eligible imminent routine. A trusted answer from Web, Telegram or Matrix updates
the common current-state path and permits timely reevaluation, without treating
the answer as approval, routine completion or a new behavioral followup.

Examples are outcomes, not natural-language parser keywords:

- A stale park observation and an imminent home-dependent routine can produce
  a natural question about return, not an assertion that the owner is home.
- Missing partner co-presence can matter even when a legacy suppress_when_true
  condition currently reports allowed=true. Ask only when that uncertainty can
  change the routine's decision/message, not because any flag is null.
- Fresh owner GPS supplies only owner whereabouts. It cannot answer whether
  the partner/child is present. The question must distinguish what remains unknown.

## Scope and exclusions

Only the five volatile flags approved in context-evidence are supported initially:
user_out_of_home, family_at_home, partner_with_user, kid1_with_user, kid1_with_partner.
Do not claim the missing work/school/schedule flags problem is fully solved here.
Those need schedule-context or a separately approved evidence-policy extension.

Reuse the existing selected external worker and shared routine scheduler; do not
start another scheduler, change polling intervals or restart processes as part
of development. External questions appear in Web through canonical shared history,
not through a second independently dispatched copy.

No reaction approval changes, legacy /confirm, Android UI changes, nightly routine
creation, semantic history cleanup, provider/config changes or raw database access.

## Eligibility and consequential uncertainty

1. Load only the current routine candidates in the existing 0-15-minute upcoming
   window. Apply active/paused/muted/date/day/cooldown/conflict-group filters before
   offering a question. Quiet/mute/recent-activity gates also apply to delivery.
2. Read the common context-evidence snapshot with one aware local evaluation time.
   Do not expire unscoped work/shift/extended absence using the two-hour policy.
3. Identify uncertainty that can affect current structured conditions: evaluating
   allowed assignments to unknown booleans must show a meaningful difference.
   A separate already-known blocking condition makes a question unnecessary.
   Bounded enumeration of up to five structured booleans is API/state validation,
   not interpretation of ordinary user wording.
4. Downstream proactive guards and message context also consume state. Do not
   repair only evaluate_routine_conditions while leaving stale values authoritative
   in the later prompt/guard. Supply the canonical scoped projection throughout
   this routine's decision path; never rewrite the original observations.
5. Where a routine lacks explicit context dependencies, a tool-free semantic
   decision may name required flags from the five-key whitelist, grounded in
   supplied routine/evidence data. Validate exact candidate IDs/flag IDs. No
   routine-name keyword lists, phrase aliases or regex meaning patches.
6. Unknown on model failure stays deferred for this eligible slot. Do not invent
   dependencies or send a generic morning questionnaire. Cache unchanged failed/
   unchanged decision snapshots to avoid model calls on each poll.

## Question content and limits

- At most one pending context question globally, across processes/channels.
- At most two successfully delivered questions per Athens calendar day.
  A send attempt with unknown delivery consumes a conservative reservation until
  reconciled; it must not enable another attempt merely because its receipt failed.
- No repeated unanswered topic that day. A validated structured dependency set
  and bounded routine IDs identify the context request; semantic subject/theme
  grouping may only choose from the supplied state dimensions, not create IDs.
- Coalesce related candidate routines into one question. Ask for the minimum
  information needed, not the whole day's schedule.
- Do not ask while a critical approval, routine completion/draft offer or another
  actionable confirmation would make a short answer ambiguous. This is deferral,
  not cancellation of the other lifecycle.
- Use existing quiet/mute/recent-activity and proactive budget gates. In particular
  can_send_proactive() increments a counter: call it once immediately before a
  real reserved send attempt, not for candidate inspection or every poll.
- Model question generation is tool-free and provenance-wrapped. It cannot execute
  an action, expand an approval, or claim that a guessed state is confirmed.

## Durable state and delivery

Use a dedicated memory abstraction, not pending_followups or pending routine
completion records. Preferred storage is a small versioned JSON ledger in BASE_DIR,
using the existing FileLock plus fsync/atomic-replace pattern. This avoids a schema
migration. Never write state files directly from transport or scheduler consumers.

Proposed file: routine_context_clarification_state.json (and its lock).
Include it in the explicit data-only backup selection and .gitignore; this is
scoped support for the new state, not a backup/runtime redesign. Implement/test
using temporary paths only. Do not create the real state file during development.

Persist a stable request ID, bounded routine IDs/slot times, dependency flags,
evidence/history correlation, question text, target channel, reservation/sent time,
external receipt, answer deadline and terminal reason. Store only necessary bounded
state; diagnostics must not leak private text, locations or raw model errors.

Lifecycle: reserved -> sending -> sent -> resolved / declined / expired.
Generation can occur outside the process lock; reservation and transitions cannot.
Concurrent workers revalidate the same snapshot after generation and under the
lock immediately before reserving/sending. Do not hold a lock across slow LLM work.

- Recheck latest user history, current evidence, selected channel, eligibility,
  deadline and interrupt gates after classification/generation before delivery.
- Matrix: reuse deterministic idempotent transaction IDs for confirmed delivery
  recovery. Reconcile receipt/history state after a crash without a second question.
- Telegram: never blindly retry an uncertain send. Hold it for reconciliation;
  do not promise exactly-once transport semantics the API cannot prove.
- A known pre-send failure may retry only while eligible, under the same identity
  and budget/reservation rules. Unsupported uncertainty is held, not fabricated.
- Persist canonical assistant history once with request identity metadata; no
  duplicate user history or graph reentry. A receipt/history persistence failure
  requires recovery, not a second send. Correlation includes confirmed delivery
  ordering, not just the time classification began.
- Missing ledger initializes safely; corrupt/unreadable ledger fails closed and
  remains untouched. Restart must not reset daily budget/pending question.

## Trusted answers from any channel

Questions are natural-language conversation, not a new command syntax. Reuse the
semantic context extraction/persistence path rather than another flag writer.

- Resolve only trusted owner text later than confirmed question delivery; exclude
  mirrors, quoted external content, photo inference and untrusted tool results.
- Give the extractor a provenance-wrapped bounded pending question plus trusted
  current reply. This enables pronouns/short answers across channels without making
  an unrelated yes/no into location evidence. Validate structured output/IDs.
- A tool-free semantic result distinguishes related answer, unrelated message,
  uncertainty or refusal. No affirmative/negative phrase lists.
- A consumed context answer must not also acknowledge/complete a routine, accept
  a draft or approve a critical tool. Keep authenticated exact-target approval
  processing authoritative; never swallow a reply addressed to another lifecycle.
- Apply validated context through the canonical extractor/persistence abstraction
  once, outside delivery locks, then reevaluate using a fresh evidence snapshot.
  Partial/failed extraction does not resolve the request as successfully answered.
- An unrelated or uncertain reply leaves the question pending without prompting
  again. A refusal closes it for that topic/day, without assuming a flag value.
- An intervening newer update can resolve the uncertainty even without replying
  explicitly to the question. Do not ask again if sufficient evidence now exists.

## Timeliness and resuming routines

The first release uses the existing upcoming-slot window; answer deadline is the
scheduled routine time. At or after that time, do not replay a missed routine
through this mechanism. A late explicit statement can still update normal context.

Before any resumed reminder, recheck active/paused/muted/cooldown/conflict groups,
all conditions, existing notified/completed state and current interruption gates.
Use the normal dispatch path once. The context question itself does not mark a
routine triggered/notified/completed or reset its confidence/cooldown.

If the answer still leaves required context unknown, remain deferred; do not send
a second question for the same unanswered topic that day. Context confirmation
never grants permission to send a message to another person or execute a critical
tool: the existing action approval remains necessary.

## Observability

Extend authenticated routine Debug with evidence source/age/validity and bounded
decision reasons: not_due, independently_blocked, context_unknown, waiting_answer,
quiet, muted, recent_activity, budget, delivery_uncertain, resolved, expired or error.
Distinguish condition evaluation from final dispatch outcome so allowed=true does
not imply a message was sent. No public endpoint or full location/text dump.

## Code style, files and verification

Typed helpers, short documented state transitions, one canonical semantic path.
Likely modules: services/routine_context_clarification.py,
memory/routine_context_clarification.py, shared scheduler/context_extractor hooks
and minimal Web/Telegram/Matrix interception wiring. Prompts live in prompts/;
fixed UI replies use locales, not hardcoded Python text. Exact file boundaries
and small slices will be recorded in the subsequent implementation plan.

Tests use pytest, injected aware clocks and temporary storage/real memory
abstractions where possible. Mock only provider/transport boundaries and fail
loudly on accidental network calls. No Android/ARTEMIS prerequisites.

Planned commands (files added during implementation):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_routine_context_clarification.py tests/test_routine_context_clarification_state.py tests/test_routine_context_evidence.py -q --basetemp=C:/Users/PC/AppData/Local/Temp/astakos-clarification
.\venv\Scripts\python.exe -m pytest tests/test_scheduler_e2e_conditions.py tests/test_matrix_routine_completion.py tests/test_routine_completion_telegram.py -q --basetemp=C:/Users/PC/AppData/Local/Temp/astakos-clarification-wiring
git diff --check
```

Verify actual existing test filenames when writing the plan; do not require a
nonexistent check or claim a command above has run. No full-suite rerun by default.

## Acceptance criteria

1. Stale park state + an eligible dependent routine -> one question, not guessed
   home; irrelevant null flags and independently blocked/paused routines -> none.
2. Null suppression conditions and later guards are covered, not just known-false
   allow conditions. Fresh GPS does not fabricate household presence.
3. Web/Telegram/Matrix related answers persist correct state once and cause at
   most one still-timely normal reminder; unrelated/ambiguous/refused/late replies
   do not execute, complete or approve another action.
4. Restart, concurrent processes, model delay/newer turn, channel changes, corrupt
   state, pre-send failure, uncertain send, and receipt/history failures cannot
   reset budget or blindly duplicate a question. Exercise persisted state, not
   only mocked observations.
5. Quiet/mute/activity/budget gates and two/day/one-pending/topic limits hold.
   Frozen clock tests prove deadline behavior; authenticated Debug is truthful.

## Boundaries and status

- Always: use context-evidence plus canonical memory, history and delivery paths;
  preserve existing unrelated work; write failing regressions before each slice.
- Ask first: any actual schema migration, new dependency, broader evidence flags,
  different deadlines or changes to action approval/runtime configuration.
- Never: touch .env/credentials/config, real databases/Chroma, running processes,
  Docker/watchdogs; send live messages or manufacture natural verification.

Implementation is wired through the existing routine tick/slow worker, with
canonical eligible filters, validated semantic dependency caching, five-flag
condition/guard/prompt projection and revalidation after generation. A pending
question holds competing routine prompts. Questioned expired slots are excluded
from startup recovery; unrelated legacy missed-routine behavior is unchanged.
Matrix retries require the same durable generation correlation and transaction
identity; Telegram uncertain sends remain held. Authenticated Debug reports
bounded evidence, pending lifecycle and the recorded last scheduler outcome.
The data-only backup includes the JSON ledger, not locks or temporary files.

Offline tests use temporary routine/history/ledger stores and mocked providers
and transports, including a Web answer followed by one timely ordinary reminder.
Natural semantic accuracy, real delivery and a running scheduler remain
owner-controlled verification. No real data, credentials or runtime were changed
by verification. The owner separately authorized commit/PR and Codex review;
merge and task-branch deletion are not part of that authorization.

Final offline evidence (2026-10-06): 325 related tests passed in the combined
focused run. The final production-worker/scheduler/Debug/startup slice passed
33 tests, including canonical Web answer persistence and two scheduler ticks
producing one ordinary reminder. Legacy completion fixture suites passed in
separate processes (23 Telegram; 28 Web/Matrix), preventing their whole-module
stubs from contaminating other tests. These runs overlap; counts are not summed.
Each provider-using run reported one existing dependency deprecation warning.
An inverted deadline guard made the expected regression fail; after restoring
the guard, all eight scheduler tests passed. All 32 changed Python files compiled,
both dashboard inline scripts passed JavaScript syntax checks, and git diff
--check passed with only Git line-ending normalization notices. No full suite
or live provider/device behavior is claimed.

Pre-PR checkpoint: 107 focused evidence/worker/scheduler/Debug/startup tests
passed in 14.10 seconds with one existing dependency deprecation warning.
That checkpoint predates the PR #224 review corrections below.

## PR #224 review corrections

- Answer inference captures a shared-history/canonical-state/GPS evidence
  version and rechecks it immediately before persistence. A newer version
  defers the old answer without overwriting state or closing its question.
- Generated reminders re-read the canonical eligible-routine query, including
  active/completed/skipped state, pause, name and slot, before delivery.
- Complete answers and fresh evidence-only resolutions use one ledger
  finalization transition that persists a dispatch wakeup atomically with closing
  the question. Declines and expiry do not request dispatch.
  The selected external runtime consumes it on its existing fast worker and
  invokes the ordinary routine checker under the same in-process dispatch lock
  as periodic ticks. Web does not run a second scheduler. Idle polling is two
  seconds; busy workers/model latency can still miss a deadline. Expired wakeups
  never authorize late replay. A crash after claiming a wakeup falls back to
  normal periodic checks; this is not an exactly-once dispatch outbox.
- A confirmed transport receipt remains successful when history recording
  fails, allowing routine notification/completion state to be recorded. Only
  history repair is queued, with a stable Matrix history ID preventing duplicate
  rows. The existing in-memory repair queue is best-effort, not durable across
  shutdown or repeated storage failures; it never re-sends the message.

Review verification: 123 focused tests passed (one existing dependency warning)
and the isolated legacy Telegram completion suite passed 23 tests. Temporary
storage, frozen timing and mocked transport verify a Web answer 15 seconds before
the slot, one canonical dispatch, and no duplicate after a confirmed send plus
history failure. Mutation of the answer freshness comparison failed all three
new stale-evidence regressions; the comparison was restored. Natural scheduler,
provider and device observation remains pending; no full suite was run.

Evidence-only review correction: three regressions failed before the fix.
After sharing the finalization transition, 78 focused ledger/poll/reply/worker/
scheduler tests passed with two existing dependency warnings. The production
worker fixture verifies fresh stored evidence resolving a question 15 seconds
before its slot, followed by one ordinary reminder across two checks, including
confirmed delivery with history failure. Repeated polls cannot rearm the wakeup;
declined or expired questions do not dispatch. No live data/runtime was touched.

## Concurrent GPS and conversational answers

The live 2026-10-06 Matrix observation exposed an acknowledgement race: fresh
GPS resolved the question while owner-answer classification was still running.
An answer that lost its commit must inspect the same request identity. If that
request is already resolved, acknowledge the newer information, not a write of
the older answer. Never retry the old payload or rearm routine dispatch.
Declined, expired or still-pending requests keep their non-success outcome.
Context acknowledgements do not imply tool approval; approval gates are unchanged.
Successful system-generated Routine_Context replies are excluded from Matrix
capability classification, while deferred failures and ordinary bug reports
remain eligible. This exclusion compares exact localized system output, not
user phrases or keywords.

Verification: the real temporary GPS writer, poll and answer ledger reproduce
the race (failed before the fix); 86 focused reply/extractor/poll/channel/Matrix
background tests pass with one existing dependency warning. Natural post-fix
observation remains pending. No full suite, live provider or device call was run.

## Same-value live GPS evidence and transport diagnostics

Each validated live point refreshes `user_out_of_home.updated_at` through the
canonical context upsert, even when its boolean value is unchanged. Previously
the same-value shortcut left the stored observation stale despite repeated live
points. Static pins and unknown home geometry do not refresh this flag; owner
work and family co-presence are not inferred. Existing expiry policy is unchanged.

Matrix location callbacks record fixed acceptance/rejection reasons in the
existing private event log, correlated by a random run ID. No coordinate, sender,
room identifier or exception payload is recorded. A beacon-info sharing event
is `awaiting_point`, not a coordinate update; `processed` means the registered
location handler completed successfully. Telemetry failure does not alter trust
checks or processing. Malformed, undecrypted and wrong-sender points remain
rejected. Historical points were not retained, so the cause of the earlier
missing fresh point cannot be established retrospectively.

Verification: 101 focused location/reply/evidence tests pass on temporary data,
including same-value freshness and actual private JSON decision logs. Natural
Element share observation remains pending; no runtime restart or live send.

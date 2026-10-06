# Astakos: Current Plan

Last reconciled with the owner: 2026-10-06 (context clarification completed;
existing verification entries preserved).
Only active work is listed here; [todo.md](todo.md) records its status.
Completed evidence remains in Git history and existing specs/runbooks.
The [archived plan](archive/2026-10-02-plan.md) is not an active queue.

## Current feature: time-aware routine context evidence

Map: [routine-context-refresh-map.md](routine-context-refresh-map.md).
Owner-approved contract: [context-evidence-spec.md](context-evidence-spec.md).
Status: read-only foundation implemented on 2026-10-06; the following evidence
describes that historical checkpoint. Its clarification consumer is now wired
as documented below. Natural observation remains pending.

Build one read-only canonical evidence snapshot before changing any routine
dispatch. Two-hour validity applies only to five scoped whereabouts/co-presence
flags; fresh owner GPS lasts fifteen minutes. Expired and contradictory evidence
becomes unknown, not false. Work/shift, quiet hours and extended absence keep
their current semantics. The snapshot is not proof that a writer's persistence
time is the event time, nor that legacy stored context came directly from the
owner. No provider, transport, scheduler or database migration is included.

### Ordered implementation slices

1. **Stored evidence:** typed records and pure evaluation in
   services/routine_context_evidence.py. Use existing get_context_state through
   injected loaders. Verify recent true/false, stale park state, malformed/future
   timestamps, date expiry, read failures and timezone/DST boundaries. No writes.
2. **Owner GPS:** validate fixture/persisted point and reuse location_is_home.
   Reconcile agreement/conflict with stored owner whereabouts and expose a
   contradictory family-home claim as unknown. Never infer family co-presence.
3. **Canonical entry point:** expose build_routine_context_evidence from
   services/routine_context.py without changing build_runtime_routine_context,
   legacy defaults or existing callers. Verify isolated memory/GPS wiring and
   unchanged current resolver behavior; update only this feature's status/docs.

Dependency order: stored evidence -> GPS reconciliation -> public entry point.
Use incremental-implementation with TDD in each slice, not a large unverified
rewrite. No delegation or parallel agents are needed for these shared files.

### Verification checkpoint

Run only tests/test_routine_context_evidence.py and tests/test_routine_context.py
with the project venv and an isolated --basetemp, then syntax checks and
git diff --check. New tests must fail before implementation and pass afterward;
fixtures must prevent real memory/provider/outbound access. Document inspection
and test results separately from natural provider/device verification.

Checkpoint evidence: 26 stored-evidence tests failed then passed; the next GPS
slice added 24 initially failing tests, followed by 50 passes; wiring added eight
initially failing tests. Final two-file run passed 74 tests with one dependency
deprecation warning; four Python files compiled and git diff --check passed.
Existing resolver tests now isolate database/GPS and block network, with the
deterministic legacy shift test stubbing semantic inference. The earlier mixed
run waiting on that previously unmocked provider boundary was stopped. Final
offline wiring verifies unchanged temporary storage and legacy resolver behavior;
no natural provider/device verification or automatic clarification is claimed.

### Risks and boundaries

- Legacy state lacks writer provenance: label stored_context truthfully and hold
  conflicts as unknown, not an invented source ranking.
- Naive timestamps/DST: normalize with the evaluation time's local timezone and
  compare elapsed validity as instants. Midnight is a calendar boundary.
- Read failures/invalid GPS: unknown/error with bounded reasons, never guessed home.
- Adding freshness directly to current dispatch would disable reminders before
  recovery exists: do not activate the snapshot in dispatch during this module.
- Followups, routine completion, initiative budgets and critical approvals stay
  separate. No live databases, Chroma, config, credentials or runtime changes.

The dependent clarification contract is approved; its implementation plan follows.
The evidence snapshot remains read-only; clarification and ordinary dispatch
now consume its scoped projection through the approved dependent module.

## Completed implementation: bounded routine context clarification

Contract: [routine-context-clarification-spec.md](routine-context-clarification-spec.md).
Status: all CQ1-CQ8 slices are implemented and wired in code on 2026-10-06.
Existing routine ticks enqueue a coalesced slow worker; no new scheduler interval
or database migration. Web/Telegram/Matrix answers share canonical persistence.
Offline evidence and final command results are recorded in the contract/todo.
No process restart, production ledger, real messages, or live provider test was
performed; owner-controlled natural observation is still pending.

### Architecture and dependency order

Use the five scoped evidence flags, a dedicated atomic JSON ledger through a
memory abstraction, tool-free semantic interpretation, and canonical history,
context persistence and external delivery. No new scheduler or DB migration.
Each slice below includes executable offline acceptance tests and documentation;
only the final scheduler slice activates the complete recovery path.

Order: CQ1 -> CQ2 -> checkpoint -> CQ3 -> CQ4 -> checkpoint -> CQ5 -> CQ6 ->
checkpoint -> CQ7 -> CQ8 -> final checkpoint. Shared files are edited sequentially.
Existing incomplete live-verification entries remain unchanged.

### CQ1: Persist one question lifecycle safely

Build typed, versioned ledger transitions through a dedicated memory abstraction.
Acceptance: one pending request and two/day reservations survive restart and
concurrent callers; refusal/expiry retain the unanswered topic for that day;
corrupt state fails closed without overwriting it. No real ledger is created.
Files: memory/routine_context_clarification.py and new
tests/test_routine_context_clarification_state.py (small).
Verification: temporary-file failing-then-passing tests with aware injected clocks,
contention and atomic-write failure coverage; syntax and diff checks.
Dependencies: approved contract and existing context-evidence foundation.
Result: temporary-ledger tests cover reservation, expiry, restart, concurrent
workers, daily/topic limits, corruption, interrupted replace and late closure.

### CQ2: Select a consequential, eligible question

Implement candidate selection and bounded structured dependency evaluation.
Acceptance: stale park evidence or relevant null suppression yields one minimal
question; irrelevant unknowns, known independent blockers and ineligible routines
yield none; delayed model output is discarded after newer history/evidence.
Validate model IDs, use provenance wrapping, and cache unchanged decisions/errors.
Files: services/routine_context_clarification.py, new
tests/test_routine_context_clarification.py, prompts/routine_context_question.md
(medium). Dependencies: CQ1.
Verification: deterministic candidate fixtures, provider boundary mocked, network
blocked; no real routine reads or questions sent.
Current progress: pure condition influence, bounded model proposal validation,
stale callback and persisted same-snapshot evaluation are offline verified.
Canonical eligible-candidate filtering, semantic dependency fallback/cache and
post-model history/evidence/channel/gate freshness rechecks are implemented.

### Checkpoint after CQ2

Historical CQ2 checkpoint: reviewed persisted lifecycle and selection together
using temporary ledger storage, before adding the dispatch consumer below.

### CQ3: Deliver and recover without blind duplicate sends

Connect question preparation to canonical transport/history through injected
boundaries, still without a scheduler caller. Acceptance: revalidate and reserve
before one budget-consuming send; Matrix retries reuse the transaction ID;
Telegram uncertain delivery stays held; receipt/history failures recover without
another outbound question. Successful history persists once by request identity.
Files: services/routine_context_clarification.py, its test module,
services/external_delivery.py only if the existing interface needs a scoped
idempotency extension, and its focused tests if modified (at most four).
Dependencies: CQ2 checkpoint.
Verification: real ledger/history fixtures with mocked transport, pre-send errors,
uncertain delivery and crash windows; no network or process restart.
Historical CQ3 progress: an inactive injected service path had focused tests for one
reservation, stable Matrix identity, held Telegram uncertainty, receipt/history
repair and stale pre-send checks. Injected current time is rechecked before
sending and used for receipt time; confirmed history repairs remain possible
after expiry or a channel change without outbound I/O. Production clock/worker
integration and persisted generation-correlated Matrix retry are implemented.

### CQ4: Interpret and persist a trusted answer canonically

Extend the shared semantic extractor with bounded pending-question context and a
structured outcome while preserving ordinary callers. Acceptance: related owner
answers persist through the canonical flag path once; unrelated/refused/uncertain
or partial failures do not invent values or report resolution; evidence refresh
can resolve the request without an explicit answer. Validate delivery correlation.
Files: services/context_extractor.py, services/routine_context_clarification.py,
new tests/test_routine_context_clarification_answers.py,
tests/test_context_extractor_presence.py (medium). Dependencies: CQ3.
Verification: final temporary persisted flags and ledger, short cross-channel
answers, quoted/untrusted content and late explicit context updates.

Current progress: the canonical extractor accepts an optional bounded question
reference and returns a structured relation plus successfully written flags.
Short replies work with each channel parameter. Nonanswers, invalid boolean
results, out-of-scope identifiers, stale post-model checks and failed/partial
writes do not acknowledge resolution. Ordinary extraction remains unchanged.
Durable answer correlation and ledger finalization are implemented. Classification
runs without a ledger lock; the short canonical persistence stage revalidates
delivery, deadline and competing confirmations under a cross-process lock.
Concurrent full answers cannot both write/resolve. Failed or partial writes never
claim resolution; DB and ledger files are not a distributed atomic transaction,
so a failed ledger save leaves retryable canonical upserts and a pending request.
Post-delivery sufficient fresh evidence automatically resolves pending questions.
Provider interpretation is mocked; these tests prove validation/persistence, not
live semantic accuracy.

Latest slice checkpoint: 123 focused answer/extractor/channel/Matrix/lifecycle
tests pass with one existing dependency warning. No live provider or outbound
transport was used; fixture persistence is temporary and the scheduler was not
started. Tests allow only asyncio's required localhost socketpair, blocking
external network connections.

### Checkpoint after CQ4

An injected candidate -> question -> trusted answer -> refreshed evidence path
passes offline. Failed interpretation stays pending; no action is executed and
no routine completion/approval record changes.

### CQ5: Wire Web and Telegram reply arbitration

Add minimal early interception backed by the shared answer service; keep exact
target approvals authoritative and avoid completion/draft consumption of context
answers. Acceptance: related replies use one common history/extraction path;
ordinary and unrelated replies retain normal processing; simultaneous actionable
confirmations defer clarification rather than interpreting an ambiguous yes/no.
Files: api/server.py, clients/telegram_bot.py,
new tests/test_routine_context_clarification_web.py,
new tests/test_routine_context_clarification_telegram.py (medium).
Dependencies: CQ4 checkpoint.
Verification: channel entry-point fixtures, no cloud calls, approvals and
completion regressions for both channels; no live runtime changes.

Current progress: early Web/Telegram interception persists consumed replies via
the existing history paths, emits a localized context-only acknowledgement and
does not dispatch graph tools or a second extractor. The adapter is a no-op if
the question ledger does not exist; no production ledger is created in this
slice. Global approval/completion/draft/asset conflicts defer interpretation and
are checked again before canonical writes. Focused entry-point and persisted
candidate/question/answer/normal-dispatch tests cover this boundary.

### CQ6: Wire Matrix through the same answer contract

Acceptance: authenticated owner answers resolve a question delivered on either
external channel; mirrors/external-derived content cannot resolve it; Reply
approval and completion behavior remain intact with history written once.
Files: services/matrix_turn.py, services/matrix_background.py only where needed,
new tests/test_routine_context_clarification_matrix.py,
tests/test_matrix_routine_completion.py (medium). Dependencies: CQ5.
Verification: Matrix entry-point fixtures and real temporary ledger/state,
transport mocked, exact-target approval and unrelated follow-up safety cases.

Current progress: trusted plain Matrix text uses the shared answer adapter;
asset-derived turns are excluded and consumed answers bypass routine completion.
History is canonical and the background hook skips duplicate flag extraction.
Ordinary Matrix extraction now explicitly supplies channel="matrix" rather than
the prior implicit Telegram default. Existing Matrix turn/completion tests pass.
The transport's exact Reply approval path remains authoritative for approval
targets. Only an exact, delivered, recorded, unexpired Matrix context-question
target bypasses emoji approval interception. The Matrix quote fallback is stripped
only for that confirmed target, preserving multiline owner answers. Correlation
propagates through task-local ContextVar scope and asyncio.to_thread; cleanup is
tested even on turn failure. Ordinary Reply targets also propagate, so a Reply
to another event cannot silently answer the current question.
An offline full transport -> turn -> canonical flag -> resolved ledger/history
test passes alongside existing verified/unverified approval tests. Latest Reply
checkpoint: 72 targeted tests pass, with two dependency deprecation warnings;
syntax and git diff --check pass. No dispatcher or production ledger is active.
Authority, entry-point and evidence-refresh resolution checks are implemented.

### Checkpoint after CQ6

All three entry points pass the same answer scenarios. Verify that short answers
cannot both resolve context and approve/complete another action. No scheduler
integration until this checkpoint passes.

### CQ7: Adopt evidence and timely recovery in normal routine dispatch

Use existing job_check_routines, no new job/interval. Acceptance: candidate
conditions, later guard and message context use the same scoped evidence view;
quiet/mute/activity/confirmation gates defer questions without consuming polling
budget; a timely answer permits at most one ordinary dispatch after all fresh
eligibility checks. At/after the scheduled time no replay occurs.
Keep non-scoped shift/work/extended-absence semantics unchanged.
Files: clients/telegram_bot.py, services/routine_context_clarification.py,
services/routine_context.py, new tests/test_routine_context_clarification_scheduler.py,
tests/test_routine_proactive_guard.py (medium). Dependencies: CQ6 checkpoint.
Verification: frozen-clock scheduler tests with real temporary memory and ledger,
restart/concurrency fixtures, budget call counts and stale downstream guard cases.
Stop and revise this slice if it requires broader unrelated scheduler refactoring.

Preparation checkpoint (2026-10-06): an injected worker in
services/routine_context_clarification_poll.py rechecks eligible candidate data,
shared history cursor, scoped evidence, channel and interrupt gates after model
latency. It waits on confirmed questions, resolves sufficient post-delivery
evidence, expires slots and repairs committed shared history without resending.
Cache keys now include known scoped values and validity timestamps; selectable
IDs are exactly the bounded model packet. Budget charging runs inside the short
durable send transition, with another clock check afterward. 68 targeted tests
pass, one dependency warning. That was the historical inactive checkpoint.
The final code now includes canonical candidate filters, semantic dependencies,
durable generation correlation/retry, downstream guard/prompt projection and
still-timely ordinary dispatch. While a question is pending, no new routine
completion prompt is introduced. Questioned slots are never replayed at/after
their deadline, including startup recovery. Unquestioned legacy startup recovery
is unchanged. Batch reminders deliver once; only confirmed sends mark notified.

### CQ8: Expose bounded diagnostics and preserve ledger in backup

Acceptance: authenticated Debug distinguishes unknown/waiting/expired/delivered
from conditions passed without private text/location dumps; new ledger/lock are
ignored; data-only backup includes the ledger but not locks or temporary files.
Files: api/server.py, services/daily_data_backup.py, .gitignore,
tests/test_routine_dashboard.py, tests/test_daily_data_backup.py (medium).
Dependencies: CQ7. Verification: authenticated endpoint fixtures and temporary
backup selection tests; no actual backup execution or real state inspection.

### Final verification and rollback boundary

Run new clarification tests plus evidence tests first; then only touched-channel,
context extractor, routine condition/guard/completion and backup regressions.
Confirmed existing test names include test_routine_conditions.py,
test_routine_proactive_guard.py, test_routine_completion_web.py,
test_routine_completion_telegram.py, test_matrix_routine_completion.py,
test_matrix_background_hooks.py and test_external_scheduler_startup.py.
test_scheduler_e2e_conditions.py exists and is used with isolated fixtures.
Legacy test_routine_completion_telegram.py uses whole-module stubs and must run
in its own pytest process, separately from real-module Web/Matrix checks.
Use venv pytest with isolated --basetemp and network-blocked fixtures; syntax
checks for touched Python files and git diff --check. No full suite by default.

Record offline execution separately from natural model interpretation and live
delivery, which remain owner-controlled observation after implementation review.
Before shipping, inspect the full scoped diff, including untracked files, against
acceptance criteria and Definition of Done. Do not mark natural verification done
on mocked-provider evidence. No commit/PR or runtime activation command is
performed as part of implementation verification.

Rollback must detach the new scheduler/reply consumers together, preserving
ledger evidence and the old context path; it must not replay uncertain sends.
Do not add a configuration switch or reset persisted state without approval.
Main risks: dual consumption of short answers, stale flags in later guards,
cross-process reservation races and delivery uncertainty. The ordered checkpoints
exercise each before integration. Schedule-derived work/school inference remains
deferred. Remaining feature work is owner-controlled natural observation and the
separately authorized Git/review lifecycle, not another implementation slice.

## Current repair: shift temporal provenance

Contract: [shift-temporal-provenance-spec.md](shift-temporal-provenance-spec.md).
Preserve the semantic schedule end rather than interpreting a memory recording
date as its effective start. Prevent the legacy fallback from overwriting that
decision; uncertain dated facts must not change the existing schedule. Validate
structured dates/values without new phrase lists. Offline persistence and
Sunday/Monday resolver coverage and explicit cancellation are implemented;
the Codex finding is addressed with 122 passing focused tests. Only natural
live model interpretation remains pending. Backup documentation stays separate.

## Pending natural verification: memory fact provenance and dated duplicates

Contract: [memory-fact-provenance-spec.md](memory-fact-provenance-spec.md).
Keep assistant acknowledgements out of deterministic USER_FACT writes; compare
nearby facts through the canonical save path across categories and languages,
preserving distinct periods and new information. Recheck a selected duplicate
after classification, outside-lock model calls, and label Debug distance correctly.
No existing-memory cleanup or original Chroma access. Offline final-storage tests
are implemented, including the Codex correction for stored photo provenance;
natural provider interpretation and latency remain to observe.

## Completed implementation: vacuum/GPS and bounded Web turns

Owner-approved contract: [vacuum-location-boundary-spec.md](vacuum-location-boundary-spec.md).

- Repair vacuum activation after the required location read using a strictly
  validated, instruction-free location projection and canonical configured-home
  geometry. Raw/malformed GPS and other external content remain untrusted.
  Unknown/stale presence must not assert current location.
- Preserve already-emitted blocked/pending results at the Web step boundary;
  otherwise report incomplete execution truthfully, without retrying actions.
- Repair implemented after offline reproduction. 160 focused tests pass,
  including mocked-hardware execution and real LangGraph budget exhaustion.
  Approval policy and recursion limits are unchanged. Owner live test remains.
- Focused offline verification only: no real vacuum, provider/transport calls,
  live data, runtime/config changes or full-suite rerun. PR #211 Codex finding
  is addressed with 25 focused Web regressions; owner authorized merge and
  deletion of its task branch. Owner-controlled live verification remains.

## Daily data-only backup (owner approved)

Contract: [daily-data-backup-spec.md](daily-data-backup-spec.md).
Build selection/verified cold package, then verified Drive upload and scoped
retention, then visible writer pause/resume and schedule switch to 00:00.
Preserve all unrelated live-verification entries below and the 03:00 Matrix job.
Do not activate an incomplete backup or discard the last known-good artifact.
54 focused tests pass. Live Web/Matrix pause and restart in their original
consoles succeeded. A cold 47-file, 64,334,713-byte package was extracted into an
isolated directory and every file matched its manifest SHA-256; this verifies
byte restoration, not application-level recovery on a replacement host.
Owner authorized removal of eight broken legacy JSON photo-index entries and
recycling seven matching outputs; Chroma cleanup is explicitly deferred.
Owner authorized making the configured Drive folder owner-only. After OAuth
reconnection, upload size/checksum and private permissions were verified; old
daily folders were trashed and one managed ZIP remains active.
Owner ran the registration script; Scheduler readback confirmed the 00:00
trigger, scripts/nightly_data_backup.py action, venv interpreter and project
working directory. The first scheduled execution succeeded on 2026-10-03.
The 03:00 Matrix task is unchanged. Manual execution of the actual daily
Scheduler task completed on 2026-10-02 in about 88 seconds (LastTaskResult=0,
status=complete, 47 files). The timed 00:00 invocation also completed successfully.
PR #212 Codex findings are addressed with failing-then-passing regressions:
include persisted meal history and recipe library, and preserve supervisor
recovery after descendant shutdown failure without overlapping old writers.
26 focused backup/watchdog/launcher tests pass for this repair. The earlier
47-file live capture predates the added skill data; no new live run is claimed.

## Remaining live verification

1. **Matrix recovery:** the timed 03:00 invocation is now verified; full Element
   key recovery and replacement-host recovery remain separate work. PR #210 is merged; encrypted private Drive
   delivery, actual Scheduler invocation and isolated server/bot restore were
   already verified. Full Element key recovery and replacement-host recovery
   remain separately bounded verification, not a complete host-loss guarantee.
   Reference: [matrix-backup-recovery-spec.md](matrix-backup-recovery-spec.md).
   The 2026-10-03 timed run failed in the headless stop guard. Native pythonw
   reproduction showed WinError 6 with invalid inherited stdin. Non-interactive
   backup subprocesses now use explicit DEVNULL input; stage/failure diagnostics
   preserve the primary failure separately from recovery. Actual Scheduler retry
   at 08:48:53 local completed at 08:49:57 with LastTaskResult=0, verified encrypted
   upload and recovery under the same visible parent. The timed 2026-10-04 run
   succeeded: Scheduler start 03:00:01 local, backup completion 03:00:52,
   LastTaskResult=0, status=uploaded/stage=complete. The 6,332,292-byte encrypted
   artifact matches its recorded SHA-256; the status records a Drive upload ID.
   Recovery logs show the encrypted Matrix channel restarted, with no remaining
   pause/maintenance marker. This check did not repeat a Drive download/restore
   or visually inspect the terminal; it is not full host-loss recovery evidence.
   The separate 00:00 data-only run succeeded on 2026-10-03: 47 files, revision
   dd20296, completion at 00:00:47 local and LastTaskResult=0.
2. **Behavioral conversation:** naturally observe relevant commentary, semantic
   topic opt-out/re-enable and an appropriate spontaneous opener. Reconcile new
   exceptions from actual observations. Implementation/offline tests are complete;
   do not manufacture live messages to claim provider verification.
   Reference: [behavioral-conversation-spec.md](behavioral-conversation-spec.md).
   Initiative telemetry keeps the last check and last model evaluation separately
   in `behavioral_initiative_state.diagnostics.json`, shown by the authenticated
   behavioral Debug section. Gate/decision/error codes explain skips without
   recording chat text, model output or exception messages. Cached polls retain
   the last evaluation; telemetry failure cannot change send/approval behavior.
   A natural Matrix tick at 2026-10-04 22:31 recorded recent_activity. Natural
   model evaluation/opener observation remains pending. Followups are separate
   specific-event continuations and are not changed by initiative diagnostics.

## Standing boundaries, not pending tasks

- Owner-confirmed Telegram–Matrix parity and cross-channel context continuity
  are complete. Critical Matrix approvals use encrypted Reply to the exact
  prompt; no reaction-based replacement or legacy `/confirm`.
- Mirrored copies must not duplicate history or re-enter the graph. Media and
  generated-file cards are not mirrored as files or private filesystem paths.
- Behavioral detection is message-triggered, not nightly routine creation.
  Initiative stays at one opener/day, seven days/topic and fifteen minutes
  without conversation/reminder activity, subject to quiet/mute/budget and
  freshness checks. Uncertain Telegram or stale Matrix delivery is held, not
  blindly resent. Recovery UI and expanded source retrieval remain deferred.
- Keep channel isolation, provenance and two-stage bug investigation approvals.
  Completed supplied-link reporting is not an open task.
- Documentation reconciliation needs document/diff checks; behavioral changes
  need focused offline regressions. No full-suite rerun by default.

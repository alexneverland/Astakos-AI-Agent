# Astakos: Current Plan

## Narrow goal-update repair (2026-10-08)

Reuse the canonical goal tools and temporal metadata, without a new scheduler,
classifier pipeline, schema change or live-data backfill. Both Chat and Dev must
be able to record trusted reported project activity and verified joint work.
Resolve the project semantically from current conversation/goal context, ask if
ambiguous, and prefer partial updates for existing goals. A result/score belongs
in milestones; completion percentage needs explicit evidence or an agreed plan.
Preserve existing creation time, description, status and untouched progress.
Verify bindings in all three channels, actual persistence at an offline storage
boundary, unknown-project rejection, external provenance and read-only diagnosis.
Provider tool selection remains a separate owner-controlled natural observation.
No unrelated routine/reflection changes or full-suite rerun.

## Next routine slice: optional context notes (2026-10-08)

Approved contract: `tasks/routine-context-notes-spec.md`. Keep the blocked action
separate from an optional 30%-gated semantic comment; work/shift is not a blanket
comment exclusion. Explicit silence, quiet hours and canonical freshness remain.
This section extends routine work; all existing live/restore tasks remain intact.

Implementation sequence, approved by the owner and implemented:

1. Reproduce the blocked-routine path and confirm a reusable durable reservation
   that records note evaluation without creating reminder pressure. Cover repeated
   ticks/restart and confirmed transport success followed by history failure.
   Expected scope: focused tests and the existing persistence abstraction. If
   schema changes are necessary, stop for explicit approval instead of migrating.
2. Implement one tool-free structured note decision with bounded, provenance-
   wrapped shared context. Retire keyword and permanent-sentimental gates from
   this path only. Verify no-note, work-context, invalid output and provider failure.
   Expected scope: focused service, prompt and tests (at most five files).
3. Connect the decision to known blocked conditions and semantic context skips
   in the shared scheduler. Preserve normal action/confirmation flow; revalidate
   state, occurrence, channel and silence immediately before delivery. Record
   evaluation/delivery diagnostics without treating the note as routine feedback.
   Expected scope: scheduler, canonical delivery helper and integration tests.

Checkpoints: RED/GREEN per slice, then focused silent-skip/dated-delivery/context
regressions, compilation and `git diff --check`. No full suite, live messages,
real data edits, runtime changes or subagents. Final natural wording needs owner
observation; successful offline tests do not prove live semantic quality.

Risks: pressure contamination, poll-based rerolls, duplicates after history
failure and stale inference. Guard with distinct note state, durable once-per-
occurrence reservation, preserved transport receipt and canonical revalidation.
No separate scheduler or new behavioral initiative is introduced.

Implemented using held `note-` evaluation entries in the existing clarification
ledger (unchanged schema), protected from same-day dependency-cache eviction.
Chance, null/error output and uncertain transport all hold that occurrence;
optional comments are deliberately not retried. The tool-free model receives
canonical context plus bounded, provenance-wrapped history and Chat personality.
Shared scheduler paths cannot fall through from a blocked note into a reminder.
Final checks cover fresh owner history, GPS/evidence versions, completion, channel
selection, explicit silence, quiet hours and proactive budgets. Confirmed sends
use canonical history delivery; history failures queue repair without resending.
Live semantic observation remains pending; the scoped PR lifecycle is tracked
on GitHub separately from offline verification.
Focused verification: 263 passed, one existing dependency warning; compilation
of all five changed Python files and whitespace checks passed. The old silent-
skip fixture now restores the original package/module reference after stubbing,
so combined dated-scheduler regressions use the real bot rather than leaked stubs.
PR #234 review correction: pin the captured external channel via the existing
assistant delivery helper's optional `target_channel`; a changed selection fails
before transport, with no fallback. Capture/recheck the all-message history rowid
because wording references include assistant/background messages as well as user
messages. Four real-router/temporary-history cases failed before these repairs.
277 focused tests passed after repair, including confirmed-send history recovery
and backward-compatible unpinned callers. Live semantic observation stays pending.

## Approved extension: daily context inference (2026-10-08)

Contract: `tasks/daily-context-inference-spec.md`, approved by the owner.
First build a bounded, provenance-filtered Athens-day reference for the existing
extractor, with source-version revalidation. Then reuse that extractor before
unknown-context questions, preserving event timestamps, canonical conditional
writes and the existing ledger evaluation budget. Verify the exact cross-channel
Sofia-home/owner-departure lifecycle and conflicting/future/stale/racing cases.
No separate scheduler, state store, schema migration or live-data repair.
Implemented: owner-day sources are bounded (128 records / 32,000 characters),
provenance-filtered and timestamped. The existing extractor consumes them with
canonical context; source version and conditional writes reject intervening changes.
Before a question, one ledger-budgeted resolution per evidence fingerprint can
write only requested volatile flags backed by validated source IDs and a recent
event. It preserves that event's timestamp and cannot replace newer stored state.
Reloading normal eligibility then decides whether a question is still necessary.
Oversized/unavailable day views disable inference, not explicit current reports.
204 focused offline tests passed; live model interpretation remains unverified.
Owner-approved adjacent fix: remove the partner-work-mode lexical fallback that
misattributed the owner's work to a partner staying home. Preserve the existing
semantic extractor, including explicit remote-work statements, across channels.
The regression reproduced false persisted `remote` in Web, Matrix and Telegram.
PR #233 review fixes: recent-hour history scans adjacent source dates and filters
roles, provenance, event time and the rowid boundary before retaining 12 eligible
references. Both findings failed focused regressions before repair. Combined
offline verification passed 288 tests (one existing dependency warning).
Second review: daily limits count eligible Athens-day owner sources only, using
streamed adjacent-date candidates without an intermediate row cap. Extraction
freshness reuses the canonical latest-trusted-user identity, so assistant-only
or external-derived rows cannot discard an explicit report; newer owner evidence
and canonical-state races remain blocking. Six regressions failed before repair.

## Conversational completion and timed shared state (2026-10-08)

Reuse the dated feedback pipeline for clear execution reports at any time of day,
including an explicitly identified past day. Response-window expiry is not an
execution deadline. Supply bounded shared, timestamped owner history and canonical
receipt-matched context-question references to resolve a late report without a
second confirmation. An expired state question is never approval or a reminder
to replay; an exact reply to it permits only semantic execution feedback, not
skip/pause/draft actions. Unknown reply targets stay isolated. Already recorded
completion is acknowledged without rewriting the occurrence or changing pressure.
The flag extractor uses the same bounded shared history, user rows only; completed
return, current location and future departure are distinguished semantically.
History is reference, not proof of current state; no habits, phrase lists, GPS
changes, extra question mechanism, migrations or live data repair are introduced.
Offline tests exercise real isolated history/question/occurrence stores with only
model/transport boundaries replaced. Live semantic accuracy remains to observe.

## Current correction: bounded context re-questions for later routines

PR #232 is merged and its task branch deleted; natural observation is pending.

The common question ledger permits at most three reservations per Athens day.
A later, different routine may re-ask an overlapping unknown context flag after
30 minutes since the previous send (or reservation when no send is recorded).
An explicit declined flag stays suppressed for the rest of that day. Pending
questions, duplicate identities and a routine already questioned that day still
block another reservation; grouped flags cannot bypass the spacing guard.
The same canonical policy is read before question classification and rechecked
atomically at reservation, so a too-early poll does not consume the only semantic
attempt for an unchanged upcoming routine. Fresh evidence prevents questions;
missing/stale GPS never implies home or work. GPS validity, mobile share duration,
routine schedules, runtime controls and live owner state are unchanged.
Offline acceptance includes rabbit 08:00:38 -> market 09:00 at 08:56:22,
expired/fresh GPS, Matrix/Telegram, spacing retry, refusal, restart and daily cap.

## Current narrow correction: completed routines need no context question

The dated occurrence ledger is authoritative for today's completion. The shared
candidate reader excludes closed dated outcomes without changing legacy fields
or pressure. A confirmed delivered question is resolved locally when all its
associated routines have closed outcomes on their individual occurrence dates; normal
activity gates still prevent new proactive messages. Other dates and unresolved
routines are not treated as completed. Existing fingerprint revalidation prevents
completion during wording inference from producing a stale question. Focused
offline tests exercise real temporary storage; no owner database writes,
migrations, runtime controls, phrase lists or full-suite run are in scope.
PR #230 is merged and its task branch deleted; natural wording observation remains
separate from this eligibility defect.
The shared candidate reader accepts an explicit occurrence date for midnight
lookahead. New grouped questions persist a validated routine-to-slot mapping;
old single questions have a known slot, while old groups without that mapping
retain the normal evidence/answer/expiry lifecycle instead of guessing dates.

## Completed implementation: routine conversation wording

PR #229 is merged and its task branch deleted (2026-10-07). This next slice
changes wording context only: the canonical dated feedback result carries its
selected routine name as bounded, provenance-wrapped display reference outside
the trusted action/date JSON. Normal conversation can acknowledge what was
actually recorded in Astakos' singular voice, without inventing current location.
Context-question generation reads up to six shared Web/Telegram/Matrix messages,
with timestamps and bounded content, for conversational wording only. The
separate dependency classifier and all current evidence, freshness, persistence,
approval and scheduling guards remain unchanged. Optional history failure falls
back to the normal evidence-only question prompt. Offline tests exercise real
temporary history/feedback storage and mock only the provider boundary.
Natural model wording remains owner-observed; no live state or runtime changes,
subagents or full-suite rerun belong to this implementation. The owner authorized
commit/PR for this slice; review and merge remain separate follow-up actions.
PR #230 corrections also supply the canonical selected name for ambiguous-date
clarifications (no feedback write) and limit wording history to the current
daily shared session. Tests exclude obsolete sessions while retaining today's
cross-channel dialogue, and require explicit stale/error context without names.

## Completed implementation: Git inspection and approved-result continuation

PR #228 merged on 2026-10-07 after focused verification and Antigravity CLEAN.
Live context-answer interpretation remains naturally observable, not claimed
verified. Git inspection is separate: the classifier previously read token 1 as
the subcommand and misclassified `git -C <directory> log`. The bounded fix skips
only well-formed -C directory pairs and retains approval for unknown globals,
config overrides, mutations, file output and external diff/textconv helpers.
No terminal execution, credentials, live state or runtime changes belong here.
Matrix approval result analysis now captures only a bounded original owner
request and structured agent identity in the pending terminal record. A successful
authenticated execution passes its output to a tool-free stage using that
agent's canonical prompt. It does not re-enter the graph or executor. Shell
errors are evidence, not success; missing/invalid context and provider failures
preserve raw output without guessing another request or reexecuting the tool.
Analysis is recorded in the originating Matrix/Web/Telegram history with external
terminal-output provenance. Nonterminal approval behavior remains unchanged.
Direct Web/Telegram approval callbacks now use the same bounded analysis and
history helper. Web execution and inference run off the event loop; Telegram
retains owner/chat authorization. No graph replay or extra tool execution is
performed. Legacy approvals and unavailable providers preserve the raw result.
Live interpretation and transport observation remain pending owner testing.
No subagents or full-suite reruns for these slices, per owner request.

## Current work: dated routine feedback (2026-10-07)

### Current rollout status — supersedes historical checkpoints below

PR #227 review scope: remove legacy inactive transitions from dated ordinary
single/group/deferred sends, preserving the canonical draft-offer window.
Carry authenticated Telegram inbound event IDs through text/voice and both
history writers so repeated contents remain distinct and replay cannot create
another saved turn. Tighten the test-only downloader hostname assertion.
The separate context-answer follow-up now preserves mixed messages: semantic
classification decides whether other facts/requests remain, rather than parsing
user phrases. The original owner text enters ordinary conversation once, with
one history pair and existing approval gates. Extra current flags are validated
against the same ordinary schema and persisted through the answer's existing
freshness guard. A held stale answer is never retried by background extraction;
its additional conversation/requests still reach the normal agent. Refusal of
the question is distinct from a separate request and allows ordinary extraction
of independently stated facts. Already-closed questions before interpretation
remain ordinary turns. Question generation imports only the canonical Chat
personality section, not its tool instructions, with singular natural address.
Offline routing/persistence regressions pass; live interpretation/wording and
review remain. Git/Terminal read-only classification and approved-result
continuation stay separate. No live storage repair/reset, config change or
runtime restart is part of this follow-up.

PR #228 review corrections separate durable routine reconciliation from live
flag interpretation. Continued mixed replies queue the canonical reconciler
without rerunning live extraction. Missing model continuation metadata preserves
normal conversation but does not expand permitted flag keys. Context batches
compare pre-inference stored versions and write atomically in the existing
routine DB abstraction; conflicting newer state holds the entire old batch.
No schema migration or live data repair is required. Offline tests cover pending
ledger provenance, held batch resolution, rollback, durable shifts, and Matrix
transport reservation during concurrent/replayed mixed events. Enum identifiers
remain invalid question dependencies; only additional explicit enum facts can
be stored by the ordinary bounded schema. Live wording/tool interpretation and
final PR review remain separate verification steps.

RF1-RF6 implementation and owner-approved migration/reset are complete.
All 12 routines now have cooldown 0, confidence 1.0 and zero pressure counters;
the scoped reset preserves pauses, conditions, schedules, receipts and history.
The consistent pre-reset backup is Git-ignored at
C:\astakos_v2\backups\routine-feedback\before-reset-20261007-184017.sqlite3.
Paired Web/Telegram/Matrix dependencies install before workers on normal startup
only when the occurrence schema already exists; startup never migrates or resets.
Routine dispatch is serialized. Reflection remains disabled/unscheduled; its
retained action code is defensively guarded, not activated by this change.
Debug reports active policy only when its handler is installed.
Focused verification passed; no full suite was run. Owner subsequently requested
commit/PR for review on codex/dated-routine-feedback; no merge is authorized.
No Astakos process was detected during reset. Normal launcher startup and natural
observation remain; no hidden duplicate process or live test message was started.
Web exact-reply UI is deferred, not required for semantic dated feedback.
The older paragraphs below are chronological implementation evidence, not the
current backlog. See tasks/todo.md for current remaining work.

Contract: [routine-feedback-spec.md](routine-feedback-spec.md).
Ordered implementation: [routine-feedback-plan.md](routine-feedback-plan.md).
Owner approved the additive occurrence table and preserving existing tasks.
RF1 is complete as an inactive temporary-store foundation (32 focused tests,
atomic projection and durable baseline included); activation and the live
cooldown=0/confidence=1 reset wait for all focused verification gates.
No runtime or production storage changes are part of the foundation slice.
Debug presentation now distinguishes recorded dispatch decisions from condition
checks, stored cooldown from current scheduler cooldown, and staged dated policy
from live behavior. Read-only diagnostics do not activate schema or reset data.
All three channels now have default-inactive saved-turn feedback injection points
and one common outcome-to-graph bridge. Web/Matrix dated persistence is verified
against temporary stores; Telegram adapter ordering is separately offline tested.
Structured draft delegation and Matrix exact-reply propagation are offline
verified; preparation does not complete a routine or approve an external send.
Canonical active-draft protection now rechecks before and after classification,
including a draft created during inference (127 focused tests pass).
Telegram text polling now forwards exact reply IDs without implicit fallback for
invalid/external replies; 115 focused completion/compatibility tests pass.
Telegram voice-note replies now preserve that scope through transcription;
50 isolated completion tests and 39 voice/fast-path/approval compatibility tests
pass (one dependency warning). Unknown explicit replies never reach classification.
Other media, Web reply plumbing and scheduler wiring remain
before rollout, along with final turn arbitration.
RF4 now has an inactive durable per-occurrence dispatch reservation and receipt
coordinator. Timeout holds prevent resend without counting silence; history
repair does not invalidate confirmed delivery. Twelve offline dispatch tests
cover restart/concurrency and receipt persistence. Existing scheduler integration,
canonical eligibility/freshness, held-claim/ledger-write recovery and periodic
reconciliation are still required. No live ledger/schema change was performed.
Confirmed receipt-write errors retain a repair callback and durable staged proof
in the same ledger row. Reopen/restart recovery writes only confirmed receipts;
original delivery time and current pressure evaluation are separate. 144 focused
tests pass (one dependency warning). Durable history repair now retains confirmed
text/channel/time separately from staged receipt cleanup, replaying through a
stable transport-derived conversation ID. Lost history commit acknowledgements
are retryable without duplicate rows. The default confirmed assistant recorder
uses that same bounded ID. Scheduler wiring remains pending; claims without
committed proof remain held, never guessed sent. Latest checkpoint: 149 focused
dispatch/store/policy/external-delivery tests pass, one dependency warning;
compile and diff checks pass. No live migration was performed.
RF4 maintenance now has a default-inactive callback on job_check_routines, before
quiet/mute gates. It recovers confirmed receipt/history writes and reconciles
only routines already represented in the dated ledger. Receipt-repair failure
blocks projection from incomplete evidence; history repair can still progress.
Maintenance failure prevents dispatch on that pass. No additional scheduler,
transport call, schema initialization or live callback installation was added.
Final dispatch eligibility, single/batch/deferred send wiring and removal of
legacy timeout accounting remain prerequisites before installing this callback.
Latest tick checkpoint: 194 focused dispatch/store/policy/transport/scheduler/
inactive-window/context-worker tests pass, one dependency warning; compile and
diff checks pass. The actual runtime still uses legacy dispatch and accounting.
RF4 single ordinary-send wiring now exists behind a default-None sender injection.
It snapshots the ledger revision before generation, rechecks canonical eligibility
and selected channel at reservation, and uses a confirmed DeliveryReceipt rather
than the legacy send wrapper. Confirmed ledger/history failures queue write-only
repair; unknown transport outcomes stay held without fallback. This path stores
bounded prompt scope in the ledger, not the legacy 30-minute pending-timeout pool.
205 focused offline tests pass, one dependency warning; compilation/diff pass.
This is not activation: batches, deferred sends, draft-offer routing, full
freshness arbitration and exclusion of remaining legacy pressure writers still
require their own slices. No live schema, installation, reset or runtime change.
RF4 batch reservation foundation now shares the single-send policy under one
BEGIN IMMEDIATE transaction. Any rejected member rolls back the entire group's
claims and pressure projection; overlapping concurrent groups cannot both win.
Fourteen new temporary-store cases cover completion, existing reservation,
stale revision, backoff, gate failure, invalid dates/identifiers and a real
second-member SQLite abort. 219 focused tests pass, one dependency warning;
compile/diff checks pass. This is only reservation, not batch transport:
atomic shared-receipt staging, group reply correlation and scheduler batch
wiring remain pending. No live initialization, activation or reset performed.
RF4 shared-receipt staging now commits immutable proof for the whole group in
one transaction. Single staging delegates to that same path. Membership is
unique and receipt/channel/instant/occurrence date must represent one send.
Conflicts or a second-member SQLite abort leave no partial proof/history work.
Restart recovery can finish partially projected receipts without transport;
stable message identity yields one conversation row for the shared history.
231 focused tests pass, one dependency warning; compile/diff checks pass.
Group reply correlation now retains all unresolved members only when their
transport proof matches. Exact replies cannot select an unrelated routine;
ambiguous or multi-member answers clarify, and evidence changed during inference
is rejected. Completing one member leaves the others pending. 234 focused
store/selector/freshness/dispatch/policy tests pass, one dependency warning.
The existing scheduler now has a default-disabled batch sender dependency.
It captures member revisions before generation, rechecks canonical group/context/
channel gates at reservation, sends once and stages all confirmed member proofs.
Single and batch sends use the same coordinator; blocked/uncertain delivery never
falls back to legacy transport. Confirmed group history and receipt repairs do
not resend or create legacy 30-minute confirmations. Deferred/draft coordination,
multi-outcome answers and full activation remain open.
295 focused offline tests pass, one dependency warning; compile/diff checks pass.
No schema field, live initialization, runtime installation or reset was added.
Startup missed-slot recovery now also has a default-None dated sender. It uses
the same reservation/receipt repairs and canonical eligibility, with the existing
explicit late grace window rechecked after generation. It creates no legacy
30-minute pending confirmation and never resends a confirmed/uncertain attempt.
Draft coordination, legacy accounting exclusion and full activation remain open.
Latest startup slice: 141 focused worker/scheduler/missed-routine/dispatch tests
pass, one dependency warning; compile and diff checks pass. No full suite run.
Local-draft acceptance now has an inactive dated recorder in the existing exact
offer-consumption transaction. Only a confirmed local-draft result consumes the
offer; dated acknowledgement and consumption roll back together. Completion,
confidence and external-send authorization are not changed. Legacy Athens wall
timestamps are normalized only at this bridge. Saved-turn deferral is verified
for Web/Telegram/Matrix: clears pressure, retains the actual delivery receipt,
asks for timing clarification and does not invent completion or a new schedule.
Draft delivery and full activation still remain open.
Verified: 239 focused ledger/feedback/Web/Matrix/connection tests and 50 separate
Telegram adapter tests pass; one dependency warning, compile/diff checks clean.
Response-window expiry now has a default-None dated callback in both normal and
quiet-hour scheduler paths. It closes only the exact expired pending window,
without legacy pressure/confidence decay or invented delivery evidence. Failed
cleanup remains pending for retry; newer offers and the 30-minute boundary are
protected. Seven focused regressions pass, one dependency warning; compile/diff
checks pass. This is inactive wiring, not live activation or draft-send migration.
Related verification: 279 worker/store/dispatch/connection/missed-routine tests
pass, plus the seven-case expiry guard run; one dependency deprecation warning.
Draft-offer sending now shares the inactive single-occurrence sender. Confirmed
receipt and the separate canonical draft response window commit together;
durable staged draft identity supports receipt/history repair after restart.
Unknown transport never falls back or resends. Late repair retains the receipt
without reopening an expired offer; newer pending context and resolved feedback
are preserved. The existing tick reloads canonical pending state after recovery
when the dated expiry callback is installed. No live callback/schema installation,
external send, reset or Git operation occurred. Full activation remains open.
Draft slice verification: 284 focused worker/store/dispatch/connection tests
pass, one dependency deprecation warning; changed Python files compile.
Unrecorded past-completion checkpoint: a known routine can receive an explicit
owner-reported past completion without a prior delivery row. The common semantic
selector uses the current Athens calendar; only completion may introduce such
a past date. Future dates, unknown IDs, ambiguous reports and stale/untrusted
turns remain rejected or clarified. No receipt is invented and today's occurrence
is unchanged. Verified through real catalogue/history/ledger storage across the
three channel identities: 203 focused selection/freshness/store/policy tests and
16 legacy helper tests pass, dependency warnings only; compile/diff checks pass.
This remains inactive; no live provider interpretation, installation or reset.


Last reconciled with the owner: 2026-10-06 (context clarification completed;
existing verification entries preserved).
PR #224 review corrections are implemented and verified offline; natural
observation and the owner's merge decision remain pending. See the clarification
spec for deadline, wakeup and history-repair limitations.
Only active work is listed here; [todo.md](todo.md) records its status.
Completed evidence remains in Git history and existing specs/runbooks.
The [archived plan](archive/2026-10-02-plan.md) is not an active queue.

## Current feature: time-aware routine context evidence

### Behavioral initiative timing and poll observability (2026-10-07)

Compare legacy host-local timestamps and offset-bearing context/history receipts
as UTC instants in initiative idle/cooldown and reminder gates. Daily delivery
limits still use the host-local calendar; no stored timestamps are rewritten.
Silence only the clarification poll's queue banner and its recent-activity
terminal messages. Keep structured decisions, delivery/error output and ordinary
queue task output. No scheduler intervals or proactive limits change.
Offline regression verification is recorded in todo.md; natural runtime
observation remains pending, without generating test messages to the owner.

Live GPS/answer acknowledgement race is corrected and offline verified (86
focused tests). The exact question may resolve during inference: acknowledge
the existing resolution without rewriting state or rearming dispatch. Natural
post-fix observation remains pending; see routine-context-clarification-spec.md.

Trusted live GPS now refreshes the canonical owner flag timestamp even when
home/away is unchanged. Matrix location decisions use bounded private telemetry
to distinguish sharing without a point, rejected points and completed handlers.
101 focused location/reply/evidence tests pass; no coordinates or identities are
logged. A renewed Element share still needs natural live observation.

PR #225 review corrections cover refused answers racing with GPS resolution and
offload Matrix location telemetry to worker threads, with one terminal write per
accepted point. 82 focused tests plus four refusal/nonresolution safety cases
pass offline; live observation remains pending.

The second PR #225 review is addressed: location completion/reply is durable
before awaited telemetry; partial acknowledgements recheck the exact ledger
resolution. Cancellation/recovery and partial-versus-resolved regressions failed
before the fix; 74 focused tests pass. Natural observation remains pending.

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
Acceptance: one pending request and three/day reservations survive restart and
concurrent callers; refusal suppresses the flag that day, while expiry permits a
different routine to re-ask after the shared 30-minute spacing guard;
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

Actual Web writer checkpoint (2026-10-07): the real return_saved path now returns
the canonical persisted row, including role/channel/content/provenance, required
by the dated handler. ID-only reconstruction had silently made the handler return
no observation; the earlier tests substituted the whole writer and missed this.
Two real-writer regressions failed first; 72 focused completion/upload/mirror/
behavioral-intake tests pass (one dependency warning), including a websocket
failure after successful history commit. Default ID return stays compatible.
This is a readiness fix, not live dated-handler/scheduler installation or reset.

Text-adapter arbitration checkpoint (2026-10-07): the inactive Matrix transport
resolver routes exact recorded routine Replies to dated feedback, not tool
approval; resolved receipt identity retains replay deduplication. Canonical
feedback scope/freshness remains separate from ownership. Lookup failure takes
no action; unrelated targets retain verified-device approval behavior. 225
focused tests pass (two dependency warnings), plus five Web/Matrix and one
separate Telegram context-consumption tests. Production factory wiring,
Web reply UI and live activation/reset remain pending. Media feedback isolation
is covered by the checkpoints below, not a claim of full media command parity.

Matrix audio Reply checkpoint (2026-10-07): media transport uses the same exact
Reply resolver as text and propagates task-local scope through transcription and
the saved turn. Real temporary history/ledger tests preserve yesterday's feedback
without completing today; unrelated targets cannot become implicit answers.
Scope restores on processing failure and absent Reply does not inherit another
target. 101 focused Matrix media/text/turn tests and seven final media lifecycle
cases pass (two dependency warnings); syntax/diff checks pass. The new dated
handler is not wired into production and no live state/reset was changed.

Matrix photo/document Reply safety checkpoint (2026-10-07): two characterization
cases exercise the real media/turn/document paths with temporary history, asset
and routine storage. Even an exact routine Reply with completion-like caption and
analysis leaves the occurrence and question pending. Provenance remains external;
a subsequent genuine owner text response completes the occurrence. 56 focused
media/document/turn tests pass (two dependency warnings). No application change
was necessary; this checkpoint does not prove live model behavior/tool execution.

Web/Telegram asset-feedback checkpoint (2026-10-07): Web /chat with a validated
attachment now stores user-provided-asset provenance before any routine inference,
and excludes both dated and legacy routine feedback for that attachment turn.
Two regressions failed before this guard, including an actual temporary dated
ledger completion. 40 Web completion/upload tests and two focused vision/path
cases pass. Telegram photo/document paths already persist asset provenance;
13 document tests include two real temporary history/ledger isolation cases.
Each run reports one dependency deprecation warning. Syntax/diff checks pass.
No Telegram application change, live activation, reset or Git operation occurred.

Routine-feedback arbitration checkpoint (2026-10-07): changed/expired draft
classification ends the inactive shared handler without a second feedback
mutation. 202 focused tests pass (one dependency warning), including real
temporary history/ledger state across Web, Telegram and Matrix identities.
No approval-path change, live activation, baseline reset or Git operation.

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
- Routine feedback expiry safeguard: incomplete dated wiring cannot fall back
  to legacy 30-minute pressure accounting. Pending cleanup is held for retry.
  Five initial regressions reproduced fallback; ten focused final cases pass
  and 142 existing worker/dispatch cases passed. Paired runtime installation,
  remaining pressure-writer audit and live reset are still pending.

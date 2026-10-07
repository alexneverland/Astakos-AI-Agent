# Implementation plan: dated routine feedback

Owner-approved behavior: [routine-feedback-spec.md](routine-feedback-spec.md).
Status: paired implementation and owner-approved live migration/reset completed
on 2026-10-07. All 12 routines verified at cooldown 0/confidence 1.0 with pressure
counters reset. Existing unrelated verification items are preserved. Natural
observation after normal launcher startup remains; no hidden runtime was started.
Historical checkpoints below describe their state at implementation time and
are superseded by the final rollout checkpoint.

## Approved persistence design (explicit migration completed)

Add one table through memory/routine_db.py's canonical migration abstraction:
routine_occurrences, uniquely identified by (routine_id, occurrence_date).
Store dated delivery status/time, feedback outcome/time and accounting state.
Feedback without a prompt also has an occurrence row. Require a bounded,
validated occurrence date resolved semantically from trusted owner text.

Use this ledger rather than a separate JSON file so an occurrence change and
routine backoff update can commit atomically under one SQLite transaction.
No existing routine, condition, conversation or memory table is removed.
No credentials/configuration change. Live migration/reset received explicit owner
approval and was applied through the canonical memory API on 2026-10-07.

After approving the table's purpose, finalize column-level design during the
first test-driven slice: event dates, reset-baseline state and historical
reconciliation must be represented without rewriting history or resetting
today's delivery deduplication. Do not backfill guessed outcomes from old flags.

## Ordered slices

### RF1 checkpoint (2026-10-07)

Implemented an inactive foundation in services/routine_feedback.py and
memory/routine_feedback.py. Policy recomputation and dated receipts/feedback use
aware Athens dates, a uniqueness constraint and BEGIN IMMEDIATE transactions.
Positive feedback resets pressure without inventing completion; only closed-day
silence/skip batches escalate. Historical correction derives pressure anew.
The additive table initialization is explicit, never an import-time migration.

32 offline tests cover day close, separate streaks, cap, historical correction,
reset-boundary calculation, timezone/DST, invalid/future evidence, receipt
uniqueness, reopen, concurrent independent connections, transaction rollback and
preservation of existing routine rows, independent process writers, atomic
pressure projection/rollback and durable baseline/reopen. Initial policy/store tests each failed
on the missing implementation module before passing. Syntax/diff checks pass.
No production storage, transport, runtime or Chroma access occurred.

RF1 now projects cooldown and separate streaks within the ledger transaction.
Reset instants are stored in baseline_at on real dated occurrence rows; receipts
remain intact. Confidence, pause, last-triggered and notification timestamps are
not changed by this foundation. Initialization remains explicit and inactive.
Next: RF2-RF6 adapter/dispatch/debug/reset work. Do not activate this foundation
or claim the owner's daily routine is fixed based on these isolated tests.

### RF2 protocol checkpoint (2026-10-07)

Extended the existing completion helper/selector with a separate dated feedback
protocol and prompt, without changing existing call sites or draft authorization.
The model receives an aware Athens clock and caller-supplied allowed occurrence
dates. Strict validation preserves past completion, rejects future/unknown dates,
unknown IDs, duplicate JSON keys and untrusted input. Ambiguity has a separate
clarify result; deferral does not create a guessed schedule.

73 focused offline tests pass across old completion helpers and new dated
selection/policy/ledger. A real temporary-store test verifies yesterday's
completion does not complete today's delivered occurrence or change confidence.
Only provider output was injected: natural model interpretation is not live
verified. RF2 remains incomplete: bounded correlated context, post-inference
freshness and atomic application/clarification orchestration must be implemented
before adapters use this protocol. No production migration or reset performed.

### RF2 freshness/application checkpoint (2026-10-07)

The ledger now exposes a consistent routine/evidence revision and compares it
inside BEGIN IMMEDIATE immediately before conditional feedback persistence.
The shared inactive process_feedback_turn captures revisions before inference,
revalidates the protocol, rechecks caller-supplied shared-history/correlation
freshness after inference and again under the write lock. No model call holds
the database lock. Stale or failed classification leaves evidence unchanged.

The selector accepts a bounded exact pending-question record (routine, date,
event ID and question text), structurally tied to the eligible occurrence.
RF3 callers must authenticate/reload that correlation and provide a real history
freshness loader, never a cached boolean. This foundation is not channel-wired.
Deferral records engagement and requests clarification without making a schedule;
ambiguous selection writes nothing. Permanent pause is explicitly returned as
pause_requested, NOT reported as applied; atomic existing pause-path integration
is still required before RF2 completion/activation. Shared-history changes after
the final check must remain governed by the canonical adapter concurrency path.

87 related offline tests pass, including real-store competing feedback during
classification, changed routine configuration, changed history, acknowledgement,
deferral, clarification and untrusted-input safety. Provider inference is mocked.
No live migration, reset, external send or runtime operation was performed.

### RF2 permanent-pause checkpoint (2026-10-07)

Permanent pause now uses one transaction-neutral mutation in
memory/routine_pause.py, reused by the existing routine_db API and dated ledger.
Its existing semantics are preserved: paused_indefinitely=1 blocks dispatch;
the lifecycle state is normalized independently. Feedback, pause metadata and
pressure projection commit or roll back together under the freshness guard.
A completed occurrence stays complete when a later permanent pause is requested.
Confidence, last-triggered and last-notified values are not overwritten.
process_feedback_turn reports applied only after that commit, not pause_requested.

90 related tests plus 2 existing pause regressions pass offline. The original
pause wrapper keeps its commit, error translation and telemetry boundaries.
RF2's inactive common service is complete; RF3 must still supply authenticated
pending correlation and real cross-channel history freshness loaders, preserve
draft/approval ordering, and wire acknowledgements/clarification responses.
Live inference, channel activation and production reset remain unverified/deferred.

### RF3 structured drafts and Matrix reply checkpoint (2026-10-07)

The injectable shared handler now optionally resolves structured draft offers
through the existing semantic completion selector, accepting only its draft
action. It reloads pending offers and shared owner history after inference,
rejects changed/expired offers and grants local preparation only. No occurrence
feedback is written and no pending offer is consumed by classification.
The loader contract excludes offers while another local draft is active; wiring
that production loader remains part of the rollout gate.

Web/Telegram injection points now carry the existing deferred draft-offer result
to the graph, retaining success-only consumption. Telegram sets only the existing
local-draft authorization; critical sends keep their separate approval path.
Matrix already consumes that deferred result and now propagates its existing
transport-authenticated reply scope into the dated handler. Exact historical
receipt replies resolve that occurrence, never today's implicit question.
Do not infer reply identity from quoted prose, user JSON or arbitrary metadata.
Other channels' exact reply plumbing remains unverified/unwired.

Verified 175 focused ledger/history/Matrix/Web/completion tests and 33 isolated
Telegram completion tests. New common draft/reply APIs failed first (8 tests),
Web draft routing failed first (2), Matrix lost reply identity failed first (1),
and Telegram lacked local-draft authorization failed first (1). An additional
test reproduced offer expiry during model inference and now passes after a final
time check. One dependency deprecation warning remains; syntax/diff checks pass.
No full suite, live model call, transport send, migration, activation or reset.

Ruling: continue the existing dirty owner-approved checkout and tracked task
ledger instead of introducing a worktree/scratch ledger or committing mid-task.
This preserves the accumulated work and follows the project's explicit Git and
focused-test authorization boundaries. The whole feature is not yet complete.

Remaining RF3 gates: canonical production draft loader/active-draft exclusion,
other transport reply correlation, historical dates without ledger rows and
cross-database turn arbitration. RF4 scheduler/receipts and RF6 reset are pending.

### RF3 injectable channel/context bridge checkpoint (2026-10-07)

PersistedRoutineFeedbackHandler now composes the real catalog, history freshness,
semantic selection and ledger transaction, then supplies structured graph context.
Only the recorded action/date enter trusted context; routine names and owner prose
are not promoted into system instructions. Historical completion stays historical,
acknowledgement is not completion, and deferral/ambiguity request clarification.
Stale/error results contain no claimed action and are not tool approvals.

Web and Telegram now expose explicit, default-inactive callback injection points,
like Matrix. Selecting a callback replaces the legacy mutation block completely,
even for none/error results. No fall-through can mark today after dated handling.
Normal input/reply history is still written once. Production factories/defaults
remain unchanged; there is no live ledger initialization, migration or reset.

174 focused ledger/history/Matrix/Web/mirror tests pass. The actual Matrix and
authenticated Web adapters were exercised with real temporary routine/history
stores: yesterday becomes complete while today's receipt remains unanswered.
The shared bridge is tested for all three channel envelopes and seven actions;
newer owner messages/provider errors cannot yield false completion context.
32 Telegram completion tests and 20 fast-path/transport tests pass separately to
isolate the heavy Telegram dependency stubs. The two Telegram injection tests
first failed because the callback was never invoked; the new common bridge's
28 initial tests first failed on its missing implementation. A Web test-helper
name error was corrected before verification; it is not behavioral red evidence.

RF3 is not fully complete: structured pending draft-offer delegation, exact
transport reply correlation, historical dates without ledger rows and final
adapter turn arbitration remain pending. Do not configure these callbacks in
production until those boundaries and RF4 are verified. Existing draft/approval
regressions pass on the default path, not on an activated dated draft-offer flow.
No full suite or live provider/transport test was run.

### RF3 shared-history checkpoint (2026-10-07)

Added a canonical cross-channel latest trusted user-row lookup and an inactive
feedback freshness guard. It reloads insertion order rather than client clocks
or a capped page, checks Athens day rollover, and requires a caller-provided
authenticated pending-correlation check. Storage errors fail closed. Adapters
must persist the incoming owner message first and pass that row's actual ID;
sampling a later maximum would silently bless a competing message.

106 related tests pass, including real conversation and routine stores where
the classifier inserts a newer Web, Telegram or Matrix owner message. No stale
completion or pressure update is committed. Current acknowledgement persists;
external-derived rows and assistant notifications are not owner feedback.
The 12 new history tests failed before implementation. The history suite also
passes (32 tests including those 12). No production initialization occurred.

RF3 is still incomplete: exact delivered-question correlation and channel wiring
remain pending. The guard is a reload check, not cross-database serialization;
adapter turn arbitration must also cover arrivals after the final check. RF4
receipt recording and scheduler gates must be ready before live activation.

### RF3 delivered-question checkpoint (2026-10-07)

The inactive ledger now stores optional question_text and delivery_channel with
the first confirmed receipt in the same transaction. Both nullable columns are
added only by explicit initialize; no production migration has run. Older
receipts without actual question metadata do not acquire invented context.
The scheduler must omit these fields for Messenger draft offers/tool approvals
and validate the bounded question metadata before sending during RF4 wiring.

pending_question resolves authenticated channel/event replies exactly, including
past occurrences. Uncorrelated context requires exactly one unanswered delivery
from today inside the existing 30-minute response window. Ambiguity yields no
implicit question. Window expiry performs no writes and does not count silence.
Recorded engagement/completion closes this short-answer context. Duplicate
receipt recording cannot replace the original question or channel.

process_stored_feedback_turn now supplies real persisted correlation and shared
history freshness to the common service. It reloads correlation after inference
and under the guarded ledger transaction; explicit replies cannot target another
routine. Unknown replies pass through without invoking the classifier. A test
first reproduced incorrect persistence to another routine before constraining
the explicit-reply candidate pool. All 121 related offline tests now pass,
including yesterday's exact reply completion preserving today's occurrence.

This completes the storage-backed adapter preparation, not RF3 channel parity.
Existing live handlers still use the old flow. Next: thin adapter ordering and
RF4 scheduler receipt/dedup wiring, followed by the explicit live migration gate.
No live reset, send, credentials, runtime or Chroma operation was performed.

### RF3 Matrix persisted-turn checkpoint (2026-10-07)

MatrixTurnService now persists the inbound owner row before routine inference.
The legacy callback remains supported, while an explicit alternative persisted
callback receives the saved row for the dated common service. Configuring both
callbacks is rejected: one turn cannot execute two routine mutation paths.
External-derived asset turns bypass routine confirmation. Command and existing
context-question ordering remain unchanged; Messenger draft offers still follow
their existing deferred authorization path, and tool approvals are untouched.

Temporary-store integration tests exercise MatrixTurnService through
process_stored_feedback_turn into the real routine ledger. Yesterday's completion
does not complete today's delivered occurrence, and a newer Web message during
inference prevents the stale commit. Conversation-save failure never reaches the
routine callback. The new ordering test first failed on the absent owner row.

155 focused tests pass across Matrix turns/completion, dated policy/selection,
shared-history freshness and real ledger storage. Matrix graph-turn tests now
replace the live context-question boundary rather than reading the owner's JSON.
The production Matrix factory still selects the legacy callback; the dated
callback is opt-in only until scheduler wiring and the approved migration gate.
No live migration, reset, test transport send or explicit runtime operation.

### RF3 Web history-order checkpoint (2026-10-07)

The authenticated Web text path now persists its original user message before
routine-completion inference. Normal graph responses and the four asset/draft
intercepts reuse the same saved identity. Failed user persistence returns 503
before routine mutation; authentication/firewall rejection still precedes storage.
Context-question handling retains its existing separate path and is not covered
by this ordering change. No new dated-feedback handler is activated in Web yet.

45 focused offline Web completion/mirror tests pass, including real isolated
history rows observed during classification, no duplicate intercepted input,
failure containment and rejected-input boundaries. Both new ordering/failure
regressions failed before the implementation. Existing mirror mocks were aligned
with the real saved-message contract (id plus rowid); their asset/draft tests pass.
No full suite, live ledger migration/reset, outbound send or explicit runtime
operation was performed.

### RF3 Telegram history-order checkpoint (2026-10-07)

Telegram now persists input before routine-completion inference/mutation and
retains that actual rowid for background work. A missing/invalid saved identity
stops the turn before routine changes. The normal reply and preview/clear/send
intercepts do not insert the user again. Context construction excludes only the
current rowid, not matching words: identical older Web/Telegram messages remain.
Context-question handling retains its separate existing path, unchanged.

Three reproduction tests failed before implementation. 30 focused Telegram
completion tests now pass, including real temporary history, actual handler to
context to graph continuity, saved-input failure, shared Web history and the
three draft intercepts. Confirm-send only queues the existing approval; it does
not execute the pipeline. An additional 20 fast-path/transport-safety tests pass
in a separate run to isolate the completion suite's heavy-module stubs. Existing
fast-path mocks now return a real-shaped row identity and accept the context's
new keyword; context questions, routine candidates and assets are mocked there
to avoid live files/model work. Syntax/diff checks pass.

No dated handler, live ledger migration/reset, explicit runtime operation or
outbound test send was activated. RF3 remains open: shared candidate/context
composition and Web/Telegram dated-handler wiring, including draft-only
delegation, are next; RF4 follows with scheduler receipts and day-close accounting.

- [x] RF1: temporary-store occurrence ledger and deterministic policy.
  Acceptance: one row per occurrence, success-only delivery, atomic/idempotent
  feedback, Athens day-close accounting and separate three-event streaks;
  0 -> 20 -> 40 -> 72 with no confidence penalty. Late correction recomputes
  pressure; repeated ticks/feedback cannot escalate twice. Preserve uncertainty.
  Files: memory/routine_db.py, services/routine_feedback.py, focused new tests.
  Verify: temporary SQLite fixtures, day boundaries/DST, restart and concurrent
  writers. Failing tests before implementation; never import production storage
  unisolated during tests.
- [x] RF2: semantic dated feedback through one inactive common service.
  Acceptance: complete/acknowledge/skip/pause semantics; early, late same-day
  and explicit past-day reports update the correct occurrence. Validate date/ID,
  pending correlation, trusted origin and freshness after model inference.
  Unclear dates/deferral timing request clarification, never fabricated schedules.
  Files: services/routine_completion_helper.py, services/routine_completion_selector.py,
  prompts/routine_completion_selector.md, dedicated selector/service tests.
- [ ] Checkpoint: review persisted RF1/RF2 outcomes before channel activation.
- [x] RF3 draft safety checkpoint: reuse the canonical active-draft resolver
  before classification and inside post-inference freshness checks. Existing
  content is preserved when a draft is already active or becomes active during
  inference; no offer consumption, feedback write or send is authorized.
  Verified with actual temporary draft files and ledger/history: six cases
  reproduced the missing guard, then 127 focused tests passed (one dependency
  deprecation warning). This does not activate the new handler or serialize
  cross-process draft creation after the final freshness check.
- [x] RF3: wire Web, Telegram and Matrix through the same feedback service.
  Telegram text-reply checkpoint: polling carries the exact same-chat transport
  message ID to both canonical context-question and dated-feedback handlers.
  Invalid/external replies remain explicit-but-unusable rather than falling back
  to another implicit question. No reply leaves existing implicit behavior intact.
  Real polling with synthetic updates, temporary history and the real ledger
  verifies yesterday's exact reply preserves today's receipt/dispatch state.
  The missing transport propagation failed first, followed by the external-reply
  safeguard. 46 isolated Telegram completion tests and 69 separate history,
  fast-path, approval-auth, external-transport and clarification-reply tests pass
  (one dependency deprecation warning). Compile and diff checks passed.
  Voice/media reply metadata and Web reply UI are not verified by this slice;
  no live ledger migration/activation/reset or notification occurred.
  Subsequent Telegram voice-note checkpoint: polling and transcription preserve
  the same canonical reply scope into the saved-turn handler. Real temporary
  ledger/history tests cover yesterday, today, unknown and malformed replies;
  unknown explicit scope never reaches classification. Three cases failed before
  the forwarding fix. 50 isolated completion tests and 39 separate voice-input,
  transcription, fast-path and approval-auth tests pass (one dependency warning).
  Existing non-reply voice calls retain their call contract; audio stays temporary.
  Other media and Web reply UI remain outside this checkpoint. No live activation,
  migration, reset or real outbound message occurred.
  Shared catalog checkpoint: canonical names, recorded occurrence dates and
  revisions now load on one read transaction. The injectable catalog entry point
  carries these revisions through classification and locked persistence, so a
  rename/configuration change between catalog loading and inference is rejected.
  Focused ledger/policy/selection/freshness verification: 110 passed, one dependency
  deprecation warning. Tests use temporary storage and injected model boundaries;
  this is not proof of live natural-language or scheduler behavior.
  No production activation or schema migration occurred. Historical dates without
  a recorded occurrence remain unsupported by this catalog (no invented lookback);
  resolve them against canonical schedule semantics before claiming full parity.
  Acceptance: no channel/pending-window differences; acknowledgement not
  completion; historical completion never marks today's routine complete.
  Preserve Messenger draft authorization and external approval boundaries.
  Files: api/server.py, clients/telegram_bot.py, services/matrix_routine_completion.py,
  focused adapter tests (split adapter wiring into smaller changes as necessary).
- [x] RF4: canonical scheduler delivery gates and end-of-day reconciliation.
  Inactive dispatch checkpoint: one durable dispatch_started_at reservation on
  each dated ledger row prevents concurrent/restarted sends even at zero cooldown.
  It is created only after revision, canonical caller eligibility, dated feedback
  and derived backoff checks. Claims are not receipts and never count as silence.
  Confirmed delivery is retained separately from history repair; a timeout stays
  held rather than being retried or guessed successful. No network work runs
  under the SQLite write transaction. No automatic claim expiry/release exists.
  Seven missing-coordinator regressions failed before implementation; 12 dispatch
  tests now cover real ledger persistence, independent concurrent connections,
  reentrant sends, restart, history failure through the actual delivery boundary,
  past/future slots, late backoff expiry and acknowledgement deduplication.
  Final focused gate: 134 dispatch/store/policy/external-delivery tests passed
  with one dependency deprecation warning; compilation and diff checks passed.
  This is NOT scheduler activation: canonical eligibility wiring, final freshness
  arbitration, transport/ledger repair recovery and existing-tick reconciliation
  remain required before rollout. A ledger failure after transport keeps the claim
  held; receipt recovery must be completed before activation. The added nullable
  reservation column is initialized only in temporary tests; live schema approval
  must cover it explicitly with the other additive ledger fields.
  Receipt-write repair checkpoint: an actual temporary SQLite abort now yields
  recording_pending with the confirmed receipt and an in-process write-only
  repair callback. Repeated repair never contacts transport and keeps the original
  delivered_at; reconciliation uses the current instant so newer completion
  evidence remains valid. Future delivery instants are rejected before mutation.
  Malformed external receipt IDs/channels are uncertain, never offered as proof.
  Two repair regressions and four proof-validation cases failed before their fixes.
  Final focused verification: 140 dispatch/store/policy/external-delivery tests
  pass, one dependency warning; Python compilation and diff checks pass.
  This does not durably queue repair payloads across a full process restart: the
  claim remains held but receipt recovery still needs scheduler/history integration.
  Neither this callback nor a timeout grants permission to release/resend a claim.
  Durable ledger-repair checkpoint: four nullable staged-proof fields in the same
  occurrence row now retain receipt ID, original delivery instant, actual channel
  and optional bounded question before canonical receipt projection. An existing
  dispatch claim is mandatory; another receipt cannot replace committed proof.
  Reopened stores repair only the original receipt, including after a channel
  change or later completion, with no transport argument or resend path.
  Proof cleanup and canonical receipt/projection commit atomically; repeated
  SQLite failures preserve staged work. Two restart regressions failed first;
  144 focused dispatch/store/policy/external-delivery tests now pass, one dependency
  warning. Compilation and diff checks pass. No live storage was touched.
  Live migration approval must include these four additive fields. A crash or
  storage outage before proof staging commits still leaves an ambiguous held
  claim, not recoverable confirmed evidence; never guess or automatically resend.
  Durable chat-history checkpoint: nullable pending_history_json retains the
  original confirmed text/channel/time when AssistantHistoryError occurs. It
  commits alongside staged transport proof, survives canonical receipt cleanup,
  and clears only after history recording acknowledges the exact payload.
  Restart recovery accepts an injected canonical recorder, not a transport;
  stable bounded transport-derived IDs make uncertain commits idempotent.
  The default confirmed assistant recorder shares this identity. Custom
  recorders supplied at scheduler integration must honor the same stable ID.
  Two new restart/negative tests failed before implementation. Temporary-store
  coverage includes concurrent receipt/history failures and long receipt IDs.
  Latest verification: 149 focused dispatch/store/policy/external-delivery tests
  pass, one dependency warning; compilation and diff checks pass.
  Live migration approval must also include pending_history_json; no live
  initialization or migration occurred. Scheduler tick integration and final
  freshness arbitration remain activation gates; held claims are not released.
  Existing-tick maintenance checkpoint: job_check_routines now offers one
  default-None callback before quiet/mute/pause gates. An explicitly injected
  maintain_dated_feedback call repairs committed receipts, independently repairs
  history, and projects closed-day pressure for existing ledger routine IDs.
  Receipt failure blocks projection of incomplete evidence; any maintenance
  failure stops that dispatch pass. Logs expose only phase/error class and
  structured routine IDs, not receipt IDs or private reminder content.
  Nine focused tests failed before this boundary existed. Real temporary-store
  integration tests exercise the actual shared Matrix/Telegram scheduler entry
  point across Athens midnight with no transport calls; three delivered days
  count only after the last day closes, leaving confidence unchanged.
  No new job, interval, runtime startup/restart or live schema initialization.
  Callback installation MUST wait for final eligibility, single/batch/deferred
  send integration and exclusion of the legacy 30-minute timeout pressure writer.
  A pre-existing inactive-window test used a Telegram-only send mock despite
  Matrix channel selection; it failed in isolation too. Its two shared test
  helpers now mock the channel-neutral delivery boundary, avoiding real sends
  and history while retaining real routine eligibility/temporary-store checks.
  Verification: 194 focused dispatch/store/policy/transport/scheduler/inactive-
  window/context-worker tests pass, one dependency warning; compile/diff pass.
  Single ordinary-send checkpoint: DatedRoutineSender is explicitly injectable
  into job_check_routines and defaults to None. Ledger revision is captured before
  generation; canonical completion/config/context gates, current slot, selected
  channel and proactive budget are rechecked at reservation. An injected actual
  confirmed-delivery boundary retains transport proof separately from history.
  SQLite receipt failure queues write-only recovery; uncertain sends stay held.
  Ordinary dated prompts do not enter the legacy pending-confirmation timeout
  pool. Draft offers and context notes remain on their existing separate paths;
  no partial rollout is installed in production. Long text is delivered unchanged
  but omitted from bounded question scope rather than truncated or reinterpreted.
  Eight initial regressions failed on the absent sender. Eleven new real
  scheduler/temporary-ledger cases cover both channels, history failure, an actual
  SQLite abort followed by receipt-only repair, unknown delivery, channel switch,
  completion and ledger acknowledgement during generation. 205 focused tests
  pass, one dependency warning; compile/diff checks pass. Remaining activation
  gates: batch/deferred/draft coordination, complete evidence/turn arbitration,
  exclusion of all remaining legacy response-pressure writers, explicit schema
  approval and recoverable baseline reset. No live storage or transport used.
  Batch reservation checkpoint: claim_batch_dispatch reserves a whole group on
  one write transaction using the same canonical per-member policy as single
  dispatch. Rejection or exception rolls back every claim and pressure update.
  A claim remains only a reservation, not delivery or unanswered evidence.
  Nine initial regressions failed before the method existed. Fourteen new real
  temporary-store tests cover stale/complete/reserved/backoff members, a false
  canonical group gate, invalid structured input, past/future dates, reopen,
  overlapping independent concurrent connections and an actual SQLite abort on
  the second member. Single-send revision-before-eligibility semantics remain
  intact. 219 focused dispatch/store/policy/transport/scheduler tests pass,
  one dependency warning; compile/diff checks pass. No schema field, runtime
  callback, transport or migration added. This does NOT finish batch delivery:
  atomic shared-receipt staging/recovery, grouped question/reply provenance and
  scheduler generation-to-send wiring must be covered before activation.
  Shared-receipt staging checkpoint: stage_deliveries atomically retains one
  confirmed transport receipt/channel/instant/date across unique reserved members.
  Single stage_delivery delegates to it, preserving the existing proof checks.
  Conflicting or unreserved members roll back the entire proof/history write;
  SQLite failure retains claims, not permission to resend. Existing maintenance
  recovers committed staged proofs after reopen even when one member's canonical
  receipt projection fails. Shared history uses its stable transport identity,
  so repeated per-member repair creates one conversation row, not duplicates.
  Eight initial regressions failed before the group stage API existed. Twelve
  new temporary-store cases cover Matrix/Telegram, reopen/idempotency, real
  second-member stage/projection aborts, immutable receipt/channel/time identity,
  empty/duplicate membership and unreserved/conflicting members. 231 focused
  tests pass, one dependency warning; compile/diff checks pass. No new field,
  runtime callback, live schema initialization, outbound send or reset occurred.
  This verifies recording/recovery only, not full batch delivery.
  Group reply checkpoint: matching receipt/channel/date/instant/question proves
  one grouped message; separate deliveries cannot become one implicit question.
  Exact replies restrict semantic selection to unresolved group members. One
  clearly identified completion affects only that member; ambiguity clarifies,
  unrelated IDs are rejected and changed group evidence during inference is
  stale. Resolving one member leaves the others pending. Single-question callers
  retain their original protocol. Multi-member outcomes in one answer remain
  unsupported by the one-selection protocol and require clarification, not a
  guessed first member. Eight initial regressions failed before implementation;
  234 focused store/selector/freshness/dispatch/policy tests now pass with one
  dependency warning. Compile/diff checks pass. No activation or live data work.
  Batch dispatch checkpoint: DatedRoutineSender.send_batch and single send now
  share one coordinator. All members reserve before one transport call; confirmed
  proofs stage atomically before per-member projection. A projection failure
  retains staged work for recovery, not permission to resend. History repairs
  share a stable message identity. The existing scheduler captures revisions
  before generation and rechecks canonical group/context/channel eligibility at
  reservation. Confirmed batches record each member without legacy 30-minute
  pending confirmations; unknown or blocked sends never fall back to old transport.
  Six initial coordinator and eight scheduler cases failed before the new paths
  existed. Real temporary stores cover Matrix/Telegram, history/transport/ledger
  failures, reopen, duplicate ticks and changed evidence/completion/channel during
  generation. Batch dependency remains None by default; deferred/draft coordination,
  multi-outcome answers, full activation and the baseline reset remain pending.
  Verified: 295 focused dispatch/store/policy/selector/freshness/scheduler/external
  delivery/startup tests pass with one dependency deprecation warning; changed
  Python files compile and diff checks pass. No real outbound delivery occurred.
  Startup recovery checkpoint: default-None dated deferred sender captures state
  before generation and rechecks canonical gates within the existing explicit
  late grace window. Confirmed/uncertain attempts do not fall back to legacy
  delivery; confirmed receipts survive ledger/history failures through repairs.
  No old pending timeout is registered. Draft coordination and activation remain
  pending. Sixteen Matrix/Telegram regression cases failed before implementation
  and now pass using real temporary ledger/history stores and injected transport.
  Combined startup-slice verification: 141 focused worker/scheduler/missed-routine/
  dispatch tests pass, one dependency warning; compile/diff checks pass. Legacy
  tests mock the assistant delivery boundary rather than assuming the PC's
  selected channel is Telegram. No full suite, live activation or reset.
  Draft acceptance checkpoint: the existing exact-offer consumer has a default-
  None dated feedback callback within its SQLite transaction. After verified local
  draft creation it records acknowledgement, never completion or fake delivery.
  Invalid/replaced/expired offers, newer feedback and completed occurrences cannot
  be consumed through this callback. A later consumption write failure rolls back
  feedback too. Naive canonical legacy timestamps use Athens only at this bridge.
  Saved-turn deferral is verified in Web/Telegram/Matrix: retains its real receipt,
  clears pressure and requests timing clarification without changing schedule,
  pause, confidence or completion. Draft sending exclusion and activation
  remain pending; the new callback is not installed in any live process.
  Verified: 239 focused store/policy/selector/freshness/connection/Web/Matrix tests
  and 50 separate Telegram adapter tests pass. One dependency deprecation warning;
  compile/diff checks pass. No full suite or production data operation.
  Response-window expiry checkpoint: both scheduler branches share a default-
  None dated callback. Exact expired pending state is closed transactionally,
  without touching ledger evidence, pressure or confidence. Failed cleanup stays
  pending for retry; a replaced offer cannot be removed and missing delivery
  proof remains missing. Athens legacy wall times and aware timestamps compare
  as UTC instants. Seven focused regressions pass, one dependency warning;
  compile/diff checks pass. Draft-send migration and live installation remain
  separate gates; no full suite, live schema change or baseline reset occurred.
  Related worker/store/dispatch/connection/missed-routine check: 279 tests pass,
  plus the seven-case expiry guard run, with one dependency warning.
  Draft dispatch checkpoint: single sender passes a bounded canonical draft event
  separately from ordinary question scope. Staged proof retains staged_draft_event
  in the explicitly initialized additive ledger; old history payloads remain
  compatible. Receipt recording and pending offer creation share a transaction,
  so pending write failure retains staged proof rather than permission to resend.
  Recovery preserves the original receipt instant, never replaces newer offers
  or reopens expired/resolved offers. History repair retains the same transport
  identity and separate draft scope. Existing dated ticks refresh canonical
  pending state after repair; queued receipt repair refreshes it immediately.
  This remains default-inactive: no production initialization, callback install,
  live delivery, baseline reset or Git operation occurred.
  Verification: 284 focused worker/store/dispatch/connection tests pass, one
  dependency deprecation warning; changed Python files compile.
  Historical completion checkpoint: known catalogue dates no longer exclude an
  explicitly reported, unrecorded past completion. The semantic selector must
  ground its date in the trusted current message and authoritative Athens clock;
  ambiguous dates clarify. Strict structured validation still rejects unknown
  routines, future/noncanonical dates and past non-completion actions. The shared
  history/ledger freshness guards are unchanged. No historical delivery is
  manufactured, and today's receipt/outcome is preserved. Four tests failed
  first; real temporary catalogue/history/ledger tests now cover all three
  channel identities. 203 focused tests and 16 legacy helper tests pass, with
  dependency warnings only; compile/diff checks pass. Live model interpretation,
  final turn arbitration and full activation/reset remain separate gates.
  Acceptance: zero-hour cooldown does not cause same-occurrence duplicates;
  successful delivery persists even if chat history repair fails. Transport
  ambiguity is held, not guessed successful. Response-window expiry closes only
  conversation pending state, not the entire day's opportunity to respond.
  Reconcile on existing scheduler ticks, recover after offline/restart without
  sending obsolete reminders. Separate refusal and unanswered accounting.
  Verify: injected transport, clocks and temporary ledger; no live outbound calls.
- [x] RF5: accurate diagnostics and scoped obsolete-path exclusion.
  Debug checkpoint: final recorded decisions no longer get replaced by a later
  condition pass. Condition checks retain their own timestamps. Stored cooldown
  zero is preserved and shown separately from the current legacy scheduler's
  clamped value; elapsed time compares timestamp instants, with invalid values
  reported as unknown rather than expired. Ledger diagnostics use read-only
  storage, never initialize it, and label derived pressure as staged policy until
  RF3/RF4 activation. UI shows dated evidence, separate streaks, baseline and
  backoff deadline without exposing raw receipts or question text. Proven-dead
  legacy cleanup and post-activation debug parity remain pending.
  Verified: 72 focused dashboard/ledger/browser tests passed, one dependency
  deprecation warning; compile and diff checks passed. Actual dashboard rendered
  in isolated Chrome at 320/768/1024/1440px using intercepted synthetic responses
  with no page errors. No live runtime endpoint, credentials or outbound channel
  were used. This does not prove RF3/RF4 live behavior or complete the reset.
  Acceptance: final decision survives later condition-success logs; show actual
  backoff/streak/occurrence status. Remove legacy cooldown functions only after
  reference checks, including tools and dynamic registrations. No unrelated cleanup.
- [x] RF6: recoverable, owner-authorized fresh baseline and verification.
  Acceptance: snapshot scoped routine fields and ledger baseline through canonical
  abstraction, set cooldown=0/confidence=1.0 and reset pressure. Preserve paused/
  muted states, schedule, conditions, completed dates and delivered receipts.
  No old ledger failures may immediately reapply pressure after baseline reset.
  Verify offline first, then live scoped readback; do not raw-SQL live databases.

## Verification commands

### Text-adapter arbitration checkpoint (2026-10-07)

Matrix transport accepts an optional default-None routine-target resolver. The
shared saved-turn handler exposes exact channel/confirmed-question receipt
ownership through the canonical ledger; resolved receipts retain routing identity
so replay does not become tool approval. Ownership never grants completion or
execution: the saved-turn selector, pending scope and freshness guards still
decide feedback. Registered routine Replies bypass tool-approval interpretation
and remove only Matrix's protocol quote block. Failed lookup leaves the event
unprocessed/retryable with no approval or graph action. Unmatched targets retain
the existing verified-device approval path. Production factory is not wired yet.

225 focused transport/turn/store/approval tests pass, two dependency warnings;
five focused Web/Matrix context/draft-consumption tests and one separate Telegram
context-arbitration test pass. Consumed context answers persist once and bypass
dated/legacy feedback and graph in all three text adapters. Syntax/diff checks
pass. Remaining RF3 gates include other media reply metadata, Web reply UI and
paired activation of the transport resolver with the dated handler. No full
suite, live schema initialization, runtime restart, reset or Git operation.

### Matrix audio Reply checkpoint (2026-10-07)

Media transport now shares text's exact Reply resolver after attachment trust
validation. The task-local scope reaches audio transcription and the saved Matrix
turn, restoring the previous scope even on processing failure. No Reply explicitly
uses an empty scope instead of inheriting another turn's target. This adds no
capability to approve tools or interpret image/document content as routine feedback.

Two persisted-outcome regressions first failed by completing today instead of
yesterday (or completing today for an unrelated target). After the fix, 101 focused
Matrix media/download/text/turn tests pass, followed by seven final media lifecycle
tests covering exception restoration too; two dependency deprecation warnings.
Compile/diff checks pass. Remaining media parity review, Web reply plumbing,
paired production activation and reset remain separate gates. No full suite,
live database initialization, runtime restart or Git operation was performed.

### Matrix photo/document provenance checkpoint (2026-10-07)

Real media transport, image question and document service paths preserve asset
provenance even for an exact routine Reply. Completion-like caption/analysis
does not complete the occurrence or consume its pending question. The archive
prompt remains staged once; subsequent genuine owner text can complete the routine.
Tests inspect real temporary history, routine ledger and pending assets rather
than only mocked handler calls. No application behavior was changed here.

56 focused media/document/turn cases pass with two dependency deprecation
warnings. The first run exposed only a test expectation type error (set versus
list), not an application defect. This characterizes feedback isolation, not
live model/tool execution. Web/Telegram media parity, Web reply plumbing, paired
activation and reset remain separate gates.

### Web/Telegram asset-feedback checkpoint (2026-10-07)

The validated Web /chat attachment path previously attempted routine inference
before constructing asset provenance. An attachment caption could therefore
complete a pending routine through either legacy or injected dated feedback.
The first saved row now carries user-provided-asset provenance, and this turn
bypasses both routine-feedback paths while normal asset analysis continues.
Two reproductions failed before repair, including actual temporary ledger state.
40 focused Web completion/upload tests pass, plus two vision/path-boundary cases.

Telegram photo/document handlers required no application change. Two
characterization cases run the real handlers with temporary persisted history
and ledger storage; asset rows cannot become dated owner feedback. All 13
document tests pass. The initial Telegram test failure was fixture aliasing of
the history writer, not an application defect. Each run has one dependency
deprecation warning; syntax/diff checks pass. No full suite, live database/reset,
runtime change or Git operation was performed. Web reply UI, paired activation
and scheduler/legacy-writer/reset gates remain pending. This verifies routine
feedback isolation, not live model/tool execution or all media command parity.

### Actual Web history-writer checkpoint (2026-10-07)

The actual Web writer previously stripped its saved result to id/rowid. The
inactive dated handler requires canonical role/channel/content/provenance, so
tests substituting the whole writer had not exposed that real integration gap.
return_saved now preserves the original canonical saved row. Its default return
remains the message ID; missing history still returns a fail-closed empty identity.
A failed websocket notification after the commit cannot discard persisted proof.

Two tests run the real writer with the real temporary history/ledger and injected
dated handler, and failed before repair. 72 focused Web completion/upload/mirror/
behavioral-intake cases pass with one dependency deprecation warning. Syntax/diff
checks pass. Scheduler activation still requires paired installation and exclusion
of legacy pressure writers; no live store initialization, runtime restart, reset
or Git operation occurred. This checkpoint is not proof of live LLM behavior.

### Draft arbitration checkpoint (2026-10-07)

The inactive shared handler now ends routine arbitration with stale context
when an offer, local draft or owner history changes during draft classification,
or its response window expires. It cannot fall through into a second semantic
feedback classification and record an unrelated acknowledgement. Fresh draft
acceptance still grants local preparation only; approval paths are unchanged.
Nine cases failed before the fix. 202 focused store/selection/freshness tests
pass, including all three channel identities, with one dependency warning.
Compilation and diff checks pass. No live activation, reset or Git operation.
Full adapter arbitration and activation remain separate rollout gates.

Use .\venv\Scripts\python.exe -m pytest with per-slice test files and an isolated
--basetemp under C:\Users\PC\.pytest_temp. Run git diff --check and compile changed
Python files after implementation. No full suite by default, no commits/pushes
without a Git request, no live test notifications. Natural model interpretation
and subsequent real scheduler behavior remain separately reported evidence.

### Final paired rollout and approved reset (2026-10-07)

One startup-only composition supplies all sender/tick/expiry/feedback hooks and
the transactional draft recorder together. Matrix installs its authenticated
handler and exact reply ownership before background startup; Web installs its
handler before workers. Missing schema stays inactive; incomplete schema fails
closed. Startup does not initialize/reset owner data. The whole routine job is
serialized against an answer-triggered wakeup, rather than only its elapsed helper.

Regression-first checks covered rollback, exclusive backup creation, preserved
receipts/completions/pauses, paired startup, actual Web history and debug labels.
Final focused runs: 159 dispatch/clarification/debug tests, 51 isolated Telegram
completion tests, 102 startup/Web/Matrix tests, 42 reader/missed/inactive-window
tests, and runtime/reflection verification. Counts overlap, not a unique total.
No full suite was run. The final live readback caught the legacy zero-to-four-hour
clamp; two reproductions failed before repairing the canonical reader. Nonzero
legacy bounds are unchanged. Reflection was already disabled/unscheduled and is
not implicated as the cause of this incident. Its retained cooldown/frequency
action code is defensively guarded after explicit dated migration; this does not
enable reflection or change unrelated reflection actions.

The owner explicitly approved the additive table and scoped baseline reset.
All 12 routines were reset through RoutineFeedbackStore, with confidence/cooldown
verified inside the transaction and zero cooldown/derived pressure rechecked
after commit through canonical APIs. Backup:
C:\astakos_v2\backups\routine-feedback\before-reset-20261007-184017.sqlite3
(consistent SQLite snapshot, 180224 bytes, Git-ignored). No receipts, completed
dates, history, pause/mute state, conditions or schedules were deleted. No Chroma,
credentials or config changes. No Astakos runtime process was detected; hooks
activate on next normal startup. Live LLM interpretation and midnight behavior
remain natural-observation evidence, not offline claims. No Git operations.

Manual compatibility/debug operations are retained intentionally. Ordinary
dated adapters do not fall through to legacy mutation on none/error. Web exact
reply UI remains a future enhancement, not a blocker for semantic dated input.

## Risks

### Partial installation expiry safeguard (2026-10-07)

If any dated feedback/tick/sender dependency is installed without its expiry
handler, cleanup now returns retry-pending instead of calling the legacy
30-minute pressure writer. The default all-inactive legacy path is unchanged.
Five regression cases failed first. The final ten targeted cases pass after
fixing the fixture to represent trigger_pending; 142 existing worker/dispatch
cases passed in the preceding run. One dependency warning per run. This is a
guard, not full paired installation or proof that every legacy writer has been
excluded. No live activation, reset, database mutation or Git operation.

- Historical correction can undo earlier pressure: derive from dated outcomes,
  not subtraction of mutable counters without provenance.
- Multiple channel processes share storage: transaction and uniqueness constraints
  must cover reads and writes, not only a process-local threading lock.
- Confidence has unrelated existing learning/reflection writers: inventory before
  changes, remove only response-driven confidence decay.
- Cold/live baseline rollback must not erase receipts written after a snapshot.
- Existing active work is preserved; agree task-list placement before editing it.

# Astakos: Current Tasks

## Conversational project updates (2026-10-08)

- [x] Reproduce missing goal-update bindings in Chat and Dev across Web,
  Matrix and Telegram; eight failing cases before the repair.
- [x] Expose existing goal tools in both agents; record reported activity or
  verified joint work using partial updates, not a full goal reset. Scores
  remain milestones, not completion percentages. Read-only diagnosis is unchanged.
- [x] Focused goal/security checks: 221 passed, two existing dependency warnings.
  Agent bindings, persisted milestones/timestamps, unknown-project rejection,
  external provenance and read-only diagnosis verified offline. Compilation
  and whitespace/diff review passed; no full-suite run or live-data changes.
- [ ] Observe a natural project update/follow-up reply; offline bindings and
  persistence do not prove the provider's future semantic tool selection.
- PR requested by the owner; review/merge remain separate next steps.
  No live goal backfill or storage migration.

## Optional routine context notes (2026-10-08)

- [x] Owner-approved scope: one 30% gate; work/shift may allow a relevant comment,
  never the blocked activity. Explicit silence and quiet hours remain respected.
- [x] Review the scoped implementation sequence at the top of `tasks/plan.md`.
- [x] Reproduce blocked-path and durable evaluation/delivery lifecycles offline;
  confirm storage reuse without schema or live-data changes.
- [x] Unified structured semantic note decision without keyword lists; exact
  positive, no-note and safety/error cases fail before repair and pass afterward.
- [x] Shared scheduler integration and fresh-state/once-per-occurrence delivery;
  no pending confirmation, completion, cooldown or confidence mutation.
- [x] Focused regression tests, compilation and whitespace/diff review; no full suite.
  263 passed, one existing Google dependency deprecation warning. Both channels
  record one note without dated feedback/confirmation changes; owner-history,
  GPS, completion, silence and channel races reject stale comments. Fixed the
  old silent-skip fixture's stale package reference after combined tests exposed
  cross-module contamination. Five changed Python files compile successfully.
  No live messages, provider calls, schema migration or owner-data changes.
- [ ] Owner-controlled natural observation remains separate from offline evidence.
- [x] PR #234 Codex P1/P2 reproduced in both channels (four failing regressions):
  pin note delivery through the canonical helper's optional target channel and
  invalidate inference on any shared-history update, not only owner messages.
  277 related offline tests passed, one existing dependency warning; compilation
  and whitespace checks clean. Matching-channel history repair remains idempotent;
  no full suite, live messages, configuration or owner-data changes.

## Daily context inference (approved 2026-10-08)

- [x] RED/GREEN: source-timed daily references and canonical flag persistence.
- [x] Before-question resolution through the same extractor, with bounded
  evaluation, source freshness and no timestamp renewal of old observations.
- [x] Focused offline verification: 204 passed, two existing dependency warnings.
  Removing the source-age guard made the old-event regression fail; restored it.
  No full-suite run, live provider calls or owner-data repair.
- [ ] Live semantic observation remains separate from offline verification.
- [x] Reproduced both PR #233 P2 findings: UTC midnight reference loss and
  premature history cap. Scan adjacent dates, filter eligible sources before
  retaining the latest 12 by actual instant; preserve the rowid boundary.
  Combined focused verification: 288 passed, one existing dependency warning.
- [x] Prepare the scoped extension/review fixes for PR #233 and a new Codex review.
- [x] Second review findings reproduced in six cases: filter daily candidates
  before the source bound; reuse latest trusted owner row for extraction freshness.
  Preserve the 128-row / 32,000-character bounds and newer-owner/state rejection.
  113 related offline tests passed (one existing dependency warning); repaired
  a stale fixture loader name that had caused six setup errors in the first run.
  Compilation and whitespace checks passed; no full suite or live-data changes.
- [x] Final Codex review of `bf5400d` completed without new findings; checked
  inline comments and top-level result. Earlier actionable findings are fixed.
- [x] Owner approved including partner-work-mode repair in this PR. Removed the
  word-cooccurrence fallback; the canonical semantic extractor retains explicit
  remote-work support. Real-store regressions cover all three channels.
  Three original-scenario cases failed before removal; 128 focused tests passed
  after it (one existing warning), with compilation and whitespace checks clean.

## Conversational completion and timed shared state (2026-10-08)

- [x] Reproduce the 09:31 question / 09:45 expiry / 10:09 departure sequence:
  missing reference produced no recorded completion despite the clear report.
- [x] Shared timed owner history for flag extraction and dated routine selection;
  canonical receipt-matched expired question is meaning context, not permission.
- [x] Preserve any-time / explicit past-day completion and idempotent acknowledgement;
  no late reminder, fabricated delivery, automatic arrival or pressure reset.
- [x] Guard unknown reply targets, stale inference and provenance-marked references.
- [x] 316 related offline tests passed (two existing dependency warnings);
  UTC/local chronological-order regression failed before the final correction,
  then 66 focused continuity/history/extractor tests passed (one warning).
  Changed Python files compiled and diff review/whitespace checks passed.
  These runs overlap; counts are not added. No full suite or live model test.
- [x] Owner authorized a separate commit/PR after merging PR #232.
- [ ] Owner-controlled live observation and review lifecycle.

## Bounded context re-questions (2026-10-08)

- [x] Reproduce same-day location topic blocking a later routine and the consumed
  model-attempt trap on a too-early poll (six failing offline cases before repair).
- [x] Shared ledger: three questions/day, 30-minute overlapping-flag spacing,
  no repeat for the same routine/day, one pending question, explicit refusal kept.
- [x] Preflight the same policy before semantic wording; final reservation stays
  atomic. Existing GPS/context validity and ordinary dispatch gates are untouched.
- [x] 217 focused offline tests passed (one existing Google dependency warning),
  including the exact morning sequence, absent/expired/fresh GPS and both channels.
  Diff review and whitespace check passed; no full-suite rerun or live data writes.
- [x] Owner authorized commit/PR for this narrow correction.
- [x] PR #232 review finding addressed by aligning the spec with the approved
  three-question policy; merged and task branch deleted (2026-10-08).
- [ ] Natural live observation remains separate.

## Completed routines and context questions (2026-10-08)

- [x] Reproduce today's early completion still producing a location question:
  the dated ledger recorded completion, but candidate selection used only legacy
  `last_triggered`. Regression tests use isolated real routine/question stores.
- [x] Filter candidates by canonical dated outcomes; acknowledgement and legacy
  databases remain eligible. Retire delivered questions when every associated
  routine is closed for its slot date, even during recent conversation activity.
- [x] Focused verification and local diff review: 293 tests passed, including
  completion during inference, other-date isolation and acknowledgement eligibility.
  No full-suite rerun, live database writes, migrations or cooldown/confidence reset.
- [x] Owner authorized commit/PR for this correction.
- [x] PR #231 review findings reproduced: query closures by the candidate's
  concrete occurrence date; persist each grouped routine's own slot and use it
  for closure. Legacy single questions retain their known date; ambiguous old
  groups are not auto-closed from guessed dates.
  Both midnight regressions failed before the fix; 162 focused tests passed
  afterward, including malformed mappings and legacy-group safety.
- [x] PR #231 reviewed clean at 96693f1, merged; task branch deleted.
- [ ] Naturally observe the next early completion.

## Routine conversation wording (2026-10-07)

- [x] PR #229 merged; its task branch deleted. Terminal-result continuation
  remains bounded/tool-free; natural approved-inspection observation is pending.
- [x] Recorded dated feedback supplies the canonical selected routine name as
  bounded untrusted display reference, separately from the trusted action/date.
  Web, Telegram and Matrix share the same handler and conversation tone.
- [x] Context questions receive up to six shared recent messages for wording
  only. Current evidence and unknown-flag validation remain authoritative;
  dependency classification does not read the added dialogue.
- [ ] Naturally observe explicit routine acknowledgements and contextual
  questions in Astakos' singular voice. Offline tests verify prompt inputs,
  persistence and safety boundaries, not live model phrasing.
- [x] Owner authorized commit/PR for this narrow wording slice.
- [x] PR #230 review corrections: retain the canonical name for routine-specific
  date clarifications without recording feedback; restrict wording dialogue to
  the current daily session across channels; require stale/error context in tests.
- [x] PR #230 reviewed and merged; its task branch deleted (2026-10-08).

## Dated routine feedback — implementation and approved reset completed

- [x] PR #227 review corrections: dated single/group/deferred notifications
  stay on the dated lifecycle; Telegram text/voice turns retain provider event
  identity through shared-history and fallback writes. The URL test assertion
  checks the parsed hostname, not a substring.
- [x] Separate follow-up after PR #227: mixed context answers continue through
  the ordinary Web/Telegram/Matrix conversation once, retaining memory,
  routine-feedback and reminder/skill requests. Extra current facts use the same
  canonical schema and guarded write; background extraction cannot retry stale
  related answers. Standalone answers remain context-only. Question generation
  reuses Chat's personality section and singular tone, without tool instructions.
- [ ] Review and naturally verify mixed context answers and question wording.
  Offline verification is not proof of live model interpretation or tool delivery.
- [x] PR #228 actionable review fixes: durable routine reconciliation continues
  separately from live flags; missing continuation metadata fails open only for
  normal conversation, not writable scope. Semantic flag batches use atomic
  version comparison, including additional mixed-answer facts. Provenance tests
  include a real pending ledger and detect removal of the guard.
- [x] Final PR #228 review/merge (merged 2026-10-07; branch deleted).
  Matrix concurrent/replayed events are already
  claimed by the production transport; enum-only clarification questions are
  unsupported and rejected before provider inference. No new global replay
  subsystem or enum-question feature is part of this fix.
- [x] Separately investigate Git global-option read-only classification and
  returning approved terminal results to the requesting agent. No change to
  terminal execution or approval continuation belongs to this context fix.
- [x] Git classification slice: reproduce `git -C C:\astakos_v2 log -n 1 --stat`
  incorrectly requiring approval. Parse only bounded directory-selection options;
  mutations, config overrides, output writes and external diff/textconv helpers
  remain outside SAFE. Focused offline classifier and approval-risk coverage.
- [x] Matrix terminal approval analysis: save bounded original request/agent with
  the pending terminal call; after authenticated execution, interpret its output
  with the original agent prompt and no bound tools or graph replay. Failed
  analysis/legacy context preserves raw output. Shared originating Matrix/Web
  history retains the agent and external-output provenance; existing nonterminal
  acknowledgements remain unchanged. Focused tests only; live wording pending.
- [x] Apply the same tool-free result analysis to approvals handled directly by
  Web or Telegram (not approvals delivered/executed through Matrix). Do not
  assume those independent callbacks resume an agent automatically. Both use
  the shared analysis/history helper, with authentication, sequential replay,
  provider-failure fallback and original-agent/provenance offline coverage.
- [ ] Naturally verify terminal result wording after a real approved inspection;
  no live terminal execution or external send was performed during this fix.

- [x] RF1/RF2: dated ledger, Athens day-close accounting and canonical semantic
  feedback. Separate three-occurrence unanswered/refusal streaks; acknowledgement,
  postponement and silence do not reduce confidence.
- [x] RF3: paired Web/Telegram/Matrix startup composition, authenticated saved
  owner turns, shared-history freshness and exact external reply correlation.
  Local draft preparation remains separate from external-action approval.
- [x] RF4: single/deferred/group delivery uses one durable dated sender. Confirmed
  receipts survive history failures; concurrent routine ticks are serialized.
  Maintenance uses the existing scheduler, not another background scheduler.
- [x] RF5: debug distinguishes final decisions from condition checks, and active
  dated policy from staged diagnostics. The canonical reader preserves cooldown
  zero. Reflection remains unscheduled/disabled; its retained action code has a
  defensive guard against overwriting dated automatic backoff. Legacy
  adapters are excluded when the paired handler is installed; manual compatibility
  APIs remain deliberately available, rather than being blindly deleted.
- [x] RF6: owner explicitly approved live migration/reset on 2026-10-07.
  All 12 routines reset to cooldown 0, confidence 1.0 and zero pressure counters.
  Pause/mute/schedule/conditions/completed days/receipts/history are preserved.
  Consistent pre-reset backup (Git-ignored):
  C:\astakos_v2\backups\routine-feedback\before-reset-20261007-184017.sqlite3.
  The reset transaction verified all confidence/cooldown fields; subsequent
  canonical readback verified zero cooldown and derived pressure for all 12.
- [ ] Natural observation after normal launcher startup: late completion,
  acknowledgement/refusal, Athens midnight accounting and debug outcomes.
  Offline verification is not a claim that live LLM interpretation was tested.
  No Astakos runtime process was detected during the approved reset; the new
  hooks install on next normal startup. No hidden duplicate runtime was started.

Verification: 159 dispatch/clarification/debug cases, 51 isolated Telegram
completion cases, 102 paired startup/Web/Matrix cases and focused store/reset/
reflection regressions passed. Runs overlap; these are not a unique-test total.
Only focused suites were run. Owner requested commit/PR for review; the task
branch is codex/dated-routine-feedback. Runtime databases/backups are not staged.
Web exact-reply UI is a future enhancement; current semantic dated feedback is
supported without inventing a reply target.

Contract/evidence: [routine-feedback-spec.md](routine-feedback-spec.md) and
[routine-feedback-plan.md](routine-feedback-plan.md).
Existing unrelated natural/live verification below is preserved.

## Current feature: context-evidence (foundation offline verified)

- [x] Fix mixed naive/offset timestamps blocking behavioral initiative before
  model evaluation; cover idle, future history, daily/topic limits and reminders.
  Clarification no-op ticks are quiet in the terminal; errors/deliveries and
  structured diagnostics remain visible. 94 tests pass in the expanded offline
  check; syntax checks and git diff --check pass. Ten regressions failed first.
- [ ] Repair legacy test transport isolation in two missed-routine tests
  (test_event_log_and_missed_routines.py): they mock Telegram sends despite
  Matrix selection. Both also fail with the pre-change queue/activity/reminder
  implementations from HEAD; deferred rather than bundled into this fix.
- [ ] Naturally verify that the active external worker no longer reports the
  initiative timestamp TypeError and clarification no-op banners after restart.
  An opener remains optional: model decisions and existing safety gates apply.

- [x] Fix live Matrix GPS/answer race: acknowledge an already-resolved question
  without reapplying the old answer or offering a spurious capability bug.
  Verified with 86 focused offline tests; approval gates unchanged.
- [ ] Observe the corrected acknowledgement naturally when fresh GPS resolves
  a question during an owner reply. Do not manufacture live routine sends.
- [x] Refresh same-value owner whereabouts on trusted live GPS updates and log
  Matrix location acceptance/rejection reasons without coordinates or identities.
  Verified offline with 101 focused location/reply/evidence tests.
- [ ] Observe a renewed Element live share and inspect its private decision log;
  a sharing event alone is not a received coordinate update.
- [x] Address PR #225 P2 findings: recognize concurrent resolution on refusal;
  move location file telemetry off the event loop and halve successful-point
  writes. 82 focused tests and four terminal-state safety cases pass offline.
- [x] Address the second PR #225 review: persist GPS completion before telemetry
  cancellation and consult resolved ledger state before a partial reply.
  74 focused tests pass, including acknowledgement recovery without reprocessing.

Contract: [context-evidence-spec.md](context-evidence-spec.md).
Map: [routine-context-refresh-map.md](routine-context-refresh-map.md).
Scope: read-only foundation; automatic questions/routine adoption are not active.

- [x] CE1: Evaluate stored whereabouts/co-presence observations.
  - Acceptance: recent true/false preserved; two-hour/date expiry becomes unknown;
    invalid, future or unreadable observations do not invent current state.
  - Acceptance: timezone-aware instants, local naive legacy timestamps and DST
    handled consistently; inputs unmodified and no persistence writes.
  - Verify: failing-then-passing focused tests/test_routine_context_evidence.py.
  - Files: services/routine_context_evidence.py, tests/test_routine_context_evidence.py.
  - Dependencies: none. Scope: small (two files).
- [x] CE2: Reconcile fresh owner GPS with stored evidence.
  - Acceptance: fifteen-minute validated GPS establishes only owner home/away;
    invalid geometry/point/time or stale point cannot establish current location.
  - Acceptance: known conflicting sources resolve unknown/conflict; contradictory
    household-home claim exposed without guessed partner/child presence or writes.
  - Verify: failing-then-passing GPS/conflict/boundary tests using temporary fixtures.
  - Files: same service/test pair; reuse services/location_update.py geometry.
  - Dependencies: CE1. Scope: small (two files).
- [x] Checkpoint after CE2: focused evidence tests pass, no provider/outbound calls,
  no real database/GPS writes and no changes to current routine dispatch.
- [x] CE3: Expose and verify the canonical channel-neutral snapshot.
  - Acceptance: entry point in services/routine_context.py uses memory abstractions
    and injected evaluation time; all five flags have structured value/source/age
    validity/reason evidence without fabricating source provenance.
  - Acceptance: legacy routine context, shift/extended absence and existing callers
    remain unchanged; fixtures prove wiring and read-only behavior.
  - Verify: focused two-file command below, syntax checks and git diff --check.
  - Files: services/routine_context.py, service/test pair, feature documentation.
  - Dependencies: CE2 checkpoint. Scope: medium; no unrelated cleanup.
- [x] Final context-evidence checkpoint: record actual test evidence and deferred
  limitations. 74 focused tests pass, one dependency deprecation warning; syntax
  checks and git diff --check pass. No full-suite run, runtime adoption or live
  provider/device verification. The earlier mixed run was stopped at a legacy
  unmocked model boundary; final resolver tests are isolated and network-blocked.
- [x] Owner review of the foundation before dependent clarification implementation.
  Owner requested the next module on 2026-10-06.

Verification commands (executed after implementation with isolated temp paths):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_routine_context_evidence.py tests/test_routine_context.py -q --basetemp=C:/Users/PC/AppData/Local/Temp/astakos-context-evidence
.\venv\Scripts\python.exe -m py_compile services/routine_context_evidence.py services/routine_context.py tests/test_routine_context_evidence.py
git diff --check
```

- [x] Specify routine-context-clarification; owner approved on 2026-10-06.
  Contract: [routine-context-clarification-spec.md](routine-context-clarification-spec.md).
  Scheduler and reply adapters are now wired in code; natural verification is pending.
- [ ] Later: scope schedule-context inference after natural clarification verification.

## Routine-context-clarification: implementation complete, natural observation pending

Detailed acceptance, dependencies, file scope and verification for every CQ task
are in [plan.md](plan.md). Preserve all unrelated pending verification below.

- [x] Owner approval of the ordered implementation plan before code changes.
- [x] CQ1: Atomic dedicated ledger, one pending, bounded daily reservations, expiry/refusal/restart
  and corruption/concurrency safety; failing-then-passing temporary-storage tests.
- [x] CQ2: Consequential eligible dependency selection, minimal semantic question,
  stale-generation recheck and cache; no keyword interpretation patches.
  Pure influence/proposal/cache tests pass. Known evidence value/time changes
  invalidate cached decisions; model IDs are limited to the five supplied
  candidates. Injected poll rechecks history/evidence/eligibility/channel/gates
  after classification. Canonical schedule/pause/mute/cooldown filtering and
  validated semantic dependency caching are wired in the existing slow worker.
- [x] Checkpoint CQ1-CQ2: real temporary lifecycle/selection integration,
  provider/transport boundaries mocked and accidental network blocked.
- [x] CQ3: Reserved canonical delivery/history with idempotent Matrix recovery
  and held uncertain Telegram sends; verify persisted crash/failure outcomes.
  Production-worker transport adapters have real temporary history/ledger tests.
  Budget charging is serialized with the durable sending transition, with a
  post-budget deadline check. Persisted generation correlation permits only
  still-current Matrix retries; uncertain Telegram delivery stays held.
- [x] First implementation checkpoint: 101 focused evidence/clarification tests
  pass with one dependency warning; Python syntax and git diff --check pass.
  Historical checkpoint; no scheduler dispatch was enabled.
- [x] CQ4: Canonical trusted semantic answers and final persisted evidence;
  partial/unrelated/refused/late scenarios and unchanged ordinary extraction.
  Optional extractor contract and temporary persisted answer tests implemented;
  Durable correlation, concurrent full-answer serialization and ledger closure
  implemented. Injected poll resolves confirmed questions when all requested
  evidence is known and recorded after delivery; channel adapters are wired.
- [x] Next inactive slice checkpoint: 55 targeted answer/extractor/delivery/state
  tests pass. Receipt/history repair survives expiry or channel change; receipt
  timestamps use injected current time. Historical inactive-slice checkpoint.
- [x] Checkpoint CQ3-CQ4: injected question/answer flow, no execution or changes
  to approval/routine completion records.
- [x] CQ5: Web/Telegram arbitration before completion/draft interpretation;
  ordinary replies unchanged, exact-target approvals authoritative.
  Early consumed-answer path and competing-authority safety are tested.
- [x] CQ6: Matrix wiring with shared answer contract; trusted owner only,
  cross-channel correlation and single history/extraction path.
  Plain-text adapter/history/background guard wired and tested. Exact Reply to
  a confirmed context question now reaches semantic extraction, with protocol
  fallback stripping and task-local correlation. Approval targets retain their
  existing verified-device gate; unrelated and ambiguous answers pass through.
- [x] Element Reply checkpoint: 72 targeted transport/approval/answer/channel
  tests pass (two dependency warnings), including final temporary flag/ledger/
  history outcome and correlation cleanup after failure. No live dispatcher.
- [x] Answer/channel slice: 123 targeted extractor/arbitration/Matrix/lifecycle
  tests pass with one existing dependency warning. No question dispatcher,
  production ledger, live transport or full-suite run was activated.
- [x] Checkpoint CQ5-CQ6: all three channel entry points pass related/unrelated
  replies and short-answer dual-consumption safety tests.
- [x] CQ7: Existing routine dispatch consumes scoped evidence end-to-end and
  resumes only timely eligible routines; quiet/mute/activity/budget gates hold.
  Existing routine ticks enqueue one coalesced worker. Conditions, later guards
  and message prompts share the five-flag projection. Recheck before dispatch;
  pending questions hold competing confirmations and questioned past slots
  are excluded from startup replay. Distinct due routines send one batch.
  No process was started/restarted and no real question was sent for testing.
- [x] CQ8: Authenticated bounded Debug, ignore ledger/lock, data-only backup
  selection verified in temporary fixtures; no actual backup/runtime changes.
- [x] Final focused checks and diff inspection: 325 related tests passed;
  final worker/scheduler/Debug/startup slice passed 33 tests. Legacy completion
  fixtures passed separately (Telegram 23, Web/Matrix 28) to avoid whole-module
  stub contamination. Deadline mutation was caught and restored. All 32 changed
  Python files compiled; both inline JS scripts passed syntax validation;
  git diff --check passed (only Git CRLF-normalization notices).
  No full-suite rerun, live provider verification or commit/PR claimed.
- [ ] Owner-controlled natural observation after implementation review: one useful
  question, an answer from another channel, and one still-timely reminder.
- [x] PR #224: address all four Codex findings: reject stale answer versions;
  recheck canonical completion/skip/slot eligibility; durably request an existing
  external-worker dispatch after a complete answer; preserve successful delivery
  when history fails and retry only recording. 123 focused tests and 23 isolated
  legacy Telegram tests pass. Busy-worker/deadline and best-effort history-repair
  limits are documented in the spec. No merge or live verification is claimed.
- [x] Latest PR #224 P2: evidence-only resolution now uses the same atomic
  ledger close/wakeup transition as complete answers. 78 focused tests pass;
  timely dispatch, repeated polls, expiry and decline are covered offline.

## Current repair: shift temporal provenance

Contract: [shift-temporal-provenance-spec.md](shift-temporal-provenance-spec.md).

- [x] Reproduce the Sunday expiry overwrite and prevent conflicting fallback writes.
- [x] Validate semantic dates/shift values and cover final state across Monday.
- [ ] Naturally observe a weekly shift staying effective after the date boundary.
- [x] Address the Codex cancellation finding; 122 focused tests pass.
  No stored-memory cleanup is included.

## Pending natural verification: user-fact provenance and dated duplicates

Contract: [memory-fact-provenance-spec.md](memory-fact-provenance-spec.md).

Implementation and the Codex photo-provenance correction are complete: 23 focused
regressions pass. Existing memories are unchanged; cleanup is excluded.

- [ ] Naturally observe a new dated update: no courtesy fact and no same-period
  duplicate, while a genuinely different week's update remains distinct.
  Model interpretation and extra background latency are not proven by offline fixtures.

## Pending live verification: vacuum/GPS and Web step boundary

Contract: [vacuum-location-boundary-spec.md](vacuum-location-boundary-spec.md).

PR #211 implementation and its Codex correction are complete; owner authorized
merge and task-branch deletion. Verification: 160 focused regressions, followed
by 25 focused Web tests covering the review correction. No limit increase or
full-suite run.

- [ ] Owner-controlled live vacuum/Web test after review. Offline verification
  does not prove live model interpretation or physical hardware behavior.

## Pending natural/live verification

## Daily data-only backup

- [x] Build and fixture-test the selective cold package and indexed assets.
- [x] Verify single upload and scoped retention on mocked Drive failures.
- [x] Resolve broken legacy photo-index entries with owner authorization;
  Chroma cleanup remains explicitly deferred.
- [x] Verify live pause/resume in the original Web/Matrix consoles, cold capture,
  isolated extraction with matching SHA-256, private Drive upload and retention.
  This is byte-level restore evidence, not replacement-host application recovery.
- [x] Switch the existing 00:00 task action to scripts/nightly_data_backup.py.
  Owner ran the registration script; Scheduler readback confirmed the new
  action, venv interpreter and working directory. The 03:00 Matrix job is unchanged.
- [x] Run the actual Scheduler task manually: 2026-10-02 22:07:54 to 22:09:22
  local, LastTaskResult=0 and complete 47-file backup; original consoles resumed.
- [x] Address PR #212 Codex findings: persist meal/recipe data in the package
  and recover supervisors after descendant shutdown failure. 26 focused tests
  pass; live evidence above predates the additional skill data.
- [x] Observe the scheduled 2026-10-03 00:00 data-only run: complete, 47 files,
  revision dd20296, LastTaskResult=0; finished at 00:00:47 local.
- [ ] Separately verify application-level recovery on an isolated installation.

## Existing natural/live verification (preserved)

- [x] Verify the timed 03:00 Matrix backup after the headless-handle fix.
  The 2026-10-04 invocation started at 03:00:01 local; backup status spans
  03:00:03 to 03:00:52, with LastTaskResult=0 and stage=complete/status=uploaded.
  The encrypted 6,332,292-byte artifact matches the recorded SHA-256. A Drive
  upload ID is recorded; Matrix startup is present in the recovery log and no
  maintenance/pause marker remains. No new restore rehearsal or Drive download
  was performed during this read-only verification.
- [ ] Separately scope Element recovery-key and replacement-host verification.
  Current evidence does not prove complete client/host-loss recovery.
- [ ] Observe normal behavioral commentary, topic opt-out/re-enable and one
  appropriate spontaneous opener during ordinary use, including non-repetition.
- [ ] Observe initiative diagnostics on a natural scheduler tick: last check,
  retained model evaluation and skip/error reason in Behavioral Patterns Debug.
  A natural Matrix tick on 2026-10-04 at 22:31 recorded recent_activity.
  Retained model evaluation still awaits natural observation; offline tests pass.
  Older evaluations have no recorded reason; do not infer one retrospectively.
- [ ] Reconcile new behavioral exceptions from that observation. Known held
  delivery/recovery limitations are already documented in the plan and spec.

No completed channel, review or backup implementation phase remains an active
task. Do not rerun the full test suite by default.

Routine feedback RF3 checkpoint: shared catalog/dated-turn composition verified
with 110 focused offline tests. Names, dates and revision tokens share one read
snapshot; stale catalog selections cannot persist. Adapter activation, unrecorded
historical occurrence resolution, dispatch/day-close integration and the final
owner-approved cooldown/confidence baseline reset are still pending. No live
schema activation, reset or runtime change was performed.

Latest RF3 checkpoint (2026-10-07): stale draft classification can no longer
fall through into routine-feedback mutation. 202 focused tests pass with one
dependency warning; compile/diff checks pass. The previous paragraph is a
historical checkpoint: unrecorded past completion is now offline verified.
Remaining rollout gates include full adapter arbitration, activation/legacy
exclusion and the scoped recoverable cooldown/confidence baseline reset.

# Astakos: Current Tasks

Last reconciled with the owner: 2026-10-06 (context-evidence added;
existing verification entries preserved).
[plan.md](plan.md) defines scope and policy. Completed entries were removed from
this active checklist; evidence remains in Git history, specs/runbooks and the
[archive](archive/2026-10-02-todo.md). Archived unchecked items are not this backlog.

## Current feature: context-evidence (foundation offline verified)

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
- [x] CQ1: Atomic dedicated ledger, one pending, two/day, expiry/refusal/restart
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

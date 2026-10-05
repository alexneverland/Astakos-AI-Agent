# Astakos: Current Plan

Last reconciled with the owner: 2026-10-04.
Only active work is listed here; [todo.md](todo.md) records its status.
Completed evidence remains in Git history and existing specs/runbooks.
The [archived plan](archive/2026-10-02-plan.md) is not an active queue.

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

1. **Matrix nightly backup:** observe the next timed 03:00 run and recovery in
   the original visible terminal. PR #210 is merged; encrypted private Drive
   delivery, actual Scheduler invocation and isolated server/bot restore were
   already verified. Full Element key recovery and replacement-host recovery
   remain separately bounded verification, not a complete host-loss guarantee.
   Reference: [matrix-backup-recovery-spec.md](matrix-backup-recovery-spec.md).
   The 2026-10-03 timed run failed in the headless stop guard. Native pythonw
   reproduction showed WinError 6 with invalid inherited stdin. Non-interactive
   backup subprocesses now use explicit DEVNULL input; stage/failure diagnostics
   preserve the primary failure separately from recovery. Actual Scheduler retry
   at 08:48:53 local completed at 08:49:57 with LastTaskResult=0, verified encrypted
   upload and recovery under the same visible parent. Next timed run remains open.
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

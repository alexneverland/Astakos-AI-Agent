# Astakos: Current Tasks

Last reconciled with the owner: 2026-10-04.
[plan.md](plan.md) defines scope and policy. Completed entries were removed from
this active checklist; evidence remains in Git history, specs/runbooks and the
[archive](archive/2026-10-02-todo.md). Archived unchecked items are not this backlog.

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

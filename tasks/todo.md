# Astakos: Current Tasks

Last reconciled with the owner: 2026-10-03.
[plan.md](plan.md) defines scope and policy. Completed entries were removed from
this active checklist; evidence remains in Git history, specs/runbooks and the
[archive](archive/2026-10-02-todo.md). Archived unchecked items are not this backlog.

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

- [ ] Observe the next timed 03:00 Matrix backup after the headless-handle fix.
  The 2026-10-03 timed run failed. Reproduction identified invalid inherited stdin
  (WinError 6) in pythonw subprocess boundaries after console handoff. Explicit
  DEVNULL input preserves fail-closed checks. A real Scheduler retry at 08:48:53
  completed at 08:49:57 with LastTaskResult=0, encrypted verified upload and
  the original watchdog/console restored. Safe stage diagnostics are retained.
- [ ] Separately scope Element recovery-key and replacement-host verification.
  Current evidence does not prove complete client/host-loss recovery.
- [ ] Observe normal behavioral commentary, topic opt-out/re-enable and one
  appropriate spontaneous opener during ordinary use, including non-repetition.
- [ ] Reconcile new behavioral exceptions from that observation. Known held
  delivery/recovery limitations are already documented in the plan and spec.

No completed channel, review or backup implementation phase remains an active
task. Do not rerun the full test suite by default.

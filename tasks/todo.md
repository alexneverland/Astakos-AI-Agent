# Astakos: Current Tasks

Last reconciled with the owner: 2026-10-02.
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

- [ ] Observe the first timed 03:00 Matrix backup and original-terminal continuity.
  PR #210 is merged; manual Scheduler invocation, encrypted private upload and
  isolated server/bot restore are complete. Existing 22:00 backup is unchanged.
- [ ] Separately scope Element recovery-key and replacement-host verification.
  Current evidence does not prove complete client/host-loss recovery.
- [ ] Observe normal behavioral commentary, topic opt-out/re-enable and one
  appropriate spontaneous opener during ordinary use, including non-repetition.
- [ ] Reconcile new behavioral exceptions from that observation. Known held
  delivery/recovery limitations are already documented in the plan and spec.

No completed channel, review or backup implementation phase remains an active
task. Do not rerun the full test suite by default.

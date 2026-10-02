# Astakos: Current Plan

Last reconciled with the owner: 2026-10-02.
Only active work is listed here; [todo.md](todo.md) records its status.
Completed evidence remains in Git history and existing specs/runbooks.
The [archived plan](archive/2026-10-02-plan.md) is not an active queue.

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

## Remaining live verification

1. **Matrix nightly backup:** observe the first timed 03:00 run and recovery in
   the original visible terminal. PR #210 is merged; encrypted private Drive
   delivery, actual Scheduler invocation and isolated server/bot restore were
   already verified. Full Element key recovery and replacement-host recovery
   remain separately bounded verification, not a complete host-loss guarantee.
   Reference: [matrix-backup-recovery-spec.md](matrix-backup-recovery-spec.md).
2. **Behavioral conversation:** naturally observe relevant commentary, semantic
   topic opt-out/re-enable and an appropriate spontaneous opener. Reconcile new
   exceptions from actual observations. Implementation/offline tests are complete;
   do not manufacture live messages to claim provider verification.
   Reference: [behavioral-conversation-spec.md](behavioral-conversation-spec.md).

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

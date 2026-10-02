# Astakos: Current Tasks

Last reconciled with the owner: 2026-10-02.
[plan.md](plan.md) describes current scope and policy.
The detailed implementation/test history is preserved in
[the archived checklist](archive/2026-10-02-todo.md).
Unchecked entries in that dated snapshot are historical, not the active backlog.

## Open: await owner direction

- [ ] Document and verify private Matrix backup/recovery prerequisites.
  Preserve a recoverable boundary for Synapse signing key/config and PostgreSQL
  data without exposing secrets. Keep this separate from Astakos code work.
- [ ] Observe normal behavioral commentary and one appropriate opener live.
  Include relevance, unrelated requests, semantic topic opt-out/re-enable and
  absence of repetitive nagging. Implementation/offline tests are complete;
  actual provider interpretation remains a natural owner-observation check.
- [ ] Reconcile remaining behavioral exceptions after that observation.
  Already recorded: uncertain Telegram or stale Matrix delivery is held, never
  blindly retried; no automatic owner-facing recovery UI in this version.
  Do not rerun the full test suite by default.

## Completed channel verification

- [x] Final Telegram–Matrix capability-parity gate.
  Owner explicitly confirmed on 2026-10-02 that ongoing live use is satisfactory.
  Keep the agreed exceptions: no heart-to-memory reaction, no legacy Matrix
  `/confirm`, critical approvals through encrypted Reply to the exact prompt.
  This records the owner's confirmation; no new automated audit was run.
- [x] Live Web–Element model-context continuity.
  Owner explicitly confirmed on 2026-10-02 that this has been tested successfully
  over time, beyond merely seeing the same messages in both UIs.
- [x] Shared context, selected-channel mirroring, media/archive paths and
  Web-origin critical approval delivery.
  Existing offline evidence and owner-confirmed live tests are retained in the
  history. No new transport, reaction or media-mirroring policy is introduced.

## Behavioral implementation complete; live observation remains open

- [x] Reuse and audit the existing detector and cross-channel intake.
  Collection stays message-triggered, not nightly routine generation.
- [x] Implement bounded dated evidence, optional normal-reply commentary and
  shared semantic topic preferences.
- [x] Implement the approved spontaneous-opener policy with durable delivery
  identities, restart/freshness checks, quiet/mute/budget suppression and
  canonical reminder-event activity checks.
  PR #208 merged. Historical verification: 153 pre-PR focused tests; review fix
  passed 28 initiative/wiring and 22 reminder/event-log tests. No full-suite run.

## Supplied-link reporting: PR #209

- [x] Reproduce the reported Skroutz failure with native `browse_url`.
  The tool returned `reason=cloudflare`; this is a tool-reported protection
  failure, not independently proven permanent site blocking.
- [x] Fix the guard to use the latest user input and acknowledge an existing link.
  Known protocol causes are localized; unknown diagnostics stay generic.
  No raw diagnostic paths, invented page contents or protection bypass.
- [x] Focused RED/GREEN verification and compilation/diff validation.
  69 combined guard tests passed; after adding the tool-only URL negative case,
  all 12 slice tests passed. Two dependency warnings; no full-suite rerun.
- [x] Owner's next normal-chat attempt read the page and answered correctly.
  The failure reply is tested offline; access to protected sites is not guaranteed.
- [x] Commit `0278122` and open PR #209.
  Codex's attempted-page-read finding was reproduced before repair: search-only
  failures and successful page reads cannot select the link-read failure reply.
  The owner authorized correction, merge and task-branch deletion.
  Review correction: all 73 combined link/guard tests pass; compilation and
  diff validation pass. No full-suite run or live outbound chat sends.

## Historical work

Web research providers, Matrix startup/media/delivery, capability-gap proposals
and the two-stage existing-bug investigation flow are preserved in the archive
with their contracts and test evidence. Historical phase-specific deferrals do
not create new active tasks or override the current decisions in plan.md.

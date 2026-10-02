# Astakos: Current Plan

Last reconciled with the owner: 2026-10-02.
The current task status is in [todo.md](todo.md). Historical phase plans are
preserved in [the archived plan](archive/2026-10-02-plan.md); they are not a
queue of work to restart. Detailed specs remain in their existing files.

## Confirmed channel work

The owner confirmed on 2026-10-02 that ongoing live use has verified both
Telegram–Matrix capability parity and cross-channel model-context continuity.
These are closed verification gates, not pending implementation tasks.
This confirmation is owner-reported evidence, not a new automated audit.

The agreed boundaries remain unchanged:

- Critical Matrix approvals use an encrypted Reply to the exact prompt.
  Do not change this to direct reactions or add the legacy `/confirm`.
- Heart reactions do not save memories.
- Web and the selected external channel share bounded conversation context;
  mirrored display copies do not re-enter the graph or create duplicate history.
- Uploaded media and generated-file cards are not mirrored as files; use the
  agreed compact text summaries without private filesystem paths.
- Keep selected-channel isolation, provenance and existing approval gates.

Relevant references: `matrix-channel-capability-map.md`,
`shared-conversation-context-spec.md`, `unified-conversation-map.md`,
`selected-channel-mirroring-spec.md` and `bug-investigation-flow-spec.md`.
Older audit/spec snapshots describe implementation stages, not current open gates.

## Remaining work: await owner direction

1. **Private Matrix backup/recovery.** Read-only inventory is complete; the
   proposed contract and ordered checkpoints are in
   [matrix-backup-recovery-spec.md](matrix-backup-recovery-spec.md).
   The owner chose Google Drive and Google Password Manager and approved age.
   age 1.3.2, restricted local key setup and a harmless cryptographic round trip
   are verified. Owner-mediated vault retrieval also decrypted the fixture
   successfully. Package/encrypt/explicit-upload implementation is covered by
   focused fixtures. The guarded collector and capture CLI are implemented with
   mocked Docker; they require stopped bot/watchdog and explicit Synapse pause.
   First approved local live capture passed on 2026-10-02, including vault-key
   decryption, plaintext staging cleanup, healthy Synapse/HTTP 200 and bot startup.
   The owner confirmed normal Element replies. Subsequent approved capture includes
   only the deployment `.env` inside ciphertext, with hash-verified private Drive
   upload/download. The existing configured Drive parent is publicly link-readable;
   it was left unchanged and a separate owner-only My Drive folder was created.
   Opt-in bot-runtime configuration export is now implemented and tested through
   CLI packaging; only validated Matrix fields enter the encrypted archive.
   Live recapture with bot settings and private Drive download/hash verification
   passed on 2026-10-02. Synapse is healthy and bot/watchdog processes restarted;
   owner chat confirmation for this latest restart is pending.
   Separate task `Astakos_Matrix_Encrypted_Backup` is now registered for 03:00,
   interactive current user/limited privileges, no daytime catch-up or forced
   termination. Its actual Scheduler invocation passed: exit 0, verified upload,
   encrypted channel startup, Synapse healthy/HTTP 200. 72 focused tests passed.
   Isolated restore of the scheduled artifact passed on 2026-10-02: PostgreSQL,
   pinned Synapse, token/room/sync and copied bot crypto loading. No outbound
   sends or production changes. Temporary Docker resources removed; the owner
   removed the plaintext directory (absence verified) and confirmed local secret
   key/fixture cleanup after vault verification. Next: first timed nightly run;
   full Element/replacement-host
   recovery remains a separately bounded verification, not an implied guarantee.
   PR #210 review corrections preserve the original ciphertext digest on retry
   and coordinate boot-supervised Matrix pause/restart without stopping Web.
   Native CTRL_BREAK was verified only on a disposable fixture child; no live
   boot restart or full-suite run. Astakos's own `.env` and original nightly task
   are unchanged.
2. **Behavioral live observation.** Observe relevant normal commentary, topic
   opt-out/re-enable and one appropriate spontaneous opener during ordinary use.
   Do not manufacture live test messages or mark provider interpretation verified
   from offline model doubles.
3. **Behavioral exceptions.** Reconcile any further exceptions with that live
   observation. Already-agreed delivery limitations are documented below.

## Behavioral implementation and policy

PR #208 is merged. Reuse the existing message-triggered detector; this is for
natural commentary and conversation, not the nightly routine-creation flow.

- Shared optional commentary uses 30-day evidence and semantic topic preferences.
- Initiative policy: at most one opener/day, seven days/topic, and at least
  fifteen minutes without shared conversation/reminder activity.
- Quiet/mute state, freshness, selected-channel ownership and the existing
  proactive hourly budget remain authoritative.
- The canonical event log guards reminders absent from history, with a recheck
  immediately before delivery.
- Uncertain Telegram or stale Matrix delivery is held, never blindly resent.
  There is no automatic owner-facing recovery UI in this version.
- Source-text retrieval beyond the structured evidence packet remains deferred,
  not an approved next implementation task.

Detailed contract: `behavioral-conversation-spec.md`.

## Supplied-link failure reporting (PR #209)

PR #209 contains the failure-reporting fix and its focused regression coverage.
Use the latest user message and canonical website-target recognition. Only an
actual failed browse_url result can select the page-read failure reply; a failed
search alone cannot establish that the page was opened. Acknowledge an
already-supplied link and localize known error codes without exposing raw
diagnostics or inventing page contents. Browser protections and providers are
unchanged. The owner reported successful reading on the next normal-chat attempt;
failed-page reporting is verified offline.

## Verification and scope

### PR #210 visible-terminal amendment

Owner approved keeping the existing watchdog/terminal through backup. Build in
three slices: (1) current-child shutdown and visible recovery logs; (2) exact
watchdog maintenance handoff and cold-capture guard; (3) focused verification
and runbook updates. No changes to the scheduled task, credentials or live data.
All three slices are implemented: 112 focused tests passed, compilation and diff
checks passed. Same-terminal output was verified with a disposable subprocess;
live overnight terminal continuity is still pending. An already running watchdog
must be normally restarted to load its own updated maintenance logic.

Keep focused tests offline using temporary stores and mocked outbound boundaries.
Run only the checks relevant to a behavioral/code change; no full-suite rerun
by default. Documentation-only reconciliation does not require runtime tests.
Do not reopen completed phases, alter security policy, or treat deferred research
ideas in the archive as authorized work.

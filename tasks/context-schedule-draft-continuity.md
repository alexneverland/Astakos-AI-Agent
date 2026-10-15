# Context and draft continuity (2026-10-15)

Owner authorized repair after inspecting the morning conversation. Git confirms
the Oct 12 duration proof remains present; it requires explicit duration support
and today's proof is absent. Do not remove freshness or repeat that implementation.
The active 15:30 work-departure schedule is currently absent from inference input.
Web's September 12 gate requires a contact in the newest message, hiding draft
preparation for the reply "ΕΤΟΙΜΑΣΕ ΕΝΑ ΚΑΛΗΜΕΡΑ ΩΡΑΙΟ ΦΙΛΕ" to a Sofia offer.

Acceptance and plan:
- Reproduce the exact draft continuation using real Web bindings, graph approval,
  local persistence and final draft receipt. Remove only the redundant recipient
  requirement; do not create replacement drafts for bare send commands or revise
  an unrelated active draft. External sending retains approval.
- Expose bounded, trusted active daily schedules to semantic pre-question
  resolution. A schedule can bound a confirmed ongoing episode, never prove its
  execution or separate workplaces. An optional selected schedule identity must
  be validated and retained in the existing duration proof; changes invalidate it.
  Keep original source timestamps and ordinary two-hour freshness unchanged.
- Add offline persistence/poll regressions and expiry/contradiction/provenance
  guards, then run affected groups and diff checks. No provider/transport calls,
  live data repair, config, credentials, runtime or release work.

Offline model boundaries do not establish live semantic inference quality. The
absence of a stored proof does not reveal the exact historical model response.
Owner subsequently authorized PR creation on 2026-10-15; merge remains separate.

Implemented on codex/context-schedule-draft-continuity from main 3e9662c.
The draft continuation failed before repair because no draft was persisted; the
bare-send safety case passed. The schedule/poll regression failed because the
schedule was absent from inference input. Both now pass using isolated native
stores. Contact lookup uses fixture contacts with the real canonical resolver.

Final verification: 203 context cases and 98 Messenger/approval cases passed
(301 distinct cases, including 15 new regressions). The final 15-case group also
passed after strengthening fixtures. Existing dependency deprecation warnings
only. Compilation and git diff --check passed. Original flags stay unchanged;
proofs expire at their validated schedule endpoint and fail on changed schedules,
wrong IDs/hours, provenance, paused/blocked/unknown conditions and state/history
races. The exact historical model response at 10:46 remains unavailable; missing
proof is evidence of the result, not a complete inference trace. Live provider
interpretation still needs natural observation. No live drafts/messages were
created or sent during the tests. Preparing the scoped commit and PR after owner
authorization; no merge or review monitoring was requested.

PR #255 review repair: reproduced all three schedule-applicability findings on
35519ef. Missing/unsupported condition types were accepted; stored-only presence
ignored conflicting GPS; date-valid old partner_at_work remained usable. The
schedule resolver now rejects unknown types, reuses canonical GPS reconciliation
with an explicit reader (no recursive duration proof), and freshness-checks
referenced non-volatile boolean observations. Legacy user_at_home negation is
guarded against unknown owner absence. Date/shift contracts remain unchanged.
Ten added offline cases cover creation/read rejection plus an unchanged schedule
losing applicability solely through GPS conflict or observation age. Final
schedule group passed 21 cases and the related context group passed 211 cases
(213 distinct context cases in total, with two added read-lifecycle cases run in
the final group). Compilation and diff checks passed; one existing dependency
deprecation warning remains. No live state or runtime changes were performed.
The three Messenger comments are not resolved by this context-only repair:
general tool availability is semantic choice as in Chat, while shared-draft and
latest-turn races concern the pre-existing unconditional draft writer. They
remain explicitly open rather than being marked fixed by these changes.

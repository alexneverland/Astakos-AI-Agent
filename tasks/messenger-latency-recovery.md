# Bound Messenger recovery latency and expose Web mirror delay

Owner authorized repair after trace 088d5741: 320457ms total, 275112ms in
the first Messenger preparation decision, and a second 2139ms decision for the
same owner turn after an unrelated goal tool. No application retry/backoff.
Git history attributes the broad semantic recovery to PR262 (2026-10-27);
PR266 fixed structured answer parsing, not its scheduling.

Acceptance and implementation order:
1. Defer recovery during a non-Messenger tool-only response with no conversational
   candidate. Draft/send calls still require the recovery boundary before action.
   Reuse a decision only while owner dialogue, candidate and native draft/history
   guard are unchanged. A changed candidate can reveal missed mixed preparation.
   Never turn
   cached data into sending permission. Test actual graph writes and approval.
2. Apply an invocation-local 15-second HTTP request timeout to this tool-free
   classifier; Google gets exactly one SDK attempt. Keep main generation,
   other inference and global retry/config policies unchanged. Preserve
   fail-closed semantics. Verify installed SDK request options offline.
3. Persist/queue authenticated Web input before context-question inference;
   reuse that exact history identity in early and normal responses. Test the
   native mirror outbox while inference is blocked. Do not move provider work
   or external sending into the API's async event loop.
4. Expose mirror queue age and send duration without content/credentials so
   scheduler wait can be distinguished from transport wait. Existing scheduler
   is serial, but current snapshots do not prove it caused the reported delay.
   No runtime/watchdog changes or speculative scheduler rewrite in this slice.

Tests: isolated native draft/history stores and blocked external delivery,
new regression selectors first, then Messenger/approval/Web mirror groups;
git diff --check. No real messages, config or live flags changed.

## Verification

- 168 Messenger/offer/Web/context/mirror cases passed; 130 timing/provider/approval
  safety cases passed (eight overlapping cases at that point). 290 distinct
  relevant cases passed across those runs. The final affected Messenger group
  passed 110 cases after exact candidate-key alignment and provider-independent
  budget tests were added. No previously passing safety selector was excluded.
- Native Google request construction confirms timeout=15000ms and SDK total
  attempts=1. Main generation receives neither override. Other providers retain
  their SDK retry defaults with the invocation-local timeout.
- The project update regression covers success and helper timeout, one native
  goal tool execution and zero draft/send approvals. Draft/owner/candidate changes
  invalidate cached decisions. Existing mixed preparation, batched-send blocking,
  persisted revision approval and Web-failure provenance cases remain passing.
- The Web test reads its real temporary outbox from inside context inference:
  the owner copy already exists, with no duplicate owner history row. Synthetic
  mirror diagnostics distinguish 300000ms queue age from a 2000ms send attempt
  without logging display text. This does not retrospectively prove why the
  owner's earlier Matrix copy arrived late.
- No runtime/scheduler/watchdog policy, live message or cloud request changed.
  Real reply timing and any remaining mirror delay require subsequent observation.

# Partner context and GPS continuity

PR #288; initial reviewed head ea29567ccbd5d142cf81aad47d5f285678c661fa.
Owner authorized corrections after discussing family habits versus confirmed
company, and requested assessment of Codex feedback. No subagents or merge.

## Contract

- Off-work and owner-home flags alone cannot locate the partner. A declared
  household habit can inform a tentative conversational response, not persisted
  certainty. Explicit current reports, dated plans and contrary events govern.
- A shared-workplace/together report uses existing semantic extraction. No
  additional model invocation or lexical presence fallback is introduced.
- Same-value owner-location refreshes preserve fresh explicit together evidence.
  A genuine location transition can invalidate older company without guessing
  who travelled with the owner. Shared-travel reports remain authoritative.
- Duration proof anchors remain strict. The canonical context writers advance
  only an exactly matching continuous location anchor inside their transaction;
  any intervening value/expiry change invalidates the proof permanently.
- Freshness, history, expiry and GPS conflict validation remain required.
  Malformed or invalid proofs cannot erase fresh direct evidence. Optional
  transition-read failure is logged and cannot skip independent proof validation.

The existing generic context store records transition metadata without a schema
migration. Both single and conditional batch writers maintain it. No live data,
credentials, config, watchdog, release, or approval rules were changed manually.

## Evidence

Initial native-store/offline regressions reproduced ten failing cases before
repair. A separate contradictory-GPS regression also failed before its guard.
`tests/test_partner_context_review.py` covers off-work uncertainty, explicit
shared travel, work-mode uncertainty, continuous refreshes, malformed/expired/
history-invalid proofs, both writers' location round trips, transient read
failure with actual proof application, stale location and GPS conflict.

Verification groups: 173 context/extractor/reconciler cases; 162 related
evidence/daily-resolution/scheduling cases; final affected group 98 cases.
Groups overlap and must not be added as a distinct-case total. Final checks
include git diff --check and scoped staged-diff inspection. Live model semantic
accuracy is not established by offline mocked model decisions.

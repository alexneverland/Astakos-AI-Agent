# Owner-scoped quiet and household presence

## Evidence and scope (2026-11-20)

Started with a clean working tree on main at 811802d (#290). At 06:23 the
owner replied to a morning household question that he was already travelling
to work while everyone else remained home asleep. Stored quiet_hours and
partner_with_user became true. Polls reported quiet from 06:23 onward; the Sofia
message routine reported waiting_context at 10:45 and 10:55. The scheduled quiet
gate honors the stored daily mute, preventing a clarification.

Offline reproduction showed the deterministic family_at_home consistency block
overwriting explicit user_out_of_home=true and individual co-presence=false.
The old extraction contract also allowed another person's sleep to establish
owner silence without distinguishing their location or scope.

## Acceptance and implementation

- Preserve explicit owner whereabouts and individual relationship facts over
  aggregate family-home inference, including mixed clarification answers.
- Require bounded quiet_hours_basis metadata for a new true mute. The existing
  semantic call distinguishes owner_request, shared_rest and others_rest.
  Unsupported or missing scope cannot persist a new mute; valid unrelated facts
  still proceed through source/time validation and the canonical conditional
  writer. Metadata is not persisted as a context-state key.
- Preserve existing valid silence when an unsupported inference is discarded;
  explicit quiet requests outside home and explicit resume remain supported.
- Keep current quiet expiry, freshness, approval and outbound delivery gates.
  No phrase lists, extra model pass, runtime/config change or live state repair.

## Verification

Provider and outbound boundaries are replaced/blocked. Native temporary history,
routine stores and clarification ledgers exercise the final persisted outcome,
including the exact Matrix report and actual question resolution. These tests
verify extraction contracts and persistence, not a live model's interpretation.

- Initial reproduction: 9 failed, 1 passed before the production change.
- First focused group: 51 passed.
- Extended group: 203 passed, 1 failed due to a test seed using real current time
  after the historical reply. Source-order protection correctly rejected it.
  The fixture now seeds the prior quiet observation at the correct event time.
- Final affected/scheduler group: 106 passed, including all 18 new cases.
- 292 distinct relevant cases passed across these groups; git diff --check clean.
- Existing Chroma asyncio deprecation warning observed in related tests.

## PR #291 review corrections

Initial head 920390c received a completed Codex review with no findings. All five
Sourcery inline findings on that head were examined; behavior reproductions
failed six cases before the repairs (23 passed):

- 4641983068: Allow an empty flags map only in the ordinary source-bound
  validator. Still validate the exact envelope, latest source identity, support
  IDs and event freshness before independent routine reconciliation. A native
  temporary routine-pause test verifies the final saved pause; wrong, future,
  superseded and malformed sources remain rejected.
- 4641983078: Remove aggregate family-home defaults for individual location and
  company. Fresh canonical owner-away evidence rejects an ungrounded aggregate
  homecoming. A new explicit reunion still replaces earlier separation.
- 4641983085: Keep the existing whole-household meaning of family_at_home,
  including the owner. An explicit owner-away payload normalizes it to false,
  agreeing with the existing evidence reader instead of creating a conflict.
  Shared prompt guidance now states this contract for daily resolution too.
- 4641983090: Assert the entire previous quiet record is unchanged, including
  timestamp and expiry, after rejecting an unsupported sleep inference.
- 4641983096: Annotate every new fixture/test parameter and return value.

Verification after repairs: 303 relevant offline cases passed in one combined
run, including 29 owner-quiet cases (11 additional review cases). Native stores,
real clarification ledgers and blocked outbound transport remain in use.
git diff --check passed. The same existing Chroma deprecation warning remains.

Today's erroneous live flags and routine ledger were not modified, and no
message was sent or occurrence marked complete. The PR remains open for review.

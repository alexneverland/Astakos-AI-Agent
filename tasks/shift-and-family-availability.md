# Shift persistence and shared family presence

## Approved repair

The owner reported that the Sunday 2026-10-25 statement about next week's
morning shift and Tuesday's explicit reminder were acknowledged but did not
reach canonical routine state. Tuesday's football offer was blocked by an
unknown shift, then additionally by child-with-partner presence while the whole
family was together. The owner approved correcting both existing behaviors.

## Contract and slices

- [x] Reproduce live-message shift reconciliation with the real canonical
  store/resolver. Reuse semantic dated shift validation rather than expanding
  phrase lists. Preserve weekly expiry against ordinary same-value observations;
  allow explicit semantic corrections and cancellation. Reject stale writes.
- [x] Reproduce the football condition and nearby child activities. Shared
  child/partner presence alone must not exclude the owner when fresh evidence
  confirms the child is also with the owner. Other availability, completion,
  schedule and location conditions retain their own meaning.
- [x] Verify relevant offline persistence, evidence, clarification and scheduler
  paths; update the guide and Unreleased notes. Inspect diff and syntax.

Use Python annotations and existing native memory APIs. Tests use temporary
stores and model/transport boundaries; outbound network must fail loudly.
Command: `venv\Scripts\python.exe -m pytest tests/test_shift_family_availability.py -q`.
No schema migration, live data repair, credentials/config edits, runtime changes
or release is included. Passing deterministic model fixtures does
not establish live model interpretation quality.

## Verification (2026-10-27)

The initial regression run reproduced six failures: the current live semantic
shift bypass, same-value weekly expiry truncation, and shared-parent suppression
across four condition provenance variants. The shorter Sunday statement alone
could pass through a legacy fallback, so its apparent success was not proof that
the semantic live path ran.

Final focused verification: **392 passed**, including **24 new cases**, with
outbound network blocked. Coverage includes both real extraction stages, native
history/state persistence and the final routine condition resolver; explicit
shortening/cancellation, stale source/state races, missing/external provenance,
stale co-presence, and clarification dependencies. Syntax compilation and
`git diff --check` passed. One existing dependency deprecation warning remains.

The separate legacy `test_scheduler_e2e_conditions.py` group had 12 failures and
3 passes. All 12 failures reproduced with the four changed service modules
loaded from HEAD/main (`4522309`) in an isolated verification process: its
hand-built fixture lacks `context_state`, and an error-path connection prevents
Windows temporary-directory cleanup. This fixture maintenance remains outside
this repair; the passing clarification scheduler group is included in the 392.
No tests were skipped or disabled and no full suite or live provider run was
performed. Two existing context tests now provide trusted native history instead
of authorizing reconciliation from an unsaved string.

No live context/routine records were manually repaired. Historical statements
were read for diagnosis, not replayed into the live model or database. The owner
still needs natural observation of a fresh report after the source change.

## Publication authorization

The owner subsequently requested a PR and review-comment inspection. Publish
this scoped branch and inspect complete top-level, inline and issue comments.
No merge, branch deletion or automatic additional review cycle is authorized.

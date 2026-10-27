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

## Review repair (authorized after PR263 review)

Reviewed head: `6efa363ffbb328d7dca487e78df0aa2698be78d0`.
All eight Sourcery inline comments were inspected against that head. Six new
regressions initially failed for payload normalization, semantic expiry retention
and provider-error diagnostics. Additional native-store and full-handler tests
cover exact queued identity, custom history paths, later unrelated/correcting
reports and the final non-shift history guard.

- 4391416090: Preserve existing explicit non-shift routine handling instead of
  deleting it. Fence its final writes with the owner-history version. An older
  queued source can apply only a semantic shift decision informed by later
  reports. Live shifts no longer fall back to lexical shift-state rules.
- 4391416103: One observation-expiry policy covers both writers, including
  unbounded schedules. Validated semantic `schedule_revision=true` allows a real
  shortening; cancellation remains explicit. Missing revision means observation.
- 4391416116: Web/Telegram enqueue after saving the report, and all three channel
  paths carry the exact row and database path. No polling for an unsaved message.
- 4391416130: Normalize supported condition forms once and derive clarification
  dependencies from that same representation.
- 4391416134: Carry the explicit history path through ordinary extraction and
  queued reconciliation instead of reopening the global store.
- 4391416144: Record `live_shift_inference_failed` with only the error type.
  Keep known state and fail closed; no automatic cloud retry cycle.
- 4391416156: Assert accepted observation writes as well as retained expiry.
- 4391416163: Seed state before the report and assert the model callback plus
  the actual CAS rejection. The original review's claim that inference never
  runs was inaccurate: that timestamp check followed inference. The stronger
  test now distinguishes history rejection from state-CAS rejection.

Final review-repair verification: **517 distinct offline cases passed** in two
focused groups (404 context/routine cases; 113 Matrix/Web handler cases), with
outbound transport blocked. Syntax compilation and `git diff --check` passed.
No live data or runtime intervention, no full suite, and no extra review request.

# Behavioral reply and mistaken completion repair (2026-10-29)

Owner approved repair after read-only diagnosis: Behavioral_Agent asked at
08:08 whether the owner plays football with a regular group. At 08:26 the owner
answered that he and his child play at the park with other children. This was
mistakenly recorded as today's park completion. At 08:29 the owner explicitly
explained this was an answer about their habit, not current activity; the
assistant acknowledged the correction but the ledger remained complete.

## Contract and boundaries

Use the existing bounded one-hour shared-history reference horizon for ordinary
assistant commentary too, preserving provenance and source order. Habitual
answers are not reports of current execution. No phrase lists, synonym rules,
live provider calls or TTL changes to stored state.

Add a strict single-action `retract_complete` decision for an explicit correction
of a mistakenly recorded completion, against a known occurrence only. The native
ledger must check its revision, owner-turn freshness, an existing completion and
older feedback timestamp under the write lock. Clear completion feedback and
recompute its projection, preserving actual delivery and routine configuration.
Ordinary cancellation, location changes or commentary criticism cannot implicitly
undo completion. No batch retractions, external permissions or schema migration.

Initial implementation excluded live edits and publishing. The owner subsequently
authorized removing today's exact mistaken park completion and opening the scoped
PR. Credentials/config/runtime changes, context writes, unrelated cleanup, merge
and branch deletion remain outside this request.

## Ordered verification tasks

1. Reproduce the exact delayed cross-channel answer with intervening briefings;
   verify the original opener reaches semantic selection and habit feedback is
   none, while an actual current arrival can still complete the routine.
2. Reproduce explicit correction of a real temporary completion through the
   production handler/selector/store. Verify final feedback is absent and receipt
   history remains; reject missing completions, stale revisions/history, unknown
   dates, untrusted input and ordinary skips attempting to overwrite completion.
3. Run relevant existing feedback, selector, reference and pressure tests with
   outbound transport blocked; compile changed Python and run git diff --check.
   Update current documentation and Unreleased notes.

Commands: `venv\Scripts\python.exe -m pytest tests/test_behavioral_reply_feedback.py
tests/test_routine_comment_corrections.py -q --basetemp=.pytest_tmp_behavioral_reply`;
`git diff --check`. Tests use temporary SQLite/history via native abstractions;
typed Python follows surrounding code (for example
`def retract_completion(..., expected_revision: str, ...) -> bool`).

Offline provider fixtures verify prompt data and persisted lifecycle, not live
model semantic quality. Natural observation remains necessary after deployment.

## Verification outcome

- Delayed question propagation failed before repair; explicit correction through
  the real selector/handler kept the completion before repair. Six native guard
  cases initially failed because no retraction API existed.
- 313 distinct feedback/reference/store/identity/policy/activity cases passed,
  including 22 new offline cases. Provider fixtures inspect the full original
  question, candidate evidence and final persisted outcome across all channels.
- Channel/runtime/dispatch/helper coverage: 219 passed, one legacy Matrix draft
  test failed in the combined order. The same 219/1 result was reproduced with
  affected behavior loaded from main 1a9133187091b1df0b57de8d60661feb927a518d
  inside an isolated pytest process. Matrix's complete nine-case file passes
  independently, covering 533 distinct relevant passing cases across groups.
  This known order-dependent draft test remains out of scope; it is not skipped.
- Removing the retraction freshness check in an in-memory isolated mutation made
  the stale-turn safety regression fail. Production source was never mutated.
- Compilation and git diff --check pass. Documentation and Unreleased updated.
  No live data, provider or transport operation was performed during tests. Two existing
  dependency deprecation warnings remain in the focused feedback group.

## Owner-authorized live correction and PR

On 2026-10-29 the owner explicitly requested correction of today's mistake and
PR publication. Through load_initialized_feedback_store/get_connection and the
new native retract_completion API, routine 3 (park) was checked against its
exact completion timestamp 2026-10-29T08:26:57.533685+02:00 and current revision.
The latest trusted owner history row was still 8071. The guarded write cleared
only that date's completion/feedback timestamp. Readback verified feedback null,
delivery still null, every other park date unchanged and routine identity/settings
unchanged. The canonical completion_retracted event records the correction.
No context flags, history messages, other routine outcomes or baselines were
manually changed. This manual repair is separate from offline verification and
does not claim a live-model interpretation test.

## Codex follow-up: completed reminder replies

Review 4409627298 at 7996ccb correctly identified that an explicit reply to a
completed reminder returns before inference: pending_question excludes complete
feedback, although receipt ownership still routes that exact reply here.
Owner authorized this narrow repair. Reuse one canonical delivered-question
resolver with a completed-only mode requiring an explicit authenticated channel
and receipt. Only when no pending question exists, resolve the completed target
for correction-only selection, limit candidate dates to its exact occurrence,
and reject all concrete actions except a single retract_complete. Recheck the
same correlation, candidate revision and owner history before committing.
Unknown receipts and external approvals remain closed; normal pending feedback
keeps its existing resolver and permissions. No additional live data repair.

Verification: 16 new native reply cases (13 initially failed / 3 guards passed).
After repair, 329 feedback/store/reference cases, 211 channel/runtime/dispatch
cases, and the nine-case Matrix file passed separately: 549 distinct relevant
cases, with outbound sockets blocked. Exact current/past receipts invoke the
production selector; wrong date/channel/receipt, untrusted input, owner/ledger
races and non-correction actions preserve completion. Compile and diff checks
pass. The previously reproduced combined-order Matrix draft failure remains
documented above; no tests were skipped or unrelated fixtures changed.

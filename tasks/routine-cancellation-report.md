# Mixed routine outcomes (2026-10-13)

## Evidence and objective

Owner authorized fixing the first report at 15:39:55: work finished and today's
football cancelled because of rain. The live ledger did record completion of
routine 765 (work finished), but football 13 remained open until the repeated
16:55 report. A read-only configured-model diagnostic also selected completion
765 alone. Its input omitted later same-day ledger outcomes; this is a current
diagnostic, not a recovered original model response.

The canonical contract admits multiple completions only, so a message containing
completion plus cancellation cannot record both. Extend that same bounded path
to complete and skip_today only, interpreting every current clause semantically.

## Scope and acceptance

- Two to five distinct, clearly identified local outcomes may include completion
  and today's cancellation. One canonical validator checks every ID/date/action.
- Commit all outcomes atomically through the native ledger, retaining history,
  receipts, freshness/revision checks and protection against undoing completion.
  Recorded cancellations close today's occurrence before any new question.
- Bare weather, conditional plans and ambiguous identities cannot invent skips.
  Pause/defer/acknowledgement, drafts and external permissions cannot enter a
  batch. Expired state-question replies retain their completion-only safeguard.

## Plan and checks

1. Reproduce mixed outcome rejection offline through the real selector/handler
   and isolated native stores, with exact report and nearby negative cases.
2. Extend canonical validation and the existing atomic writer; update semantic
   contract and truthful graph acknowledgement, without phrase lists.
3. Verify races, rollback, replay, closed occurrence IDs and unchanged receipts;
   run relevant feedback/channel suites, compile and inspect diff.

Command: venv\Scripts\python.exe -m pytest tests/test_routine_cancellation_report.py
-q --basetemp=.pytest_tmp_cancellation_report

Source: services/routine_completion_helper.py, routine_feedback_turn.py and
prompts/routine_feedback_selector.md; persistence: memory/routine_feedback.py;
tests: tests/test_routine_cancellation_report.py; documentation: routine guide and
Unreleased. Follow existing typed Python/native ledger conventions.

No live ledger repair, schema migration, config/credentials, runtime/watchdog,
release, schedule edits or subagents. Tests mock providers and prohibit outbound calls.

## Verification

- RED: three exact-report cases (Matrix/Web/Telegram) rejected the mixed protocol
  before the change. GREEN: completion and skip_today persist together, both
  occurrence IDs close, replay stays idempotent and graph context lists both.
- 28 new offline cases cover invalid actions/IDs/dates, duplicate/oversized
  batches, history/catalogue races, untrusted source, completed-occurrence
  protection, rejected writes/rollback, expired reply safeguard, prior receipts,
  historical completion and semantic-contract negatives for bare weather/plans.
- Final feedback/store/identity/runtime/freshness/activity group: 306 passed.
  Separate Matrix/Web/Telegram completion group: 113 passed. Total 419 distinct
  related offline cases. Existing google.genai/Chroma deprecation warnings only.
- Removing rollback in an in-memory mutation caused the expected write-rejected
  regression to fail because the first completion leaked. Source was not mutated.
- After the semantic-contract update, the same configured-model diagnostic
  selected complete 765 and skip_today 13 on 2026-10-13. Neither diagnostic wrote
  feedback or sent messages. One successful diagnostic is not a guarantee of all
  future interpretations; the offline provider seam verifies final persistence.
- Compilation and git diff --check passed; guide and Unreleased were updated.

No today's live outcomes or routine schedules were changed. Owner subsequently
authorized creating the PR, monitoring reviews, fixing verified findings,
requesting another review only when warranted, then merging and deleting only
codex/routine-cancellation-report after required checks and known findings clear.

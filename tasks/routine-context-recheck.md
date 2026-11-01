# Temporary routine context skips (2026-10-10)

Owner authorized repairing the missed sleep routine and discarded comment.
At 21:25 the owner reported dinner and a new chair; at 21:45 all conditions
passed for the 22:00 sleep routine, but the model chose a context note. A
second model discarded it and last_triggered consumed the whole day.

Acceptance and implementation order:
1. Reproduce the skip with temporary real routine/feedback stores and mocked
   inference/transport. A temporary skip leaves the occurrence undelivered and
   eligible for reassessment, at most once per lead-window stage in its existing
   fifteen-minute window (five-minute stages initially, final-minute recheck).
   Durable claims prevent repeated polling/restarts.
2. Supply current time and scheduled slots to wording. Semantic instructions
   distinguish a preparation reminder from an activity happening immediately;
   unrelated earlier activity is not cancellation or rescheduling evidence.
3. Reuse a generated CONTEXT_NOTE through the existing canonical note path;
   retain the 30% chance, occurrence reservation, freshness, silence, channel,
   budget, receipt/history and uncertain-send guards. Plain CONTEXT_SKIP still
   lets the note classifier decide whether a comment is worthwhile.
4. Verify real scheduler persistence and transport isolation, actual generated
   note delivery/history, repeated polls, continued conflict and changed safety
   state. Run focused routine tests and git diff --check, update the guide.

No phrase lists, live ledger corrections, database migrations, configuration,
runtime/watchdog changes or live provider/messages. Offline model fixtures prove
the lifecycle; natural model interpretation still needs live observation.

Verification:
- Initial six regression cases failed before production changes (day consumed,
  no prepared-note entry point).
- Real storage/scheduler/note/condition group: 179 passed; legacy scheduler and
  completion group in its own process: 103 passed. Final exact sleep scenario,
  prepared-note safety and concurrency selection: 31 passed, including one new
  concurrency test (283 distinct covered cases overall).
- Existing legacy test stubs lacked the trace directory required by shared
  test isolation; added that attribute to their fake modules only.
- Provider-boundary test verifies both timestamps and the recorded dinner
  context reach the real prompt; semantic inference itself remains mocked.
- Python compilation and git diff --check passed. No live delivery or ledger
  correction was performed. Work remains local on codex/routine-context-recheck.

PR #247 review on 360294a: both inline findings reproduced (six failing cases).
The fourth stage now covers the final minute instead of requiring an exact
scheduled instant; offset-clock single/batch tests verify persisted delivery.
Empty CONTEXT_NOTE payloads remain empty through canonical validation rather
than adopting the internal diagnostic sentinel.
Review repair checks: 190 real-storage/scheduler/note/condition cases and 103
isolated legacy cases passed, plus four final empty-marker cases exercising the
real note validation path. Compilation and diff checks passed.

The second completed review (f0a6f69) identified an incident-specific production
prompt example. Removed that paragraph while retaining the general temporal
rule; the exact incident, a paraphrase and a conflicting-plan variant now remain
only in provider-boundary test fixtures. All three failed before removal.
These tests verify context propagation, not live model semantic accuracy.
All 105 isolated legacy scheduler/completion cases and diff checks passed;
combined with the previously verified 190 cases, 295 distinct cases are covered.

# Reminder delivery and deferred regression maintenance

Owner approved repair on 2026-10-09 after the three deferred failures were
reproduced against merged OwnTracks main. No subagents, live messages, real
database edits, credentials, Docker or configuration changes are included.

## Findings and repairs

- The legacy time-reminder test mocked only Telegram. It now mocks the canonical
  assistant delivery boundary and supplies a synthetic confirmed event ID.
  Unexpected external delivery fails loudly in this offline test module.
- The live GPS test expected value deduplication. Every trusted observation must
  refresh evidence time, including consecutive identical values. Its assertion
  now includes both away observations; production GPS behavior is unchanged.
- Location-memory functions committed their SQLite context managers without
  explicitly closing connections. An outer `closing` now closes on success and
  failure, retaining transaction commit/rollback behavior.
- An additional real defect was reproduced: the timed worker marked a reminder
  done after `_send_and_record_assistant` returned no delivery ID. Completion and
  sent-event logging now require confirmation. The Telegram location callback
  also propagates a missing delivery ID as failure to the shared pipeline.

## Verification

Five new regressions failed before repair: timed delivery failure in both Matrix
and Telegram, Telegram location failure, and explicit connection closure on
success/failure with retained references so garbage collection cannot mask leaks.

After repair, 100 tests passed across delivery maintenance, SQL reminders, Matrix
locations, OwnTracks, assistant delivery and external transport routing. One
pre-existing Google dependency deprecation warning remains. SQLite tests use
temporary stores; transport adapters are mocked, with no real outbound messages.

No reminder history was backfilled and no previously completed owner reminder
was manually reset. Existing assistant-history repair behavior is retained:
confirmed delivery remains confirmed even when recording is queued for repair.

## PR #244 dedup review repair

The real dedup cache reserved the message before attempting transport, delaying
retry for 60 seconds after failure. Replacing the mocked dedup in both channel
regressions reproduced this at the next 20-second tick. Canonical reservation
and conditional release now remove only the failed attempt's claim; successful
delivery retains the cooldown and a late release preserves a newer claim.
Existing `is_duplicate_notification` behavior remains compatible for other users.

Final check: 116 passed across the previous reminder/location/transport checks
plus event-log/missed-routine tests, with one existing dependency warning.

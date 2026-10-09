# Routine feedback and notification backoff

Status: behavioral contract approved by owner, 2026-10-07, including escalation
0 -> 20 -> 40 -> 72. Implementation planning is recorded in
routine-feedback-plan.md; owner approved the additive occurrence table. No live
reset has been performed. Existing plan/todo verification items remain unchanged.

## Objective

Separate notification preference from confidence that a routine is a real habit.
Use one date-aware feedback path for Web, Telegram and Matrix. Preserve natural
language interpretation; do not introduce phrase lists.

## Behavioral contract

- Count only successfully delivered reminder occurrences, once per routine and
  occurrence date. Provider/transport failure, offline time, condition blocking,
  quiet hours, pause, mute and cooldown are not unanswered deliveries.
- A delivery becomes unanswered only after the end of its occurrence day in
  Europe/Athens, not after the existing 30-minute conversational response window.
- Three consecutive unanswered delivered occurrence-days increase notification
  backoff, without reducing confidence. Nondelivery days do not add failures.
- Three consecutive explicit skip-today occurrence-days increase backoff using
  a separate counter. Never combine refusals and silence into one failure streak.
- Approved backoff levels: 0 -> 20 -> 40 -> 72 hours, capped at 72. This makes
  escalation from the owner's zero baseline meaningful.
- Acknowledgement is engagement, not completion. It clears unanswered pressure
  and backoff without falsely recording execution. A deferral must not create an
  arbitrary new reminder time: clarify timing when needed through the existing
  conversation flow.
- Completion before a prompt suppresses that occurrence's reminder. Completion
  after the response window, or a later explicit report of a past occurrence,
  updates the correct dated occurrence and reconciles its unanswered/refusal
  accounting. Uncertain dates or identities require clarification; do not guess.
- Permanent opt-out pauses the exact routine on the first explicit request;
  preserve the routine for later reactivation.
- Confidence describes evidence for the habit. Silence, skips, deferrals and
  temporary schedule/context changes do not reduce it. Do not invent a numeric
  confidence penalty from ambiguous contradictory evidence. Reuse explicit
  schedule correction/cancellation paths and clarify uncertainty.
- Confidence updates and dated completion must have the same meaning across
  channels and whether or not a response window remains pending.
- Separate same-occurrence delivery deduplication from elapsed-hour backoff.
  Zero cooldown and acknowledgement must not permit a second reminder for an
  already delivered occurrence, including restart and cross-channel handling.
- Debug must expose the final dispatch decision and blocker independently of
  condition-evaluation success; later successful condition checks must not hide
  a cooldown decision for the same occurrence.

## Owner-authorized final reset

Only after implementation and focused offline verification, use a canonical
memory-layer operation to set existing routine cooldowns to 0 and confidence to
1.0, and clear old notification-pressure counters. Produce a scoped recoverable
snapshot first and verify readback through the same abstraction.

Preserve routine IDs, times, conditions, pauses/mutes, completed dates, delivery
receipts and history. Do not reactivate paused routines or replay delivered slots.
Do not erase historical facts. Existing pressure must not reapply immediately
after reset: the reset needs a baseline boundary in the accounting model.

## Project structure and implementation boundaries

- memory/: canonical dated feedback persistence and explicit reset abstraction.
- services/: shared semantic selection, feedback orchestration and dispatch gates.
- api/server.py and clients/telegram_bot.py: thin channel adapters and diagnostics.
- prompts/: semantic intent/date contract, retaining trust and provenance boundaries.
- tests/: focused offline temporary-store regressions; no production DB fixtures.
- tasks/: approved specification and subsequent ordered plan/checklist.

No credentials, config.py, Chroma, unrelated runtime/watchdog or backup changes.
Do not run raw SQL against live databases. A required schema migration is a
separate explicit approval gate after its exact scope has been presented.
Remove obsolete cooldown paths only after verifying all references and preserving
necessary compatibility. Do not bundle unrelated cleanup or Git publication.

## Code style

Keep typed, documented canonical operations with injected clocks and date-aware
identifiers, for example:

```python
def reconcile_feedback(routine_id: int, occurrence_date: date, *, now: datetime):
    """Reconcile one dated occurrence without counting a delivery twice."""
```

This illustrates the boundary, not a prescribed implementation or approved API.

## Testing and verification

Use pytest through the project venv, starting with failing regressions. Mock the
provider and transport boundaries and fail loudly on outbound calls. Test final
persisted state, not merely selector mocks. Use injected Athens clocks and
temporary storage for day rollover, restart, concurrency and delayed reports.

Focused baseline command:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_routine_db_connection.py tests/test_routine_completion_helper.py tests/test_routine_completion_web.py tests/test_routine_completion_telegram.py tests/test_matrix_routine_completion.py tests/test_routine_dashboard.py --basetemp=C:\Users\PC\.pytest_temp\routine-feedback -q
git diff --check
```

Extend the focused list with the new occurrence-ledger/dispatch regressions.
Do not run the entire suite by default. Live observation is separate evidence;
do not send test notifications or actuate tools during offline verification.

## Acceptance scenarios

1. Monday/Tuesday/Wednesday delivered but unanswered: no penalty before each
   day closes; third closed unanswered occurrence increases backoff once.
2. Delivered but acknowledged, or completed before/after the response window:
   no unanswered penalty and no duplicate reminder for that occurrence.
3. Afternoon report of morning rabbit care, and next-day explicit report of
   yesterday's care: correct dated completion, reconciled pressure, no false
   completion of today's occurrence.
4. Explicit opt-out pauses immediately; three skips escalate separately;
   postponement is not refusal and ambiguous timing stays unguessed.
5. Failed/uncertain delivery, stale classifier result, restarted scheduler and
   concurrent feedback do not fabricate completion, failures or duplicate sends.
6. Zero cooldown is preserved by getters (no `value or default` coercion),
   while per-occurrence deduplication remains effective.
7. Final reset changes only the approved confidence/backoff baseline, preserves
   safety gates and history, and has verified abstraction-level readback.

## Open decisions before implementation

- Persistence design/migration, if necessary, must be scoped and approved before
  any production migration. Implementation planning follows spec approval.

## Dated identity evidence extension (2026-10-09)

Owner-approved repair: the 09:31 afternoon-departure reminder was acknowledged,
but the 10:04 actual departure selected the undelivered morning variant. Names
alone do not identify variants reliably after the pending response window expires.

Supply the existing semantic selector with each candidate's persisted schedule,
conditions and newest eight dated delivery/feedback occurrences, captured alongside
its existing revision on one read snapshot. Expired delivery/acknowledgement remains
identity context, never completion or renewed send authority. Current explicit
identity/date overrides implicit continuity; ambiguity requires clarification.
Dispatch conditions and paused status do not prohibit a report of actual execution.
Reject stale decisions if any compared routine/outcome or named candidate set
changes during inference, including the final transaction freshness check.

Regression scope: exact reported departure, preparation, explicit other variant,
ambiguous identity and candidate/outcome races across Web, Matrix and Telegram.
Use temporary stores and mock inference; assert both final dated outcomes.
No phrase lists, schema change, historical correction, live send or runtime change.
Live provider interpretation and owner-requested correction of today's mistaken
record are separate follow-ups.

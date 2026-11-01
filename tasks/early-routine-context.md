# Early scheduled routine context (2026-10-13)

Owner approved correcting the interaction between explicit morning schedules and
context clarification. Routine 6 is scheduled at 06:30. On 2026-10-13 it was held
as context_unknown at 06:15 and 06:26, while every clarification poll was quiet.
The morning shift remained current through 2026-10-16. No delivery was recorded.

Scope: distinguish default quiet-window suppression for spontaneous proactive
messages from an explicitly scheduled routine and its bounded required context
question. Preserve explicit current quiet requests, global/routine mute, pause,
runtime ownership, recent activity/reminder, confirmation, budget, provenance,
condition, source-version and deadline checks. Never treat unknown as false or
send a question after the slot. A greeting alone grants no location facts.

Plan: reproduce 06:15 question followed by guarded 06:20 reminder on isolated
canonical stores for Matrix/Telegram; introduce one canonical scheduled quiet
policy reused by clarification and final routine dispatch. Verify explicit quiet
and every other gate, including quiet arriving during inference and expired
requests. Then run relevant suites, compile and inspect diff/update Unreleased.

Use existing source worker and pytest; no new scheduler, phrase lists, config,
credentials, live-data repair, schema migration, runtime/watchdog or release
changes. No subagents. Default quiet-window hours remain unchanged. Provider and
transport boundaries are mocked; accidental network calls fail. Commands:
venv\Scripts\python.exe -m pytest tests/test_early_routine_context.py -q
--basetemp=.pytest_tmp_early_context
Live model interpretation still requires natural observation.

## Verification (2026-10-13)

- The original gate reproduced zero questions at 06:15 for both external
  channels. The regression follows real isolated question persistence, resolution,
  final scheduled dispatch and dated delivery receipt; repeat ticks do not resend.
- 25 new offline cases cover Matrix/Telegram, active/expired explicit quiet,
  quiet arriving before or during reminder wording, malformed active quiet,
  global/routine mute/pause, runtime ownership, activity/reminder/confirmation,
  budget, known absence, preparation-window and deadline guards.
- Final related group: 172 passed (the new cases plus context, worker and
  scheduler suites), with one existing google.genai deprecation warning.
- An in-memory mutation that ignored active explicit quiet failed the expected
  regression (one failed, two passed); production files were never mutated.
- Python compilation and git diff --check passed. Unreleased notes and the
  routine guide describe the distinction from spontaneous proactive messages.

No real messages were sent or live ledger/context/config/runtime data repaired.
This does not recover today's missed occurrence or prove future model wording.
Owner requested a pull request on codex/early-routine-context after verification.

## PR #251 review correction (2026-10-13)

Codex comment 4254826958 correctly identified that optional context notes also
reuse final scheduled dispatch validation. Their freshness predicate now checks
ordinary quiet hours both before reservation and after wording, preserving the
scheduled exemption only for required questions and actual reminders.

Eight new cases exercise real optional-note delivery/history on both channels,
at 06:15 and outside quiet hours, with newly generated and already prepared notes.
Before the fix, all four quiet-window cases incorrectly sent; the four outside
quiet cases passed. Final context/note/worker/scheduler group: 238 passed, one
existing google.genai deprecation warning. Existing post-inference quiet tests
also pass. Compilation and git diff --check passed. No live data was changed.

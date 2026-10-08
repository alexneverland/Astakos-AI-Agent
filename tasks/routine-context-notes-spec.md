# Routine context notes

## Objective

Preserve a blocked routine while optionally sending a brief, emotionally useful
comment in Astakos' normal conversational voice. This extends the existing
routine scheduler, not behavioral initiatives, follow-ups or context questions.

## Approved intent and proposed boundaries

- Never turn a failed routine condition into permission to execute its action.
- Replace the event-name keyword whitelist and the separate permanent
  sentimental classification with one tool-free, structured model decision.
- Give that decision the exact routine, fresh canonical context, failed
  conditions and bounded shared conversation as provenance-wrapped reference.
- The model may return no note. An eligible note is one or two short sentences,
  not a reminder, question, completion claim, draft offer or external action.
- Preserve explicit sentimental silence, routine pause/mute, quiet hours,
  active-channel selection and existing proactive activity/rate limits.
- Being at work or on a different shift blocks the incompatible routine action,
  not automatically the optional comment. The model must judge whether a comment
  fits that context; it must never urge an incompatible activity.
- Missing or stale evidence is not proof of a meaningful conflict: retain the
  existing clarification flow instead of inventing a reason or sending a note.
- Use one 30% chance gate, as approved by the owner, rather than
  multiplying the legacy 30% and 70% gates. Evaluate at most once per routine
  occurrence; a skipped chance must not get another chance every scheduler tick.
- No new background job, dependencies, live-data migration or pressure reset.

## Delivery and state contract

Use the same note decision for explicitly blocked conditions and semantic
context skips. Keep the normal reminder path separate. Recheck authoritative
context, occurrence eligibility, silence and channel after model inference.
An intervening completion or newer context makes the result obsolete.

Record note evaluation/delivery separately from routine feedback. A note must
not open a pending confirmation, mark completion, count as an ignored reminder,
raise cooldown or lower confidence. Repeated polls/restarts must not resend a
confirmed note. Preserve confirmed transport delivery even if history recording
fails; uncertain delivery must not be blindly repeated. Reuse existing storage
and delivery abstractions; any necessary schema change requires owner approval.

## Scope and conventions

Expected source: `clients/telegram_bot.py`, a focused service if needed, and a
prompt under `prompts/`. Extend the shared scheduler used by Telegram/Matrix;
do not build channel-specific alternatives. Tests live under `tests/`.
Use typed functions and explicit structured validation, for example:

```python
def choose_context_note(packet: dict[str, object]) -> str | None:
    """Return a validated optional comment, never a routine action."""
```

Do not edit `config.py`, settings, credentials, vendor sources, runtime or
real SQLite/Chroma data. Do not remove unrelated legacy code in this slice.

## Acceptance and focused verification

1. An emotionally relevant known blocker can yield a single natural note while
   the routine remains blocked. Unrelated blockers yield none; work/shift
   blockers may yield a relevant comment but never an incompatible reminder.
2. Refusal, quiet hours, mute, stale/unknown state, completion during inference,
   changed channel and invalid/provider-error output cause no delivery.
3. Repeated polls, restart and history-recording failure do not create duplicate
   notes or routine pressure; no pending confirmation or action is created.

Use isolated history/occurrence stores and mock only model/transport boundaries.
Exercise both active external channels without contacting providers or sending
live messages. Existing silent-skip and dated-routine regressions remain covered.

Focused command (add the new note test file when authored):

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_silent_skip.py -q --basetemp=C:\Users\PC\AppData\Local\Temp\astakos-context-notes-tests
git diff --check
```

No full-suite run. Live interpretation remains owner-observed after deployment.

## Approval

The owner approved the 30% single gate and removal of the work/shift comment
exclusion on 2026-10-08. Explicit silence remains authoritative. Implementation
uses the existing clarification ledger's bounded evaluation records without a
schema migration. An occurrence is held before chance, model inference or send:
provider failure or uncertain transport sacrifices that optional comment instead
of risking duplicates. Confirmed-history failures queue existing history repair;
the held occurrence prevents resend even if that repair cannot be queued.
Offline verification is recorded in `tasks/todo.md`; live model wording remains
owner-observed and is not established by those tests.

# Reminder approval and execution feedback

Approved scope: 2026-10-09, owner requested both repairs after the recorded Matrix
voice request to collect meat before leaving work.

## Contract

A newest trusted owner reminder creation instruction can bypass escalation caused only
by older external content. A tool-free semantic check must ground the proposed
action, task and schedule in that instruction and bounded trusted owner context.
It must fail closed on ambiguous external references, unsupported/malformed
decisions, model failures or provenance-marked current inputs. Same-turn external
tool results retain their existing block; external sends and other tools retain
their approval policy. Updates and completion retain the existing policy. No
phrase lists or global risk changes.

After an approval executes, Matrix renders the reminder's actual result and task,
without claiming success for a returned failure. Persist the reply once in the
originating Matrix history through the canonical conversation API, retaining
external-source provenance when the approved task came from external content. Existing Web
and terminal approval paths remain compatible. Reply approval remains tied to a
trusted device and the exact pending prompt; no new reaction approval mechanism.

## Ordered slices

1. RED: reproduce the exact voice wording after unrelated search-memory history,
   then guard ambiguous references, changed arguments, fresh external results and
   model failure. Add the semantic adapter and narrow approval exception.
2. RED: execute a real reminder against temporary storage through pending approval,
   render its actual result/task and verify persisted history and duplicate handling.
   Preserve reminder errors and unrelated approval output behavior.
3. Run focused approval, provenance, Matrix, reminder and terminal regressions;
   update this checkpoint and the relevant current documentation.

Verification: `venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
tests/test_reminder_approval_feedback.py tests/test_reminder_intent.py
tests/test_untrusted_tool_content.py tests/test_matrix_runtime.py
tests/test_matrix_approval_reactions.py tests/test_approved_terminal_continuation.py
tests/test_reminders_sql.py` and `git diff --check`.

Python typed helpers, normal prompt files and existing localized result rendering.
All tests use temporary stores and mocked model/transport boundaries. No Android
device, live owner-data edits, actual sends, credentials, runtime/watchdog changes,
Git publication or new release was included in the initial repair authorization.
The owner subsequently authorized creating the scoped PR; merge and a new release
remain separate instructions.

## Implementation evidence

- Initial regression run reproduced four defects: stale-history escalation,
  discarded actual schedule/task, discarded tool validation error, absent Matrix
  outcome history. The fresh-external-content negative case already passed.
- `services/reminder_intent.py` uses an unbound model and a strict two-boolean
  decision; duplicate/extra keys, generated tools, invalid output and provider
  failure retain approval. Only bounded trusted owner messages are supplied.
  The latest synthetic/provenance-marked human turn cannot reuse an older request.
- Real reminder-tool tests use temporary stores, covering direct execution,
  approved execution, resulting reminder contents, reply history deduplication,
  and external-source provenance retention. They do not prove live model quality
  or delivery to Element.
- Baseline comparison loaded HEAD's three modified production modules only inside
  a separate test process. Both unrelated failures also occur without this repair:
  `TestLocationReminders::test_live_location_updates_out_of_home_only_on_home_boundary`
  (duplicate out-of-home write), and
  `TestLeaveCurrentLocationReminders::test_fires_after_exit_and_completes_reminder`
  (Windows locked temporary SQLite cleanup). No GPS/runtime changes included.
- Legacy Telegram reminder-delivery tests require `ASTAKOS_EXTERNAL_CHANNEL=telegram`
  in the test process; owner-selected Matrix has no live transport in offline tests.
- The additional Matrix transport run passed its approval/Reply and trust checks;
  one unrelated context-clarification test also fails on HEAD because it patches
  the removed `context_extractor.load_recent_trusted_user_messages` symbol.
  Final counts are recorded below. Syntax parsing and `git diff --check` passed.
- Final focused run: **193 passed**, two existing dependency deprecation warnings,
  covering reminder grounding/persistence, untrusted-content gates, Matrix approval
  service/delivery/runtime and approved-terminal compatibility. Expanded transport
  run: 230 passed and the independently reproduced old context-test failure;
  legacy reminder run: 26 passed and the two independently reproduced GPS/cleanup
  failures. These old failures were not suppressed or changed in this slice.

## PR #242 review repair

Sourcery's history-write failure was reproduced before repair. Matrix-origin
approved reminders now atomically claim execution in the existing approval store,
then retain the actual completed result there until canonical history succeeds.
Startup/30-second recovery retries only history, without tools, providers or sends.
Stable history identity handles interruption after history commit but before
receipt removal. Completed receipts are not subject to pending approval expiry.

An interruption during tool invocation or before the result receipt commits cannot
establish whether execution completed. Its durable `executing` claim remains
non-actionable and is never automatically rerun. Recovery does not invent success
or perform a live data repair; resolving uncertain executions requires inspection.
Other tools and origins keep their existing execution/persistence behavior.

Verification after this review repair: **245 passed**, two existing dependency
warnings. The added recovery tests use the real reminder tool and temporary
canonical history/store files. They cover failed history writes, lost in-memory
responses, concurrent/uncertain execution, receipt cleanup failure, expiry and
pending-file failures, plus startup/periodic retry. No real Matrix delivery is
performed by these tests or by history recovery.

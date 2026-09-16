# Implementation Plan: Trusted Matrix Text Channel

Module id: `matrix-text`

## Overview

Implement Matrix text support in four narrow checkpoints. Start with offline
state and transport contracts, then add the Matrix application turn pipeline,
and wire runtime startup only after the lower layers pass independently.

The first implementation uses `matrix-nio[e2e]==0.26.0`, a dedicated Matrix
service account, one allowlisted owner, and one allowlisted encrypted room.

## Architecture decisions

- Keep Matrix protocol types inside `clients/matrix_client.py`.
- Inject an async turn handler into the transport; the transport does not
  import the LangGraph application.
- Put durable inbound/reply lifecycle state behind
  `memory/matrix_event_state.py`, using the existing `STATE_DB` connection
  boundary and a unique Matrix event id.
- Add a same-channel mode to the existing conversation-history abstraction
  rather than creating another history store or changing current Web/Telegram
  behavior.
- Put graph invocation and Matrix persistence in `services/matrix_turn.py`.
- Keep startup wiring last and select exactly one external transport through
  `resolve_external_channel()` while Web remains available.

## Durable event lifecycle

The state abstraction exposes transitions equivalent to:

1. `reserve(event_id, room_id, sender_id)` inserts `processing` exactly once.
2. `store_reply(event_id, reply_text)` changes `processing` to
   `reply_pending`.
3. `mark_replied(event_id)` changes `reply_pending` to `replied`.
4. `list_reply_pending()` returns saved replies for safe resend.

An existing `replied` or `reply_pending` event never invokes the graph again.
An event left in `processing` after a crash is reported for manual recovery and
is not automatically replayed. Secrets and decrypted user content are not
stored in this lifecycle table; only identifiers, status, saved assistant
reply, timestamps, and a redacted failure field are allowed.

## Build order

### Checkpoint 1: durable state contract

1. Write failing offline tests for reservation, unique event ids, legal state
   transitions, persisted reply recovery, and fail-closed stale processing.
2. Add the minimal state abstraction and schema to `STATE_DB`.
3. Run the focused state tests and `git diff --check`.

Approval gate: this checkpoint changes the existing state-database schema.

### Checkpoint 2: Matrix transport contract

1. Add the pinned E2EE SDK dependency and run a Python 3.14 import smoke test.
2. Write failing tests with a fake Matrix SDK client for allowlisting,
   encryption, initial-sync barrier, unsupported-event filtering, event-id
   deduplication, one reply, and resend of persisted `reply_pending` text.
3. Implement the smallest transport adapter that satisfies those tests.
4. Run the focused state/transport suites without network access.

Approval gate: this checkpoint modifies dependencies.

### Checkpoint 3: Matrix turn pipeline

1. Write failing tests proving `channel="matrix"`, Matrix-only recent context,
   Matrix-provenance persistence, one final reply, and no transport calls.
2. Add an opt-in same-channel recent-context mode without changing the default
   mixed behavior used by existing Web/Telegram callers.
3. Implement the narrow Matrix turn service using the existing graph and
   memory/queue abstractions.
4. Run focused Matrix tests plus conversation-history and agent regressions.

### Checkpoint 4: runtime wiring and private smoke test

1. Finalize validated environment names and diagnostics without committing
   secret values.
2. Create/log in the dedicated Matrix service account and prepare its
   persistent encryption store.
3. Wire `boot.py` so Web always starts and only the selected external transport
   starts.
4. Verify Telegram selection preserves current behavior.
5. Verify Matrix selection starts no Telegram polling or Telegram delivery.
6. Perform one private encrypted Element-to-Astakos text round trip, then test
   reconnect without duplicate processing.

Approval gate: this checkpoint modifies runtime settings, credentials, and
startup behavior.

## Planned files

- `memory/matrix_event_state.py`
- `clients/matrix_client.py`
- `services/matrix_turn.py`
- `memory/conversation_history.py` (narrow opt-in context mode only)
- `core/utils.py` (Matrix channel documentation/type surface if required)
- `boot.py` (checkpoint 4 only)
- `requirements.txt` (checkpoint 2 only)
- focused tests under `tests/`

`.env`, `config.py`, Setup Wizard, Telegram internals, routine delivery,
approvals, proactive delivery, Docker, and media remain outside checkpoints
1–3.

## Verification commands

Use an isolated pytest base directory for every checkpoint:

```powershell
venv\Scripts\python.exe -m pytest tests/test_matrix_event_state.py -q --basetemp=.pytest_tmp_matrix_state
venv\Scripts\python.exe -m pytest tests/test_matrix_text_transport.py -q --basetemp=.pytest_tmp_matrix_transport
venv\Scripts\python.exe -m pytest tests/test_matrix_turn.py tests/test_conversation_history.py -q --basetemp=.pytest_tmp_matrix_turn
venv\Scripts\python.exe -m pytest tests/test_external_channel_selection.py tests/test_setup_diagnostics_portability.py tests/test_run_telegram_shutdown.py -q --basetemp=.pytest_tmp_matrix_regression
git diff --check
```

The exact filenames may be combined if the implementation stays clearer, but
the acceptance contracts and checkpoint order do not change.

## Risks and mitigations

- Duplicate graph/tool execution after reconnect: reserve the Matrix event id
  durably before invoking the graph and never automatically replay stale
  `processing` rows.
- Lost reply after a send failure: persist reply text before sending and resend
  only that saved text.
- Historical-message replay: ignore timeline events until the initial sync
  barrier is established.
- Channel-context leakage: use an explicit Matrix-only context mode and leave
  existing callers on their current default.
- Credential leakage: inject secrets only at runtime and test error redaction.
- SDK verification regression: do not make SAS verification a prerequisite for
  the initial text channel.
- Scope expansion: keep routines, approvals, proactive messages, media, voice,
  typing, receipts, and reactions in their already deferred modules.

## Completion criteria

- Every automated Matrix test is offline and passes.
- A trusted encrypted event invokes the graph once and produces one reply.
- Reconnect/restart does not replay historical or already reserved events.
- A failed send retries the stored reply without a second graph invocation.
- Matrix context and stored messages retain `channel="matrix"` and remain
  isolated from recent Web/Telegram conversation context.
- Telegram remains available and unchanged when selected.
- Only the explicitly approved checkpoint files appear in each diff.

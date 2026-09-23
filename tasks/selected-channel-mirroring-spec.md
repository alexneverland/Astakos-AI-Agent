# Spec: Selected-Channel Mirroring

Module id: `selected-channel-mirroring` in `unified-conversation-map.md`.

## Objective

Mirror each new, ordinary Web text-chat user turn and its assistant reply into
the external conversation selected at the time: Matrix/Element or Telegram.
Messages originating in Element/Telegram already appear in Web history and
must not be re-sent. The mirror is display-only: it never enters the inbound
agent pipeline and does not create a second conversation-history row.

## Existing Structure

- `api/server.py` persists Web chat turns to the shared SQLite history.
- Matrix and Telegram run in separate processes and register their transports
  on a process-local `external_delivery_router`.
- `memory/conversation_history.py` owns conversation persistence and the Web
  history feed. The selected external channel is resolved centrally in
  `core/messaging_channel.py`.
- Matrix encryption and device trust must remain in the Matrix process.

## Delivery Contract

1. After a Web text message is persisted, enqueue one display-only delivery
   referencing its history row ID and the external channel selected then.
   Preserve the full display text even when memory history truncates a long
   code reply. Enqueue the assistant's persisted reply separately when one exists.
2. Only the selected external process consumes its deliveries. Preserve order,
   retry transient failures, and retain pending items across restarts. Never
   route a queued item to a different channel after a setting change.
3. Send attributed text (for example, `Web / Λάζαρος: ...` and
   `Web / Αστακός: ...`) so the bot does not impersonate the owner. Do not
   append these display copies to shared conversation history.
4. Normal `/chat` text turns and compact text summaries of Web uploads are in
   scope. Voice payloads, binary uploads, generated files, approvals, debug
   actions, and system/routine messages are excluded. If a Web text turn fails
   before an assistant reply, only the persisted user turn is eligible for
   mirroring. Upload copies must not reveal local paths or protected analysis.

## Commands and Tests

- Focused: `venv\Scripts\python.exe -m pytest tests/test_conversation_history.py tests/test_web_mirror_outbox.py tests/test_api_upload.py tests/test_matrix_text_transport.py tests/test_telegram_external_transport.py -q`
- Diff validation: `git diff --check`
- All tests must be offline with mocked Matrix/Telegram send boundaries.
- Regressions: Web user/reply reach only the selected channel, survive consumer
  restart, do not re-enter the graph or duplicate history, and respect order.
  A channel switch must not redirect an earlier pending item.

## Boundaries

- Always: use the existing encrypted Matrix sender; retain approval gates and
  channel authorization; keep source-channel provenance and history row IDs.
- Approved: the persistent outbox table in the shared SQLite history database.
- Ask first: adding a dependency or changing runtime/watchdog startup.
- Never: read or modify the live database with ad-hoc SQL, alter credentials,
  send live messages from tests, or fall back to an inactive channel.

## Success Criteria

1. A new Web text turn appears in Web and the selected external conversation
   with one user line and, if produced, one assistant line.
2. Element/Telegram turns retain their current Web visibility without loops.
3. Temporary transport failure or restart does not silently discard queued
   display copies, and delivery does not create additional history turns.
4. Telegram and Matrix are independently covered by offline tests.

## Delivery Limitation

The owner approved the small outbox table managed by the memory abstraction.
Telegram cannot guarantee strict exactly-once delivery if a send succeeds but
the process crashes before recording the acknowledgement. The persisted outbox
otherwise retries failed sends without re-entering the conversation history.

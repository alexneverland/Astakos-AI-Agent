# Spec: Trusted Matrix Text Channel

Module id: `matrix-text`

## Objective

Add a private, encrypted Matrix text channel that accepts messages only from
the configured Astakos owner in one configured room, processes each accepted
message through the existing LangGraph assistant with `channel="matrix"`, and
returns exactly one reply to that room.

This module does not replace or imitate Telegram. It introduces a distinct
Matrix transport and a narrow Matrix turn pipeline while preserving the
existing Web and Telegram behavior. Runtime startup wiring remains the final
step, after both parts can be tested independently.

## Why the module has two internal slices

The current Web and Telegram entry points each contain channel-specific
handling; there is no reusable generic turn handler that Matrix can call
without either copying a large handler or pretending to be another channel.
Therefore `matrix-text` is delivered as two small contracts:

1. `matrix-transport`: authenticate, sync encrypted events, enforce the Matrix
   allowlist, deduplicate events, and send text through an injected turn
   handler.
2. `matrix-turn`: invoke the existing graph with `channel="matrix"`, use
   Matrix-only recent conversation context, persist the trusted user turn and
   assistant reply with Matrix provenance, and return one reply string.

Only after both contracts pass offline tests may startup wiring select this
transport when `ASTAKOS_EXTERNAL_CHANNEL=matrix`.

## Runtime identity and trust contract

- Astakos uses a dedicated Matrix service account, not the owner's personal
  Element account.
- Exactly one full Matrix user id is allowlisted as the owner.
- Exactly one encrypted direct-message room id is allowlisted.
- Messages from other users or rooms are ignored and never reach the graph.
- Events sent by the Astakos service account are ignored.
- Only original plain text message events are accepted in this module.
- Edits, reactions, redactions, notices, media, voice, files, invitations, and
  room-management events are deferred.
- The Matrix event id is the idempotency key. A previously handled event must
  not be processed or answered again after reconnect or restart.

## Encryption and sync contract

- End-to-end encryption is mandatory for the configured room.
- The client uses a persistent local crypto/device store outside Git.
- The access token, device identity, recovery material, and encryption store
  are runtime secrets/data and must never be committed or logged.
- Initial sync establishes the live position without replaying historical room
  messages as new user turns.
- Subsequent syncs process only new allowlisted events.
- An undecryptable event is not forwarded as partial or placeholder user text.
  It is logged without message content and can be retried by the Matrix SDK.
- Initial device verification and cross-signing are operational setup steps,
  not automated by ordinary message handling. The first implementation must
  not depend on an unverified SAS flow to pass its code-level tests.

## Matrix transport boundary

The transport owns Matrix protocol details and receives an injected async turn
handler. Its application-facing shape is intentionally small:

```python
MatrixTurnHandler = Callable[[str, str], Awaitable[str]]


class MatrixTextTransport:
    async def run(self) -> None:
        """Sync trusted encrypted text events until stopped."""
```

For each accepted event the transport:

1. validates room, sender, encryption, event kind, and event id;
2. reserves the event id through the canonical deduplication store;
3. calls the injected handler once with the decrypted user text and Matrix
   event id;
4. sends exactly one text reply to the configured room;
5. marks the event complete only after the reply succeeds.

Failure states must be explicit. Authentication, encryption-store, sync, turn,
and send failures must not be converted into fabricated assistant replies. A
failed send must remain safely retryable without running the graph twice.

## Matrix turn boundary

The Matrix turn service owns Astakos application behavior, not Matrix network
operations. It must:

- build `AgentState` with `channel="matrix"`;
- invoke the existing compiled graph through the established safe invocation
  path;
- load bounded recent Matrix conversation context only;
- preserve shared long-term personal memory behavior already available to the
  graph;
- persist the trusted user text and final assistant text as Matrix messages;
- enqueue the existing context, session, working-memory, and behavioral-event
  follow-up work with Matrix provenance where those queues already accept a
  channel;
- return one final user-facing reply string to the transport.

It must not call Telegram helpers, WebSocket broadcasters, approval delivery,
routine delivery, or Matrix SDK methods.

## Conversation isolation

- New Matrix user and assistant messages are stored as `channel="matrix"`.
- Matrix recent conversational context contains only Matrix turns.
- Web and Telegram recent conversational context must not start including
  Matrix turns as a side effect of this module.
- Matrix must not load recent Web or Telegram conversational turns.
- Shared long-term personal memory remains available and is not duplicated or
  migrated.
- Existing Web/Telegram context behavior is not refactored in this slice.

If the current mixed recent-context helper cannot meet this contract, add a
bounded same-channel option or a Matrix-specific caller that reuses the
existing storage abstraction. Do not query SQLite directly and do not create a
second conversation database.

## Configuration contract

The runtime will require values equivalent to:

- homeserver URL;
- dedicated Matrix service-account user id;
- service-account access token;
- allowed owner user id;
- allowed encrypted room id;
- persistent Matrix crypto-store path.

Exact environment-variable names and setup diagnostics are finalized before
runtime wiring. Missing, blank, malformed, or conflicting required values must
fail closed before syncing. Secrets stay outside Git and must be redacted from
errors.

## SDK decision gate

The preferred client candidate is `matrix-nio` with E2EE support because its
async sync model and persistent encryption store match this transport
boundary. Before adding it to requirements:

- confirm the selected pinned version supports the project's Python version
  and Windows runtime;
- confirm its E2EE backend installs without an unmanaged system library;
- record the exact dependency diff;
- run an import smoke test in the project virtual environment;
- keep all protocol calls mocked in the normal test suite.

Adding the SDK dependency requires a separate explicit user instruction under
the repository rules.

## Testing strategy

All automated tests remain offline. A fake Matrix client/transport boundary
must fail loudly if a real network call is attempted.

### Transport tests

- an allowlisted encrypted text event in the allowlisted room calls the turn
  handler once and sends one reply;
- a different sender is ignored;
- a different room is ignored;
- the service account's own event is ignored;
- an unencrypted or undecryptable event is ignored safely;
- edits, reactions, notices, and media are ignored;
- the initial sync backlog is not processed;
- duplicate event ids across sync batches or restart are not reprocessed;
- a transient send failure is retryable without a second graph invocation;
- secrets are absent from logs and raised error messages.

### Turn-pipeline tests

- state reaches the graph with `channel="matrix"`;
- accepted user and assistant messages persist with Matrix provenance;
- only Matrix recent conversation is supplied to a Matrix turn;
- recent Web and Telegram context do not contain Matrix turns after the test;
- one graph result produces exactly one reply string;
- behavioral/context follow-up calls retain `channel="matrix"`;
- no Telegram sender, Matrix client, WebSocket, or live provider is called.

### Regression tests

- the external-channel resolver continues to default to Telegram;
- current Web and Telegram focused tests remain green;
- `git diff --check` is clean.

## Project structure

Names may be refined during the implementation plan, but responsibilities stay
separate:

- `clients/matrix_client.py`: Matrix SDK adapter and encrypted sync loop;
- `services/matrix_turn.py`: Matrix application turn pipeline;
- `core/messaging_channel.py`: existing canonical external-channel selection;
- `memory/`: existing abstractions only, extended narrowly if same-channel
  loading or durable event idempotency needs a canonical option;
- `tests/`: offline transport, turn, isolation, and regression contracts.

## Boundaries

- Always: dedicated service account, encrypted allowlisted room, exact user and
  room ids, persistent idempotency, Matrix provenance, offline tests, and one
  reply per accepted event.
- Ask first: add/pin the Matrix SDK, create or log in the service account,
  obtain/store an access token, modify runtime environment settings, edit
  `boot.py`, or change Setup Wizard/runtime services.
- Never: alias Matrix as Telegram, broadcast to both external channels, replay
  backlog into the graph, mix recent channel histories, log decrypted content
  as diagnostics, commit crypto material, or copy the complete Web/Telegram
  handler.

## Success criteria

- A new encrypted text from the allowlisted owner and room reaches the existing
  graph as `channel="matrix"` and receives exactly one Matrix reply.
- Reconnects and restarts do not duplicate user turns or replies.
- Unauthorized, unsupported, historical, and undecryptable events never reach
  the graph.
- Matrix recent context is isolated from Web and Telegram recent context.
- Existing Telegram remains untouched and functional when selected.
- The test suite verifies the final observable behavior without live Matrix,
  Telegram, cloud-provider, or user-data access.

## Deferred

- Startup/process wiring and Setup Wizard fields until transport and turn tests
  pass.
- Proactive notifications, approvals, and routines (`external-delivery` and
  `routine-parity`).
- Photos, files, voice, read receipts, typing indicators, reactions, edits,
  and room administration (`matrix-media`).
- History migration or synchronization across channels.
- Multi-user or multi-room support.

## Resolved design decisions

- A new `memory/matrix_event_state.py` abstraction will own Matrix event and
  reply lifecycle state in the existing `STATE_DB`. The Matrix client will not
  contain SQL. Creating this table is a scoped database-schema change and must
  be explicitly approved before implementation.
- The planned dependency is `matrix-nio[e2e]==0.26.0`. It declares Python 3.14
  support and its `vodozemac` E2EE backend publishes a CPython 3.14 Windows x64
  wheel, avoiding the former unmanaged `libolm` dependency.
- Reply retry uses the persisted reply text. A send failure leaves the row in
  `reply_pending`; reconnect sends that same text without invoking the graph
  again. A crash during `processing` fails closed for manual recovery instead
  of risking duplicate graph/tool execution.
- The initial setup will not depend on SAS verification. A known 0.26.0 SAS
  interoperability issue with Element is isolated from ordinary encrypted
  sync and messaging, and can be revisited when device-verification support is
  added.

## Open questions

None for implementation planning. Dependency installation, the scoped state
table, runtime credentials, and startup wiring remain separate approval gates.

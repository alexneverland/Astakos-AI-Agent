# Spec: Shared Conversation Context

Module id: `shared-conversation-context` (see `unified-conversation-map.md`).

## Objective

When the owner continues a text conversation in Web, Element, or Telegram, the
assistant can use the same recent conversation regardless of where earlier
turns were sent. A message is stored once, retains its source channel, and is
presented in chronological order. This module does not send messages between
channels; that is the later `selected-channel-mirroring` module.

## Tech Stack and Existing Structure

- Python 3.11+; SQLite conversation history in `memory/conversation_history.py`.
- Web context in `api/server.py`, Matrix context in `services/matrix_turn.py`,
  and Telegram context in `clients/telegram_bot.py`.
- Web `/history` and `/messages/poll` already read from the shared store.
- Before this change, `load_recent_context` excluded Matrix from Web/Telegram,
  and Matrix opted into `same_channel_only=True`. The shared context change
  removes that isolation through the canonical history abstraction; it does
  not create channel-specific copies of the same text.

## Commands

- Focused tests: `venv\Scripts\python.exe -m pytest tests/test_conversation_history.py tests/test_matrix_turn.py -q`
- Diff validation: `git diff --check`

## Code Style

Keep the existing typed, keyword-only history API. For example, callers use
`load_recent_context(channel="matrix", global_limit=12, channel_limit=10,
total_limit=20)` rather than constructing independent SQL queries. Preserve
the existing message fields and source-channel metadata.

## Testing Strategy

- Offline tests use temporary stores and mocked graph/provider boundaries;
  never read live conversation data or call external transports.
- A regression test covers Web → Matrix and Matrix → Web context, plus an
  intervening Telegram turn, without duplicate entries.
- A nearby safety test checks ordering, bounded context size, and that a
  source-channel label does not turn historical content into a new user turn.
- Run the focused suite and nearby channel-turn tests before claiming success.

## Boundaries

- Always: preserve one persisted row per real message, chronological ordering,
  source provenance, bounded context, and existing authorization gates.
- Ask first: database schema changes, history migrations or backfills, new
  dependencies, or changing which external channel is selected.
- Never: edit `.env` or credentials, open live Chroma/SQLite data for tests,
  send live Telegram/Matrix messages, or modify media handling in this module.

## Success Criteria

1. A new Web text turn can use recent Matrix and Telegram text context; a new
   Matrix or Telegram text turn can use recent Web text context.
2. Each historical entry appears at most once in the context window, with its
   original role, channel, and order preserved.
3. The context remains bounded and safe if one channel has no recent messages.
4. Existing Web history display, channel selection, and approval behavior do
   not regress.

## Open Questions

- None for this module. Mirroring and delivery semantics are specified in the
  dependent module before implementation of that module begins.

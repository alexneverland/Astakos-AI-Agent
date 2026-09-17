# Capability Map: Matrix Channel Integration

## Agreed behavior

- The Web UI remains available and keeps its existing channel behavior.
- Exactly one external messaging channel is active at a time: `telegram` or
  `matrix`.
- Telegram code, credentials, and history remain available unchanged when the
  channel is inactive.
- Matrix is stored and processed as `channel="matrix"`; it is never presented
  internally as Telegram.
- Web, Telegram, and Matrix messages remain separately addressable by channel.
  Shared long-term personal memory remains unchanged.
- Proactive messages, routines, and approvals are delivered only through the
  selected external channel.

## Evidence from the current code

- `memory/conversation_history.py` already stores and filters arbitrary channel
  values.
- `services/context_extractor.py` already receives a channel and loads bounded
  same-channel user context.
- `services/behavioral_event_extractor.py` incrementally consumes trusted user
  history without a Web/Telegram allowlist, so persisted Matrix user messages
  can participate without a Matrix-specific extractor.
- `boot.py` currently starts only the Web API and optional Telegram process.
- `core/approval.py` persists an origin channel but sends approval requests
  directly through Telegram.
- Routine scheduling, proactive delivery, pending routine replies, and their
  queues currently live in `clients/telegram_bot.py`; this is the main parity
  boundary and must be separated incrementally rather than copied.

## Modules

| Module id | Responsibility | Depends on |
|---|---|---|
| `channel-selection` | Validate the active external channel and start only its transport while Web remains active. | — |
| `matrix-text` | Receive and send trusted encrypted text turns as `channel="matrix"`, with an allowlisted Matrix user and room. | `channel-selection` |
| `external-delivery` | Provide one narrow delivery boundary for proactive messages and approval prompts without changing Telegram formatting internals. | `channel-selection`, `matrix-text` |
| `routine-parity` | Run scheduler/routine generation independently of Telegram polling and deliver/consume routine interactions through the active external channel. | `external-delivery` |
| `matrix-media` | Add Matrix photos, files, voice input, and optional voice replies after text/routine parity is proven. | `matrix-text`, `routine-parity` |
| `channel-parity-audit` | Inventory every supported Telegram inbound/outbound interaction and verify an equivalent Matrix path or an explicitly approved Matrix-specific exception. | `external-delivery`, `routine-parity`, `matrix-media` |

Build order:

`channel-selection` → `matrix-text` → `external-delivery` → `routine-parity` → `matrix-media` → `channel-parity-audit`

## Cross-module acceptance criteria

- Web starts regardless of the selected external channel.
- Selecting Matrix does not start Telegram polling or send Telegram traffic.
- Selecting Telegram preserves the existing Telegram behavior.
- A Matrix user turn is persisted with `channel="matrix"`, reaches the existing
  graph, and returns exactly one Matrix reply.
- Matrix recent conversation context does not leak into Web or Telegram recent
  history, and vice versa; shared long-term memory remains available.
- Behavioral-event intake accepts trusted Matrix user messages and preserves
  their Matrix provenance.
- Each scheduled routine, proactive notification, and approval request is sent
  exactly once through the active external channel.
- Matrix reaches functional parity with the Telegram channel for supported
  text, approvals, routines, proactive/follow-up delivery, commands, photos,
  files, voice input, and configured voice replies before the integration is
  declared complete.
- Tests remain offline and fail loudly on accidental Telegram or Matrix network
  access.

## Boundaries

- Always: use a separate Matrix service account, allowlist the expected Matrix
  user and room, preserve E2EE, and keep secrets outside Git.
- Ask first: add a Matrix SDK dependency, create the Matrix service account or
  access token, modify runtime environment settings, or change startup files.
- Never: alias Matrix as Telegram, broadcast to both external channels, mix
  channel histories, commit access tokens, expose Synapse publicly, or refactor
  unrelated Telegram behavior.

## Deferred until the relevant module

- Media and voice parity.
- Read receipts, typing indicators, reactions, and room-management features.
- History migration or synchronization between existing channels.
- Replacing Telegram or deleting any Telegram configuration.

## Final parity gate

Before Matrix is declared complete, compare the live Telegram handler and all
Telegram send entry points against the Matrix channel. Every user-visible
capability must have one of these outcomes:

- verified equivalent Matrix behavior;
- verified shared channel-independent behavior;
- an explicit Matrix-specific exception approved by the user.

Silence, an untested assumption, or merely having a Matrix text fallback does
not count as parity.

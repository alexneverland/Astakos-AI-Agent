# Capability Map: Unified Astakos Conversation

The owner wants one ongoing text conversation across the Web UI and whichever
external channel is selected at the time: Matrix/Element or Telegram. The
inactive external channel must not receive new messages.

| Module id | Responsibility | Depends on |
|---|---|---|
| `shared-conversation-context` | Use the existing conversation store to assemble one bounded, chronological context across Web, Matrix, and Telegram, while retaining each message's source channel. | Existing conversation history |
| `selected-channel-mirroring` | Display each new user text and single assistant answer in the Web UI and the selected external channel, with durable cross-process delivery and no feedback loop. | `shared-conversation-context`, existing external-channel selection |

Build order: `shared-conversation-context` then `selected-channel-mirroring`.

The initial release covers new text turns and compact text summaries of Web
photo/document uploads; media bytes are not copied between channels. Existing
history is not rewritten. Voice payloads and live voice transport remain
separate follow-up work; their existing processing remains unchanged.

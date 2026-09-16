# Matrix Channel Parity Audit

Evidence snapshot: 2026-09-16. This audit compares the current Telegram polling
dispatcher and outbound markers with the offline-tested Matrix channel. Live
startup and credentials remain intentionally deferred to the final switch.

## Verified equivalent or shared behavior

| Capability | Matrix outcome |
|---|---|
| Ordinary text and graph tools | Matrix-only history, graph state, and replies verified offline. |
| Approvals | Trusted encrypted reactions are correlated to the exact pending approval. |
| Routines, reminders, proactive messages, follow-ups, and briefings | Shared selected-channel delivery boundary; no Telegram fallback. |
| Admin commands | Shared status, pause, mute, sleep, resume, vacation, help, and doctor handler. |
| Photos | Encrypted download, shared vision provider, pending-photo question, and archive confirmation. |
| Documents | Encrypted download, bounded shared readers, summary, and archive confirmation. |
| Voice input and replies | Shared configured providers and encrypted Matrix audio replies with text fallback. |
| Generated files and images | `CREATED_FILE` and `SEND_PHOTO` markers become bounded encrypted Matrix attachments. |
| `/nutrition` and `/receipt` | One fresh pending photo is consumed by the same shared analyzers used by Telegram. |
| `/end` | Shared session finalizer archives under the active channel before clearing working memory. |
| Georgian translation | Matrix-local direct and one-shot pending modes reuse the existing translation helper. |
| `/story` | Shared story generation returns text plus bounded encrypted image attachments. |
| Location events | Trusted encrypted static and live Matrix locations are validated, deduplicated, and persisted without live-chat spam. |

## User-approved exception

| Telegram behavior | Matrix decision |
|---|---|
| Heart reaction saves an assistant reply to memory | Intentionally excluded: the user does not want reactions to write memory. |

Telegram typing indicators, inline keyboards, and command-menu registration are
transport-specific presentation details, not missing application capabilities.

## Final live gate

After the remaining application parity slices pass offline, wire the selected
Matrix runtime, configure credentials outside Git, and perform one encrypted
Element round trip for text, approval, media, voice, and generated output.

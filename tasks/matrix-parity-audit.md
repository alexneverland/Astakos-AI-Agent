# Matrix Channel Parity Audit

Evidence updated: 2026-09-24. This audit compares Telegram's application
behavior with the selected Matrix channel. The private Matrix runtime is active;
remaining live checks are listed below.

## Verified equivalent or shared behavior

| Capability | Matrix outcome |
|---|---|
| Ordinary text and graph tools | Shared recent cross-channel context, Matrix graph state, draft preview, and tool-result fallback verified offline. |
| Approvals | Web-origin prompt and result verified live in Element; only an encrypted Reply from a verified owner device authorizes it. Direct emoji reactions are not accepted. |
| Routines, reminders, proactive messages, follow-ups, and briefings | Shared selected-channel delivery boundary; Matrix handles pending, preemptive-today, and catalog routine decisions. No Telegram fallback. |
| Admin commands | Shared status, pause, mute, sleep, resume, vacation, and doctor handler; Matrix help reads Matrix voice state. |
| Photos | Encrypted download, shared vision provider, pending-photo question, and archive confirmation. |
| Documents | Encrypted download, bounded shared readers, summary, and archive confirmation. |
| Voice input and replies | Shared configured providers and encrypted Matrix audio replies with text fallback. |
| Generated files and images | `CREATED_FILE` and `SEND_PHOTO` markers become bounded encrypted Matrix attachments. |
| `/nutrition` and `/receipt` | One fresh pending photo is consumed by the same shared analyzers used by Telegram. |
| `/end` | Shared session finalizer archives under the active channel before clearing working memory. |
| Georgian translation | Matrix-local direct and one-shot pending modes reuse the existing translation helper. |
| `/story` | Shared story generation returns text plus bounded encrypted image attachments. |
| Location events | Trusted static/live locations are deduplicated and persisted; live home state, home/leave reminders, and departure follow-ups use the shared Telegram/Matrix lifecycle. |

## User-approved exception

| Telegram behavior | Matrix decision |
|---|---|
| Heart reaction saves an assistant reply to memory | Intentionally excluded: the user does not want reactions to write memory. |
| Legacy Telegram `/confirm <command>` | Intentionally excluded: Matrix uses the ordinary guarded terminal-tool approval path instead. Matrix `/help` does not advertise `/confirm`. |
| Plain Matrix emoji reaction on an approval | Intentionally excluded: approval requires an encrypted Reply to the exact prompt from a verified owner device. |

Telegram typing indicators, inline keyboards, and command-menu registration are
transport-specific presentation details, not missing application capabilities.

## Final live gate

The owner has exercised encrypted text and a Web-origin critical approval in
Element. Keep the final parity gate open until the following live checks are
completed and observed in both conversation views:

- One Element follow-up referring to a prior Web turn.
- One routine confirmation in Element, including the correct persisted state.
- One encrypted photo and one document upload, each with archive confirmation.
- One voice note and one `/voice` spoken reply.
- One generated file or image attachment.
- One static/live location update plus a location reminder or departure follow-up.

The related offline parity group passed 54 focused tests on 2026-09-24. This is
not a claim that those remaining live paths have been exercised.

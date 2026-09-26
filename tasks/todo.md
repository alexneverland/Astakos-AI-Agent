# Tasks: Web Research Providers, Slice 1

- [x] Define normalized provider contracts and registry.
  - Acceptance: selective provider IDs are validated; duplicate canonical URLs are removed; failures are isolated.
  - Verify: focused offline unit tests.
  - Files: `services/web_research.py`, `tests/test_web_research.py`.

- [x] Adapt existing Web search and add read-only GitHub search.
  - Acceptance: Web behavior remains compatible; GitHub public results normalize into the shared contract; no credentials are required.
  - Verify: provider tests plus unchanged `tests/test_duckduckgo_search.py`.
  - Files: `services/web_providers.py`, `tools/web.py`, `tests/test_web_research.py`.

- [x] Bind the aggregate tool to the existing Web Agent.
  - Acceptance: `research_web` is safe, registered, budgeted, and visible only through the existing Web Agent ownership path.
  - Verify: Web Agent binding, budget, and failure regression tests.
  - Files: `core/agents.py`, `core/tool_risk.py`, `tools/system.py`, `core/capability_registry.json`, `core/prompts.md`, tests.

- [x] Final verification and PR.
  - Acceptance: relevant and full test suites pass, `git diff --check` is clean, staged diff contains only this slice.
  - Verify: commands in `tasks/plan.md`.

## Slice 2: Reddit discovery

- [x] Add the Reddit provider with URL filtering and normalized provenance.
  - Acceptance: bounded site search returns only Reddit URLs and isolates failures.
  - Verify: focused offline provider tests written before implementation.
  - Files: `services/web_providers.py`, `tests/test_web_research.py`.

- [x] Register Reddit in the existing research skill and Web Agent guidance.
  - Acceptance: `sources=["reddit"]` is valid without changing agent ownership.
  - Verify: registry/tool boundary tests.
  - Files: `astakos_skills/research_web.py`, `core/prompts.md`, `core/capability_registry.json`, tests.

- [x] Final verification and PR.
  - Acceptance: focused/full suites pass and the diff contains only this slice.
  - Verify: isolated pytest basetemp and `git diff --check`.

## Slice 4: LinkedIn discovery

- [x] Add a bounded LinkedIn discovery provider.
  - Acceptance: only real LinkedIn hosts normalize with `source="linkedin"`; lookalikes are rejected.
  - Verify: focused offline provider tests written before implementation.
  - Files: `services/web_providers.py`, `tests/test_web_research.py`.

- [x] Register LinkedIn in the aggregate research tool and Web Agent guidance.
  - Acceptance: `sources=["linkedin"]` is valid and publishing remains separate.
  - Verify: registry and Web Agent regression tests.
  - Files: `astakos_skills/research_web.py`, `core/prompts.md`, tests.

- [x] Final verification and PR.
  - Acceptance: focused suites pass and the diff contains only this slice.
  - Verify: isolated pytest basetemp and `git diff --check`.

## Private Matrix server, Phase 1

- [x] Complete the isolated private Matrix server and Element smoke test.
  - Acceptance: Synapse is reachable from Element X over Tailscale HTTPS with
    registration/federation disabled and no Astakos runtime changes.
  - Verified: local Compose health, tailnet-only HTTPS proxy, and owner-tested
    encrypted Element conversation.

- [ ] Document and verify private Matrix backup/recovery prerequisites.
  - Acceptance: Synapse signing key/config and PostgreSQL data have a tested,
    recoverable backup boundary without exposing secrets in Git.
  - Verify: dry-run inventory and restore-prerequisite review; keep this server
    maintenance task separate from Astakos conversation changes.

## Matrix channel integration: `channel-selection`

- [x] Write the resolver contract tests first.
  - Acceptance: tests cover the missing-variable default, both supported
    values, normalization, and fail-closed blank/unknown values.
  - Verify: the focused test initially fails because the production module does
    not exist.
  - Files: `tests/test_external_channel_selection.py`.

- [x] Implement the pure external-channel resolver.
  - Acceptance: the focused contract tests pass without importing or starting
    either transport.
  - Verify: focused pytest command from the approved spec.
  - Files: `core/messaging_channel.py`.

- [x] Verify the completed slice.
  - Acceptance: nearby startup regressions pass; no runtime/config/credential
    file changed; diff validation is clean.
  - Verify: startup regression command and `git diff --check` from the spec.

### Checkpoint: `channel-selection`

- [x] Human reviews the task plan before implementation.
- [x] RED failure observed before production code.
- [x] Focused and nearby regression suites pass after implementation.

## Matrix channel integration: `matrix-text`

- [x] Document the trusted encrypted text-channel contract.
  - Acceptance: the spec separates transport from application turns and
    defines allowlisting, E2EE, initial-sync, idempotency, retry, and channel
    isolation behavior.
  - Files: `tasks/matrix-text-spec.md`.

- [x] Resolve the implementation architecture with repository evidence.
  - Acceptance: durable state uses an abstraction over `STATE_DB`; reply retry
    cannot invoke the graph twice; the planned E2EE SDK supports Python 3.14 on
    Windows.
  - Files: `tasks/matrix-text-spec.md`, `tasks/matrix-text-plan.md`.

- [x] Checkpoint 1: implement durable Matrix event/reply lifecycle with TDD.
  - Acceptance: unique event reservation and legal persisted transitions cover
    `processing`, `reply_pending`, and `replied`; stale processing fails closed.
  - Approval required: scoped state-database schema change.
  - Verified: RED missing-module failure; 10 focused tests and 89 nearby
    state/channel regression tests pass offline; `git diff --check` is clean.

- [x] Checkpoint 2: implement the offline-tested encrypted Matrix transport.
  - Acceptance: trusted new text produces one reply; unauthorized, historical,
    duplicate, unsupported, and undecryptable events do not reach the handler;
    failed sends reuse persisted reply text.
  - Approval required: pin and install the Matrix E2EE SDK dependency.
  - Verified: dependency/import integrity passes; 22 focused lifecycle and
    transport tests plus 144 nearby state/startup regressions pass offline.

- [x] Checkpoint 3: implement the Matrix application turn pipeline.
  - Acceptance: graph state, persistence, follow-up queues, and recent context
    use `channel="matrix"`; current Web/Telegram behavior stays unchanged.
  - Verified: Matrix event-id provenance prevents false rapid-message dedup;
    strict Matrix-only recent context is opt-in; 45 focused pipeline/history
    tests pass offline. Runtime queue hooks are connected in checkpoint 4.

- [x] Checkpoint 4: wire the selected transport and run the private smoke test.
  - Acceptance: Web always starts; only Telegram or Matrix starts externally;
    an encrypted Element round trip succeeds without duplicate processing.
  - Verified: `run_external.py` selects one watchdog, `boot.py` selects one
    transport, 70 focused startup/Matrix tests pass, and the owner exercised
    encrypted Element conversations. Runtime credentials remain outside Git.

- [ ] Final gate: verify complete Telegram-to-Matrix capability parity.
  - Acceptance: every supported Telegram text, approval, routine, proactive,
    follow-up, command, photo, file, voice-input, and configured voice-reply
    path has a tested Matrix equivalent or an explicit user-approved exception.
  - Verify: inventory the current Telegram handler/send entry points at that
    time; do not rely on this planning snapshot alone.
  - Scope: separate Matrix-wide parity audit; the unified text-conversation
    work below must not silently mark this broader gate complete.
  - Offline parity slices completed 2026-09-24: shared Matrix/Telegram live
    location lifecycle, location reminders and departure follow-ups; Matrix
    preemptive/catalog routine decisions; Messenger draft guard and preview;
    tool-result fallback; Matrix-aware `/help` voice state. PR #200 merged;
    its parity group passed 54 focused tests. The final review fixes for active
    draft protection and explicit draft cleanup passed 97 focused
    Matrix/Messenger/Web tests. Keep this gate open for the live checks in
    `tasks/matrix-parity-audit.md`.
  - Owner-approved exceptions: no heart-to-memory reaction, no legacy Matrix
    `/confirm`, and critical approvals only via encrypted Reply to the prompt.

- [x] Deliver classified capability-gap and existing-bug proposals in Matrix.
  - Acceptance: trusted ordinary Matrix text turns produce the same localized
    proposal as Web/Telegram; bug offers never authorize new-tool drafts;
    transient/uncertain and external-derived turns produce no proposal.
  - Verified offline: 50 focused Matrix/capability tests passed, including
    stale-turn, duplicate, and failed-delivery cases. Live Element delivery is
    still an explicit manual check under the open final parity gate.

## Unified conversation: `shared-conversation-context`

- [x] Reproduce the Matrix/Web context isolation with offline regression tests.
  - Acceptance: tests show that a recent Matrix turn is absent from Web context
    and a recent Web turn is absent from Matrix context on the current code.
  - Verify: focused RED run using temporary history stores and mocked graph.
  - Files: `tests/test_conversation_history.py`, `tests/test_matrix_turn.py`.

- [x] Use one bounded cross-channel recent-context policy.
  - Acceptance: Web, Matrix, and Telegram text turns can use recent messages
    from all three channels; provenance, ordering, limits, and one-row-per-turn
    storage remain intact.
  - Verify: focused GREEN tests and nearby Web/Telegram history regressions.
  - Files: `memory/conversation_history.py`, `services/matrix_turn.py`, tests.

### Checkpoint: shared conversation context

- [x] Focused and nearby offline tests pass (74 tests); `git diff --check` is clean.
- [ ] Verify live model-context continuity across Web and Element with the owner.
  - Visibility of messages in both UIs is confirmed; a cross-channel follow-up
    that demonstrably uses the earlier turn has not yet been run.
- [x] Review the `selected-channel-mirroring` spec and plan as the next module.
  - Verified: the owner approved the persistent selected-channel outbox before
    implementation; its offline delivery and isolation checks pass.

## Unified conversation: `selected-channel-mirroring`

- [x] Persist one selected-channel outbox item with each eligible Web `/chat` row.
  - Acceptance: user and assistant text are each queued once, atomically with
    their history rows; voice and debug messages are excluded. Web uploads
    enqueue only compact text summaries, never media bytes or private paths.
  - Verify: offline SQLite tests including repeated writes and channel switch.

- [x] Drain the outbox in the active external process.
  - Acceptance: ordered, attributed display messages use the existing Matrix
    encryption or Telegram sender; failure stays pending for retry and no
    display copy re-enters conversation history or the graph.
  - Verify: offline Matrix/Telegram transport fakes and restart test.

### Checkpoint: selected-channel-mirroring

- [x] Focused and nearby offline tests pass (59 tests); `git diff --check` is clean.
- [x] Owner verifies a live Web → Element text exchange before PR/deploy.
  - Verified: the owner observed the Web message and one assistant answer in
    Element, with the original Web history retained.
- [x] Reconcile the merged Web/Element conversation and delivery regressions.
  - Verified in PR #195: repeated Web turns retain separate history/outbox rows;
    Telegram mirror chunks are acknowledged only after every send succeeds;
    Web upload turns keep compact text summaries without mirroring media bytes.

## Matrix channel integration: `external-delivery`

- [x] Add the canonical one-channel delivery router.
  - Acceptance: text and approval requests go only to the selected external
    transport; missing/failing Matrix delivery never falls back to Telegram.
  - Verify: offline router tests cover selection, failure, and no-broadcast
    behavior.

- [x] Persist exact Matrix approval-message correlation.
  - Acceptance: one pending `tool_call_id` maps to one Matrix event id; lookup
    cannot cross channels or reuse the same external message for another call.
  - Verify: focused persistence tests plus existing approval/plan regressions.

- [x] Add Matrix approval rendering and trusted reaction handling.
  - Acceptance: only the allowlisted owner reacting ✅/❌ to the exact encrypted
    approval event can execute or reject its pending action; stale or unrelated
    reactions are inert.
  - Verified offline: prompt/event correlation, current device allowlisting,
    authenticated decrypted reactions, and duplicate/untrusted rejection are
    covered. The owner has exercised Matrix approval in a live conversation.

- [x] Queue Web-origin approvals for delivery by the active Matrix process.
  - Acceptance: the Web process does not claim direct Element delivery; the
    Matrix process retries queued prompts with a stable transaction ID, then
    correlates the sent event before a trusted reaction can execute the action.
  - Verified in PR #195: cross-process pending-file writes, queued delivery,
    scheduler registration, retry identity, and Web → Matrix → approval/reject
    boundaries pass offline. Telegram's existing callback path is unchanged.
- [x] Exercise one Web-origin critical-tool approval live in Element.
  - Owner confirmed live: one prompt arrived in Element, an encrypted Reply
    with 👍 approved it once, and the result appeared correctly in both views.
    A direct emoji reaction was not the working approval path in this test.

- [x] Move routine, proactive, reflection, and follow-up outbound sends onto
  the canonical router without changing the active Telegram runtime.
  - Verified offline: the shared assistant-send boundary covers reminders,
    routines, proactive alerts, follow-ups, briefings, analytics notices, and
    reflection digests; selected-channel delivery is persisted under that
    channel and never falls back to the other transport.

- [x] Connect trusted Matrix turns to shared background behavior pipelines.
  - Acceptance: persisted Matrix user turns schedule behavioral-event intake;
    completed exchanges queue working memory, session log, slow memory sifting,
    context flags, and pending follow-up processing with `channel="matrix"`.
  - Verified offline: the Matrix turn factory attaches every required hook;
    focused Matrix/background regressions pass without network access.

- [x] Detach scheduler startup from Telegram polling before the runtime switch.
  - Acceptance: the existing scheduler runs once for either selected external
    channel, without starting Telegram polling when Matrix is selected.
  - Verified offline: startup is idempotent, refuses an in-process channel
    change, passes the active channel to recovery/context/event paths, and the
    current Telegram entry point preserves its existing job set.
  - Deferred: selection in `boot.py` remains checkpoint 4 by user decision.

- [x] Add the shared text/admin command boundary.
  - Acceptance: recognized scheduler/admin commands bypass the LLM and use one
    canonical implementation for Telegram and Matrix; unknown and media/voice
    commands remain available to their specialized paths.
  - Verified offline: Matrix command bypass and Telegram compatibility tests
    cover status, override mutation, graph fallback, and command ownership.

- [x] Add trusted encrypted Matrix media ingestion and durable callback lifecycle.
  - Acceptance: only allowlisted, decrypted E2EE image/file/audio events from
    the configured room are downloaded; payloads are integrity-decrypted,
    bounded to 20 MB, written atomically under generated local names, and use
    the existing at-most-once reply state machine.
  - Verified offline: traversal names, wrong room/user/type, plaintext media,
    oversized payloads, decryption failure, cached duplicate delivery, callback
    registration, and durable reply behavior are covered by focused tests.
  - Deferred to the next narrow slice: connect the stored asset to shared
    photo, document, and voice application analyzers without duplicating the
    Telegram implementations.

- [x] Extract shared voice, vision, and document-input boundaries.
  - Acceptance: Telegram and Matrix use the selected configured providers and
    existing bounded document readers through channel-neutral services; no
    provider credentials or runtime selection are duplicated.
  - Verified offline: Telegram voice/provider modes, silence and provider
    failures, Telegram vision/untrusted-content flows, document type/size/path
    safeguards, and all shared service contracts pass.
  - Matrix audio application parity is complete: transcripts enter the normal
    Matrix graph turn and actionable provider failures are returned in-channel.
  - Deferred to the next narrow slice: Matrix pending-photo question handling,
    document summary/archive prompts, and their channel-isolated persistence.

- [x] Complete Matrix photo/document conversation and archive lifecycles.
  - Acceptance: a fresh uncaptioned photo is consumed only by the next ordinary
    Matrix message; admin commands do not consume it; user-visible history keeps
    only the clean question while path/analysis remain protected model context.
  - Acceptance: supported documents use the shared bounded readers and summary
    prompt, persist only under `channel="matrix"`, and create Matrix-only pending
    archive state; explicit yes/no saves or cancels only after a recent prompt.
  - Verified offline: pending expiry/one-shot behavior, command precedence,
    protected photo context, document path/name safety, cross-channel isolation,
    localized confirmation recognition, archive persistence, and composed
    channel-service wiring are covered.
  - Related repair: the shared document prompt now includes the bounded filename
    and untrusted document content; the previous Telegram template omitted both.

- [x] Add Matrix spoken-reply parity with durable encrypted delivery.
  - Acceptance: `/voice` is Matrix-local and starts disabled; voice input alone
    does not enable spoken replies; enabled normal/audio turns request encrypted
    `m.audio` delivery through the configured TTS provider.
  - Acceptance: `reply_mode` is persisted with pending Matrix replies so restart
    retries preserve voice intent; TTS/upload/send failure produces an actionable
    notice followed by the complete text reply, never Telegram fallback.
  - Verified offline: encrypted upload metadata, provider cleanup, mode toggling,
    text fallback, persisted retry mode, transport delivery, Telegram voice
    compatibility, and composed channel wiring pass.

- [x] Deliver generated files through encrypted Matrix attachments.
  - Acceptance: up to five `CREATED_FILE` or `SEND_PHOTO` outputs under
    `outputs/` are removed
    from visible reply text and delivered as encrypted `m.image` or `m.file`
    events; unsafe, missing, and oversized paths never leave the machine.
  - Acceptance: text and per-file delivery progress is durable, so restart or
    transient failure retries only the unsent stages and never reruns the graph.
  - Verify: focused parser, state, upload, turn, and retry tests stay offline;
    then run the complete Matrix parity regression group and `git diff --check`.
  - Verified: both output marker forms, five-file bounding, output-root/size
    validation, encrypted upload metadata, ordered durable stages, transient
    retry, clean history, and voice-mode preservation pass. Telegram now uses
    the same marker parser, hides both internal tags, preserves photo/document
    presentation, and sends every returned file in marker order. The broader
    Matrix/shared-channel suite and focused Telegram regressions pass offline.

- [x] Close the remaining application-parity gaps recorded in
  `tasks/matrix-parity-audit.md`.
  - Acceptance: location, translation state, pending-photo nutrition/receipt,
    story generation, and session end have tested Matrix equivalents through
    shared application services. Heart reactions are explicitly excluded from
    memory writes by user decision.
  - Verify: one narrow TDD slice per capability; no runtime credentials or
    startup changes until all offline parity checks are green.
  - Verified slice: `/end` uses one channel-neutral finalizer; failed summaries
    preserve working memory, while Telegram retains its existing progress and
    completion messages.
  - Verified slice: Matrix `/nutrition` and `/receipt` consume exactly one fresh
    pending photo through the same analyzers as Telegram; unrelated commands do
    not consume the photo.
  - Verified slice: Matrix-local Georgian direct/pending translation state,
    shared `/story` generation with encrypted image attachments, and trusted
    static/live location event validation and deduplication are covered offline.
    Heart reactions intentionally do not write memory.

- [x] Implement the existing-bug investigation handoff in
  `tasks/bug-investigation-flow-spec.md`.
  - [x] Reproduce accepted, declined, stale, and unrelated responses with
    focused offline tests before changing routing.
  - [x] Route only an accepted current bug offer to read-only Dev_Agent and
    enforce the tool boundary in `approval_check`.
  - [x] Require a later explicit fix instruction; retain normal approval gates
    and block vague assent. Verify relevant suites and `git diff --check`.
  - Verified offline: 179 focused routing, approval, project-access, Web,
    Telegram, and Matrix tests passed. Live Web/Element validation remains a
    separate owner check.

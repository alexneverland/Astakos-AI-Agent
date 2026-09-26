# Spec and Implementation Plan: Web Research Providers, Slice 1

## Objective

Add a small provider layer owned by the existing `Web_Agent` so one research
request can collect normalized results from the existing Web search and a new
read-only public GitHub search without changing Supervisor ownership or current
`duckduckgo_search` behavior.

## Commands

- Focused tests: `venv\Scripts\python.exe -m pytest tests/test_web_research.py tests/test_duckduckgo_search.py tests/test_web_failure_guard.py -q --basetemp=<isolated-dir>`
- Full tests: `venv\Scripts\python.exe -m pytest tests -q --basetemp=<isolated-dir>`
- Diff validation: `git diff --check`

## Project Structure

- `services/web_research.py`: normalized contracts, registry, selection, aggregation, deduplication, and provider failure isolation.
- `services/web_providers.py`: concrete Web and read-only GitHub providers.
- `tools/web.py`: LangChain tool boundary and backward-compatible Web-search wrapper.
- `core/agents.py`: existing Web Agent tool binding and research-call budget only.
- `tests/`: provider, fallback, normalization, deduplication, and Web Agent regression coverage.

## Architecture Decisions

- The Supervisor remains the top-level router and `Web_Agent` remains the owner of research.
- The LLM selects provider identifiers through tool arguments; deterministic code validates identifiers and availability but does not interpret natural language.
- `duckduckgo_search` remains a compatible public tool and delegates to the Web provider path.
- GitHub research is read-only and uses the public REST search endpoint without requiring credentials. Optional existing credentials are not read or changed in this slice.
- Provider failures are returned as structured internal status and do not discard successful results from other providers.
- No new dependency, background process, database, credential, Setup Wizard, Docker, runtime, or watchdog change.

## Testing Strategy

- Write failing unit tests before each implementation increment.
- Mock every network boundary; tests must remain offline.
- Preserve existing DDGS tests and Web Agent failure/budget behavior.
- Cover provider selection, result normalization, unavailable fallback, duplicate URL handling, and exception isolation.

## Success Criteria

- `research_web(query, sources=[...], max_results=...)` can selectively use `web` and `github`.
- Every successful provider returns the same `SearchResult` shape with provenance.
- One failed or unavailable provider does not fail the entire request.
- Duplicate canonical URLs appear once.
- Existing `duckduckgo_search` output and bounded retry behavior remain compatible.
- The Web Agent exposes the new safe tool without exposing mutation-capable `github_manager`.

## Deferred

- Reddit, X, LinkedIn, YouTube, RSS, cookies, browser-session authentication.
- Concurrent provider execution and persistent health caching.
- Agent Reach installation or runtime dependency.

## Risks and Mitigations

- Web-search regression: keep the legacy tool contract and run its existing tests unchanged.
- GitHub rate limiting: use one bounded request, expose availability/failure honestly, and fall back to Web results.
- Tool loops: count `research_web` within the existing three-call research budget.
- Untrusted content: retain provider provenance and pass results through existing external-content boundaries.

---

# Spec and Implementation Plan: Reddit Research Provider, Slice 2

## Objective

Add a zero-credential Reddit discovery provider to the existing `research_web`
skill. It will reuse the established Web-search adapter with a Reddit site
constraint, accept only Reddit result URLs, and normalize them with
`source="reddit"`.

## Boundaries

- Keep Supervisor and Web Agent ownership unchanged.
- Do not call Reddit's direct Data API without approved access/OAuth.
- Do not read browser cookies, install CLIs, scrape post bodies/comments, or
  modify credentials, config, Setup Wizard, Docker, runtime, or databases.
- Treat search snippets as discovery evidence, not complete Reddit threads.

## Success Criteria

- `research_web(..., sources=["reddit"])` selects only the Reddit provider.
- The provider issues a bounded Reddit-site Web query and returns only absolute
  `reddit.com` or `redd.it` URLs with normalized Reddit provenance.
- Non-Reddit results are discarded, provider failures remain isolated, and a
  failed Reddit provider can use the existing Web fallback.
- Existing Web and GitHub behavior remains unchanged and all network tests are
  offline.

## Deferred

- Authenticated Reddit API access and full post/comment retrieval.
- Browser sessions, cookies, OpenCLI, and `rdt-cli`.
- Concurrent provider execution, persistent health state, and new UI/settings.

---

# Spec and Implementation Plan: LinkedIn Research Provider, Slice 4

## Objective

Add zero-credential public LinkedIn discovery to the existing `research_web`
skill so the Web Agent can return up to 10 normalized LinkedIn results, including
job listings, while preserving the separate authenticated post-publishing flow.

## Commands

- Focused tests: `venv\Scripts\python.exe -m pytest tests/test_web_research.py tests/test_web_failure_guard.py -q --basetemp=<isolated-dir>`
- Diff validation: `git diff --check`

## Project Structure and Code Style

- Extend the existing provider pattern in `services/web_providers.py`.
- Register the provider through `astakos_skills/research_web.py` and document its
  selection in `core/prompts.md`.
- Return the existing typed `SearchResult` contract with `source="linkedin"`;
  do not introduce a parallel search tool or dependency.

## Testing Strategy

- Write offline failing tests before implementation.
- Mock the Web-provider boundary and verify exact query, result limit, normalized
  provenance, accepted LinkedIn hosts, and rejected lookalike domains.
- Verify registry selection and Web Agent prompt/tool behavior remain compatible.

## Boundaries

- Always: use bounded public Web discovery and strict LinkedIn hostname checks.
- Ask first: any future authenticated LinkedIn/Talent API integration.
- Never: read or reuse `LINKEDIN_TOKEN`, browser cookies, private pages, or alter
  post publishing, credentials, Setup Wizard, Docker, runtime, or databases.
- Treat snippets as discovery evidence; do not claim a listing is active unless
  the returned public evidence establishes that.

## Success Criteria

- `research_web(..., sources=["linkedin"], max_results=10)` is valid.
- Only `linkedin.com` and its real subdomains are returned; lookalikes are dropped.
- Results use normalized LinkedIn provenance and remain isolated from provider failures.
- Existing Web, GitHub, Reddit, YouTube, and LinkedIn publishing behavior is unchanged.

## Open Questions

- None for this public-discovery slice. Official Talent API access remains deferred.

---

# Implementation Plan: Private Matrix Server, Phase 1

## Objective

Deploy an isolated Synapse/PostgreSQL homeserver on Neverland for private
Element X access over Tailscale. Keep all Astakos integration out of this
phase.

## Build Order

1. Enroll Neverland in Tailscale and confirm its permanent MagicDNS identity.
2. Generate Synapse configuration only after the immutable `server_name` is
   approved.
3. Validate and start the isolated Compose project with no published database
   port and a loopback-only Synapse listener.
4. Add private HTTPS through Tailscale, then create accounts and smoke-test
   Element X.
5. Document the backup boundary for signing keys, configuration, and database
   data.

## Risks and Mitigations

- Wrong permanent Matrix identity: do not generate Synapse config before the
  Tailscale DNS name is confirmed.
- Accidental exposure: keep Synapse on loopback and PostgreSQL only on the
  internal Compose network; use Tailscale for remote access.
- Secret leakage: store runtime secrets only under `C:\Neverland-Matrix` and
  never print or commit them.
- Astakos regression: use a separate directory, Compose project, containers,
  network, and volumes.

## Verification Checkpoints

- After enrollment: Tailscale reports `Running` and a stable MagicDNS name.
- Before startup: Compose renders successfully and exposes no PostgreSQL port.
- After startup: both services are healthy and local Synapse health responds.
- After HTTPS: the homeserver is reachable only from the tailnet.

---

# Implementation Plan: Matrix Channel Selection

Module id: `channel-selection`

## Overview

Implement the approved `ASTAKOS_EXTERNAL_CHANNEL` contract as a pure resolver.
This is an additive foundation for later Matrix startup wiring; it does not
change the running Web or Telegram processes.

## Architecture decisions

- Put the contract in `core/messaging_channel.py`, not `config.py`, so it can be
  imported and tested without loading provider credentials or transports.
- Default only a genuinely missing environment variable to `telegram`.
  Configured blank or unknown values fail closed.
- Keep this slice side-effect free. `boot.py` integration waits for the
  `matrix-text` module to provide a real Matrix entry point.

## Dependency order

1. Add failing offline tests for the approved configuration contract.
2. Add the minimal typed resolver that makes those tests pass.
3. Run the focused suite, nearby startup regressions, and diff validation.

## Risks and mitigations

- Backward-compatibility regression: prove the missing-variable default remains
  `telegram`.
- Accidental runtime change: do not edit `boot.py`, `.env`, `config.py`, or any
  transport in this slice.
- Permissive misconfiguration: reject blank and unsupported configured values.

## Verification checkpoint

- Focused channel-selection tests pass offline.
- Existing setup/Telegram-watchdog startup tests pass unchanged.
- `git diff --check` is clean and only the approved files belong to this slice.

---

# Implementation Plan: Trusted Matrix Text Channel

The approved implementation plan lives in `tasks/matrix-text-plan.md`.

Build order:

1. Durable Matrix event/reply lifecycle in the existing state-store boundary.
2. Encrypted allowlisted Matrix transport with an injected turn handler.
3. Matrix-only application turn pipeline using the existing graph and memory
   abstractions.
4. External-channel startup wiring and private encrypted smoke test.

## Final media-output slice

1. Parse generated-file markers into a typed Matrix reply while persisting only
   the clean assistant text.
2. Persist text/file delivery progress with the existing Matrix event lifecycle.
3. Encrypt and send approved `outputs/` files, then verify retry behavior and
   the complete offline Matrix parity suite.

Runtime selection and encrypted Element conversations are operational. The
Matrix-wide parity audit remains a separate, broader final gate in
`tasks/todo.md`; `tasks/matrix-parity-audit.md` is an older evidence snapshot,
not proof that every current behavior has been rechecked.

---

# Implementation Plan: Unified Conversation, Shared Context

Module id: `shared-conversation-context`. The approved scope and acceptance
criteria are in `tasks/shared-conversation-context-spec.md`; module ordering is
in `tasks/unified-conversation-map.md`. This plan covers only the first module.

## Architecture decisions

- Reuse the existing SQLite conversation history and its canonical bounded
  context loader. Do not migrate, duplicate, or backfill persisted messages.
- Preserve each entry's role, timestamp/order, and source channel in the model
  context. Web, Matrix, and Telegram already write to the shared store.
- Keep transport sends out of this slice. Web and the selected external channel
  run in separate processes; mirroring needs its own reviewed contract.

## Task order and checkpoint

1. Add offline RED tests for Matrix → Web and Web → Matrix context, including
   a Telegram turn, duplicate suppression, provenance, and window bounds.
2. Make the smallest change to `memory/conversation_history.py` and the Matrix
   caller so all three channels use the canonical cross-channel policy.
3. Run the focused and nearby history/turn suites and check the diff. The
   owner has verified cross-channel message visibility; a live test of whether
   the assistant uses prior context from the other channel remains open.

Tasks and verification checkboxes are tracked under
`Unified conversation: shared-conversation-context` in `tasks/todo.md`.

## Risks and mitigations

- Context contamination: preserve existing untrusted-content formatting and
  source labels; test roles, order, and bounded windows.
- Duplicate history: reuse persisted message IDs for merging; no new writes or
  mirrored rows in this module.
- Scope creep: do not touch approvals, routines, media, credentials, runtime
  startup, or the broader Matrix parity gate.

## Mirroring decision

External user text mirrored from Web is attributed as a relay from the owner,
not impersonated as a native Element/Telegram user message. The reviewed
delivery/retry contract is in `tasks/selected-channel-mirroring-spec.md`.

## Next module: selected-channel-mirroring

The owner approved the persistent SQLite outbox described in
`tasks/selected-channel-mirroring-spec.md`. Web display deliveries are inserted
atomically with their source history rows and drained by the selected external
process. Mirror copies stay out of conversation history and the inbound graph.
Offline tests cover queue ordering, retry, restart, and channel switching;
the owner confirmed a live Web → Element text exchange.

---

# Implementation Plan: Matrix Capability Proposal Parity

Objective: after a trusted ordinary Matrix text turn, deliver the same
classified capability-gap proposal or existing-bug investigation offer used by
Web/Telegram, without granting draft authority for bugs or creating a
permanent record for transient/uncertain failures.

1. Add offline regression tests for a missing capability, an existing bug,
   stale/duplicate suppression, and no outbound delivery on uncertainty or
   external-derived turns.
2. Reuse one proposal renderer and the canonical self-awareness classifier;
   pass the persisted Matrix user row ID through the completed-turn hook.
3. Send through the selected Matrix delivery boundary, persist the delivered
   assistant proposal with Matrix provenance, and verify focused Matrix and
   capability suites. No new approval behavior, credentials, or runtime setup.

The full bug diagnosis-to-fix workflow and remaining live Matrix parity checks
remain separate tasks. The task checklist is in `tasks/todo.md`.

---

# Implementation Plan: Existing-Bug Investigation Handoff

Objective: honor a current bug-investigation offer with a read-only diagnostic
turn, then require a separate explicit owner instruction before any fix. The
acceptance contract and exclusions are in `tasks/bug-investigation-flow-spec.md`.

1. Add focused offline RED tests for current-offer acceptance, refusal/question
   and stale/unrelated replies, with shared Web/Telegram/Matrix graph routing.
2. Route affirmative intent semantically to Dev_Agent in diagnosis-only mode.
   Bind read-only project inspection tools and enforce the same boundary in
   `approval_check` against injected or looped mutating calls.
3. Cover the second explicit fix request and vague-assent negative case;
   preserve normal access and tool approvals. Run focused routing/approval
   regressions, relevant channel tests, and `git diff --check`.

No live cloud calls, credentials, database migrations, runtime edits, or PR
actions are part of this implementation. Live owner testing remains separate.

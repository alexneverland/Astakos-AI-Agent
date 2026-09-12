# Web multi-result search specification

## Goal

Make list-style Web research return a useful set of unique results through one
bounded search operation, while keeping LinkedIn job searches distinct from
LinkedIn post creation.

## Acceptance criteria

- A bare LinkedIn mention is not assigned deterministic search or publication
  meaning; the Supervisor resolves it contextually. An explicit LinkedIn
  post-creation request still resolves to `linkedin_post`.
- `duckduckgo_search` accepts a bounded requested result count, aggregates valid
  results across its existing backends, and deduplicates canonical URLs.
- Partial successful results are returned even if a later backend or translated
  fallback fails.
- Alternate-query fallback is attempted only when a primary backend responded
  but the requested result count was not reached. Work remains bounded to four
  backend attempts total: two primary engines for the original query and two
  recovery engines for either the rewritten query or direct outage recovery.
- When no provider returns usable evidence, the tool returns clearly marked,
  unverified live-search links that the Web Agent surfaces without synthesis.
- A contextual Web request without a known recipient does not expose the
  reversible Messenger draft tool. Existing recipient-backed draft flows remain
  intact.
- Web synthesis must not call a result active, current, or recent unless the
  retrieved evidence establishes that status.

## Boundaries

No new dependency, provider, credential, Docker, database, or live-network test.
Do not add wording-specific interpretation rules or a LinkedIn-only search tool.

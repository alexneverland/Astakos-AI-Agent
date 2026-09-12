# Web multi-result search specification

## Goal

Make list-style Web research return a useful set of unique results through one
bounded search operation, while keeping LinkedIn job searches distinct from
LinkedIn post creation.

## Acceptance criteria

- A LinkedIn job-search request resolves to the safe `web_search` capability;
  an explicit LinkedIn post-creation request still resolves to `linkedin_post`.
- `duckduckgo_search` accepts a bounded requested result count, aggregates valid
  results across its existing backends, and deduplicates canonical URLs.
- Partial successful results are returned even if a later backend or translated
  fallback fails.
- Greek fallback is attempted only when the requested result count has not been
  reached, and work remains bounded to the two configured backends for the
  original query plus those same backends for one translated query.
- A Web request already classified as `web_search` does not expose the unrelated
  reversible Messenger draft tool. Existing Messenger draft flows remain intact.
- Web synthesis must not call a result active, current, or recent unless the
  retrieved evidence establishes that status.

## Boundaries

No new dependency, provider, credential, Docker, database, or live-network test.
Do not add wording-specific interpretation rules or a LinkedIn-only search tool.

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

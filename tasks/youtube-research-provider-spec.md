# Spec: YouTube research provider

## Objective

Add `youtube` as an explicit read-only source for the existing `research_web`
tool so the Web Agent can discover public YouTube videos with normalized
titles, snippets, and links.

## Commands

- Focused tests: `venv\Scripts\python.exe -m pytest tests\test_web_research.py -q`
- Diff validation: `git diff --check`

## Project Structure

- `services/web_providers.py`: bounded YouTube discovery adapter.
- `astakos_skills/research_web.py`: canonical provider registration and tool contract.
- `core/prompts.md`: Web Agent source-selection boundary.
- `core/capability_registry.json`: user-facing capability description.
- `tests/test_web_research.py`: offline provider and guidance regressions.

## Code Style

Follow the existing `RedditResearchProvider`: inject `WebSearchProvider`, apply
a strict hostname predicate before accepting evidence, and return normalized
`SearchResult` objects with source provenance.

## Testing Strategy

Offline tests must verify accepted canonical YouTube hosts, rejected lookalike
hosts, normalized provenance, provider-health mapping, canonical registration,
and agent-facing documentation. No live network calls are allowed.

## Boundaries

- Always: remain read-only, cap aggregate results at 10, preserve source URLs.
- Ask first: transcripts, comments, authenticated YouTube APIs, or credentials.
- Never: treat search snippets as full video/transcript contents or bypass URL validation.

## Success Criteria

- `research_web(..., sources=["youtube"])` is accepted.
- Results contain only `youtube.com` subdomains or `youtu.be` URLs.
- Results use `source="youtube"` and declare Web-search discovery provenance.
- Web Agent guidance states that YouTube results are discovery snippets, not transcripts/comments.
- Existing Web/GitHub/Reddit behavior remains unchanged and focused tests pass.

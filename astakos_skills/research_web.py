"""Read-only multi-source research skill for the existing Web Agent."""

from __future__ import annotations

import json

from langchain_core.tools import tool

from services.web_providers import (
    GitHubResearchProvider,
    RedditResearchProvider,
    WebSearchProvider,
)
from services.web_research import ResearchProviderRegistry


def _default_research_registry() -> ResearchProviderRegistry:
    """Build the first-slice provider registry for one request."""
    return ResearchProviderRegistry([
        WebSearchProvider(),
        GitHubResearchProvider(),
        RedditResearchProvider(),
    ])


@tool
def research_web(
    query: str,
    sources: list[str] | None = None,
    max_results: int = 10,
) -> str:
    """Research selected read-only sources with normalized provenance.

    Valid sources are ``web``, ``github``, and ``reddit``. Select only
    sources relevant to the request. Use GitHub search qualifiers such as
    ``repo:owner/name`` and ``is:issue`` for repository-specific research.
    Reddit provides discovery snippets and links through bounded Web search,
    not full post/comment retrieval. The total result count is capped at 10.
    """
    from tools.web import _format_unverified_search_fallback

    try:
        response = _default_research_registry().search(
            query,
            sources=sources,
            max_results=max_results,
        )
    except ValueError as exc:
        return f"[WEB_TOOL_ERROR][research_web][reason=invalid_sources] {exc}"

    providers_unavailable = any(
        not status.available
        for status in response.statuses.values()
    )
    if not response.results and providers_unavailable:
        return _format_unverified_search_fallback(query, response.fallback_urls)

    payload = {
        "results": [result.to_dict() for result in response.results],
        "providers": {
            name: {
                "available": status.available,
                "detail": status.detail,
            }
            for name, status in response.statuses.items()
        },
        "fallback_used": response.fallback_used,
    }
    return "[RESEARCH_RESULTS]\n" + json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

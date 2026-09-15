"""Offline tests for the Web Agent research-provider layer."""

import json

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from services.web_providers import GitHubResearchProvider, WebSearchProvider
from services.web_research import (
    ProviderHealth,
    ProviderUnavailableError,
    ResearchResponse,
    ResearchProviderRegistry,
    SearchResult,
)


@dataclass
class FakeProvider:
    """Small controllable provider used at the registry boundary."""

    name: str
    results: list[SearchResult]
    available: bool = True
    failure: Exception | None = None
    calls: int = 0

    def check(self) -> ProviderHealth:
        """Report whether the fake adapter is ready."""
        return ProviderHealth(
            provider=self.name,
            available=self.available,
            detail="ready" if self.available else "not configured",
        )

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return configured results or raise the configured failure."""
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.results[:max_results]


def _result(title: str, url: str, source: str) -> SearchResult:
    return SearchResult(title=title, url=url, content=title, source=source)


def test_registry_selects_only_requested_providers() -> None:
    """Provider selection is explicit and does not query every source."""
    web = FakeProvider("web", [_result("Web", "https://example.com/web", "web")])
    github = FakeProvider(
        "github",
        [_result("GitHub", "https://github.com/example/repo/issues/1", "github")],
    )
    registry = ResearchProviderRegistry([web, github])

    response = registry.search("voice bug", sources=["github"], max_results=5)

    assert [result.source for result in response.results] == ["github"]
    assert web.calls == 0
    assert github.calls == 1


def test_registry_normalizes_result_contract() -> None:
    """Every provider result exposes the shared provenance-preserving fields."""
    result = SearchResult(
        title="Issue title",
        url="https://github.com/example/repo/issues/1",
        content="Issue body",
        source="github",
        author="octocat",
        published_at="2026-09-15T00:00:00Z",
        score=9.5,
        metadata={"state": "open"},
    )

    assert result.to_dict() == {
        "title": "Issue title",
        "url": "https://github.com/example/repo/issues/1",
        "content": "Issue body",
        "source": "github",
        "author": "octocat",
        "published_at": "2026-09-15T00:00:00Z",
        "score": 9.5,
        "metadata": {"state": "open"},
    }


def test_registry_falls_back_to_web_when_requested_provider_is_unavailable() -> None:
    """An unavailable requested source degrades to the registered Web provider."""
    web = FakeProvider(
        "web",
        [_result("Fallback", "https://example.com/fallback", "web")],
    )
    github = FakeProvider("github", [], available=False)
    registry = ResearchProviderRegistry([web, github])

    response = registry.search("voice bug", sources=["github"], max_results=5)

    assert [result.title for result in response.results] == ["Fallback"]
    assert response.statuses["github"].available is False
    assert response.fallback_used is True
    assert web.calls == 1
    assert github.calls == 0


def test_registry_does_not_fall_back_when_requested_provider_has_no_matches() -> None:
    """A healthy provider's empty result is authoritative for explicit selection."""
    web = FakeProvider("web", [_result("Fallback", "https://example.com/fallback", "web")])
    github = FakeProvider("github", [])
    registry = ResearchProviderRegistry([web, github])

    response = registry.search("no matching issue", sources=["github"], max_results=5)

    assert response.results == []
    assert response.fallback_used is False
    assert response.statuses["github"].available is True
    assert web.calls == 0
    assert github.calls == 1


def test_registry_deduplicates_canonical_urls_across_providers() -> None:
    """Equivalent URLs from different sources appear only once."""
    web = FakeProvider(
        "web",
        [_result("Web copy", "HTTPS://GitHub.com/example/repo/issues/1/", "web")],
    )
    github = FakeProvider(
        "github",
        [_result("GitHub copy", "https://github.com/example/repo/issues/1", "github")],
    )
    registry = ResearchProviderRegistry([web, github])

    response = registry.search("voice bug", sources=["web", "github"], max_results=5)

    assert len(response.results) == 1


def test_registry_isolates_provider_exception_and_keeps_other_results() -> None:
    """One broken source cannot discard evidence from another source."""
    web = FakeProvider("web", [_result("Healthy", "https://example.com/healthy", "web")])
    github = FakeProvider(
        "github",
        [],
        failure=ProviderUnavailableError("github", "rate limited"),
    )
    registry = ResearchProviderRegistry([github, web])

    response = registry.search("voice bug", sources=["github", "web"], max_results=5)

    assert [result.title for result in response.results] == ["Healthy"]
    assert response.statuses["github"].available is False
    assert response.statuses["github"].detail == "rate limited"


def test_registry_rejects_unknown_provider_without_calling_known_sources() -> None:
    """Unknown source identifiers are validated, not silently interpreted."""
    web = FakeProvider("web", [])
    registry = ResearchProviderRegistry([web])

    with pytest.raises(ValueError, match="Unknown research provider"):
        registry.search("voice bug", sources=["reddit"], max_results=5)

    assert web.calls == 0


@pytest.mark.parametrize(
    "url",
    ["", "not-a-url", "/relative", "ftp://example.com/file"],
)
def test_canonical_result_url_rejects_non_http_absolute_urls(url: str) -> None:
    """Only navigable absolute Web URLs can become verified evidence."""
    from services.web_research import canonical_result_url

    assert canonical_result_url(url) == ""


def test_web_provider_normalizes_ddgs_results() -> None:
    """The existing DDGS backend shape is converted to ``SearchResult``."""
    with patch("ddgs.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = [{
            "title": "Example",
            "href": "https://example.com/article",
            "body": "Article summary",
        }]
        mock_ddgs.return_value.__enter__.return_value = instance

        results = WebSearchProvider().search("example", 1)

    assert results == [SearchResult(
        title="Example",
        url="https://example.com/article",
        content="Article summary",
        source="web",
        metadata={"backend": "duckduckgo"},
    )]


def test_web_provider_exposes_unverified_links_on_complete_failure() -> None:
    """Provider outage returns navigation fallbacks without treating them as results."""
    from ddgs.exceptions import DDGSException

    with patch("ddgs.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.side_effect = DDGSException("offline")
        mock_ddgs.return_value.__enter__.return_value = instance

        with pytest.raises(ProviderUnavailableError) as error:
            WebSearchProvider().search("voice bug", 5)

    assert error.value.provider == "web"
    assert error.value.fallback_urls == (
        "https://www.google.com/search?q=voice+bug",
        "https://www.bing.com/search?q=voice+bug",
    )


def test_web_provider_treats_accent_only_rewrite_as_same_query(capsys) -> None:
    """The provider preserves the legacy accent-insensitive rewrite guard."""
    response = MagicMock(text='{"query": "δοκιμη"}')
    with patch("ddgs.DDGS") as mock_ddgs, patch(
        "services.gemini.safe_gemini_call",
        return_value=response,
    ):
        instance = MagicMock()
        instance.text.return_value = []
        mock_ddgs.return_value.__enter__.return_value = instance

        with pytest.raises(ProviderUnavailableError):
            WebSearchProvider().search("δοκιμή", 5)

    assert instance.text.call_count == 4
    assert "Gemini returned the original query." in capsys.readouterr().out


def test_web_provider_clamps_explicit_zero_limit_to_one() -> None:
    """The provider preserves the legacy minimum of one requested result."""
    with patch("ddgs.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = [
            {
                "title": f"Example {index}",
                "href": f"https://example.com/{index}",
                "body": "Summary",
            }
            for index in range(5)
        ]
        mock_ddgs.return_value.__enter__.return_value = instance

        results = WebSearchProvider().search("example", 0)

    assert len(results) == 1
    assert instance.text.call_args.kwargs["max_results"] == 1


def test_github_provider_normalizes_public_issue_results(monkeypatch) -> None:
    """GitHub's raw issue response is hidden behind the shared result contract."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "items": [{
            "title": "Audio decoder fails",
            "html_url": "https://github.com/example/repo/issues/7",
            "body": "WebM cannot be decoded.",
            "user": {"login": "octocat"},
            "created_at": "2026-09-15T00:00:00Z",
            "score": 12.0,
            "state": "open",
            "comments": 4,
            "repository_url": "https://api.github.com/repos/example/repo",
        }]
    }
    get = MagicMock(return_value=response)
    monkeypatch.setattr("services.web_providers.requests.get", get)

    results = GitHubResearchProvider().search("audio decoder is:issue", 5)

    assert results == [SearchResult(
        title="Audio decoder fails",
        url="https://github.com/example/repo/issues/7",
        content="WebM cannot be decoded.",
        source="github",
        author="octocat",
        published_at="2026-09-15T00:00:00Z",
        score=12.0,
        metadata={
            "state": "open",
            "comments": 4,
            "repository": "example/repo",
            "kind": "issue",
        },
    )]
    get.assert_called_once()
    assert get.call_args.kwargs["params"] == {
        "q": "audio decoder is:issue",
        "per_page": 5,
        "sort": "updated",
        "order": "desc",
    }


def test_github_provider_reports_rate_limit_without_retrying(monkeypatch) -> None:
    """A bounded GitHub request fails honestly when its public quota is exhausted."""
    response = MagicMock()
    response.status_code = 403
    response.headers = {"x-ratelimit-remaining": "0"}
    response.json.return_value = {"message": "API rate limit exceeded"}
    get = MagicMock(return_value=response)
    monkeypatch.setattr("services.web_providers.requests.get", get)

    with pytest.raises(ProviderUnavailableError, match="rate limit"):
        GitHubResearchProvider().search("audio decoder is:issue", 5)

    get.assert_called_once()


def test_reddit_provider_discovers_and_normalizes_only_reddit_urls() -> None:
    """Reddit discovery rejects unrelated Web results and keeps provenance."""
    from services.web_providers import RedditResearchProvider

    web = MagicMock()
    web.search.return_value = [
        SearchResult(
            title="Useful discussion",
            url="https://www.reddit.com/r/LocalLLaMA/comments/abc/topic/",
            content="Community feedback",
            source="web",
            metadata={"backend": "bing"},
        ),
        SearchResult(
            title="Unrelated result",
            url="https://example.com/not-reddit",
            content="Not Reddit",
            source="web",
        ),
    ]

    results = RedditResearchProvider(web_provider=web).search("voice agents", 5)

    assert results == [SearchResult(
        title="Useful discussion",
        url="https://www.reddit.com/r/LocalLLaMA/comments/abc/topic/",
        content="Community feedback",
        source="reddit",
        metadata={"backend": "bing", "discovered_via": "web_search"},
    )]
    web.search.assert_called_once_with("site:reddit.com voice agents", 5)


def test_reddit_provider_maps_web_unavailability_to_reddit() -> None:
    """A failed discovery backend reports the selected provider as Reddit."""
    from services.web_providers import RedditResearchProvider

    web = MagicMock()
    web.check.return_value = ProviderHealth("web", False, "DDGS unavailable")
    provider = RedditResearchProvider(web_provider=web)

    assert provider.check() == ProviderHealth(
        "reddit",
        False,
        "Reddit discovery unavailable: DDGS unavailable",
    )


def test_default_research_registry_includes_reddit_provider() -> None:
    """The canonical research skill accepts Reddit as a selectable source."""
    from astakos_skills.research_web import _default_research_registry

    registry = _default_research_registry()

    assert "reddit" in registry._providers


def test_research_web_tool_serializes_results_and_provider_status(monkeypatch) -> None:
    """The agent-facing tool preserves provenance and partial-provider status."""
    from astakos_skills.research_web import research_web

    registry = MagicMock()
    registry.search.return_value = ResearchResponse(
        results=[_result("Issue", "https://github.com/example/repo/issues/1", "github")],
        statuses={
            "github": ProviderHealth("github", True, "ready"),
            "web": ProviderHealth("web", False, "offline"),
        },
    )
    monkeypatch.setattr(
        "astakos_skills.research_web._default_research_registry",
        lambda: registry,
    )

    raw = research_web.invoke({
        "query": "audio bug",
        "sources": ["github", "web"],
        "max_results": 4,
    })

    marker, payload_text = raw.split("\n", 1)
    payload = json.loads(payload_text)
    assert marker == "[RESEARCH_RESULTS]"
    assert payload["results"][0]["source"] == "github"
    assert payload["providers"]["web"] == {
        "available": False,
        "detail": "offline",
    }
    registry.search.assert_called_once_with(
        "audio bug",
        sources=["github", "web"],
        max_results=4,
    )


def test_research_web_tool_uses_canonical_skill_module() -> None:
    """New agent-facing capabilities live under ``astakos_skills``."""
    from tools.system import research_web

    assert research_web.func.__module__ == "astakos_skills.research_web"


def test_research_web_tool_preserves_healthy_provider_zero_matches(monkeypatch) -> None:
    """A healthy explicit source returns an empty aggregate, not Web links."""
    from astakos_skills.research_web import research_web

    registry = MagicMock()
    registry.search.return_value = ResearchResponse(
        results=[],
        statuses={"github": ProviderHealth("github", True, "ready")},
    )
    monkeypatch.setattr(
        "astakos_skills.research_web._default_research_registry",
        lambda: registry,
    )

    raw = research_web.invoke({
        "query": "no matching issue",
        "sources": ["github"],
        "max_results": 5,
    })

    marker, payload_text = raw.split("\n", 1)
    assert marker == "[RESEARCH_RESULTS]"
    assert json.loads(payload_text)["results"] == []

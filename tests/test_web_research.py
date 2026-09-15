"""Offline tests for the Web Agent research-provider layer."""

from dataclasses import dataclass

import pytest

from services.web_research import (
    ProviderHealth,
    ProviderUnavailableError,
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
    web = FakeProvider("web", [_result("Fallback", "https://example.com/fallback", "web")])
    github = FakeProvider("github", [], available=False)
    registry = ResearchProviderRegistry([web, github])

    response = registry.search("voice bug", sources=["github"], max_results=5)

    assert [result.title for result in response.results] == ["Fallback"]
    assert response.statuses["github"].available is False
    assert response.fallback_used is True
    assert web.calls == 1
    assert github.calls == 0


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

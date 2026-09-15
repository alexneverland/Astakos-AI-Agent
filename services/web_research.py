"""Provider contracts and aggregation for Web Agent research."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Protocol
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class SearchResult:
    """One normalized result returned by any research provider."""

    title: str
    url: str
    content: str
    source: str
    author: str | None = None
    published_at: str | None = None
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return the stable serialization consumed at tool boundaries."""
        return asdict(self)


@dataclass(frozen=True)
class ProviderHealth:
    """Readiness state for one provider adapter."""

    provider: str
    available: bool
    detail: str = ""


@dataclass(frozen=True)
class ResearchResponse:
    """Normalized aggregate plus per-provider execution status."""

    results: list[SearchResult]
    statuses: dict[str, ProviderHealth]
    fallback_used: bool = False
    fallback_urls: tuple[str, ...] = ()


class ProviderUnavailableError(RuntimeError):
    """A provider cannot serve the request without failing the whole search."""

    def __init__(
        self,
        provider: str,
        detail: str,
        *,
        fallback_urls: Iterable[str] = (),
    ) -> None:
        super().__init__(detail)
        self.provider = provider
        self.detail = detail
        self.fallback_urls = tuple(fallback_urls)


class ResearchProvider(Protocol):
    """Minimal contract implemented by Web Agent research providers."""

    name: str

    def check(self) -> ProviderHealth:
        """Return whether the adapter is ready for a bounded request."""
        ...

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return normalized results or raise ``ProviderUnavailableError``."""
        ...


def canonical_result_url(url: str) -> str:
    """Normalize a URL for cross-provider duplicate detection."""
    parts = urlsplit((url or "").strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


class ResearchProviderRegistry:
    """Select providers and isolate their failures behind one result contract."""

    def __init__(self, providers: Iterable[ResearchProvider] = ()) -> None:
        self._providers: dict[str, ResearchProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: ResearchProvider) -> None:
        """Register or replace one provider by its stable identifier."""
        name = str(getattr(provider, "name", "") or "").strip().lower()
        if not name:
            raise ValueError("Research provider requires a name")
        self._providers[name] = provider

    def search(
        self,
        query: str,
        *,
        sources: Iterable[str] | None = None,
        max_results: int = 10,
    ) -> ResearchResponse:
        """Run selected providers and preserve any successful evidence."""
        selected = self._normalize_sources(sources)
        limit = self._normalize_limit(max_results)
        statuses: dict[str, ProviderHealth] = {}
        batches: list[list[SearchResult]] = []
        fallback_urls: list[str] = []

        for name in selected:
            batch, status, provider_fallbacks = self._search_one(
                self._providers[name], query, limit
            )
            statuses[name] = status
            fallback_urls.extend(provider_fallbacks)
            if batch:
                batches.append(batch)

        fallback_used = False
        if not batches and "web" not in selected and "web" in self._providers:
            fallback_used = True
            batch, status, provider_fallbacks = self._search_one(
                self._providers["web"], query, limit
            )
            statuses["web"] = status
            fallback_urls.extend(provider_fallbacks)
            if batch:
                batches.append(batch)

        return ResearchResponse(
            results=self._round_robin_unique(batches, limit),
            statuses=statuses,
            fallback_used=fallback_used,
            fallback_urls=tuple(dict.fromkeys(fallback_urls)),
        )

    def _normalize_sources(self, sources: Iterable[str] | None) -> list[str]:
        selected = [str(source).strip().lower() for source in (sources or ["web"])]
        selected = list(dict.fromkeys(source for source in selected if source))
        unknown = [source for source in selected if source not in self._providers]
        if unknown:
            raise ValueError(f"Unknown research provider: {', '.join(unknown)}")
        return selected or ["web"]

    @staticmethod
    def _normalize_limit(max_results: int) -> int:
        try:
            return max(1, min(int(max_results), 10))
        except (TypeError, ValueError):
            return 10

    @staticmethod
    def _search_one(
        provider: ResearchProvider,
        query: str,
        limit: int,
    ) -> tuple[list[SearchResult], ProviderHealth, tuple[str, ...]]:
        try:
            health = provider.check()
        except Exception as exc:
            return [], ProviderHealth(provider.name, False, str(exc)), ()
        if not health.available:
            return [], health, ()

        try:
            return provider.search(query, limit), health, ()
        except ProviderUnavailableError as exc:
            return (
                [],
                ProviderHealth(provider.name, False, exc.detail),
                exc.fallback_urls,
            )
        except Exception as exc:
            return [], ProviderHealth(provider.name, False, str(exc)), ()

    @staticmethod
    def _round_robin_unique(
        batches: list[list[SearchResult]],
        limit: int,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        max_batch_size = max((len(batch) for batch in batches), default=0)
        for index in range(max_batch_size):
            for batch in batches:
                if index >= len(batch):
                    continue
                result = batch[index]
                canonical = canonical_result_url(result.url)
                if not canonical or canonical in seen_urls:
                    continue
                seen_urls.add(canonical)
                results.append(result)
                if len(results) >= limit:
                    return results
        return results

"""Concrete read-only providers used by Web Agent research."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Callable
from urllib.parse import parse_qs, quote_plus, urlsplit

import requests

from services.web_research import (
    ProviderHealth,
    ProviderUnavailableError,
    SearchResult,
    canonical_result_url,
)


def _bounded_result_limit(value: Any, *, default: int = 5) -> int:
    """Clamp a provider result limit while preserving an explicit zero."""
    try:
        parsed = default if value is None else int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 10))


class WebSearchProvider:
    """Adapt the existing bounded DDGS strategy to normalized results."""

    name = "web"
    _PRIMARY_BACKENDS = ("duckduckgo", "google")
    _RECOVERY_BACKENDS = ("bing", "brave")

    def check(self) -> ProviderHealth:
        """Report whether the installed DDGS adapter can be imported."""
        try:
            import ddgs  # noqa: F401
        except ImportError:
            return ProviderHealth(self.name, False, "ddgs is not installed")
        return ProviderHealth(self.name, True, "DDGS adapter ready")

    def search(
        self,
        query: str,
        max_results: int,
        *,
        url_filter: Callable[[str], bool] | None = None,
        empty_result_is_success: bool = False,
    ) -> list[SearchResult]:
        """Search bounded DDGS backends while preserving partial successes.

        ``empty_result_is_success`` lets a domain-scoped provider distinguish a
        healthy zero-match response from complete backend unavailability.
        """
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
        from services.gemini import safe_gemini_call

        query = str(query or "").strip()
        if not query:
            return []
        limit = _bounded_result_limit(max_results)
        collected: list[SearchResult] = []
        seen_urls: set[str] = set()

        def run_backends(search_query: str, phase: str, backends: tuple[str, ...]) -> bool:
            had_response = False
            for backend in backends:
                if len(collected) >= limit:
                    break
                try:
                    with DDGS(timeout=5) as ddgs:
                        raw_results = list(ddgs.text(
                            search_query,
                            max_results=limit,
                            backend=backend,
                        ))
                    had_response = True
                    valid_count = self._append_results(
                        raw_results,
                        backend=backend,
                        destination=collected,
                        seen_urls=seen_urls,
                        limit=limit,
                        url_filter=url_filter,
                    )
                    if valid_count:
                        print(
                            f"[Web Search]: {phase} DDGS search succeeded via "
                            f"{backend} ({valid_count} valid results)."
                        )
                    elif raw_results:
                        print(
                            f"[Web Search]: {phase} DDGS result from {backend} "
                            "contained no valid entries."
                        )
                except RatelimitException:
                    print(f"[Web Search]: {phase} DDGS backend {backend} was rate limited.")
                except TimeoutException:
                    print(f"[Web Search]: {phase} DDGS backend {backend} timed out.")
                except DDGSException:
                    print(f"[Web Search]: {phase} DDGS backend {backend} failed with DDGSException.")
                except Exception:
                    print(f"[Web Search]: {phase} DDGS backend {backend} failed unexpectedly.")
            return had_response

        original_responded = run_backends(
            query, "Original", self._PRIMARY_BACKENDS
        )
        if len(collected) >= limit:
            return collected[:limit]

        if not original_responded:
            print("[Web Search]: Primary DDGS backends failed; trying recovery backends directly.")
            recovery_responded = run_backends(
                query,
                "Original recovery",
                self._RECOVERY_BACKENDS,
            )
            if collected:
                return collected[:limit]
            if empty_result_is_success and recovery_responded:
                return []
            raise self._unavailable(query)

        try:
            print("[Web Search]: Original query incomplete; requesting an alternate English search query.")
            prompt = (
                "Rewrite or translate this into a different, short English search query. "
                "Preserve requested websites, role names, and locations. "
                "Return STRICT JSON with exactly one key 'query'.\n"
                f"Original query: {query}"
            )
            response = safe_gemini_call(prompt, retries=1)
            alternate_query = self._parse_alternate_query(response.text, query)
            print("[Web Search]: Gemini produced an English fallback query; retrying DDGS.")
            before_fallback = len(collected)
            run_backends(
                alternate_query,
                "English fallback",
                self._RECOVERY_BACKENDS,
            )
            if len(collected) == before_fallback:
                print("[Web Search]: English fallback DDGS retry produced no valid results.")
        except Exception as exc:
            print(
                "[Web Search]: English fallback failed before retry "
                f"({type(exc).__name__})."
            )
            if not collected:
                print("[Web Search]: Trying recovery backends with the original query.")
                run_backends(query, "Original recovery", self._RECOVERY_BACKENDS)

        if collected:
            return collected[:limit]
        if empty_result_is_success:
            return []
        raise self._unavailable(query)

    @staticmethod
    def _append_results(
        raw_results: list[Any],
        *,
        backend: str,
        destination: list[SearchResult],
        seen_urls: set[str],
        limit: int,
        url_filter: Callable[[str], bool] | None = None,
    ) -> int:
        """Validate and normalize one DDGS backend response."""
        valid_count = 0
        for raw in raw_results:
            if len(destination) >= limit:
                break
            if not isinstance(raw, dict):
                continue
            title = raw.get("title")
            url = raw.get("href")
            content = raw.get("body")
            if not all(isinstance(value, str) for value in (title, url, content)):
                continue
            title, url, content = title.strip(), url.strip(), content.strip()
            canonical = canonical_result_url(url)
            if (
                not title
                or not canonical
                or not content
                or canonical in seen_urls
                or (url_filter is not None and not url_filter(url))
            ):
                continue
            seen_urls.add(canonical)
            destination.append(SearchResult(
                title=title,
                url=url,
                content=content,
                source="web",
                metadata={"backend": backend},
            ))
            valid_count += 1
        return valid_count

    @staticmethod
    def _parse_alternate_query(raw_response: str, original_query: str) -> str:
        raw = str(raw_response or "").strip()
        fenced_match = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )
        payload = fenced_match.group(1) if fenced_match else raw
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            print("[Web Search]: English fallback skipped because Gemini returned invalid JSON.")
            raise ValueError("Invalid JSON") from exc
        if not isinstance(data, dict) or len(data) != 1 or "query" not in data:
            print("[Web Search]: English fallback skipped because Gemini returned an invalid JSON structure.")
            raise ValueError("Invalid JSON structure")
        query = data["query"]
        if not isinstance(query, str) or not query.strip():
            print("[Web Search]: English fallback skipped because Gemini returned an empty or non-string query.")
            raise ValueError("Invalid query")
        query = query.strip()
        if WebSearchProvider._fold_query(query) == WebSearchProvider._fold_query(
            original_query
        ):
            print("[Web Search]: English fallback skipped because Gemini returned the original query.")
            raise ValueError("Same query")
        return query

    @staticmethod
    def _fold_query(query: str) -> str:
        """Match the legacy accent-insensitive alternate-query comparison."""
        normalized = unicodedata.normalize("NFKD", query.strip())
        return "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        ).casefold()

    def _unavailable(self, query: str) -> ProviderUnavailableError:
        encoded = quote_plus(query)
        return ProviderUnavailableError(
            self.name,
            "No verified Web results were available.",
            fallback_urls=(
                f"https://www.google.com/search?q={encoded}",
                f"https://www.bing.com/search?q={encoded}",
            ),
        )


class RedditResearchProvider:
    """Discover public Reddit discussions through bounded Web search results."""

    name = "reddit"

    def __init__(self, web_provider: WebSearchProvider | None = None) -> None:
        self._web_provider = web_provider or WebSearchProvider()

    def check(self) -> ProviderHealth:
        """Map Web-search readiness to the Reddit discovery capability."""
        health = self._web_provider.check()
        if not health.available:
            return ProviderHealth(
                self.name,
                False,
                f"Reddit discovery unavailable: {health.detail}",
            )
        return ProviderHealth(
            self.name,
            True,
            "Reddit discovery via Web search ready",
        )

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return only Reddit-hosted results with normalized provenance."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = _bounded_result_limit(max_results)
        discovered = self._web_provider.search(
            f"(site:reddit.com OR site:redd.it) {query}",
            limit,
            url_filter=self._is_reddit_url,
        )
        results: list[SearchResult] = []
        for result in discovered:
            if not self._is_reddit_url(result.url):
                continue
            results.append(SearchResult(
                title=result.title,
                url=result.url,
                content=result.content,
                source=self.name,
                author=result.author,
                published_at=result.published_at,
                score=result.score,
                metadata={
                    **result.metadata,
                    "discovered_via": "web_search",
                },
            ))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _is_reddit_url(url: str) -> bool:
        """Accept canonical Reddit hosts and reject lookalike domains."""
        hostname = (urlsplit(url).hostname or "").lower()
        return (
            hostname == "reddit.com"
            or hostname.endswith(".reddit.com")
            or hostname == "redd.it"
        )


class YouTubeResearchProvider:
    """Discover public YouTube videos through bounded Web search results."""

    name = "youtube"

    def __init__(self, web_provider: WebSearchProvider | None = None) -> None:
        self._web_provider = web_provider or WebSearchProvider()

    def check(self) -> ProviderHealth:
        """Map Web-search readiness to the YouTube discovery capability."""
        health = self._web_provider.check()
        if not health.available:
            return ProviderHealth(
                self.name,
                False,
                f"YouTube discovery unavailable: {health.detail}",
            )
        return ProviderHealth(
            self.name,
            True,
            "YouTube discovery via Web search ready",
        )

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return only YouTube-hosted results with normalized provenance."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = _bounded_result_limit(max_results)
        discovered = self._web_provider.search(
            f"(site:youtube.com OR site:youtu.be) {query}",
            limit,
            url_filter=self._is_youtube_url,
        )
        results: list[SearchResult] = []
        for result in discovered:
            if not self._is_youtube_url(result.url):
                continue
            results.append(SearchResult(
                title=result.title,
                url=result.url,
                content=result.content,
                source=self.name,
                author=result.author,
                published_at=result.published_at,
                score=result.score,
                metadata={
                    **result.metadata,
                    "discovered_via": "web_search",
                },
            ))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        """Accept canonical YouTube video URLs and reject pages or lookalikes."""
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        if hostname == "youtu.be":
            return bool(parsed.path.strip("/").split("/", 1)[0])
        if hostname != "youtube.com" and not hostname.endswith(".youtube.com"):
            return False
        if parsed.path.rstrip("/") == "/watch":
            return bool(parse_qs(parsed.query).get("v"))
        return any(
            parsed.path.startswith(prefix) and bool(parsed.path[len(prefix):].strip("/"))
            for prefix in ("/shorts/", "/live/")
        )


class LinkedInResearchProvider:
    """Discover public LinkedIn pages through bounded Web search results."""

    name = "linkedin"

    def __init__(self, web_provider: WebSearchProvider | None = None) -> None:
        self._web_provider = web_provider or WebSearchProvider()

    def check(self) -> ProviderHealth:
        """Map Web-search readiness to the LinkedIn discovery capability."""
        health = self._web_provider.check()
        if not health.available:
            return ProviderHealth(
                self.name,
                False,
                f"LinkedIn discovery unavailable: {health.detail}",
            )
        return ProviderHealth(
            self.name,
            True,
            "LinkedIn discovery via Web search ready",
        )

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return only LinkedIn-hosted results with normalized provenance."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = _bounded_result_limit(max_results)
        discovered = self._web_provider.search(
            f"site:linkedin.com {query}",
            limit,
            url_filter=self._is_linkedin_url,
            empty_result_is_success=True,
        )
        results: list[SearchResult] = []
        for result in discovered:
            if not self._is_linkedin_url(result.url):
                continue
            results.append(SearchResult(
                title=result.title,
                url=result.url,
                content=result.content,
                source=self.name,
                author=result.author,
                published_at=result.published_at,
                score=result.score,
                metadata={
                    **result.metadata,
                    "discovered_via": "web_search",
                },
            ))
            if len(results) >= limit:
                break
        return results

    @staticmethod
    def _is_linkedin_url(url: str) -> bool:
        """Accept public LinkedIn hosts and reject non-Web or lookalike URLs."""
        try:
            parsed = urlsplit(url)
        except ValueError:
            return False
        hostname = (parsed.hostname or "").lower()
        return (
            parsed.scheme.lower() in {"http", "https"}
            and (hostname == "linkedin.com" or hostname.endswith(".linkedin.com"))
        )


class GitHubResearchProvider:
    """Search public GitHub issues and pull requests without mutation access."""

    name = "github"
    _SEARCH_URL = "https://api.github.com/search/issues"

    def check(self) -> ProviderHealth:
        """Report readiness of the built-in HTTP adapter."""
        return ProviderHealth(self.name, True, "public GitHub REST adapter ready")

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Return normalized public issue and pull-request search results."""
        query = str(query or "").strip()
        if not query:
            return []
        limit = _bounded_result_limit(max_results)
        try:
            response = requests.get(
                self._SEARCH_URL,
                params={
                    "q": query,
                    "per_page": limit,
                    "sort": "updated",
                    "order": "desc",
                },
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2026-03-10",
                    "User-Agent": "Astakos-AI-Agent",
                },
                timeout=10,
            )
        except requests.RequestException as exc:
            raise ProviderUnavailableError(self.name, f"GitHub request failed: {exc}") from exc

        if response.status_code != 200:
            detail = self._error_detail(response)
            raise ProviderUnavailableError(self.name, detail)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(self.name, "GitHub returned invalid JSON") from exc
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise ProviderUnavailableError(self.name, "GitHub returned an invalid result shape")
        return [
            result
            for item in items[:limit]
            if (result := self._normalize_item(item)) is not None
        ]

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        remaining = response.headers.get("x-ratelimit-remaining", "")
        try:
            payload = response.json()
            message = payload.get("message", "") if isinstance(payload, dict) else ""
        except ValueError:
            message = ""
        if response.status_code in (403, 429) and (
            remaining == "0" or "rate limit" in str(message).lower()
        ):
            return "GitHub rate limit exceeded"
        return f"GitHub search failed with status {response.status_code}"

    @staticmethod
    def _normalize_item(item: Any) -> SearchResult | None:
        if not isinstance(item, dict):
            return None
        title = item.get("title")
        url = item.get("html_url")
        if not isinstance(title, str) or not title.strip():
            return None
        if not isinstance(url, str) or not canonical_result_url(url):
            return None
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        repository_url = str(item.get("repository_url") or "")
        repository = repository_url.removeprefix("https://api.github.com/repos/")
        raw_score = item.get("score")
        score = float(raw_score) if isinstance(raw_score, (int, float)) else None
        body = item.get("body")
        content = body.strip()[:4000] if isinstance(body, str) and body.strip() else title.strip()
        return SearchResult(
            title=title.strip(),
            url=url.strip(),
            content=content,
            source="github",
            author=str(user.get("login") or "") or None,
            published_at=str(item.get("created_at") or "") or None,
            score=score,
            metadata={
                "state": item.get("state"),
                "comments": item.get("comments", 0),
                "repository": repository,
                "kind": "pull_request" if item.get("pull_request") else "issue",
            },
        )

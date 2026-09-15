"""Concrete read-only providers used by Web Agent research."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import quote_plus

import requests

from services.web_research import (
    ProviderHealth,
    ProviderUnavailableError,
    SearchResult,
    canonical_result_url,
)


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

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Search bounded DDGS backends while preserving partial successes."""
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
        from services.gemini import safe_gemini_call

        query = str(query or "").strip()
        if not query:
            return []
        limit = max(1, min(int(max_results or 5), 10))
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
            run_backends(query, "Original recovery", self._RECOVERY_BACKENDS)
            if collected:
                return collected[:limit]
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
        raise self._unavailable(query)

    @staticmethod
    def _append_results(
        raw_results: list[Any],
        *,
        backend: str,
        destination: list[SearchResult],
        seen_urls: set[str],
        limit: int,
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
            if not title or not canonical or not content or canonical in seen_urls:
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
        limit = max(1, min(int(max_results or 5), 10))
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

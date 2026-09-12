import pytest
import json
from unittest.mock import patch, MagicMock
from tools.web import duckduckgo_search

from typing import Any

class MockMastroResponse:
    def __init__(self, text: str) -> None:
        """Initializes a mock response with the given text payload."""
        self.text = text

def test_ddgs_aggregates_unique_results_until_requested_count() -> None:
    """Collect unique results across backends until the requested count is met."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.side_effect = [
            [{"title": "First", "href": "https://example.com/jobs/1", "body": "One"}],
            [
                {"title": "Duplicate", "href": "https://example.com/jobs/1/", "body": "Same"},
                {"title": "Second", "href": "https://example.com/jobs/2", "body": "Two"},
            ],
        ]
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "jobs", "max_results": 2})

        assert "First" in res
        assert "Second" in res
        assert "Duplicate" not in res
        mock_gemini.assert_not_called()
        assert mock_instance.text.call_count == 2
        mock_instance.text.assert_any_call("jobs", max_results=2, backend="duckduckgo")
        mock_instance.text.assert_any_call("jobs", max_results=2, backend="google")


def test_ddgs_malformed_entry_ignored_and_later_valid_succeeds() -> None:
    """Ensures malformed DDGS results are skipped and valid ones are processed."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.side_effect = [[
            "not a dict",
            {"title": None, "href": "http://test.com", "body": "body"},
            {"title": "Valid Title", "href": "http://valid.com", "body": "Valid body"},
            {"title": "Second Title", "href": "http://second.com", "body": "Second body"},
        ]]
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "δοκιμή", "max_results": 2})

        assert "Valid Title" in res
        assert "Second Title" in res
        mock_gemini.assert_not_called()
        mock_instance.text.assert_called_once_with(
            "δοκιμή", max_results=2, backend="duckduckgo"
        )


def test_ddgs_preserves_partial_results_when_later_attempts_fail() -> None:
    """A later backend failure must not discard an earlier valid result."""
    from ddgs.exceptions import DDGSException

    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.side_effect = [
            [{"title": "Only result", "href": "https://example.com/1", "body": "One"}],
            DDGSException("backend unavailable"),
            DDGSException("fallback unavailable"),
            DDGSException("fallback unavailable"),
            DDGSException("fallback unavailable"),
            DDGSException("fallback unavailable"),
            DDGSException("fallback unavailable"),
            DDGSException("fallback unavailable"),
        ]
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_gemini.return_value = MockMastroResponse(
            json.dumps({"query": "logistics manager Thessaloniki"})
        )

        res = duckduckgo_search.invoke({
            "query": "αγγελίες logistics manager Θεσσαλονίκη",
            "max_results": 5,
        })

        assert "Only result" in res
        assert "WEB_TOOL_ERROR" not in res
        assert mock_instance.text.call_count == 4
        mock_gemini.assert_called_once()


def test_ddgs_placeholder_only_triggers_fallback(capsys: Any) -> None:
    """Ensures a fenced Gemini JSON response triggers a fallback search."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()

        def mock_text(query: str, max_results: int, backend: str) -> list[Any]:
            """Mocks DDGS text search, returning placeholders for Greek and valid results for English."""
            if query == "δοκιμή":
                # Return placeholder
                return [{"title": " ", "href": "", "body": ""}]
            elif query == "test":
                # Return valid
                return [{"title": "En Title", "href": "http://en.com", "body": "En body"}]
            return []

        mock_instance.text.side_effect = mock_text
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse("```json\n{\"query\": \"test\"}\n```")

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        assert "En Title" in res

        mock_gemini.assert_called_once()

        assert mock_instance.text.call_count == 4
        calls = mock_instance.text.call_args_list
        # Two primary attempts, then two recovery attempts for the rewrite.
        assert calls[0][0][0] == "δοκιμή"
        assert calls[0][1]["backend"] == "duckduckgo"
        assert calls[1][0][0] == "δοκιμή"
        assert calls[1][1]["backend"] == "google"
        assert calls[2][0][0] == "test"
        assert calls[2][1]["backend"] == "bing"
        assert calls[3][0][0] == "test"
        assert calls[3][1]["backend"] == "brave"
        output = capsys.readouterr().out
        assert "Original query incomplete; requesting an alternate English search query." in output
        assert "Gemini produced an English fallback query; retrying DDGS." in output
        assert "English fallback DDGS search succeeded via bing" in output


def test_ddgs_fallback_failure_returns_live_search_links(capsys: Any) -> None:
    """Complete DDGS failure degrades to useful live-search links."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse(json.dumps({"query": "test"}))

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        assert "https://www.google.com/search" in res
        assert "https://www.bing.com/search" in res
        assert "[WEB_TOOL_ERROR][duckduckgo_search][reason=unverified_live_links]" in res

        # Two primary attempts plus two rewritten-query recovery attempts.
        assert mock_instance.text.call_count == 4
        assert "English fallback DDGS retry produced no valid results." in capsys.readouterr().out


def test_ddgs_english_only_requests_alternate_query(capsys: Any) -> None:
    """An English-only query receives the same bounded rewrite recovery."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_gemini.return_value = MockMastroResponse(json.dumps({"query": "english only"}))

        res = duckduckgo_search.invoke({"query": "english only"})

        assert mock_instance.text.call_count == 4
        mock_gemini.assert_called_once()
        assert "https://www.google.com/search?q=english+only" in res
        assert "Gemini returned the original query." in capsys.readouterr().out


@pytest.mark.parametrize(("gemini_json", "expected_log"), [
    ("invalid json", "Gemini returned invalid JSON."),
    ('{"query": "test",}', "Gemini returned invalid JSON."),
    ('{"query": ""}', "Gemini returned an empty or non-string query."),
    ('{}', "Gemini returned an invalid JSON structure."),
    ('{"query": "english", "extra": true}', "Gemini returned an invalid JSON structure."),
    ('"just a string"', "Gemini returned an invalid JSON structure."),
    ('{"query": 42}', "Gemini returned an empty or non-string query.")
])
def test_ddgs_gemini_strict_validation_fails_closed(
    gemini_json: str,
    expected_log: str,
    capsys: Any,
) -> None:
    """Invalid Gemini JSON returns live links without calling fallback DDGS."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse(gemini_json)

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        # Two primary attempts plus two direct recovery attempts.
        assert mock_instance.text.call_count == 4
        mock_gemini.assert_called_once()
        assert "https://www.google.com/search" in res
        assert "[WEB_TOOL_ERROR][duckduckgo_search][reason=unverified_live_links]" in res
        assert expected_log in capsys.readouterr().out


def test_ddgs_same_query_gemini_fails_closed(capsys: Any) -> None:
    """Ensures that a translated query identical to the original fails closed."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse(json.dumps({"query": "δοκιμή  "}))

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        # Two primary attempts plus two direct recovery attempts.
        assert mock_instance.text.call_count == 4
        mock_gemini.assert_called_once()
        assert "https://www.google.com/search" in res
        assert "Gemini returned the original query." in capsys.readouterr().out


def test_ddgs_uses_recovery_backend_after_primary_failures() -> None:
    """A supported recovery backend can return results when primary engines fail."""
    from ddgs.exceptions import DDGSException

    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()

        def mock_text(query: str, max_results: int, backend: str) -> list[dict[str, str]]:
            if backend == "bing":
                return [{
                    "title": "Recovered job",
                    "href": "https://example.com/recovered",
                    "body": "Recovered through another engine",
                }]
            raise DDGSException("backend unavailable")

        mock_instance.text.side_effect = mock_text
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "logistics manager jobs", "max_results": 1})

        assert "Recovered job" in res
        assert any(call.kwargs.get("backend") == "bing" for call in mock_instance.text.call_args_list)
        mock_gemini.assert_not_called()


def test_ddgs_rewrites_latin_query_when_all_original_attempts_are_empty() -> None:
    """Latin or mixed queries receive the same bounded alternate-query recovery."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()

        def mock_text(query: str, max_results: int, backend: str) -> list[dict[str, str]]:
            if query == "warehouse logistics jobs Thessaloniki" and backend == "bing":
                return [{
                    "title": "Alternate result",
                    "href": "https://example.com/alternate",
                    "body": "Found with a rewritten query",
                }]
            return []

        mock_instance.text.side_effect = mock_text
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_gemini.return_value = MockMastroResponse(
            json.dumps({"query": "warehouse logistics jobs Thessaloniki"})
        )

        res = duckduckgo_search.invoke({
            "query": "linkedin logistic manager thessaloniki",
            "max_results": 5,
        })

        assert "Alternate result" in res
        mock_gemini.assert_called_once()


def test_ddgs_returns_live_search_links_after_complete_provider_failure() -> None:
    """A total provider outage returns useful live searches instead of a dead end."""
    from ddgs.exceptions import DDGSException

    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.side_effect = DDGSException("backend unavailable")
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "logistics manager Thessaloniki"})

        assert "https://www.google.com/search?q=logistics+manager+Thessaloniki" in res
        assert "https://www.bing.com/search?q=logistics+manager+Thessaloniki" in res
        assert "[WEB_TOOL_ERROR][duckduckgo_search][reason=unverified_live_links]" in res
        assert mock_instance.text.call_count == 4
        mock_gemini.assert_not_called()


def test_ddgs_caps_backend_attempts_across_original_and_rewritten_queries() -> None:
    """The alternate-query path shares one four-attempt backend budget."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = []
        mock_ddgs.return_value.__enter__.return_value = mock_instance
        mock_gemini.return_value = MockMastroResponse(
            json.dumps({"query": "warehouse logistics jobs Thessaloniki"})
        )

        duckduckgo_search.invoke({
            "query": "linkedin logistic manager thessaloniki",
            "max_results": 10,
        })

        assert mock_instance.text.call_count == 4


def test_ddgs_docstring_documents_unverified_live_link_fallback() -> None:
    """Tool metadata tells callers that provider failure returns unverified links."""
    assert "unverified live search links" in duckduckgo_search.description

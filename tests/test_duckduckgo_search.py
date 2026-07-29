import pytest
import json
from unittest.mock import patch, MagicMock
from tools.web import duckduckgo_search

from typing import Any

class MockMastroResponse:
    def __init__(self, text: str) -> None:
        """Initializes a mock response with the given text payload."""
        self.text = text

def test_ddgs_valid_original_returns_directly() -> None:
    """Ensures valid DDGS results are returned directly without calling Gemini."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [
            {"title": "Test Title", "href": "http://test.com", "body": "Test body"}
        ]
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        assert "Test Title" in res
        mock_gemini.assert_not_called()

        # Only called once (duckduckgo first backend)
        mock_instance.text.assert_called_once_with("δοκιμή", max_results=5, backend="duckduckgo")


def test_ddgs_malformed_entry_ignored_and_later_valid_succeeds() -> None:
    """Ensures malformed DDGS results are skipped and valid ones are processed."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [
            "not a dict",
            {"title": None, "href": "http://test.com", "body": "body"},
            {"title": "Valid Title", "href": "http://valid.com", "body": "Valid body"}
        ]
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        assert "Valid Title" in res
        mock_gemini.assert_not_called()
        mock_instance.text.assert_called_once()


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

        assert mock_instance.text.call_count == 3
        calls = mock_instance.text.call_args_list
        # original pass
        assert calls[0][0][0] == "δοκιμή"
        assert calls[0][1]["backend"] == "duckduckgo"
        assert calls[1][0][0] == "δοκιμή"
        assert calls[1][1]["backend"] == "google"
        # fallback pass returns early on first backend
        assert calls[2][0][0] == "test"
        assert calls[2][1]["backend"] == "duckduckgo"
        output = capsys.readouterr().out
        assert "Original Greek query failed; requesting an English fallback query." in output
        assert "Gemini produced an English fallback query; retrying DDGS." in output
        assert "English fallback DDGS search succeeded via duckduckgo" in output


def test_ddgs_fallback_failure_preserves_error(capsys: Any) -> None:
    """Ensures that if both original and fallback searches fail, the error is preserved."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse(json.dumps({"query": "test"}))

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        # Check existing failure format (handles localized string)
        assert "WEB_TOOL_ERROR" in res or "search_all_failed" in res

        # 2 original backend attempts + 2 fallback backend attempts
        assert mock_instance.text.call_count == 4
        assert "English fallback DDGS retry produced no valid results." in capsys.readouterr().out


def test_ddgs_english_only_fails_closed_without_gemini(capsys: Any) -> None:
    """Ensures an English-only query fails closed without triggering the Gemini fallback."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        res = duckduckgo_search.invoke({"query": "english only"})

        assert mock_instance.text.call_count == 2
        mock_gemini.assert_not_called()
        assert "English fallback skipped because the original query has no Greek characters" in capsys.readouterr().out


@pytest.mark.parametrize(("gemini_json", "expected_log"), [
    ("invalid json", "Gemini returned invalid JSON."),
    ('{"query": ""}', "Gemini returned an empty or non-string query."),
    ('{}', "Gemini returned an invalid JSON structure."),
    ('{"query": "english", "extra": true}', "Gemini returned an invalid JSON structure."),
    ('"just a string"', "Gemini returned invalid JSON."),
    ('{"query": 42}', "Gemini returned an empty or non-string query.")
])
def test_ddgs_gemini_strict_validation_fails_closed(
    gemini_json: str,
    expected_log: str,
    capsys: Any,
) -> None:
    """Ensures strict validation of Gemini JSON fails closed without calling fallback DDGS."""
    with patch("ddgs.DDGS") as mock_ddgs, \
         patch("services.gemini.safe_gemini_call") as mock_gemini:

        mock_instance = MagicMock()
        mock_instance.text.return_value = [] # Always fail
        mock_ddgs.return_value.__enter__.return_value = mock_instance

        mock_gemini.return_value = MockMastroResponse(gemini_json)

        res = duckduckgo_search.invoke({"query": "δοκιμή"})

        # 2 original attempts only, no fallback attempts
        assert mock_instance.text.call_count == 2
        mock_gemini.assert_called_once()
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

        # 2 original attempts only
        assert mock_instance.text.call_count == 2
        mock_gemini.assert_called_once()
        assert "Gemini returned the original query." in capsys.readouterr().out

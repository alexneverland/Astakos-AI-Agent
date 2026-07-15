import pytest
from unittest.mock import patch, MagicMock
from astakos_skills.hn_briefing import _fetch_hn_items, hn_briefing

# --- Mock Data ---

MOCK_XML_HAPPY_PATH = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
    <title>Hacker News</title>
    <link>https://news.ycombinator.com/</link>
    <description>Links for the intellectually curious, ranked by readers.</description>
    <item>
        <title>Test Story 1</title>
        <link>https://example.com/1</link>
        <description>Description for story 1</description>
        <pubDate>Wed, 15 Jul 2026 10:00:00 +0000</pubDate>
    </item>
    <item>
        <title>Test Story 2</title>
        <link>https://example.com/2</link>
        <description>Description for story 2</description>
        <pubDate>Wed, 15 Jul 2026 10:05:00 +0000</pubDate>
    </item>
</channel>
</rss>
"""

MOCK_XML_EMPTY = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
<channel>
    <title>Hacker News</title>
</channel>
</rss>
"""

# --- Tests ---

@patch("astakos_skills.hn_briefing.requests.get")
def test_fetch_hn_items_happy_path(mock_get):
    """Test that valid XML is parsed correctly into dicts."""
    mock_resp = MagicMock()
    mock_resp.text = MOCK_XML_HAPPY_PATH
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    items = _fetch_hn_items(limit=5)
    
    assert len(items) == 2
    assert items[0]["title"] == "Test Story 1"
    assert items[0]["link"] == "https://example.com/1"
    assert items[1]["title"] == "Test Story 2"


@patch("astakos_skills.hn_briefing.requests.get")
def test_hn_briefing_empty_feed(mock_get):
    """Test behavior when the RSS feed has no items."""
    mock_resp = MagicMock()
    mock_resp.text = MOCK_XML_EMPTY
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    # If no items are found, the tool returns a specific string
    result = hn_briefing.invoke({"limit": 5})
    assert result == "No Hacker News stories could be fetched."


@patch("astakos_skills.hn_briefing.safe_llm_invoke")
@patch("astakos_skills.hn_briefing.requests.get")
def test_hn_briefing_llm_failure_fallback(mock_get, mock_llm):
    """Test deterministic fallback if LLM throws an error or returns empty."""
    # 1. Setup mock RSS response
    mock_resp = MagicMock()
    mock_resp.text = MOCK_XML_HAPPY_PATH
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    # 2. Force LLM to raise an Exception
    mock_llm.side_effect = Exception("Simulated LLM Timeout/Error")

    # 3. Call the tool
    result = hn_briefing.invoke({"limit": 5})

    # 4. Assert it returns the deterministic fallback instead of crashing
    assert "Hacker News Briefing:" in result
    assert "- Test Story 1" in result
    assert "- Test Story 2" in result


@patch("astakos_skills.hn_briefing.requests.get")
def test_hn_briefing_network_failure(mock_get):
    """Test behavior if requests.get completely fails."""
    mock_get.side_effect = Exception("Connection Refused")
    
    result = hn_briefing.invoke({"limit": 5})
    assert result == "Hacker News could not be fetched right now."

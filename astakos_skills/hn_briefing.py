from __future__ import annotations

import datetime
import html
import re
import xml.etree.ElementTree as ET

import requests
import config
from core.brain import llm, safe_llm_invoke
from core.i18n import load_prompt
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool


_HN_RSS_URL = "https://news.ycombinator.com/rss"


def _clean_text(text: str, max_chars: int = 280) -> str:
    """Remove HTML noise and keep feed text compact."""
    if not text:
        return ""
    cleaned = html.unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _fetch_hn_items(limit: int = 6) -> list[dict[str, str]]:
    """Fetch top Hacker News RSS items."""
    safe_limit = max(1, min(int(limit or 6), 10))
    response = requests.get(_HN_RSS_URL, timeout=20)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    items: list[dict[str, str]] = []

    for item in root.findall(".//item")[:safe_limit]:
        title = _clean_text(item.findtext("title", ""))
        link = _clean_text(item.findtext("link", ""))
        description = _clean_text(item.findtext("description", ""), max_chars=220)
        pub_date = _clean_text(item.findtext("pubDate", ""))

        if not title:
            continue

        items.append(
            {
                "title": title,
                "link": link,
                "description": description,
                "pub_date": pub_date,
            }
        )

    return items


def _render_hn_prompt(*, today: str, hn_items: str) -> str:
    """Render the HN briefing prompt with runtime values."""
    prompt = load_prompt("hn_briefing.md")
    replacements = {
        "{BOT_NAME}": config.BOT_NAME,
        "{USER_NAME}": config.USER_NAME,
        "{RESPONSE_LANGUAGE}": config.RESPONSE_LANGUAGE,
        "{TODAY}": today,
        "{HN_ITEMS}": hn_items,
    }
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, str(value))
    return prompt


def _format_items(items: list[dict[str, str]]) -> str:
    """Convert fetched RSS items to deterministic text for the prompt."""
    blocks = []
    for i, item in enumerate(items, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[ITEM {i}]",
                    f"Title: {item.get('title', '')}",
                    f"Link: {item.get('link', '')}",
                    f"Summary: {item.get('description', '')}",
                    f"Published: {item.get('pub_date', '')}",
                ]
            )
        )
    return "\n\n".join(blocks)


@tool
def hn_briefing(limit: int = 6) -> str:
    """
    Creates a Hacker News morning briefing from the HN RSS feed.
    """
    try:
        print("[HNBriefing]: Fetching Hacker News feed...")
        items = _fetch_hn_items(limit=limit)
        if not items:
            return "No Hacker News stories could be fetched."
    except Exception as exc:
        print(f"[HNBriefing]: Feed error - {exc}")
        return "Hacker News could not be fetched right now."

    today = datetime.datetime.now().strftime("%A, %d %B %Y")
    raw_items = _format_items(items)
    prompt = _render_hn_prompt(today=today, hn_items=raw_items)

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        content = getattr(response, "content", "") or ""
        if content.strip():
            return content
    except Exception as exc:
        print(f"[HNBriefing]: LLM error - {exc}")

    # deterministic fallback if LLM fails
    lines = ["Hacker News Briefing:"]
    for item in items[:5]:
        lines.append(f"- {item['title']}")
    return "\n".join(lines)


def get_hn_briefing(limit: int = 6) -> str:
    """Backward-compatible wrapper for direct callers."""
    return hn_briefing.invoke({"limit": limit})


if __name__ == "__main__":
    print(get_hn_briefing())

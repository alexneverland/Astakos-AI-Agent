from __future__ import annotations

import datetime

import config
from core.brain import llm, safe_llm_invoke
from core.i18n import load_prompt
from core.utils import clean_message
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from tools.web import get_news


def _render_morning_prompt(
    *,
    today: str,
    local_news: str,
    tech_news: str,
    ai_news: str,
    roblox_news: str,
) -> str:
    """Render the external morning briefing prompt with runtime values."""
    prompt = load_prompt("morning_briefing.md")
    replacements = {
        "{BOT_NAME}": config.BOT_NAME,
        "{USER_NAME}": config.USER_NAME,
        "{KID1_NAME}": config.KID1_NAME,
        "{DEFAULT_CITY}": config.DEFAULT_CITY,
        "{RESPONSE_LANGUAGE}": config.RESPONSE_LANGUAGE,
        "{TODAY}": today,
        "{LOCAL_NEWS}": local_news,
        "{TECH_NEWS}": tech_news,
        "{AI_NEWS}": ai_news,
        "{ROBLOX_NEWS}": roblox_news,
    }
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, str(value))
    return prompt


@tool
def morning_briefing() -> str:
    """
    Creates a daily morning briefing from live news.

    Includes local/default-city news, technology, AI, and Roblox/kids-friendly
    highlights when available.
    """
    try:
        print("[MorningBriefing]: Fetching news...")
        tech_news = get_news.invoke({"topic": "Technology news", "limit": 2})
        local_news = get_news.invoke({"topic": f"{config.DEFAULT_CITY} local news", "limit": 2})
        ai_news = get_news.invoke({"topic": "AI news", "limit": 3})
        roblox_news = get_news.invoke({"topic": "Roblox news", "limit": 2})
    except Exception as exc:
        print(f"[MorningBriefing]: Error fetching news - {exc}")
        tech_news = "Technology news could not be fetched."
        local_news = "Local news could not be fetched."
        ai_news = "AI news could not be fetched."
        roblox_news = "Roblox news could not be fetched."

    today = datetime.datetime.now().strftime("%A, %d %B %Y")
    prompt = _render_morning_prompt(
        today=today,
        local_news=local_news,
        tech_news=tech_news,
        ai_news=ai_news,
        roblox_news=roblox_news,
    )

    try:
        response = safe_llm_invoke(llm, [HumanMessage(content=prompt)])
        return clean_message(response.content)
    except Exception as exc:
        print(f"[MorningBriefing]: LLM error - {exc}")
        return (
            f"⚠️ Good morning {config.USER_NAME}. "
            "There was a problem creating the morning briefing."
        )


def get_morning_briefing() -> str:
    """Backward-compatible wrapper for direct callers."""
    return morning_briefing.invoke({})


if __name__ == "__main__":
    print(get_morning_briefing())

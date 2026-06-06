from langchain_core.tools import tool

import json
@tool
def text_stats(text: str) -> str:
    """
    Calculates text statistics and returns a JSON string.
    Returns characters, words, lines, and estimated_reading_seconds.
    """
    characters = len(text)
    words = len(text.split())
    lines = len(text.splitlines())
    
    # Average reading speed: ~200 words per minute -> ~3.33 words per second
    estimated_reading_seconds = max(1, round(words / 3.33)) if words > 0 else 0
    
    result = {
        "characters": characters,
        "words": words,
        "lines": lines,
        "estimated_reading_seconds": estimated_reading_seconds
    }
    return json.dumps(result)

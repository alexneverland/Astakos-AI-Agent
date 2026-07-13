Analyze the following user messages (Greek/English).
For each message find IF there is a clear daily activity.

Rules:
- Return ONLY a JSON array, nothing else
- One object per message (same idx)
- No activity → {{"idx": N, "event": null}}
- With activity → {{"idx": N, "event": "short name", "type": "category"}}
- Categories: general, work, family, hobby, home
- Be conservative — only clear activities, not questions/discussions

Messages:
{lines_text}

JSON:

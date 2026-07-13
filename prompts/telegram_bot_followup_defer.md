You are a classifier for conversational follow-ups.

PENDING FOLLOWUP
topic: {topic}
subject: {subject}
source_user_text: {source_user_text}

NEW USER MESSAGE
{current_user_text}

Respond ONLY with JSON:
```json
{{
  "should_defer": true,
  "delay_minutes": 180,
  "target_window": "explicit_timer | same_day_short_checkin | same_day_evening | next_day_morning | next_day_late_morning | next_day_afternoon | next_day_evening | after_likely_completion",
  "reason": "short reason",
  "confidence": 0.0
}}
```

Rules:
- should_defer=true only if the user does NOT say they did it, but postpones it for later
- examples of defer:
  - "I will do them tomorrow"
  - "not today, tomorrow"
  - "I will go later"
  - "later"
  - "in 2 hours"
- if the user says they already did it or closed the topic, then should_defer=false
- if you are not sure enough, should_defer=false

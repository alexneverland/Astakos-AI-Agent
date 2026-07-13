Analyze the following exchange and decide if it is worth creating a FUTURE conversational follow-up.

We want a follow-up only when:
- there is a natural next step or outcome
- it would make sense to ask "how did it go?" later
- the topic concerns an action / event / purchase / outing / plan / family movement / task progression

We do NOT want a follow-up when:
- it is simple chit-chat
- it is purely an update with no next step
- it is a pure tool result / operational reply
- it is too vague

Respond STRICTLY in JSON:
```json
{{
  "should_follow_up": true,
  "topic": "food_purchase | outing | task_progress | family_plan | appointment | general_progress",
  "subject": "short subject",
  "delay_minutes": 180,
  "target_window": "explicit_timer | same_day_short_checkin | same_day_evening | next_day_morning | next_day_late_morning | next_day_afternoon | next_day_evening | after_likely_completion",
  "confidence": 0.0,
  "reason": "short reason"
}}
```

or

```json
{{
  "should_follow_up": false,
  "reason": "short reason"
}}
```

Rules:
- If in [Active Pending Follow-ups] you see a topic that perfectly matches the new conversation (e.g. they are discussing the same bath again), DO NOT set should_follow_up: true. Instead, use update_existing_id: <its id> so the time of the existing one is refreshed!
- subject up to 4 words
- prefer compact noun phrase, not full description
- avoid "and", "for", "so that", "to"
- delay_minutes integer (the time in minutes we must wait, e.g. 180, 480, 1440)
- confidence 0.0 to 1.0
- do not return anything except JSON
- target_window must describe WHEN it makes natural sense to speak again
- Do not choose target_window based on a general "later", but based on the actual likely outcome

Use:
- "explicit_timer" when the user has provided a specific time/interval themselves and we must respect delay_minutes without semantic override
- "same_day_short_checkin" when the user just started something and there will be progress soon
- "same_day_evening" when the topic will logically conclude later on the same day
- "next_day_morning" when the topic moves to the next day and makes sense early but not at dawn
- "next_day_late_morning" when the topic relates to food / outing / family movement that will logically clear up closer to noon
- "next_day_afternoon" when the topic is expected to clear up after noon
- "next_day_evening" when it's an evening plan / later development
- "after_likely_completion" when the follow-up must happen after the probable end of the event

Examples:
- "in 2 hours ask me if I did it" -> target_window: "explicit_timer"
- "remember to ask me tomorrow at 3" -> target_window: "explicit_timer"
- "the steaks tomorrow" -> target_window: "next_day_late_morning"
- "I'm going now to meet them at the park" -> target_window: "same_day_short_checkin"
- "tomorrow we will see about the interview" -> target_window: "next_day_afternoon"
- "tonight we will go out" -> target_window: "same_day_evening"

Examples of a good subject:
{example_1}
{example_2}
{example_3}

Examples of a bad subject:
{example_4}
{example_5}

{active_followups_text}

[Agent]: {agent_name}
[User]: {user_text}
[Assistant]: {ai_text}

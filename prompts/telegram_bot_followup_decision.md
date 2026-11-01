You are the AI and you decide if a conversational follow-up should be sent now.

Goal:
- Use live state, time, recent context, and decision history.
- Prefer correctness over politeness.
- If the original follow-up scenario is no longer true, no longer relevant, or has been superseded by newer facts, do NOT keep it drifting as pending forever.
- Use "skip" with skip_action="resolve" when the scenario is effectively closed, canceled, superseded, or no longer meaningful.
- Use "skip" with skip_action="defer" only when the same scenario is still valid but the timing is still premature.
- If the follow-up is due, still relevant, and the scenario appears active, lean slightly toward "send" rather than endlessly deferring.
- Avoid premature assumptions like "how did it go" when the user may still be in the middle of the situation.
- Avoid repeated defer loops. If defer_count is already high and the scenario still looks active, prefer "send". If it no longer looks active, prefer "resolve".

CURRENT TIME:
- local_time: {local_time}
- hour: {hour}

LIVE STATE:
{state_block}

DECISION HISTORY:
{history_block}

FOLLOW-UP ITEM:
- topic: {topic}
- subject: {subject}
- due_at: {due_at}
- original_user_text: {original_user_text}
- original_ai_text: {original_ai_text}
- source_channel: {source_channel}
- source_agent: {source_agent}

RECENT CONTEXT:
{recent_context}

Respond ONLY with valid JSON. Do not include markdown formatting or rules in the output, just the raw JSON object. Examples of valid responses:

Example 1 (Send):
```json
{{
  "decision": "send",
  "skip_action": "none",
  "stage": "decision_pending",
  "message": "...",
  "reason": "...",
  "context_evidence": ""
}}
```

Example 2 (Skip and Resolve):
```json
{{
  "decision": "skip",
  "skip_action": "resolve",
  "stage": "skip",
  "message": "",
  "reason": "...",
  "context_evidence": ""
}}
```

Example 3 (Skip and Defer):
```json
{{
  "decision": "skip",
  "skip_action": "defer",
  "stage": "skip",
  "message": "",
  "reason": "...",
  "context_evidence": ""
}}
```

Rules:
- "send" only if the follow-up is still contextually valid now.
- "skip" + "resolve" if newer facts indicate the original situation already changed, completed, got canceled, or became irrelevant.
- "skip" + "defer" only if the same situation still exists but now is not the right moment.
- If recent context gives clear new reality/state facts, trust those facts more than the old pending follow-up.
- If defer_count >= 2, avoid another defer unless the context clearly indicates a true postponement.
- Keep "message" short, natural, and in {language} only when decision="send".
- ONLY return JSON.
- For topic "departure", ordinary conversational follow-ups require a short verbatim context_evidence copied from RECENT CONTEXT.
- Exception: a fresh departure with source_agent "Location_Event" may itself be reliable evidence when LIVE STATE says user_at_work=true. If RECENT CONTEXT does not say that the user already returned home or changed plans, send a short work check-in; context_evidence may be empty.
- For every other departure case, if no context evidence exists, return "skip" with skip_action="resolve". Never send a generic departure check-in.
- For every other topic, set "context_evidence" to an empty string.

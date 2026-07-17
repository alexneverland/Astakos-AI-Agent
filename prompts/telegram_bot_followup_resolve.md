Decide if the new user message resolves/closes a pending conversational follow-up.

Pending follow-up:
- topic: {topic}
- subject: {subject}
- original source message: {source_user_text}

New user message:
{user_text}

Respond STRICTLY in JSON. Examples:

Example 1:
```json
{{
  "resolves": true,
  "resolution_type": "completed | canceled | superseded | irrelevant",
  "confidence": 0.9,
  "reason": "short reason"
}}
```

Example 2:
```json
{{
  "resolves": false,
  "confidence": 0.9,
  "reason": "short reason"
}}
```

Rules:
- resolves=true if the new message gives a newer world-state fact that closes or supersedes the original scenario.
- resolves=true if the user says it already happened, did not happen, was canceled, changed form, or is no longer relevant.
- resolves=true if the new message implies the old follow-up question would now be stale, off-target, or based on outdated assumptions.
- resolves=false if the new message is only a timing postponement like "later", "tomorrow", "in 2 hours". Those belong to deferral, not resolution.
- When in doubt between "defer" and "resolve", prefer resolves=true if the message changes the real-world situation rather than only the timing.
- confidence 0.0 to 1.0
- ONLY return JSON.

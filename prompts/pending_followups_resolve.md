Decide if the new user message resolves/closes a pending conversational follow-up.

Pending follow-up:
- topic: {topic}
- subject: {subject}
- original source message: {source_user_text}

New user message:
{user_text}

Respond STRICTLY in JSON:
{{
  "resolves": true,
  "resolution_type": "completed | canceled | postponed | superseded | irrelevant",
  "confidence": 0.0,
  "reason": "short reason"
}}

or

{{
  "resolves": false,
  "confidence": 0.0,
  "reason": "short reason"
}}

Rules:
- resolves=true if the user says they did it, they didn't do it, it was pushed to tomorrow, they found the person, they returned, it was canceled, it was postponed
- resolves=false if it is irrelevant or insufficient
- confidence 0.0 to 1.0
- ONLY JSON

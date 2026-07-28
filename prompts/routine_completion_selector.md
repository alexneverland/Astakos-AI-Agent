You are given a list of routine activities and a user message.
The user has indicated they completed an activity.
Determine which ONE routine (if any) was completed.

Routines:
{routines_block}

User message: "{user_text}"

Rules:
- If the user's message clearly refers to exactly one routine, return its ID.
- Account for Greek morphological variation (e.g. "καθάρισα" matches "Καθάρισμα", "κουνέλι" matches "κουνελιού").
- If the message is ambiguous, unclear, or matches zero or multiple routines, return null.
- Respond ONLY with valid JSON. No other text, no markdown fences.

Output format (strict):
{"routine_id": <integer>}
or
{"routine_id": null}

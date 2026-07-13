Analyze this conversation between {user_name} and the AI and fill out a reporting JSON.
Reply ONLY with the JSON.

{
  "date": "{date}",
  "channel": "{channel}",
  "summary": "2-3 sentences about what was discussed today in {language}",
  "completed": ["list of completed items"],
  "pending": ["list of pending/unfinished items"],
  "next_session_hint": "What should the AI remember for next time",
  "mood": "productive|relaxed|debugging|planning"
}

[CONVERSATION]
{dialogue_text}

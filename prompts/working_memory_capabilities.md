Analyze the conversation and identify NEW capabilities OF ASTAKOS (can_do) or specific failures OF ASTAKOS (cannot_do).
Respond ONLY with JSON:
{{
  "can_do": "Short description",
  "cannot_do": "Short description"
}}
If there is no new information, put null.
ATTENTION: Write the sentences generally, not for the specific moment.
IT IS FORBIDDEN to write as can_do/cannot_do things that Lazaros, Sofia, Alexandros or the family does, can do or experienced. These are USER_FACTs, not self-awareness.
Examples that MUST be null:
- "Lazaros can take his son to school"
- "Alexandros is starting elementary school"
- "Sofia is home"
Examples of valid can_do:
- "Astakos can send a Messenger message after approval"
- "Astakos can search shared SQLite history and Chroma memories"

[Agent: {agent}]
Lazaros: {user_text}
Astakos: {ai_text}

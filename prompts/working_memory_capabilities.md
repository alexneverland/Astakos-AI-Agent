Analyze the conversation and identify NEW capabilities OF ASTAKOS (can_do) or specific failures OF ASTAKOS (cannot_do).
Respond ONLY with JSON:
{{
  "can_do": "Short description",
  "cannot_do": "Short description"
}}
If there is no new information, put null.
ATTENTION: Write the sentences generally, not for the specific moment.
IT IS FORBIDDEN to write as can_do/cannot_do things that {USER_NAME}, {PARTNER_NAME}, {KID1_NAME} or the family does, can do or experienced. These are USER_FACTs, not self-awareness.
Examples that MUST be null:
- "{USER_NAME} can take his son to school"
- "{KID1_NAME} is starting elementary school"
- "{PARTNER_NAME} is home"
Examples of valid can_do:
- "Astakos can send a Messenger message after approval"
- "Astakos can search shared SQLite history and Chroma memories"

[Agent: {agent}]
{USER_NAME}: {user_text}
Astakos: {ai_text}

This is a read-only semantic resolution of unknown routine context before asking
the owner. Do NOT treat the last conversational line as a new state report now.
Use the daily source identities and their actual event times. Infer only allowed
flags that follow clearly from a recent completed/current event combined with
an explicit applicable plan, not an intention, habit or old location observation.
An old plan alone is insufficient. Include all relevant contrary later reports;
omit flags if they leave any uncertainty. Never select an earlier event to avoid
a newer contradiction. The event is the latest relevant actual transition, not a
later acknowledgement, draft request or unrelated message that would renew its age.

Return ONLY an object with exactly these fields:
{"flags": {}, "event_rowid": null, "support_rowids": []}
For a grounded resolution, flags maps allowed identifiers to booleans,
event_rowid identifies the actual recent owner event, and support_rowids lists
its source plus the explicit daily-plan/other relevant source IDs. No actions,
routine completion, messages, tool use, invented source IDs or new permissions.

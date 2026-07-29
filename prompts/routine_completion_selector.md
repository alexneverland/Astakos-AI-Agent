You interpret one current user message against one dynamic routine candidate pool.

Pool: {pool}
Candidates:
{routines_block}

Current user message: "{user_text}"

Decide whether the user clearly reports that they completed one full candidate routine now.
Natural paraphrases and inflection are valid. A generic, similar, planned, in-progress,
questioning, uncertain, or unrelated statement is not enough. If the full routine reference is
ambiguous or unclear, choose none. Never infer a routine merely because it shares a broad action.

For the pending pool only, a clear user dismissal can use action "dismiss". For the today
pool, action "dismiss" is forbidden. Return exactly one candidate or none.

Respond ONLY with strict JSON containing exactly the keys "action" and "routine_id".
Allowed actions are "complete", "dismiss", and "none". Use an integer candidate ID for
"complete" or "dismiss"; for "none", use null. Example: {"action":"none","routine_id":null}

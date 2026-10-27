# Mixed Messenger preparation and pre-question context (2026-10-27)

Owner authorized repair after today's Web preparation produced prose with no
relay_local_payload call, followed by two Matrix inactive-draft errors. Native
storage still contained yesterday's sent revision. The exact mixed preparation
and prepare-then-send wording classified as general_chat. Current traces do not
record the provider's private preparation decision, so its precise false-negative
cause cannot be proven retrospectively.

Scope and acceptance:
- One bounded semantic recheck of a missed owner preparation request uses the
  candidate reply as untrusted reference. Only the latest direct owner turn can
  authorize local preparation. Reuse the existing required-tool retry, guarded
  writer and persisted receipt. No phrase-list additions.
- If preparation is established, remove any batched execute_local_pipeline call,
  even when the provider also supplies the write. Finish local reviewable
  preparation first; subsequent sends retain revision-bound external approval.
  This does not automatically deliver a combined prepare-and-send request.
- Bare sends, negative requests and explanatory questions cannot obtain local
  write permission from an unsolicited candidate reply. Failed model/tool output
  cannot claim a saved draft.
- Give pre-question daily inference a dedicated historical prompt, rather than
  also labelling the latest historical source as a new User Message and supplying
  current-message extraction examples. Keep source times, two-hour observation
  limits, schedule/duration validation and conditional canonical persistence.
- Record bounded daily_context_resolution outcomes in existing event logs:
  applied observation/duration, model_unknown, validation/supersession, state
  change, no sources and malformed output. No conversation text or GPS coordinates.

Evidence limits: the 06:20 report of travel to work plus partner working today
alone cannot establish separate locations at 10:46. No duration proof currently
exists. This slice does not manufacture one, extend TTLs, or guarantee no future
clarification. Existing live events show the question but not the original model
proposal; new telemetry makes later unknown/rejected decisions distinguishable.

Tests use isolated native history/draft/routine stores and mock model/transport
boundaries. Four graph regressions failed before the Messenger repair; two
historical-prompt/outcome cases failed before context separation; a batched
send/write regression failed before filtering both-call responses. Negative
preparation cases retain empty drafts and approvals. No live data, credentials,
configuration, transport service or runtime/watchdog operation is part of this
repair. No real message is sent by validation.

Final verification: 303 distinct relevant offline cases passed: 242 draft,
intent, native graph, presence, daily-context, duration and schedule cases;
60 additional draft-authorization/approval/routing cases; and the pending
approval cross-process case with normal pytest module startup. Its initial
stdin-based harness could not be imported by Windows multiprocessing spawn;
normal module startup passed without a production change. Two existing
third-party deprecation warnings remain. Syntax and git diff --check passed.
Live semantic interpretation and transport delivery were not exercised.

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


## PR 262 review repair (2026-10-27)

The owner authorized addressing Sourcery while the original Codex review remains
running on 8366a3b27906d91d948fbf1fdff1db4fd69f9473. No duplicate review was sent.
All ten inline findings were checked against that head:

- 4387191411: native pending-send routing now defers to preparation, with graph
  cases proving the old revision cannot reach approval when a new draft is needed.
- 4387191422: recovery reuses active-draft/contact eligibility. An unrelated
  pending draft remains intact when the new request does not identify its recipient.
- 4387191431: filtered responses retain text plus normalized surviving calls,
  without native send content parts. Both tool_use/function_call formats are tested.
- 4387191435: the semantic resolver excludes tool content rather than vetoing
  every history containing tools. Tests cover a new direct request after a local
  tool result, plus exclusion of external/synthetic permission sources.
- 4387191444: Web failure handling runs recovery/native-write enforcement before
  returning. The current-turn external-content action block is deliberately kept;
  its graph regression requires no persisted draft and a native blocked receipt,
  rather than bypassing that security rule to satisfy a review recommendation.
- 4387191452: forced preparation receives the actual generated candidate inside
  an untrusted reference. It never supplies owner permission by itself.
- 4387191464: inner history-read/provider exceptions now record resolution_error.
- 4387191471: the post-generation semantic check replaces the earlier check,
  rather than adding another request to every ordinary conversation. A graph
  regression asserts one decision. Pending send/preparation arbitration is separate.
- 4387191479: the model stub validates the actual decoded candidate, and forced
  preparation asserts that candidate reaches its input. Key presence alone no
  longer satisfies the regression.
- 4387191485: the added test functions and model methods have type annotations.

Nine initial review regressions failed before repair; two inner-resolution error
cases also failed. Existing continuation/binding tests now inspect the final
required-write binding, since semantic authorization moved after generation.
The Web-node tests now use isolated draft paths and the same guard captured at
real graph entry, avoiding accidental dependence on the owner's stored draft.
No external-content approval rule was weakened. No real send/model call is used
in final offline verification.


Final repaired-head verification: 372 distinct relevant offline cases passed in
focused groups: 253 draft/context/presence/duration/schedule cases, 58 isolated
Web binding/failure cases and 61 authorization/approval/cross-process cases.
After carrying the preparation decision by the current owner-message identity,
the 140 affected Messenger/continuation/Web cases passed together. Four candidate
cases also verify the displayed historical text for combined prepare-and-send.
Syntax and git diff --check passed. Ordinary synthesis-count stubs distinguish
semantic decisions from synthesis retries. Two third-party deprecation warnings
remain. Native external-content write blocks and revision-bound send approvals
remain intact. Live semantics and Messenger transport were not exercised.

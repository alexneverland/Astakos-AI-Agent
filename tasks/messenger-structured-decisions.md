# Messenger structured decision repair (2026-10-30)

Owner authorized repair after today's 11:00 Web request: partner at home,
prepare a loving message because they had already spoken this morning. The
assistant supplied a tender message but called no tools. The 11:02 send request
then failed because no active draft existed. Native readback showed only
yesterday's already-sent draft; today's routine ledger held acknowledge, which
does not prove draft creation. No message was sent today in the inspected trace.

Both semantic Messenger decision resolvers parse str(response.content), which
does not turn structured provider text blocks into their JSON answer. The
existing required-native-write safeguard depends on this preparation decision,
so losing it permits prose-only synthesis. The original model response was not
retained; reproduce the concrete provider-shape path rather than claiming its
historical format is proven.

Plan: native graph regression using exact wording, routine feedback context and
yesterday's sent draft; decision responses as scalar/text blocks and fragmented
text. Assert a new native pending draft contains the generated text, and a later
send reaches revision-bound approval without transport. Reuse LangChain's
answer-only BaseMessage.text extraction in both Messenger semantic resolvers.
Reject reasoning/tool text containing valid decisions, malformed output and
untrusted owner turns. Preserve existing active-draft/contact/history/CAS guards.
No phrase lists, receipt fabrication, approval weakening or broad parser changes.

Use temporary native stores with outbound blocked. Run focused Messenger,
binding and approval tests, compile and git diff --check. No live data edits,
real sends, credentials/config/runtime changes, commit/push/PR or cleanup in this
implementation request. Commands: venv\Scripts\python.exe -m pytest
tests/test_messenger_structured_decisions.py -q --basetemp=.pytest_tmp_messenger_blocks.
Provider fixtures prove persistence/approval behavior, not live semantic quality.

## Verification outcome

The exact mixed request plus a dated routine acknowledgement and yesterday's
sent draft was exercised through the native graph. At the initial code, block
and split-block preparation decisions left yesterday's revision unchanged;
scalar preparation already created a new draft. The approval fixture was then
aligned with native Web-to-Matrix queueing (notification need not be synchronous)
and the semantic model stub distinguishes preparation from the later send turn.

Both resolvers now use AIMessage(content=response.content).text, the installed
LangChain answer-text accessor: scalar/string fragments/type=text blocks are
joined without injected characters, and reasoning/tool/unknown blocks excluded.
No shared provider normalizer, approval policy or routing interpretation changed.

Verification: 129 Messenger cases passed, including the initial nine new cases;
the final 18-case new file adds nine invalid/provenance/lifecycle cases, all
passing. Another 42 approval/routing/history/cross-process cases passed with
outbound blocked. Total: 180 distinct relevant passing cases. Native graph
readback verifies a new pending revision with the displayed message; the later
send creates exactly one revision-bound approval while the draft remains pending.
Non-answer valid JSON, malformed/value-type errors and untrusted owner turns
confer no permission. Compilation and git diff --check pass. Two existing
dependency warnings remain. No full suite or live provider/send test was run;
today's real draft/ledger/history were not manually modified.

## Subsequent explicit send authorization

The owner then requested that Codex send the previously approved message and
record delivery. Verified no newer active draft, loaded the exact quoted text
from owner-approved assistant row 8101, and persisted it through relay_local_payload
for the canonical Sofia contact. The owner's direct instruction authorized that
exact content: native save_pending bound the new revision and
execute_approved_pending invoked execute_local_pipeline once. The pipeline
returned executed/success and draft status sent; no retry was performed.

After success, native routine-store CAS changed only routine 4's October 30
acknowledge to complete. Readback verified it. An idempotent history message keyed
by the sent draft revision and a bounded send event record the outcome. No reminder
delivery receipt was invented; this was an owner-requested manual send. This live
action is distinct from the offline structured-decision tests and does not prove
live-model classification quality. The owner subsequently authorized the scoped
PR, including its normal commit/push lifecycle. Merge, deletion and review
polling remain separate actions.

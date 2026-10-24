# Messenger draft lifecycle repair

Scope approved by the owner on 2026-10-24. Base: main c865c651.

## Reproduced evidence

The 2026-10-24 Web turn presented a new message and claimed it was saved without
calling relay_local_payload. The stored draft was from the previous day and had
expired. A subsequent Web send correctly failed on that expired draft. A Matrix
send then ended with a Chat_Agent promise to forward it to Web_Agent, without an
actual tool call or approval request. The previous evening's owner explanation
that they had already spoken to the recipient left the old draft pending.
Separately, the tool-free routine notification could display a fabricated draft.

## Acceptance and implementation slices

1. Reproduce prose-only preparation through the real graph, local tool, approval
   gate and native draft file. Require one bounded tool retry, with an honest
   failure if the provider does not supply it. Display native write receipts
   directly, avoiding another unnecessary provider synthesis.
2. Resolve send/retire intent from bounded direct-owner conversation and stored
   draft state. Sending creates the existing critical tool call and retains its
   external approval gate. Expired drafts return their native inactive result.
3. Retire unwanted pending drafts, including expired ones, only against the
   captured owner-history version and exact file fingerprint. Recheck under
   the writer lock; do not erase newer work. Continue mixed conversation with
   an internal receipt that is not routine completion/skip evidence.
4. Use the existing partner-Messenger routine resolver to render a local
   preparation offer on tool-free notifications. Preserve context skip/note
   outcomes and the explicit offer-permission boundary.

No new phrase lists, transport changes, live data edits, configuration changes,
releases or manual runtime restarts. Provider calls and sends are replaced at
their boundaries in offline tests; these tests establish lifecycle enforcement,
not live model interpretation quality or real Messenger delivery.

## Verification

- Six initial graph regression cases failed before repair; the additional
  proactive false-save cases also failed before their repair.
- 410 distinct related offline cases passed in focused groups: 107 native
  draft/intent/goal cases (including 20 new lifecycle cases), 117 real worker
  cases, 66 legacy Telegram routine cases, 21 capability-authorization cases,
  and 99 Web/Matrix/external/plan approval cases.
- Bypassing conditional clear only inside an isolated test process makes the
  newer-revision regression fail as expected; production source was not mutated.
- Python compilation and git diff --check passed. The installed Google provider
  binding supports requiring a named function; no live provider/send was invoked
  to validate message interpretation or delivery.
- The legacy capability-draft authorization group assumes Telegram delivery;
  run it with ASTAKOS_EXTERNAL_CHANNEL=telegram in that test process only.
- Run test_routine_completion_telegram.py separately from the real worker group:
  its module stubs cause scheduler failures when those groups share a process.
  The real worker group passes all 117 cases in isolation.
- The final channel/plan group also uses the disposable offline socket guard
  (non-loopback connections fail loudly) and Telegram as its test-process
  default, while channel-specific fixtures override that setting as needed.

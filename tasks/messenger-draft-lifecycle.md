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

## PR 261 review repair

Reviewed head 50874763a18908bac2d2783c713dc8ec2580f99e. The Codex finding
4366625384 is confirmed: Matrix appended a dated no-action SystemMessage after
the owner. The Matrix turn service now keeps the owner last; real service/graph
tests cover both retirement persistence and send approval after feedback.

All eight Sourcery findings were evaluated against the same head:

- 4366626993: approval now binds the observed revision, including channel
  shortcuts; native dispatch rejects replacements and legacy unbound approvals.
- 4366626997: pending execution is claimed atomically and native draft dispatch
  persists `sending` before transport; completed/uncertain claims cannot replay.
  This prevents automatic duplicates, without claiming exactly-once delivery
  across a remote Messenger acceptance and a process crash.
- 4366626998: the native history abstraction uses a short BEGIN IMMEDIATE
  transaction across the version check and file replacement; appenders serialize
  with that operation. No schema change or live migration is involved.
- 4366627000: send completion conditionally records sent/uncertain only for the
  claimed revision; it does not remove a replacement saved during transport.
- 4366627003: Web and Matrix clear shortcuts capture/pass the same conditional
  history/revision guard, rather than invoking an unconditional clear.
- 4366627007: non-draft tool calls no longer satisfy required preparation;
  the bounded retry preserves their calls beside the actual draft write.
- 4366627008: mixed tool outcomes retain native saved-draft and sibling receipts.
- 4366627011: history guard failures with pending draft work return an explicit
  unavailable outcome instead of falling through to prose-only processing.

Review regressions exercise real native storage/approval and the real send tool
with Playwright mocked at the transport boundary. The initial mixed receipt,
non-draft call, invalid guard and send-claim cases failed before their repairs.
No test sent a real message or called a cloud model.

Final review verification: 479 distinct related offline cases passed in focused
groups (217 core/channel/approval cases, 117 real scheduler worker cases, 66
legacy Telegram cases and 79 additional intent/goal/approval cases). The core
group's 215-case run was supplemented by two additional review safety cases;
the 14 review regressions passed together afterward. The binding-only goal
tests now stub the native draft-state read as well as the old active-state
helper, avoiding an unintended read of the owner's actual draft when invoking
agent nodes outside graph entry. Syntax, locale JSON and diff checks passed.

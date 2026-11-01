# Routine duration context (2026-10-12)

Owner approved the scoped repair after discussing the distinction between a
momentary presence report and explicitly applicable work/day context. No further
permission is needed for implementation; PR creation/merge remain separate.

Observed: 07:36 work arrival and partner working today; partner_with_user became
unknown at 09:40; clarification was sent at 10:45. Ordinary observations and
pre-question resolutions currently both require an event younger than two hours.

Acceptance: allow semantic pre-question inference from explicit current-day
duration sources, with a concrete end time no later than next local midnight.
Do not prolong plain presence, infer separation merely because both work, invent
shift hours, revive yesterday, or ignore newer contradictions. Preserve actual
source time and ordinary two-hour validity. No phrase lists or global TTL change.

Plan: first reproduce the morning-arrival/10:45 poll with isolated history and
routine stores; then implement a bounded duration proof through the canonical
context CAS abstraction and evidence loader. The proof is separate from the
original flags, anchored to canonical states and trusted owner history. Changed
history/state invalidates it. Test expiry, malformed proofs, races, contradiction,
same workplace, remote work and stale momentary reports. Finally document/check.

Files: services/context_extractor.py, services/routine_context_evidence.py,
services/routine_context.py, prompts/daily_context_resolution.md, tests and docs.
No schema migration, new dependency, live data edits, config, secrets, runtime,
transport or release changes. Python functions use typed arguments/docstrings;
semantic model output is validated structurally before canonical CAS persistence.

Verify: venv\Scripts\python.exe -m pytest tests/test_routine_duration_context.py
tests/test_daily_context_inference.py -q --basetemp=.pytest_tmp_duration
Then related routine evidence/clarification/context tests, compilation and
git diff --check. Mock only provider/transport boundaries; sockets fail loudly.
Live semantic inference remains to observe naturally.

Implemented one internal context proof with source IDs, actual event time,
explicit bounded end, trusted-history marker and canonical state anchors. Only
pre-question resolution can create it; ordinary flag writes keep their existing
contract. The shared evidence loader exposes it to clarification/final routine
checks, without copying it into the ordinary runtime context. Legacy three-field
resolutions remain accepted. Changed GPS flag evidence also invalidates it.

Verification: original duration/poll regression failed before repair. Initial
related group passed 319 cases; final affected group passed 145, covering seven
additional cases (326 distinct related cases overall). The exact morning wording
is tested with separately explicit duration support, and also as insufficient
evidence alone. Providers/transports are mocked and outbound sockets prohibited
in the new tests. Semantic model quality is not proven by offline mocks. No live
state was manually repaired and no external message was sent by testing.
Final new-test group: 24 passed, including exact end-time expiry. An in-memory
mutation removing the trusted-history marker guard failed its regression as
expected; production source was never mutated. Compilation/diff checks passed.
Two existing dependency deprecation warnings appeared in the broader group.

PR #249 review repair: an equal-time canonical true and duration false was
reproduced offline, including proof persistence and eventual effective false.
Duration commit now requires equal-time canonical evidence to agree with the
proposed value. The conflicting regression failed before repair; agreeing
equal-time evidence remains usable without renewing its source. 121 affected
duration/daily/evidence cases passed, including both new regressions. Compilation
and diff checks passed; one existing Google dependency warning remains.

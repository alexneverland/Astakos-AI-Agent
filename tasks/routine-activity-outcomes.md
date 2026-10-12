# Routine activity outcomes (2026-10-12)

Owner approved repairing today's Roblox/park interpretation and premature outing
state. This does not authorize rewriting today's live ledger or flags manually.

Observed: 17:23 playing Roblox at home, future park plan; at 17:24 the legacy
reconciler wrote outing=in_progress. At 18:35 the owner was incorrectly told
Roblox was skipped; at 18:52 correction persisted Roblox complete, but park was
not recorded. The feedback selector sees only one hour of references and can
return only one action. Its actual-execution criterion must follow the routine's
meaning: visiting a place can be fulfilled by arrival, unlike completing a
cleanup task. Plans, reminders and generic presence cannot establish execution.

Approved scope: generic semantic outing state in the canonical context schema;
stop legacy memory reconciliation from owning that volatile state/its conditions.
Reuse bounded owner-day references for feedback and reject inferred cancellation
merely because a new activity replaces an earlier one. Add bounded multi-routine
completion only, using one atomic canonical ledger transaction and truthful graph
context for every persisted outcome. Keep single selections and exact reply,
draft, approval, identity, date, provenance and stale-source contracts compatible.

Order/checkpoints: reproduce outing lifecycle on isolated stores; implement/test
semantic state and writer ownership. Then reproduce both activities and the
71-minute history gap; extend selector, atomic ledger and handler together; test
malformed batches, duplicate IDs, mixed unsafe actions, races, rollback,
idempotence, future plans and truthful acknowledgements on all channels. Finally
run related suites, inspect diff, compile and update Unreleased/docs.

Tools: Python >=3.11, pytest using venv\Scripts\python.exe -m pytest and isolated
--basetemp directories. Native memory abstractions only. Tests use disposable
SQLite and mock only provider/transport boundaries; accidental sockets fail.
Production semantics remain model-based: no phrase/alias/regex patches. No schema
migration, configuration, credentials, Chroma, Docker/runtime or release changes.
No subagents. Live semantic interpretation remains to observe after deployment.

Implemented: bounded completions-only batch protocol, reused per-item validation,
atomic ledger writer using the existing locked transaction/projection, and plural
trusted graph outcomes with bounded untrusted display names. The prior single
protocol remains valid. Exact replies retain their candidate/correlation limits.
Semantic context now owns the outing enum; old outing helper functions remain
available for existing compatibility tests, but are no longer registered in
production reconciliation. Memory-model proposals for this state/condition are
also filtered. No existing live condition or historical outcome was rewritten.

Evidence: three outing regressions and the two-activity channel lifecycle failed
before repair. Initial outing/context group: 50 passed. Related group: 334 passed
with 18 prompt-delimiter fixture failures; retaining the INPUT delimiter resolved
all 18 identity tests. Final consumer/selection/runtime/identity group: 108 passed,
including six additional prior skip/complete receipt-preservation cases. Expanded
channel/context group: 226 passed and one order-dependent legacy Matrix draft
test failed. That same failure reproduces with the selector loaded from main in
the combined channel group (131 passed / 1 failed); both main and current selector
pass the failing case in isolation. Separate Matrix/clarification/duration group:
57 passed. This test-order issue is outside the activity fix and remains deferred.
An in-memory mutation removing the completions-only guard failed its unsafe-batch
regression as expected; production source was never temporarily mutated.
Final affected activity/selector group: 71 passed, including all 23 new activity
cases. Combined collection across the focused groups confirms 622 distinct cases;
each was exercised successfully in its corresponding focused/isolated group,
with the documented legacy combined-order exception above. Compilation of all
seven changed Python modules and git diff --check passed. Existing Google/Chroma
dependency deprecation warnings remain. Live model choice is still unverified.

Subsequent explicit owner instruction authorized today's manual checks before PR
creation. At 21:26 Athens on 2026-10-12, canonical ledger API recorded completion
for routine 3 (park); routine 100 (Roblox) was already complete and stayed
unchanged, including its original 17:45 delivery and 18:52 completion receipt.
No delivery was invented for park, no other routine or context flag was changed,
and the feedback baseline was preserved. This is an owner-authorized correction,
not evidence of automatic model interpretation after the source change.

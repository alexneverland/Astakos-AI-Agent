# Behavioral initiative evidence repair (2026-10-11)

Owner authorized analysis and scoped changes because no spontaneous opener has
been observed since implementation. This is separate from follow-up messages.

Read-only evidence: 126 confirmed / 88 candidate observations, six Debug patterns,
latest observation today at 09:27. No opener receipts or ambiguous pending send.
At 09:44 the model evaluated three candidates and returned no topic; at 10:04
recent activity blocked evaluation. These are recorded gates, not evidence of
transport failure or proof of the model's internal motive.

PR #236 already implemented semantic identity references. Historical aliases
were deliberately retained. The current catalog used newest-first references
without dated support, making a recent alternate label appear ahead of a more
established one. New extraction gets distinct-date support and stable earliest
source tie ordering; the model still decides identity, with no synonym rules,
historical merging, migration or retroactive classification.

Reproduced two initiative defects offline: the top-three evidence cutoff hid
other eligible topics, and a skipped evaluation was cached against history,
preferences/context/day only, ignoring new background evidence. Both regressions
failed before repair. Both conversation selectors now opt into twelve packets;
the ordinary reply still receives only its one selected observation. The same
top-three omission was reproduced for the owner's current-plan beer example.
A validated optional evidence digest extends the initiative evaluation cache key;
existing version-one state/receipts/pending sends remain readable and preserved.

The prompt allows ordinary positive or neutral interest without requiring a
problem and asks for comparison by relevance/freshness, not frequency rank.
No fabricated topic or forced fallback send bypasses model decline.

Acceptance: actual temporary observation and history persistence must show a
lower-ranked topic can be selected and delivered once; updated evidence reopens
a cached decline, unchanged polls remain cached. Preserve one opener/day, seven
days/topic, fifteen-minute idle, quiet/mute/opt-outs, selected-channel ownership,
recent reminder and stale-context checks, durable receipt/history recovery and
ambiguous-send protections. Verify bounded pools, legacy state compatibility,
cross-language reference reuse and different entities/actions staying separate.

Owner clarified that repeated-behavior comments must not duplicate follow-ups.
A canonical read-only follow-up topic loader exposes active pending subjects and
seven-day sent topics to both selectors. No table initialization or write occurs.
Both prompts compare meaning, not labels, and respect recently_discussed; the
initiative's existing context freshness guard includes follow-up changes.
Tests cover pending/sent topic propagation, unchanged queues, missing storage,
semantic duplicate refusal and a new follow-up arriving during classification.

Follow-ups retain their pending-topic intake and delivery pipeline. No changes
to follow-up queue records, routines, live state, configuration, credentials, runtime
supervisors or releases. Offline provider/transport fixtures prove lifecycle and
data propagation; live semantic choice/delivery still requires natural observation.

Verification: 288 related behavioral/follow-up cases passed together. Final
affected reply/production-worker selection: 38 passed, including three additional
cases; final read-only follow-up group: 4 passed. This covers all 291 currently
collected distinct cases. Initial cache/pool/reference regressions failed before
repair. Accidental outbound sockets fail in the consumer/identity/worker tests.
Python compilation and git diff --check passed; one existing Google dependency
deprecation warning remains. No live provider or transport test was performed.

Read-only application of the broader thirty-day pool exposes four eligible topics
(home, work, rabbit care, park), compared with the former three. The Debug panel's
six all-time patterns include two that lack three qualifying dates in this window.

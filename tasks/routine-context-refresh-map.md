# Routine context refresh: capability map

Status: both module contracts approved and implemented on 2026-10-06.
Context evidence and clarification are wired into the existing routine tick;
offline verification is complete, owner-controlled natural observation is pending.
Owner requested on 2026-10-06: keep daily context useful without requiring a
complete morning report, and ask only when uncertainty matters to an upcoming
routine. The owner approved the map and clarification budget. No schedule-context
inference or runtime configuration change is included.

## Capability map

| Module id | Responsibility | Depends on |
|---|---|---|
| context-evidence | Canonical, time-aware evidence snapshot: value, source, observation time, validity, and known/unknown status. Reconcile trusted conversation and fresh owner GPS without inventing family presence. | Existing context/location abstractions |
| routine-context-clarification | Identify consequential uncertainty for an eligible upcoming routine; ask one bounded question; incorporate the owner's answer and reevaluate only while the routine remains timely. Include delivery/history/debug evidence. | context-evidence |
| schedule-context | Later extension: use owner-confirmed dated schedules as expectations, distinguish today's exceptions from habitual patterns, and request confirmation when needed. | context-evidence, routine-context-clarification |

Build order: context-evidence -> routine-context-clarification.
schedule-context is explicitly deferred until the first two are naturally verified.

## Verified starting points (source inspection, not a live diagnosis)

- services/context_extractor.py applies semantic current-state updates through
  memory/routine_db.py; many boolean updates expire on today's date.
- services/routine_context.py resolves the effective routine context, with
  differing unknown/default behavior across flags. Some GPS fallback logic
  accepts a point up to four hours old; this is not a proposed freshness policy.
- services/location_update.py already updates user_out_of_home from trusted
  live points. The owner's phone location does not establish another person's
  location, co-presence, sleep, or routine completion.
- services/routine_conditions.py permits a suppress_when_true condition when
  its actual value is null. Unknown is not uniformly blocking, so clarification
  must consider whether uncertainty could change the relevant decision; it
  cannot be limited to conditions already returning blocked.
- clients/telegram_bot.py contains the shared routine scheduler and currently
  considers routine slots 0-15 minutes ahead. Preserve the existing scheduler
  owner and channel isolation; do not start a second independent scheduler.
- Existing completion confirmations, pending followups and behavioral initiative
  are separate lifecycles. A context question is not routine completion, a bug
  approval, a new routine, or a behavioral opener.

## Proposed behavior and safety boundaries

- An expired observation becomes unknown, not the opposite boolean.
- Expiry depends on the meaning of structured state; no hardcoded natural-language
  words, aliases or regex patches for the owner's examples.
- Retain confirmed schedule scope/dated exceptions; do not indiscriminately expire
  weekly shifts or extended child absence with transient whereabouts.
- Prefer fresh relevant evidence. An elapsed outing duration is a reason to
  reconsider or ask, never proof of return. Fresh GPS can establish only owner
  home/away under valid configured geometry and location quality requirements.
- Historical memories and behavioral habits are evidence/expectations, not
  authoritative claims about today's family state. No automatic schedule-context
  inference is included in the first release.
- Ask only for an otherwise eligible routine whose decision or appropriate
  message depends on unresolved context. Do not ask for paused/muted routines or
  when another known condition already rules out the routine independently.
- Reuse quiet/mute/budget gates, selected-channel delivery and shared history.
  Coalesce questions across routines needing the same evidence. Do not repeat
  pending questions on each scheduler poll or after restart.
- An answer from Web, Telegram or Matrix uses the same semantic/current-state
  path. Recheck current evidence and routine eligibility after slow generation
  and before delivery; a newer answer must invalidate an obsolete question.
- Without a reply, remain uncertain; no implicit yes, completion or external
  action. A late answer may update context but cannot replay expired routines.
- Context confirmation never bypasses critical-action approval.
- Surface effective value, source, age/validity and defer/question reasons in
  authenticated debug output, without leaking private data or secret values.

## Approved decisions for the module specs

1. Evidence validity: structured per-state policy, fresh GPS criteria, precedence
   and contradiction handling. Do not guess universal durations during coding.
2. Clarification budget: one pending context question globally and a conservative
   two-reservations/day ceiling, with no repeated unanswered topic that day.
   Confirmed deliveries are counted separately in Debug. Existing initiative
   limits remain unchanged.
3. Routine window: start with the existing upcoming-slot window. Explicitly define
   answer deadlines and distinguish unavailable context from genuine suppression.
4. Persistence: use existing memory abstractions; if durable evidence/question
   state requires a schema migration, obtain explicit approval before migration.
   Never modify real databases, Chroma, .env, credentials, config or runtime here.

## Verification requirements (covered offline; natural observation pending)

- Stale park observation -> unknown -> one relevant question, not guessed home.
- Fresh owner-home GPS -> owner home; no fabricated partner/child co-presence.
- Fresh explicit exception supersedes an older expectation.
- Unknown suppression flag can require clarification despite legacy allowed=true.
- Irrelevant missing flags and independently blocked routines do not cause questions.
- Shared answer handling, pending-question deduplication, restart/failure recovery,
  slow-model freshness, quiet/mute/budget enforcement and late-answer safety.
- Backend tests use isolated fixtures and fail loudly on accidental provider or
  outbound calls. No Android/device exploration is required for backend tests.
- Natural owner-controlled observation remains distinct from offline evidence.

Existing tasks/plan.md and tasks/todo.md contain unrelated pending natural/restore
verification and are preserved. First module contract:
[context-evidence-spec.md](context-evidence-spec.md), approved on 2026-10-06.
The bounded context-evidence plan was approved and implemented on 2026-10-06;
74 foundation tests passed at that checkpoint. The dependent clarification
contract is approved and implemented; final evidence is recorded in
[routine-context-clarification-spec.md](routine-context-clarification-spec.md).

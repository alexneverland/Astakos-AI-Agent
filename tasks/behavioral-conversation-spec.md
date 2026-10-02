# Spec: Behavioral Conversation Initiative

Status: evidence, ordinary Chat_Agent replies and unsolicited initiative are
implemented and offline-tested after owner approval. Live semantic verification
and owner assessment of one appropriate opener remain pending.

## Objective

Use observed behavioral repetition to enrich ordinary replies and, separately,
start a considerate conversation with the owner. This is not routine detection
or routine creation. The nightly analytics/routine flow remains unchanged.
Examples include interest in recurring activities, positive encouragement, and
a gentle question about repeated drinking. Examples are not keyword rules.

Retain the existing detector, do not rebuild it. Intake is triggered after each
new persisted user message on Web, Telegram and Matrix through the background
queue, not nightly. Queuing does not guarantee synchronous extraction before
the immediate assistant reply.

## Capability map and build order

| Module id | Responsibility | Depends on |
|---|---|---|
| behavioral-evidence | Bounded recent observations with dates and source provenance | Existing observational intake |
| behavioral-reply | Relevant optional commentary within the normal answer | behavioral-evidence |
| behavioral-initiative | Optional unsolicited conversation with durable suppression and delivery | behavioral-evidence, behavioral-reply policy |

Build order: evidence -> ordinary replies -> unsolicited initiative. Each
module needs its own approved implementation contract before coding.

## Verified starting point

- `services/behavioral_pattern_aggregator.py` groups confirmed observations;
  candidate qualification requires three distinct dates, not three messages.
- Its default Debug candidates remain unchanged. Opt-in evidence now exposes
  supporting dates/source references, with a caller-selected recent window;
  this evidence is not yet wired into conversation behavior.
- `memory/behavioral_event_state.py` provides observational persistence and
  read-only access through `list_events(initialize=False)`.
- `memory/context_builder.py` is the shared bounded conversation-context path.
- The proactive helpers in `clients/telegram_bot.py` already handle quiet
  hours, mute, recent activity and delivery to the selected external channel.
  `job_proactive_scan` scans watch-folder files; it is not the habit engine.

## Module contract: behavioral-evidence

Foundation audit (2026-10-02): read-only inspection found 163 observations,
93 confirmed (Web 21, Telegram 47, Matrix 25), and two aggregated patterns.
76 focused offline tests passed, including real temporary cross-channel history
through intake, storage and aggregation with external/assistant exclusion and
replay checks. A RED regression exposed missing source dates in the model
input; GREEN verifies that each source date now reaches the extraction prompt.
This does not prove live model semantic accuracy. Existing limits remain:
at most one event from the first 500 characters, no legacy reclassification,
and no proof of daily frequency or exact occurrence time from a candidate alone.

Objective: provide an evidence-only bounded packet, usable by both consumers,
without changing live storage, prompts, delivery or routines in this slice.

Implemented in `services/behavioral_conversation_evidence.py`, delegating to
the existing normalizer and detector (`include_evidence=True`). The caller must
provide `today` and `window_days` explicitly (1..366 inclusive calendar days);
there is no activated 30-day default. Output is capped at three patterns and
twelve recent source references per pattern; all qualifying dates remain in
the packet. Only source identifiers are included, not source text or inferred
occurrence times. Storage reads reuse `list_events(initialize=False)`; current
storage access loads confirmed observations before filtering in memory.

Verification: 99 focused offline tests passed, including RED/GREEN evidence
tests and existing channel/storage/Debug regressions. A read-only 30-day manual
packet check returned the two existing patterns with dated cross-channel
references. No live messages, migration, Chroma or routine changes occurred.

- Select only structurally valid, confirmed, direct-user observations; reject
  negated, hypothetical, wrong-subject, untrusted and future-dated records.
- Reuse canonical grouping, but apply an explicit recent-date window. Expose
  distinct dates separately from raw references, plus source IDs and relevant
  event/source timestamps. Do not infer occurrence time from ingestion time.
- Do not claim daily behavior, amounts, causation, shift or location context
  unless the supporting evidence establishes it. Missing dates/context stay
  unknown. Legacy ambiguous observations are not silently reclassified.
- Supporting source text is bounded and retains provenance through the
  existing persisted-content boundary. It is evidence, never instructions.
- Missing stores, read failures or inadequate evidence produce no packet;
  normal conversation continues. No backfill or migration.

## Consumer contracts to specify next

### behavioral-reply

Owner approved the 30-day window and a separate shared preference file on
2026-10-02. Implement normal Chat_Agent replies through the shared prompt builder;
other specialist agents and unsolicited sends remain unchanged. Use a tool-free
semantic decision (one bounded additional model call on a direct chat turn)
to select at most one relevant pattern or save/revoke an explicit topic opt-out.
No phrase matching. Use recent shared assistant history to avoid repeating advice.
Persistence: `behavioral_conversation_preferences.json` under BASE_DIR, ignored
by Git, FileLock plus atomic replace. Missing file means no opt-outs; corruption,
provider failure or a concurrent preference change means no optional commentary.
No live state is initialized by development/tests. Current or history-visible
external content excludes automatic preference writes and optional commentary,
using the existing provenance gate. Suppression scope is semantic,
not a pattern label, and persists even before a pattern exists. Re-enabling needs
an explicit request, not just mentioning the activity again.

- Add evidence through the shared context path, not separate channel heuristics.
- The LLM decides relevance and whether a comment helps; it may say nothing.
  It must still answer the user's request rather than turn every reply into
  advice. Plans such as going for a drink are not proof of consumption.
- Respect semantic topic opt-out across Web, Matrix and Telegram. Persisted
  suppression must be designed and approved before enabling this behavior.
- Corrections and changed circumstances override stale pattern assumptions.
  No medical diagnosis, shaming, quantity guesses or unsupported generalizations.

### behavioral-initiative

Owner approved on 2026-10-02: at most one confirmed opener per local calendar
day, seven full days per topic, and at least fifteen minutes since any shared
conversation/reminder message. Reuse the 30-day evidence window and shared
semantic preferences. Poll every ten minutes through the existing slow queue,
not with model work on the scheduler thread. No live test sends are authorized.
Store separate ignored atomic FileLock-protected JSON delivery state. Persist
send intent before transport and receipt before history recording; record with
a stable message ID using the existing history schema (no migration). Matrix
retries use the same transaction ID, only while context/preferences stay fresh.
Telegram ambiguous sends are held, never automatically resent. A stale ambiguous
pending send is held for inspection rather than risking a duplicate or stale
opener. Confirmed receipts retry local history recording only. No routine changes.
State also remembers the last evaluated day/history/preferences/context, avoiding
repeated provider calls on unchanged skipped context. New shared activity or
preferences/context, or a new day, permits evaluation after the quiet interval.

Implementation: `memory/behavioral_initiative_state.py`,
`services/behavioral_conversation_initiative.py`,
`services/behavioral_initiative_scheduler.py`, and
`prompts/behavioral_initiative.md`. The shared external scheduler registers a
coalesced slow-queue poll; Matrix reuses the existing transaction-aware encrypted
sender. `append_message(message_id=...)` uses the existing unique-ID column,
without schema changes. Confirmed openers are recorded in shared history and
shown in Web through the existing history view, not sent to both transports.

Verified offline: 23 fixed-clock lifecycle tests, four durable-state/history
tests, three adapter/scheduler/production-worker integration tests, plus focused
conversation-history and existing transport/scheduler regressions. No real
transport/model calls or live data changes were used. Syntax/diff checks pass.
Tests establish plumbing and safety contracts, not live semantic model accuracy.

- A separate habit-conversation job reuses existing quiet/mute/activity and
  selected-channel delivery boundaries, not the file-scanning job's meaning.
- Require recent evidence, useful context and a semantic send-or-skip decision.
  Include positive and neutral topics, not only warnings.
- Persist topic cooldown and delivery identity across restarts/processes;
  share suppression with in-conversation comments. Failed delivery must not
  count as delivered, and retries must not duplicate an already delivered turn.
- Recheck context and owner activity immediately before sending; do not send
  a stale question or compete with an ongoing conversation or recent follow-up.
- Record one delivered assistant message in shared history, visible through
  existing channel mechanisms. Never broadcast to both external transports.

## Project structure and code style

Use typed services under `services/`, storage abstractions under `memory/`,
localized prompts under `prompts/`, and offline pytest tests under `tests/`.
Extend existing paths rather than add a new agent/tool or keyword parser.
Illustrative interface (design only):

```python
def build_behavioral_evidence(
    events: Iterable[Mapping[str, Any]], *, today: date, window_days: int
) -> list[dict[str, Any]]:
    """Return bounded dated evidence without inferring or changing routines."""
```

## Testing strategy and commands

Use RED/GREEN backend tests with synthetic observations, temporary storage,
fixed clocks and mocked LLM/transport boundaries; accidental outbound calls
must fail. No mobile UI tests are part of this backend feature.

- Existing foundation: `venv\Scripts\python.exe -m pytest tests/test_behavioral_pattern_aggregator.py tests/test_behavioral_event_state.py -q -p no:cacheprovider --basetemp=C:\Users\PC\AppData\Local\Temp\astakos-behavioral-foundation-20261002`
- Planned evidence tests, once authored: `venv\Scripts\python.exe -m pytest tests/test_behavioral_conversation_evidence.py -q -p no:cacheprovider --basetemp=C:\Users\PC\AppData\Local\Temp\astakos-behavioral-evidence-20261002`
- Diff validation: `git diff --check`
- Ordinary-reply/preference final checks: `venv\Scripts\python.exe -m pytest tests/test_behavioral_conversation_reply.py tests/test_behavioral_conversation_preferences.py -q -p no:cacheprovider --basetemp=C:\Users\PC\AppData\Local\Temp\astakos-behavioral-pref-prompt-green-20261002 --tb=short` (33 passed; two dependency deprecation warnings).
- Consumer regression groups will be selected from actual integration points;
  do not run the full suite by default or claim unexecuted tests passed.

## Acceptance scenarios

1. Several reports on one day cannot establish a repeated multi-day pattern.
2. Three scattered historical dates cannot support "every day lately".
3. A planned activity or quoted third-party statement is not completed behavior.
4. Relevant recent repetition may inform one natural reply; unrelated requests
   get their normal answer, and unavailable evidence does not break the turn.
5. A topic opt-out suppresses both consumers across channels and restarts.
6. Quiet/muted/active-conversation or stale-evidence conditions prevent an
   unsolicited message. Delivery failure/restart does not duplicate a message.
7. No consumer creates/updates routines or changes the nightly analytics flow.

## Boundaries

- Always: canonical context/storage/delivery paths, provenance, localized
  natural-language semantics, bounded evidence and focused offline tests.
- Ask first: policy values, new persistent suppression/delivery schema,
  dependencies or any runtime scheduler registration changes.
- Never: hardcoded human phrase lists, live-data migration/backfill, editing
  `.env`, credentials, `config.py`, Chroma, Docker or watchdog; automatic
  medical conclusions; modifications to approvals or routine creation.
- This document does not authorize live unsolicited test messages, Git/PR
  actions, or modifications to existing incomplete Matrix work.

## Decisions and remaining work

- Ordinary replies use the approved 30-day window. Opt-out scopes and explicit
  re-enabling are persisted in the shared ignored atomic JSON preference store.
  The model decides relevance and avoids repeating recent assistant commentary;
  unsolicited sends use the separate durable cooldown described above.
- This adds one tool-free semantic decision call per eligible direct Chat_Agent
  turn. Errors skip optional commentary; no promise of saved preferences on error.
  Other specialist agents are unchanged. Plans are not recorded as consumption.
- Owner live checks: a relevant gentle comment, an unrelated question, semantic
  opt-out/re-enable across channels, and no repetitive nagging. Offline model
  doubles verify plumbing/persistence, not the provider's actual interpretation.
- Approved initiative policy: one opener/day, seven days/topic, fifteen minutes
  without shared activity, respecting the existing proactive hourly budget.
  Uncertain Telegram or stale Matrix delivery is held for inspection; this first
  version has no automatic owner-facing recovery UI or unsafe resend mechanism.
- Live owner verification remains pending. Git/PR work needs a separate request.

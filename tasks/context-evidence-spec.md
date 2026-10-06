# Spec: time-aware routine context evidence

Module: context-evidence, from [routine-context-refresh-map.md](routine-context-refresh-map.md).
Status: owner-approved contract and plan; foundation implemented and offline
verified on 2026-10-06. No routine dispatch adoption or automatic questions yet.
Date: 2026-10-06 (Europe/Athens).

## Objective

Provide one truthful, read-only evidence snapshot for future routine clarification.
The snapshot distinguishes recent observations from expired/unknown state without
guessing that the owner returned home or that family members are together.

This module is a foundation, not an independently completed user-facing feature.
Existing routine decisions remain unchanged until the dependent clarification
module integrates the snapshot with question/defer/reevaluation behavior. Merely
adding expiry to every current resolver would silently disable routines before
the recovery path exists and is explicitly excluded from this slice.

## Tech stack and scope

Use existing Python/pytest and memory/routine_db.py abstractions; no new dependency,
schema migration, raw database access, provider call, scheduler or transport.
The public entry point lives in services/routine_context.py; the canonical
implementation is services/routine_context_evidence.py. There are no separate
Web/Telegram/Matrix interpretations.

Initial volatile-state scope:

- user_out_of_home
- family_at_home
- partner_with_user
- kid1_with_user
- kid1_with_partner

Work attendance, quiet hours, weekly shifts, school/football seasons, child
extended absence and confirmed schedules remain outside this initial freshness
policy. Later work may extend it by an explicit state-specific contract.

## Evidence contract

Each scoped flag exposes:

- effective_value: true, false or null; null means unknown, never false by default.
- stored_value: validated prior boolean or null, retained for explanation only.
- source: stored_context, gps, none, or conflict. Stored context must not be labeled
  owner-confirmed: today's schema does not preserve who/what wrote the record.
- recorded_at: parsed existing updated_at or GPS timestamp; no invented timestamp.
- valid_until: computed validity boundary or null if not establishable.
- status: known or unknown.
- reason: a bounded structured code such as missing, invalid_value,
  invalid_timestamp, future_timestamp, expired, stale, conflict, or fresh.

All calculations use one injected timezone-aware evaluation time. Interpret
legacy naive updated_at in the application's local timezone; compare aware
times as instants. Test both naive and aware input, day boundaries and DST.
Document that updated_at is last persistence time, not proven original event
time. Do not present it as stronger evidence than it is.

## Approved first-release validity policy

These are owner-approved policy choices, not discovered user habits:

1. Scoped stored whereabouts/co-presence is usable for at most two hours after
   its recorded update, shortened by any existing expiry. At the boundary it
   becomes unknown, never its opposite value.
2. Fresh GPS is usable for at most fifteen minutes after its recorded timestamp.
   A GPS point does not refresh family co-presence. Passing time alone does not
   establish departure, arrival, sleep or completion.
3. Missing, invalid or future timestamps cannot establish a current observation.
   Expired state is not revived by historical semantic memories.
4. Date-only expires_at remains valid through that local calendar day and expires
   at the following local midnight; do not add a fixed 24 hours across DST.
5. Preserve false as an observed boolean; absence of evidence is null.

The implementation must make the policy explicit and centrally testable using
structured flag IDs, not natural-language phrase lists.

## GPS and conflicts

- Read the existing GPS state through a bounded loader; validate finite coordinates,
  timestamp, configured home geometry and radius before using the point.
- Reuse services/location_update.py:location_is_home for geometry rather than
  duplicating distance logic. Do not edit config.py or discover work coordinates.
- Existing GPS records do not establish whether a point was a live beacon or a
  static pin and do not retain accuracy. Do not manufacture either attribute or
  claim certainty beyond a recent recorded owner-location point.
- GPS establishes only user_out_of_home. It cannot set user_at_work,
  family_at_home=true, partner_with_user, or any child flag to a guessed value.
- Agreeing recent owner-location candidates may establish the same effective
  value. Conflicting recent stored context and GPS produce unknown/conflict in
  this first slice: stored writer provenance is insufficient for a blanket
  GPS-versus-explicit-message precedence rule.
- If stored owner-location is missing/stale and GPS is fresh, GPS may establish
  owner home/away. If GPS is stale and stored context is recent, use stored context.
- Contradictory evidence must not be silently flattened: fresh owner-away evidence
  plus family_at_home=true cannot be presented as a fully coherent known household
  snapshot. Expose the household claim as unknown/conflict, without rewriting it.
- Reading the snapshot never changes stored flags, observation times, location
  files or routine state. Transport provenance gates remain unchanged.

## Public interface and style

Use typed functions and documented value objects/dictionaries, with dependencies
injectable at the test boundary. Example contract shape (not implementation):

```python
def build_routine_context_evidence(now: datetime) -> dict[str, ContextEvidence]:
    """Return time-bounded observations without modifying persisted state."""
```

Consumers can inspect effective values and reasons without examining user wording
or rerunning an LLM. A read failure must produce unknown/error evidence, not home,
false or a fabricated fresh timestamp. Do not mutate caller-supplied records.

## Commands and testing strategy

Use focused backend pytest with fake clocks, memory abstraction stubs and
temporary GPS fixtures. No Android/device interaction is part of this module.

Planned focused commands after implementation:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_routine_context_evidence.py tests/test_routine_context.py -q --basetemp=C:/Users/PC/AppData/Local/Temp/astakos-context-evidence
git diff --check
```

New tests must fail against the unimplemented contract before production code.
Make cloud/outbound access fail loudly. Existing resolver regressions must stay
green; no full-suite rerun or live user data needed for this foundation.

## Acceptance criteria

1. A park/away record three hours old resolves to unknown/stale; a recent valid
   true or false resolves accurately. Expired/invalid/future records do not revive.
2. Fresh home GPS establishes owner-home without assigning partner/child presence;
   stale/invalid GPS does not. Test just-before/at validity boundaries and conflicts.
3. Legacy naive timestamps, aware timestamps, local midnight and DST comparisons
   are consistent; persistence time is not misrepresented as actual event time.
4. The complete snapshot is read-only and channel-neutral. Work/shift/extended
   absence semantics and current routine dispatch remain unchanged in this slice.
5. Exceptions and missing provenance are visible as unknown, not silent defaults.

## Boundaries and deferred work

- Always: use canonical memory/location abstractions, preserve unrelated work,
  document unknown/conflict states and use offline focused regressions.
- Ask first: persistence/provenance schema changes, policy changes beyond the
  approved first-release durations, or changes to existing dispatch semantics.
- Never: modify real databases, Chroma, .env, credentials, config.py, runtime,
  watchdogs or Docker; send live messages; add phrase-list meaning parsers;
  change critical-action approval or mark routines complete from GPS.
- Deferred: automatic questions, answer correlation/retry, scheduler adoption,
  authenticated Debug UI presentation, historical memory/program inference,
  GPS accuracy enrichment and authoritative writer provenance. These belong to
  the following module specs or separately approved work.

## Owner-approved decisions

- Two hours for transient whereabouts/co-presence and fifteen minutes for GPS.
  They govern evidence freshness, not a timer that sends questions automatically.
- Conservative unknown on contradictory GPS/context until provenance can
  distinguish the writer, rather than guessing which one is authoritative.

## Implementation verification

- Stored-evidence RED: 26 failing tests before the new module; GREEN: 26 passed.
- GPS/conflicts RED: 24 failed / 26 passed before the next slice; GREEN: 50 passed.
- Entry-point RED: 8 failed / 50 passed before wiring.
- Final focused run: 74 passed, one dependency deprecation warning (google.genai
  uses _UnionGenericAlias). Python syntax checks and git diff --check passed.
- Existing resolver tests now isolate state/location fixtures and block network.
  The legacy deterministic shift test stubs its previously unmocked semantic
  model boundary; an earlier mixed run was stopped while waiting there. The
  passing final run is offline evidence, not provider verification.
- Integration uses real memory abstractions with a temporary SQLite database and
  a temporary GPS file, verifies unchanged records/file and unchanged legacy
  shift/extended-absence behavior. No real user data was written by this module.
- Legacy naive timestamps at ambiguous/nonexistent DST wall times become unknown;
  aware timestamps compare as instants. No missing fold information is invented.
- This foundation checkpoint preceded scheduler/Debug integration. The dependent
  routine-context-clarification module now consumes the projection; see its
  contract for current implementation status. Natural observation remains pending.

# Spec: Behavioral Events — Phase 3 Read-Only Patterns

## Objective

Derive inspectable, deterministic pattern candidates from already confirmed
behavioral events. This phase makes the event history easier to audit without
changing the assistant's behavior.

## Scope

- Read only `record_state="confirmed"` events from the existing behavioral
  event store.
- Group a named observation by its subject, normalized item, and recorded
  status. Retain the strict event-type/category/subject/status grouping only
  when no item exists. This prevents harmless extractor taxonomy drift from
  hiding repeated named observations, while avoiding cross-person grouping or
  merging distinct observation outcomes.
- Return a candidate only after at least three distinct event dates.
- Return evidence only: occurrence count, first date, last date, and the
  grouping fields.
- Order candidates deterministically by evidence count, then recency.

## Out of scope

- No new database schema, migrations, dependencies, or background jobs.
- No LLM call, prompt/context injection, Chroma write, profile write, or
  memory write.
- No routine, reminder, goal, follow-up, notification, or user-visible chat
  change.
- No causal, health, preference, or schedule claim from a candidate alone.

## Architecture

- `services/behavioral_pattern_aggregator.py` will contain a pure function
  accepting event mappings and returning candidate mappings.
- `memory/behavioral_event_state.py` remains the sole source of persisted
  behavioral events; Phase 3 does not modify it.
- A later, separate task may expose the result in a debug-only inspection
  surface after the pure aggregation is tested.

## Candidate contract

Each candidate contains only:

- `event_type`, `category`, `subject`, `item`, `status` (for a named-item
  candidate, these are the deterministic latest-event display fields)
- `occurrence_count`, `first_date`, `last_date`

Candidates are observations, not facts about the user. A missing optional
`item` remains distinct from a named item.

## Commands

- Focused tests: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_pattern_aggregator.py -q`
- Phase checks: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_event_state.py tests/test_behavioral_event_extractor.py tests/test_behavioral_pattern_aggregator.py -q`
- Diff validation: `git diff --check`

## Boundaries

- Always: use deterministic logic, validate event fields, and test before
  implementation.
- Ask first: changing thresholds, adding persistence, exposing candidates
  outside debug, or adding any consumer action.
- Never: infer a routine, send a message, write memory, or change a prompt
  from a Phase 3 candidate.

## Success criteria

- Only confirmed events can contribute to a candidate.
- Fewer than three distinct dates never yield a candidate.
- Candidate ordering and evidence are stable for the same input.
- The aggregation is pure and has no runtime side effects.

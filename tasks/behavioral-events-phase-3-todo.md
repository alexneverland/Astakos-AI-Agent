# Behavioral Events — Phase 3 Tasks

## Task 1: Pure pattern aggregation

- [x] Add a deterministic confirmed-event aggregator.
- [x] Acceptance: it groups only matching confirmed events and requires three
  distinct dates.
- [x] Verify: focused unit tests, including candidate, duplicate-date,
  candidate-state, and ordering cases.

## Task 2: Debug-only inspection

- [x] Expose the computed candidates through an existing debug inspection path.
- [x] Acceptance: it performs no behavioral-event or schema write and is unavailable to normal agent
  prompts or tools.
- [x] Verify: focused endpoint tests.

## Checkpoint

- [x] Review real candidate output manually before considering any user-facing
  use.
- [x] Keep all routines, messages, reminders, memory, and prompts unchanged.

## Task 3: Debug progress visibility

- [x] Return confirmed-event count, required dates, and strongest signature
  progress from the existing read-only debug endpoint.
- [x] Show that summary in both empty and populated dashboard states.
- [x] Verify focused aggregation, endpoint, and static dashboard tests.

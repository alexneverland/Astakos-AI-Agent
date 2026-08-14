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

- [ ] Review real candidate output manually before considering any user-facing
  use.
- [ ] Keep all routines, messages, reminders, memory, and prompts unchanged.

# Behavioral Events — Phase 2 Tasks

## Task 1: Debounced background scheduler

- [x] Add a small process-local scheduler that coalesces rapid intake requests.
- [x] Acceptance: one scheduled runner invokes the existing intake after the
  quiet period; failures are contained.
- [x] Verify: focused scheduler tests.

## Task 2: Web and Telegram integration

- [x] Enqueue the scheduler only after normal user history persistence.
- [x] Acceptance: both normal graph paths request background intake without
  changing graph output or user-visible messages.
- [x] Verify: focused integration tests.

## Checkpoint

- [x] Run focused behavioral-event tests, compile checks, and `git diff --check`.
- [x] Remove behavioral intake from the nightly analytics job; routine analytics
  remains enabled and no consumer behavior changed.

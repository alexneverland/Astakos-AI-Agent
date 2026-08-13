# Spec: Behavioral Events — Phase 2 Background Intake

## Objective

Process newly persisted trusted user messages shortly after they arrive, without
blocking a chat response. Behavioral intake is not run by the nightly job.

## Scope

- Schedule one debounced intake task after a user message is persisted.
- Reuse the existing validated watermark-based intake and its provenance filter.
- Reuse the existing slow queues in Web and Telegram; do not add a scheduler,
  thread, dependency, or database schema.
- Keep the work observational: no prompt, routine, Chroma, profile, reminder,
  or user-visible changes.

## Design

- A process-local debouncer coalesces repeated enqueue requests into one slow
  task after a short quiet period. On the first run, it carries the earliest
  newly persisted row id so intake starts immediately before that boundary
  instead of silently baselining those new messages.
- The slow task invokes `run_behavioral_event_intake()` and fails quietly; the
  queue worker must remain healthy.
- Each process may schedule work independently. The shared watermark preserves
  the earliest bootstrap boundary and only advances, while event source
  deduplication keeps rare cross-process replay safe.

## Success Criteria

- A persisted trusted user message schedules non-blocking intake in Web and
  Telegram's normal graph flows.
- Several rapid schedules produce one queued invocation per process window.
- A task failure neither blocks the queue nor changes user-facing behavior.
- Existing provenance rules still reject externally-derived history rows.

## Boundaries

- Always: test the debouncer and both integration call sites before merge.
- Ask first: changing delay policy, adding an event consumer, backfilling
  history, modifying real databases, or changing routines/prompts.
- Never: process raw external content or add a per-message synchronous LLM
  call.

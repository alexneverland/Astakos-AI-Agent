# Spec: Behavioral Events — Phase 1

## Objective

Record high-confidence, user-reported behavioral events as structured local data.
This phase creates no trends, prompt injection, routine changes, proactive messages,
or user-visible replies. Its purpose is to establish trustworthy source data for
later analysis.

## Scope

- Process only persisted direct user messages from the shared conversation history.
- Store a confirmed event only when extraction explicitly identifies the user,
  a completed/active fact, a date, and sufficient confidence.
- Store lower-confidence or ambiguous extraction as a candidate event only.
- Deduplicate by source conversation message and event signature.
- Preserve source row/message identity and channel for auditability.

## Out of scope

- No retrieval or context-builder changes.
- No trends, baselines, insights, or proactive messaging.
- No modifications to routines, goals, reminders, profile facts, or Chroma.
- No backfill of historic conversations in the first rollout.

## Architecture

- `memory/behavioral_event_state.py`: isolated SQLite store and query helpers.
- `services/behavioral_event_extractor.py`: validated normalization boundary for
  extractor output. It must fail closed on ambiguity.
- New conversation rows are processed by the existing 03:00 passive-analytics
  job using an independent watermark. First execution only establishes that
  watermark; it never backfills historic conversation data.

## Event contract

Required fields for a confirmed event:

- `event_type`, `category`, `subject`, `status`, `event_date`, `confidence`
- `negated`, `hypothetical`, `reported_by_user`
- `source_message_id`, `source_rowid`, `source_channel`

An event is confirmed only when `subject == "user"`, it is user-reported,
not negated, not hypothetical, and confidence meets the configured threshold.
All other structurally valid extractor results are retained as candidates and
cannot affect later behavior until a future phase explicitly promotes them.

## Commands

- Focused tests: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_event_state.py tests/test_behavioral_event_extractor.py -q`
- Diff validation: `git diff --check`

## Boundaries

- Always: validate before write, use parameterized SQLite queries, write tests first.
- Ask first: historic backfill, migrations of existing stores, new dependencies,
  user-visible behavior.
- Never: read/write real user databases directly, touch Chroma, inject event data
  into prompts, or send proactive messages in this phase.

## Success criteria

- Isolated tests prove confirmed versus candidate classification.
- Negated, hypothetical, third-person, and duplicate source records never become
  confirmed user events.
- The event store can be created on a fresh SQLite file and queried deterministically.

# Behavioral Events — Phase 1 Tasks

## Task 1: Isolated event schema and persistence

- [x] Add a dedicated SQLite state module with idempotent setup and source-level deduplication.
- [ ] Acceptance: a confirmed event and a candidate event can be stored and listed; replaying the same source is a no-op.
- [ ] Verify: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_event_state.py -q`
- [ ] Files: `memory/behavioral_event_state.py`, `tests/test_behavioral_event_state.py`

## Task 2: Validated event normalization

- [x] Add a pure extractor-output validator that classifies only safe user facts as confirmed.
- [ ] Acceptance: negation, hypothetical statements, third-party subjects, and low confidence become candidates.
- [ ] Verify: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_event_extractor.py -q`
- [ ] Files: `services/behavioral_event_extractor.py`, `tests/test_behavioral_event_extractor.py`

## Checkpoint

- [x] Run both focused test modules and `git diff --check`.
- [x] Confirm no prompt injection, agent tools, Chroma writes, routine writes, or messages changed.

## Task 3: Incremental runtime intake

- [x] Add a separate watermark-driven background intake to the existing passive analytics job.
- [ ] Acceptance: first run only initializes the watermark; later runs process only new,
  provenance-free direct user messages.
- [ ] Verify: `./venv/Scripts/python.exe -m pytest tests/test_behavioral_event_extractor.py -q`
- [ ] Files: `services/behavioral_event_extractor.py`, `memory/behavioral_event_state.py`,
  `clients/telegram_bot.py`, `tests/test_behavioral_event_extractor.py`

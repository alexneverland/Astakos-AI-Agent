# Spec: External Messaging Channel Selection

Module id: `channel-selection`

## Objective

Add one canonical, side-effect-free resolver for the active external messaging
channel. The resolver supports `telegram` and `matrix`, defaults to the existing
Telegram behavior when the setting is absent, and rejects invalid configured
values before any transport starts.

This slice defines and tests the selection contract only. It does not start a
Matrix client or modify the current `boot.py` process lifecycle. Boot wiring is
deferred until the `matrix-text` module provides a real, testable Matrix entry
point, so the repository remains runnable after this slice.

## Configuration contract

- Environment variable: `ASTAKOS_EXTERNAL_CHANNEL`
- Supported canonical values: `telegram`, `matrix`
- Missing variable: resolves to `telegram` for backward compatibility
- Configured blank or unsupported value: raises a clear configuration error
- Surrounding whitespace and letter case are normalized
- Web/API availability is not controlled by this setting

## Commands

- RED/GREEN focused test:
  `venv\Scripts\python.exe -m pytest tests/test_external_channel_selection.py -q --basetemp=.pytest_tmp_matrix_channel_selection`
- Nearby startup regression:
  `venv\Scripts\python.exe -m pytest tests/test_setup_diagnostics_portability.py tests/test_run_telegram_shutdown.py -q --basetemp=.pytest_tmp_matrix_startup_regression`
- Diff validation: `git diff --check`

## Project structure

- `core/messaging_channel.py`: canonical type, configuration error, and pure
  resolver.
- `tests/test_external_channel_selection.py`: offline contract tests.
- `boot.py`: intentionally unchanged in this slice.
- `.env`, `config.py`, Setup Wizard, Docker, runtime services, databases, and
  Telegram clients: unchanged.

## Code style

Use explicit typed values and fail closed on configured invalid input:

```python
ExternalChannel = Literal["telegram", "matrix"]


def resolve_external_channel(raw_value: str | None = None) -> ExternalChannel:
    """Return the validated external messaging channel without side effects."""
    ...
```

The implementation must not import Telegram or Matrix transports and must not
perform network, file, database, or process operations.

## Testing strategy

Write the focused tests before production code and observe the missing-module
failure. Tests cover:

- missing environment setting preserves `telegram`;
- canonical `telegram` and `matrix` values;
- case and surrounding-whitespace normalization;
- blank and unsupported configured values fail clearly;
- resolving the setting performs no transport import or outbound operation.

All tests remain offline. The nearby startup regression protects current boot
and Telegram watchdog behavior even though those files are not modified.

## Boundaries

- Always: preserve Telegram as the default, keep the resolver deterministic,
  keep the slice additive, and use exact typed channel identifiers.
- Ask first: modify `.env`, `config.py`, Setup Wizard, `boot.py`, Docker, or add
  a Matrix dependency/process.
- Never: start both external transports, alias Matrix as Telegram, silently
  accept an unsupported channel, access credentials, or add channel-specific
  behavior to the resolver.

## Success criteria

- One canonical resolver returns only `telegram` or `matrix`.
- Existing installations without the new variable still select Telegram.
- Explicit invalid configuration stops selection with an actionable error.
- The resolver has no imports or side effects from either transport.
- Focused and nearby startup regression tests pass offline.
- `git diff --check` is clean and the slice contains only the resolver, its
  tests, and this approved specification.

## Deferred

- Starting or stopping transport processes in `boot.py`.
- Matrix SDK selection, credentials, login, sync, E2EE, and message handling.
- Proactive delivery, approvals, routines, media, voice, and Setup Wizard UI.

## Open questions

None for this contract-only slice.

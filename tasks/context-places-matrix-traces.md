# Context, known places and Matrix traces

Owner authorization: 2026-10-09, following the 19:00–20:29 conversation audit.
The owner approved both confirmed repairs and Matrix trace parity in this turn.

## Scope and acceptance

1. Context: reproduce a completed family reunion while newer GPS repeatedly
   refreshes the same owner-presence value. Preserve newer evidence timestamps
   without dropping independently grounded relationship updates. Retain source
   identity, freshness, typed validation and atomic compare-and-set protections.
   Contrary newer evidence and ambiguous/future statements must not be overwritten.
2. Places: the existing home/work locations are configured geometry, not a generic
   writable POI registry. Add one local known-place store and an explicit Home tool
   for saving a named fresh current GPS point, listing configured/custom places,
   and matching fresh GPS to their radii. Never claim a save from a memory note.
   No config edits, reverse geocoder changes, family inference from GPS, migrations
   or automatic replay of the owner's historical park request.
3. Matrix: reuse ExecutionTrace for routing, tool arguments/results, latency,
   final response and errors; save even on failure. Protect concurrent Web/Matrix
   append operations and redact credential fields. A trace is execution evidence,
   not proof that a final response was delivered by the transport.
4. OwnTracks: handle a phone disconnect during HTTP body streaming without an
   unhandled exception or partial intake; retain authentication and upload limits.

## Implementation order

- [x] Failing persisted-context regression and nearby contrary/race safety tests.
- [x] Repair the canonical context validator/writer; run existing context tests.
- [x] Known-place persistence/tool integration with isolated file/GPS tests.
- [x] Matrix trace integration with persisted tool/error/intercept tests.
- [x] Focused combined verification, compilation, diff review and documentation.

## Commands and conventions

`venv\Scripts\python.exe -m pytest <focused modules> -q --basetemp=.pytest_tmp_context_places`

`git diff --check`

Use typed Python functions, existing memory abstractions, @tool skills and the
shared trace recorder. Tests use temporary stores and fail at unexpected provider
boundaries. No live database mutation, provider/transport calls, new dependency,
runtime/watchdog edits, tags or releases are included. The owner subsequently
authorized the disconnect repair and publication of all slices in one PR.

## Diagnostics questions

Which agent/tools actually ran? What bounded result did each return and how long
did it take? Did the turn fail or produce a response? Was a known-place write
confirmed by the canonical store? Live semantic interpretation remains an owner
observation after the offline regression suite passes.

## Verification (2026-10-09)

RED: two persisted reunion cases failed with newer same-value observations,
six named-place cases failed before implementation, and three Matrix trace cases
failed because no trace was recorded. The original extractor's raw provider
payload was not retained, so the reproduced GPS rejection mechanism is evidence
of a concrete defect, not a claim about every earlier model decision.

GREEN: 347 related tests passed, with two existing dependency deprecation warnings.
The suite covers real isolated context transactions, real compiled ToolNode place
storage, damaged/failed/concurrent writes, stale/future GPS, provenance gates,
Matrix command/graph/error traces, credential redaction and 40 concurrent trace
records from separate Web/Matrix processes. Four existing context review tests
needed their obsolete loader mock renamed to the current canonical loader.
Python compilation, registry parsing, local documentation links and diff checks
passed. No live historical context/POI repair or outbound test was performed.

Primary regressions: `tests/test_context_gps_reunion.py`,
`tests/test_known_places.py`, `tests/test_matrix_execution_trace.py`.
Operator contract: `docs/known-places-and-traces.md`.

OwnTracks RED: both real ASGI disconnect cases raised ClientDisconnect before
the repair. GREEN: all 37 OwnTracks tests passed, including empty/partial upload
disconnects, no queue writes, and a successful subsequent authenticated fix.

Final combined pre-PR verification: 384 tests passed across 18 related modules,
with the same two dependency deprecation warnings; compilation and diff checks
passed. All changes are published together in one pull request.

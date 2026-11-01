# End-to-end turn latency evidence

Approved scope (2026-10-30): measure the whole response path and model calls,
including application retry attempts and backoff, without changing decisions.

Questions: was time spent before graph execution, inside a particular node or
helper model call, or in retry backoff? Which provider/model was involved?

Acceptance:
- Web, Matrix and Telegram collect timing from handler entry through return,
  including early returns/errors. Existing trace files and console carry one
  correlation identity and bounded timing spans without prompt/response data.
- Graph nodes, prompt construction, routine/context/Messenger/behavioral helpers
  have named spans. LangChain callbacks capture direct and helper model calls.
- Application retry attempts and actual sleep durations are explicit. Provider
  SDK internal retries are included in call duration; only callback-exposed
  retries can be counted, never guessed.
- Nested/parallel intervals are not added as if sequential; show wall time,
  union of model intervals, and uncovered time separately. Timing must not
  alter results, approval gates, retry policies or exception propagation.

Implementation slices: collector and offline tests; entry/node/provider wiring;
debug display and documentation. Use ContextVars (propagated by asyncio.to_thread
and LangGraph) with per-collector locking, bounded storage and closed-turn guard.
Keep existing native ExecutionTrace persistence, defer its save until turn exit.

Verification: venv\\Scripts\\python.exe -m pytest tests/test_turn_timing.py
tests/test_execution_trace.py tests/test_matrix_execution_trace.py
tests/test_debug_dashboard_latency.py with isolated --basetemp. Run affected
channel/provider regression groups offline and git diff --check.

No config, credentials, live stores, runtime/watchdogs, dependency or routing
changes. No external test traffic. No PR/merge requested in this turn.

## Verification evidence

- Implemented shared content-free collector, LangChain callbacks and native
  provider-operation spans. Existing channel traces retain their preview and
  approval contracts; text handler saves defer until handler exit.
- Offline groups: 103 provider/timing/display cases; 174 channel cases; final
  130 timing/trace/Messenger/Behavioral cases (12 overlap with the first group).
  395 distinct passing cases across these groups. New timing scenarios use a
  synthetic monotonic clock, actual LangChain/LangGraph callback propagation,
  transport fakes, isolated trace files and outbound network blocking.
- Three existing Behavioral chat-node cases fail on both this branch and the
  unchanged main source at 1718a466ead911ceb438c1c518c528a693cfe8a8: they expect
  normal replies without the current draft write guard. Verified by loading
  HEAD versions of modified production modules in a separate pytest process,
  without replacing workspace files or touching runtime. Left outside scope;
  final focused group excludes exactly that already reproduced selector.
- Fixed duplicate native turn_finished events detected during intermediate
  testing; final Web/Telegram success/error/empty/pending trace tests pass.
- No live message or provider call was triggered to validate timing. Actual
  provider/network latency diagnosis awaits a subsequent real slow turn.

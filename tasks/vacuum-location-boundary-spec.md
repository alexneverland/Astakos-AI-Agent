# Vacuum presence and bounded Web turns

## Objective and approved scope

Repair owner-requested vacuum activation after its mandatory GPS read without
trusting arbitrary external text, and return a truthful Web result when a short
graph turn reaches its existing step budget. No vocabulary/phrase matching.

## Design

1. The canonical location tool emits only a closed, typed local data projection:
   bounded numeric coordinates/timestamp and computed presence, or a fixed
   missing/invalid/stale status. No copied strings, HTML, error text or extra keys.
   Reuse configured home geometry. Only this concrete schema is instruction-free;
   legacy/raw GPS text and other external tools remain untrusted. Normal approval
   risks remain unchanged. Sanitation and streamed provenance share this resolver.
2. A bounded Web iterator preserves an already-emitted pending/blocked approval
   if LangGraph exhausts the step budget immediately afterwards. Otherwise it
   emits a localized partial-execution warning, never retries or claims success.
   Keep recursion budgets unchanged.

## Ordered tasks and acceptance

- [x] RED: reproduce mandatory location -> vacuum rejection across Web/Matrix/
  Telegram and exercise hostile GPS/other-source negative cases offline.
- [x] GREEN: strict numeric-only location contract, canonical home calculation,
  normal approval and consistent provenance. Missing/invalid presence is unknown.
- [x] RED/GREEN: real scripted LangGraph budget exhaustion returns a blocked
  response or honest incomplete result without additional tools/side effects.
- [x] Focused regression verification: 160 passed, two dependency deprecations.
  This includes the real approval/ToolNode path with a mocked vacuum device and
  real finite LangGraph exhaustion. No physical vacuum or provider was contacted.
  Final Web extraction/endpoint coverage: 23 passed after guarding draft-result
  formatting from overwriting the incomplete-turn warning. Syntax/diff checks pass.
  PR #211 Codex follow-up: exact-budget terminal approvals also propagate the
  exhaustion marker without replacing their message/agent. Combined real-graph
  extraction plus Web endpoint regressions reproduced both blocked/pending draft
  overwrite before repair; 25 focused Web tests pass after repair.
- [ ] Owner-controlled live test after review; model wording is not proved offline.

## Commands and conventions

Use typed/docstring Python functions, existing LangChain tools and core.i18n.
Tests are pytest in tests/test_vacuum_location_boundary.py and
tests/test_web_graph_budget.py. Run venv/Scripts/python.exe -m pytest on these
and affected untrusted/location/API regressions with isolated --basetemp.
Compile changed Python with venv/Scripts/python.exe -m py_compile; git diff --check.

## Boundaries

Always fail closed on arbitrary tool-result text; retain selected-channel gates.
Never invoke real vacuum, cloud providers, Matrix/Telegram transport or live data.
Do not alter config.py/.env, real stores, runtime/watchdogs, limits, or PR #210.
Owner requested commit, PR and Codex review. Merge still requires direction.
Existing backup/behavioral tasks stay intact.

# Tasks: Web Research Providers, Slice 1

- [x] Define normalized provider contracts and registry.
  - Acceptance: selective provider IDs are validated; duplicate canonical URLs are removed; failures are isolated.
  - Verify: focused offline unit tests.
  - Files: `services/web_research.py`, `tests/test_web_research.py`.

- [x] Adapt existing Web search and add read-only GitHub search.
  - Acceptance: Web behavior remains compatible; GitHub public results normalize into the shared contract; no credentials are required.
  - Verify: provider tests plus unchanged `tests/test_duckduckgo_search.py`.
  - Files: `services/web_providers.py`, `tools/web.py`, `tests/test_web_research.py`.

- [x] Bind the aggregate tool to the existing Web Agent.
  - Acceptance: `research_web` is safe, registered, budgeted, and visible only through the existing Web Agent ownership path.
  - Verify: Web Agent binding, budget, and failure regression tests.
  - Files: `core/agents.py`, `core/tool_risk.py`, `tools/system.py`, `core/capability_registry.json`, `core/prompts.md`, tests.

- [x] Final verification and PR.
  - Acceptance: relevant and full test suites pass, `git diff --check` is clean, staged diff contains only this slice.
  - Verify: commands in `tasks/plan.md`.

## Slice 2: Reddit discovery

- [x] Add the Reddit provider with URL filtering and normalized provenance.
  - Acceptance: bounded site search returns only Reddit URLs and isolates failures.
  - Verify: focused offline provider tests written before implementation.
  - Files: `services/web_providers.py`, `tests/test_web_research.py`.

- [ ] Register Reddit in the existing research skill and Web Agent guidance.
  - Acceptance: `sources=["reddit"]` is valid without changing agent ownership.
  - Verify: registry/tool boundary tests.
  - Files: `astakos_skills/research_web.py`, `core/prompts.md`, `core/capability_registry.json`, tests.

- [ ] Final verification and PR.
  - Acceptance: focused/full suites pass and the diff contains only this slice.
  - Verify: isolated pytest basetemp and `git diff --check`.

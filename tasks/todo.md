# Tasks: Web Research Providers, Slice 1

- [ ] Define normalized provider contracts and registry.
  - Acceptance: selective provider IDs are validated; duplicate canonical URLs are removed; failures are isolated.
  - Verify: focused offline unit tests.
  - Files: `services/web_research.py`, `tests/test_web_research.py`.

- [ ] Adapt existing Web search and add read-only GitHub search.
  - Acceptance: Web behavior remains compatible; GitHub public results normalize into the shared contract; no credentials are required.
  - Verify: provider tests plus unchanged `tests/test_duckduckgo_search.py`.
  - Files: `services/web_providers.py`, `tools/web.py`, `tests/test_web_research.py`.

- [ ] Bind the aggregate tool to the existing Web Agent.
  - Acceptance: `research_web` is safe, registered, budgeted, and visible only through the existing Web Agent ownership path.
  - Verify: Web Agent binding, budget, and failure regression tests.
  - Files: `core/agents.py`, `core/tool_risk.py`, `tools/system.py`, `core/capability_registry.json`, `core/prompts.md`, tests.

- [ ] Final verification and PR.
  - Acceptance: relevant and full test suites pass, `git diff --check` is clean, staged diff contains only this slice.
  - Verify: commands in `tasks/plan.md`.

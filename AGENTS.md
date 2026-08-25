# Astakos AI Agent - Instructions for AI Coding Agents

## Project Overview
Astakos is a modular, local-first, LLM-agnostic multi-agent companion. It features a LangGraph supervisor orchestrating specialized agents (Chat, Home, Web, Tech, Git, Mail, Dev), a proactive scheduler, and a hybrid memory system (ChromaDB + SQLite) to learn user habits.

## Project Structure
```text
astakos/
├── api/              # FastAPI Web Server + /debug/runtime observability
├── astakos_skills/   # Modular Python skills (created with register_tool)
├── core/             # Agents, Supervisor, Planner, and LangGraph components
├── memory/           # Hybrid ChromaDB & SQLite storage logic
├── services/         # Analytics and Reflection Engines
├── tools/            # Local project, web, and system tools
└── vendor/           # External workflows (e.g., agent-skills)
```

## Key Files
- `core/agents.py` - LangGraph nodes, tools binding, and supervisor definition
- `main.py` - CLI Entry point
- `run_telegram.py` - Telegram Bot Entry point
- `config.py` - Environment Variables (DO NOT EDIT directly unless explicitly requested)

## Development Workflow & Rules
1. **Tool Usage:** Always prioritize using native Astakos tools defined in the project before writing new scripts.
2. **Skill Creation:** New capabilities should be created as skills inside `astakos_skills/` using the `@tool` decorator.
3. **Database Integrity:** Do not interact directly with `.db` files using raw SQL or Python scripts. Always use the provided abstractions in `memory/`.
4. **Environment Constraints:** Never expose, leak, or modify `.env` or `credentials.json` directly.
5. **Agent Skills (Addy Osmani):** You MUST strictly adhere to the workflows outlined in `vendor/agent-skills/AGENTS.md`. Specifically:
   - **Doubt-Driven Development:** Never make blind global changes (e.g., changing global variables, configurations, or limits) without explicitly verifying the consequences across the entire codebase.
   - **Search Before Edit:** Always use tools like `grep_search` and `view_file` to understand the surrounding context and existing logic before modifying any file.
   - **Zero-Tolerance for Hacks:** Do not implement quick hacks. If a specialized mechanism exists (like `context_builder.py` logic), extend it rather than bypassing it with global overrides.

## Git and Pull Request Autonomy

When the user asks an agent to create, finish, or close a pull request for a
scoped task, that request is standing authorization for the normal Git
lifecycle of that task. Do not request separate confirmation for each routine
step. Complete the work in this order:

1. Inspect the working tree and current branch before changing Git state.
2. Create a short-lived task branch from the current integration branch when
   practical; do not disturb unrelated local work.
3. Stage only the files that belong to the requested task. Never use
   `git add -A` or `git add .`.
4. Run the relevant tests and `git diff --check`; inspect the staged diff
   before committing.
5. Create an atomic, descriptive commit, push the task branch, and open or
   update its pull request. Then stop and report that the PR is ready.
6. Do not merge, delete the branch, poll for reviews, or address review
   comments unless the user explicitly asks for that next action. A green
   review check is not evidence that a review has no comments.
7. When the user asks to read comments, retrieve and summarize the completed
   reviews from the requested PR. A generic review summary, green check, or
   reaction is never proof that there are no findings. Before saying a review
   is clean, explicitly retrieve the PR's inline review comments as well as
   its top-level reviews, and inspect every comment attached to the latest
   reviewed commit. Do not filter comments by a shortened SHA, guessed time
   window, or the review body alone. Report whether each latest-commit finding
   is actionable, already addressed by a later commit, or intentionally
   deferred with the user's agreement. When the user asks to address comments,
   resolve the actionable findings, verify the change, and update the PR.
8. Only when the user explicitly asks to merge and delete may the agent merge
   the PR, after required checks pass and all known actionable review findings
   are resolved. Then update the integration branch and delete only the merged
   task branch.

The following always require a new, explicit user instruction and must not be
inferred from a general PR request: force-pushes; `git reset --hard`; `git
clean`; history rewrites; modifying remotes; deleting branches other than the
agent's merged task branch; creating or publishing tags/releases; modifying
credentials, `.env`, or `config.py`; database migrations; and Docker,
runtime, or watchdog changes. Platform-enforced confirmations and higher-level
safety policies always take precedence over this repository policy.

## Coding Conventions
- Python >= 3.11 required.
- Provide type hints (typing) and professional docstrings for all functions.
- Ensure terminal commands respect the constraints defined in `core/safe_executor.py`.

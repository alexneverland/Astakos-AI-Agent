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

## Coding Conventions
- Python >= 3.11 required.
- Provide type hints (typing) and professional docstrings for all functions.
- Ensure terminal commands respect the constraints defined in `core/safe_executor.py`.

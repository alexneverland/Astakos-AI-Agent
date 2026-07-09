---
name: astakos-ai-agent
description: A modular, local-first, LLM-agnostic multi-agent companion framework
---

## What I can accomplish
- Routine Learning: Learn user habits from conversational context and trigger proactive reminders via background scheduler.
- Hybrid Memory: Store and extract temporal (SQLite) and semantic (ChromaDB) facts, handling dedup and sentiment overrides.
- Multi-Agent Orchestration: Delegate tasks across LangGraph-based agents (Chat, Home, Web, Tech, Git, Mail, Dev).
- Smart Integrations: Control IoT devices (Vacuum), manage Google Calendar, generate/upload files to Google Drive, and parse receipts/product labels.

## Required inputs
- API Keys: GEMINI_API_KEY, TELEGRAM_TOKEN
- Local Configuration: `.env` setup with standard tokens

## Constraints
- Local-first execution: All `.db` and memory states reside strictly on the local machine.
- Environment: Python 3.11+ required.
- Approval Gates: All CRITICAL operations (e.g. `write_code`, `push_git`) require explicit Telegram approval before execution.

## Key documentation
- [README.md](/README.md): Full overview of the architecture and roadmap
- [AGENTS.md](/AGENTS.md): Coding rules and AI workflow instructions
- [llms.txt](/llms.txt): Discovery map for AI agents

## Example Usage
Here is an example of how an AI Agent can use the native Astakos tools to interact with the project:

```python
from tools.system import execute_shell_command

# DO NOT use raw sqlite3 to touch memory! Use the abstractions:
# The following is just an example of executing a safe command via Astakos.
result = execute_shell_command("echo 'Hello Astakos'")
print(result)
```

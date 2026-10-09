---
name: astakos-ai-agent
description: A modular, local-first, LLM-agnostic multi-agent companion framework
---

## What I can accomplish

- Routine Learning: Learn user habits from conversational context and trigger proactive reminders via background scheduler.
- Hybrid Memory: Store and extract temporal (SQLite) and semantic (ChromaDB) facts, handling dedup and sentiment overrides.
- Multi-Agent Orchestration: Delegate tasks across LangGraph-based agents (Chat, Home, Web, Tech, Git, Mail, Dev).
- Smart Integrations: Control IoT devices (Vacuum), manage Google Calendar, generate/upload files to Google Drive, and parse receipts/product labels.
- Shared Web/Telegram/Matrix conversation with one active external transport.
- Semantic context transitions, dated routine feedback provisioned by normal startup,
  behavioral conversation and partial goal updates.
- Selective daily data backup and separate encrypted Matrix operator workflows.

## Required inputs

- One chat provider: Vertex AI credentials, `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`
- Local configuration completed through the Setup Wizard or `.env`
- Optional: `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID` for Telegram, or a configured dedicated Matrix account, encrypted room and trusted owner devices for Element
- Optional: a separate embeddings or voice provider when the chat provider does not supply that capability

## Constraints

- Local-first execution: All `.db` and memory states reside strictly on the local machine.
- Environment: Python 3.11+ required.
- Approval Gates: CRITICAL operations require the configured approval flow before execution. Delivery uses the selected external transport; Matrix requires an exact Reply to the approval request, not a reaction.

## Key documentation

- [README.md](../README.md): Full overview of the architecture and setup
- [SETUP_GUIDE.md](../SETUP_GUIDE.md): Provider, voice, Docker, and integration setup
- [AGENTS.md](../AGENTS.md): Coding rules and AI workflow instructions
- [llms.txt](../llms.txt): Discovery map for AI agents
- [Routines and context](routines-and-context.md): State, dated feedback and delivery meanings
- [Data backup](daily-data-backup.md): Selected inventory and recovery limits
- [Release readiness](release-readiness.md): Proposed v2.8.0 and installation gates

## Example Usage

Here is an example of how an AI Agent can use the native Astakos tools to interact with the project:

```python
from tools.project_tools import list_project_files

# The user must first approve this root for read access through Astakos.
# Project tools then keep reads bounded.
result = list_project_files.invoke({
    "folder_path": r"C:\projects\example",
    "pattern": "**/*.py",
})
print(result)
```

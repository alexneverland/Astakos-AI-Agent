<div align="center">

# Astakos AI Agent

### Your own proactive AI assistant, running from your computer.

**Download it, start it with Docker, choose your AI provider, and chat through the Web UI or Telegram.**

Astakos remembers useful context, learns recurring routines, follows up naturally, creates files, uses tools, and keeps its long-term memory and runtime state on your machine.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-One--Command_Setup-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

[Beginner Setup Guide](SETUP_GUIDE.md) · [Screenshots](#screenshots) · [Features](#what-astakos-can-do) · [Architecture](#architecture) · [Roadmap](#roadmap)

</div>

---

## Start in Minutes with Docker

You need **Docker Desktop** and an API key or credentials for one supported AI provider.

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
docker compose up --build -d
```

Then open:

```text
http://localhost:8000
```

The Web Setup Wizard guides you through provider selection and configuration.

**No manual Python environment. No dependency hunting. No Playwright setup. Docker handles the runtime.**

Prefer not to use Git? Download the repository as a ZIP, extract it, open a terminal in the folder, and run:

```bash
docker compose up --build -d
```

Read the complete **[Beginner Setup Guide](SETUP_GUIDE.md)** for Windows, Linux, macOS, updates, troubleshooting, and the manual Python path.

> Astakos is self-hosted and Docker-first, not a magical zero-configuration executable. You still choose and configure the external AI provider that powers model calls.

---

## Why Astakos Is Different

Most assistants wait for a prompt, forget the conversation, and start from zero next time.

Astakos is designed as a personal AI operating layer with continuity:

| | Astakos |
|---|---|
| **Runs from your computer** | Long-term memory, databases, routines, logs, settings, and uploads live in your local project folder. |
| **Remembers across channels** | Telegram and Web UI share conversation history and long-term context. |
| **Learns routines** | It detects recurring habits and can remind you before they happen. |
| **Follows up naturally** | It can revisit purchases, outings, tasks, and goals when a follow-up still makes sense. |
| **Uses real tools** | Files, Gmail, Calendar, web research, GitHub, local projects, reminders, and more. |
| **Asks before risky actions** | SAFE, WARNING, NOTIFY, and CRITICAL approval levels control execution. |
| **Works with multiple model providers** | Vertex AI, Gemini API, OpenAI, and Anthropic. |

Astakos is not just an API wrapper with a chat box. It combines memory, agents, schedulers, approvals, analytics, and tools into one local-first system.

---

## Screenshots

### Telegram

<img width="320" alt="Astakos Telegram screenshot" src="https://github.com/user-attachments/assets/c5ca1afd-c290-4c95-a50c-886e2fa6c955" />

### Web UI

<img width="650" alt="Astakos Web UI screenshot" src="https://github.com/user-attachments/assets/f112fad5-2480-4a9f-ae2f-719c0106b176" />

### Runtime Dashboard

<img width="650" alt="Astakos Runtime Dashboard screenshot" src="https://github.com/user-attachments/assets/f83756cd-51bb-4208-ac55-8d85b932d471" />

---

## What Astakos Can Do

### Personal Memory and Context

- Shared Telegram and Web conversation history in SQLite.
- ChromaDB semantic memory for facts, goals, sessions, documents, and photos.
- Structured profile, reminder, routine, and analytics databases.
- Hybrid recall combining recent context, SQLite history, and semantic memory.
- Memory provenance, confidence, importance, freshness, and retrieval tracking.
- Category-safe overwrite rules and memory-audit logging.

### Proactive Assistance

- Learns recurring routines from conversation history.
- Uses live context such as work shifts, family outings, school state, football season, quiet hours, and whether people are home.
- Sends reminders before an activity rather than after it is already useless.
- Applies adaptive anti-spam cooldowns when reminders are ignored.
- Creates delayed conversational follow-ups and cancels them when the topic is already resolved.
- Checks stale long-term goals and can follow up after inactivity.

### Multi-Agent Tools

LangGraph routes work to specialized agents:

- **Chat** — conversation and personal context.
- **Home** — household and routine workflows.
- **Web** — search, news, weather, places, and navigation.
- **Tech** — diagnostics, system health, and technical support.
- **Git** — repository and version-control actions.
- **Mail** — Gmail search, reading, drafting, and sending.
- **Dev** — local project work, file generation, and coding tasks.

### Planning and Execution

Planner v2 supports:

1. automatic detection of multi-step requests;
2. a confirmation gate before execution;
3. step-by-step progress;
4. output and failure validation;
5. automatic re-planning or skipping failed steps;
6. a final success summary;
7. post-plan reflection saved as a lesson.

### Files and Documents

- Generate styled Excel, Word, PDF, CSV, and text files.
- Send generated files directly through Telegram.
- Show downloadable file cards in the Web UI.
- Upload to Google Drive on demand.
- Read and summarize uploaded documents.
- Keep discussing a recent upload without pasting it again.
- Convert large Web UI pastes into virtual files for reliable analysis.

### Images, Voice, and Daily Life

- Voice input with Whisper or Gemini.
- Greek neural voice replies with `edge-tts`.
- Product-label analysis for food, cosmetics, and household items.
- Receipt scanning into structured JSON.
- Children's story generation with AI illustrations.
- Google Fit summaries for steps, sleep phases, and heart rate.
- Google Calendar CRUD and proactive briefings.
- Georgian language helper and text-to-speech.

### Safety and Observability

- SAFE, WARNING, NOTIFY, and CRITICAL action levels.
- Telegram and dashboard approval controls for CRITICAL actions.
- Approval expiry protection.
- Terminal-command classification and blocking.
- Per-turn execution traces with agent, tools, duration, and errors.
- Tool performance statistics.
- `/doctor` runtime health reports.
- Debug dashboard for routines, memory, scheduler jobs, approvals, follow-ups, and traces.

---

## Privacy Model

Astakos is **local-first**:

- conversation history and session exchanges are stored in SQLite;
- semantic memories are stored in ChromaDB;
- routines, reminders, profile facts, analytics, logs, and indexes remain in the local project folder;
- credentials, databases, logs, uploads, caches, and generated outputs are excluded from Git.

Local-first does not mean offline-only. When you enable an external service, Astakos may send the prompts, media, or tool payloads required by that service. This includes configured model providers, Telegram, Google APIs, GitHub, Spotify, LinkedIn, and other optional integrations.

You control the machine, credentials, enabled integrations, and stored runtime state.

---

## Supported AI Providers

| Provider | Required configuration |
|---|---|
| Gemini API | `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` |
| OpenAI | `LLM_PROVIDER=openai` and `OPENAI_API_KEY` |
| Anthropic | `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` |
| Vertex AI | Google credentials JSON, project ID, and location |

Only one provider is required to start.

---

## Everyday Docker Commands

```bash
# Status
docker compose ps

# Live logs
docker compose logs -f

# Stop
docker compose down

# Start again
docker compose up -d

# Rebuild after updating
git pull
docker compose up --build -d
```

The project directory is mapped into the container, so SQLite databases, ChromaDB, configuration, logs, and other runtime files persist on the host.

---

## Manual Developer Setup

Docker is recommended for normal use. Developers can run Astakos directly with Python 3.11+:

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python -m venv venv
```

Windows:

```powershell
.\venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python boot.py
```

Linux/macOS:

```bash
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python boot.py
```

To reopen the setup wizard:

```bash
python boot.py --setup
```

To run the Web API and Telegram bot together:

```bash
python boot.py --server
```

See **[SETUP_GUIDE.md](SETUP_GUIDE.md)** for full instructions.

---

## Architecture

```text
 Telegram Bot          Web UI             CLI
      │                   │                │
      └──────────── Shared conversation ───┘
                          │
                    Pre-check / Router
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   Task Executor      Supervisor       Plan Control
                          │
       Chat · Home · Web · Tech · Git · Mail · Dev
                          │
                    Approval Check
              SAFE / WARNING / NOTIFY / CRITICAL
                          │
                       Tools
                          │
                Validation / Re-plan
                          │
                    Final Reflection
                          │
        ┌─────────────────┴──────────────────┐
        │                                    │
 SQLite history, profile, state      ChromaDB semantic memory
 routines, reminders, analytics      facts, goals, documents
```

A central scheduler handles reminders, routines, conversational follow-ups, proactive scans, health briefings, goal checks, analytics, and reflection.

---

## Core Runtime Storage

Astakos currently uses:

- `astakos_conversation_history.db` — shared Telegram/Web history and session exchanges
- `astakos_profile.db` — structured profile facts
- `astakos_state.db` — reminders, sessions, lists, and pending state
- `astakos_routines.db` — routines, context flags, reflections, and confirmations
- `analytics_state.db` — incremental routine-learning progress
- `astakos_embeddings_cache.db` — embeddings cache
- `chroma_db/` — semantic vector memory
- `logs/events/` and `logs/traces/` — runtime and execution diagnostics
- local JSON sidecars — lightweight working state and media indexes

Back up the entire project folder before major upgrades when your stored memory matters.

---

## Telegram Commands

| Command | Effect |
|---|---|
| `/pause` | Pause reminder notifications. |
| `/mute` | Mute proactive messages. |
| `/sleep N` | Sleep for N hours. |
| `/resume` | Clear overrides. |
| `/status` | Show scheduler and runtime status. |
| `/voice` | Toggle voice replies. |
| `/nutrition` | Analyze the last product-label photo. |
| `/receipt` | Parse the last receipt photo. |
| `/story [theme] \| [characters]` | Generate a children's story and illustrations. |
| `/plan [goal]` | Plan and execute a multi-step goal. |
| `/confirm <cmd>` | Confirm a shell command. |
| `/end` | Summarize and close the current session. |
| `/help` | Show commands and current settings. |

---

## Routine Learning

Astakos processes new shared conversation history incrementally and promotes a routine only after a recurring pattern is strong enough.

```text
LEARNED → ACTIVE → TRIGGER_PENDING → CONFIRMED → ACTIVE
                                   → IGNORED   → ACTIVE with longer cooldown
                                   → DISMISSED → ACTIVE or DECAYED
                                   → DECAYED   → ARCHIVED
```

Before triggering, Astakos resolves current context and checks whether the reminder is still appropriate. Multiple simultaneous routines can be batched into one message.

---

## Project Highlights

- Docker-first Web Setup Wizard
- LangGraph multi-agent orchestration
- Shared cross-channel SQLite conversation memory
- ChromaDB semantic long-term memory
- Incremental routine analytics
- Context-aware proactive reminders
- Conversational follow-up engine
- Planner v2 with validation and re-planning
- File and document generation
- Gmail, Calendar, GitHub, Google Drive, and local project tools
- Voice, image, receipt, product, story, and health workflows
- Runtime dashboard, traces, tool statistics, and System Doctor
- Local approval and risk-control system
- MIT licensed and model-provider agnostic

---

## Roadmap

### Planned

- [ ] Planner v3 with parallel execution and per-step Telegram approval buttons
- [ ] Behavior analytics that adjusts routine timing from real ignore/confirmation patterns
- [ ] Long-term pruning of low-value memories after enough real usage data exists
- [ ] Personal knowledge graph for structured relationships
- [ ] SQLite tool-execution journal for long-term performance trends

Ideas, bug reports, and contributions are welcome through [GitHub Issues](https://github.com/alexneverland/Astakos-AI-Agent/issues).

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

*Built with care by a Maker, for Makers.*

**[alexneverland](https://github.com/alexneverland)**

</div>

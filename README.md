<div align="center">

# Astakos AI Agent

### Your own proactive AI assistant, running from your computer.

**Download it, start it with Docker, choose your AI provider, and chat through the Web UI or Telegram.**

Astakos remembers useful context, learns recurring routines, follows up naturally, creates files, uses tools, and keeps its long-term memory and runtime state on your machine.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Automatic_Updates-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

[**Latest Release & Downloads**](https://github.com/alexneverland/Astakos-AI-Agent/releases/latest) · [Beginner Setup Guide](SETUP_GUIDE.md) · [Screenshots](#screenshots) · [Features](#what-astakos-can-do) · [Architecture](#architecture)

</div>

---

## Recommended: Docker with Automatic Updates

The release deployment uses the official GHCR image and Watchtower. Watchtower checks for a newer image every five minutes, replaces only the application container, and preserves the Astakos data volume.

Download `docker-compose.release.yml` from the **[Latest Release](https://github.com/alexneverland/Astakos-AI-Agent/releases/latest)**, place it in an empty folder, and run:

```bash
docker compose -f docker-compose.release.yml up -d
```

Then open:

```text
http://localhost:8000
```

The Setup Wizard is local-only by default. Docker keeps port 8000 bound to `127.0.0.1`; do not expose it publicly without a trusted authenticated reverse proxy.

The Web Setup Wizard guides you through provider selection and configuration.

> **Note:** Web/API setup works with only one configured AI provider. Telegram is optional until `TELEGRAM_TOKEN` is configured. Docker can start Astakos in Web/API mode even before Telegram is configured. If `TELEGRAM_TOKEN` is missing, Astakos starts the Web Setup Wizard and Web UI only; Telegram features become available after Telegram is configured.

> **Vertex AI + Docker note:** if you choose `Vertex AI`, you must mount a real Google service-account JSON file into the container and set `GOOGLE_APPLICATION_CREDENTIALS` to the in-container path. A local Windows/macOS/Linux path by itself is not enough for the release Docker setup.

### What is preserved during an automatic update

- `.env` and provider settings
- SQLite databases
- ChromaDB memory
- logs, uploads, generated files, backups, and runtime data
- credentials and OAuth token files

The release image refreshes application code while keeping those user-owned files in the persistent `astakos_data` Docker volume.

### Useful release commands

```bash
# Status
docker compose -f docker-compose.release.yml ps

# Astakos logs
docker compose -f docker-compose.release.yml logs -f astakos

# Watchtower logs
docker compose -f docker-compose.release.yml logs -f watchtower

# Stop
docker compose -f docker-compose.release.yml down

# Start again
docker compose -f docker-compose.release.yml up -d

# Force an immediate image check
docker compose -f docker-compose.release.yml pull
docker compose -f docker-compose.release.yml up -d
```

> The Watchtower deployment requires access to the local Docker socket. This is standard for container auto-updaters, but it gives Watchtower control over Docker on that machine. Use the source-build method below when this trade-off is not acceptable.

---

## Source Build with Docker

Developers and users who prefer to control every update manually can clone the repository:

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
docker compose up --build -d
```

Update manually with:

```bash
git pull
docker compose up --build -d
```

Prefer not to use Git? Open the **[Latest Release](https://github.com/alexneverland/Astakos-AI-Agent/releases/latest)** and download the current Source code ZIP.

Read the complete **[Beginner Setup Guide](SETUP_GUIDE.md)** for Windows, Linux, macOS, backups, troubleshooting, and the manual Python path.

> Astakos is self-hosted and Docker-first, not a zero-configuration executable. You still choose and configure the external AI provider that powers model calls.

---

## Why Astakos Is Different

Most assistants wait for a prompt, forget the conversation, and start from zero next time.

| | Astakos |
|---|---|
| **Runs from your computer** | Long-term memory, databases, routines, logs, settings, and uploads remain in your local runtime storage. |
| **Remembers across channels** | Telegram and Web UI share conversation history and long-term context. |
| **Learns routines** | It detects recurring habits and can remind you before they happen. |
| **Follows up naturally** | It can revisit purchases, outings, tasks, and goals when a follow-up still makes sense. |
| **Uses real tools** | Files, Gmail, Calendar, web research, GitHub, local projects, reminders, and more. |
| **Asks before risky actions** | SAFE, WARNING, NOTIFY, and CRITICAL approval levels control execution. |
| **Works with multiple providers** | Vertex AI, Gemini API, OpenAI, and Anthropic. |

Astakos combines memory, agents, schedulers, approvals, analytics, and tools into one local-first system.

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

### Memory and proactive assistance

- Shared Telegram and Web conversation history in SQLite.
- ChromaDB semantic memory for facts, goals, sessions, documents, and photos.
- Hybrid recall combining recent context, SQLite history, and semantic memory.
- Isolated behavioral observations that classify trusted user reports and surface repeated pattern candidates in Debug before they can influence any future feature.
- Recurring-routine learning with context-aware reminders and adaptive anti-spam cooldowns.
- Delayed conversational follow-ups that cancel when the topic is already resolved.
- Long-term goal tracking and follow-up after inactivity.

### Multi-agent tools

LangGraph routes work to specialized Chat, Home, Web, Tech, Git, Mail, and Dev agents.

- Gmail search, reading, drafting, and sending
- Google Calendar and Drive workflows
- web research, weather, places, and navigation
- local project and GitHub actions
- reminders, routines, files, documents, images, voice, receipts, stories, and health summaries

### Planning and safety

Planner v2 supports automatic multi-step detection, confirmation before execution, progress reporting, validation, re-planning, and final reflection.

Astakos includes SAFE, WARNING, NOTIFY, and CRITICAL action levels, approval expiry, terminal-command protection, provenance handling for external content, execution traces, tool statistics, `/doctor`, and runtime dashboards.

---

## Privacy Model

Astakos is **local-first**. Conversation history, semantic memory, routines, reminders, profile facts, analytics, logs, and indexes remain in local Docker storage or the local project folder.

Local-first does not mean offline-only. Enabled model providers and integrations may receive the prompts, media, or tool payloads required to perform their function.

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

### Optional Gemini model selection

Gemini API and Vertex AI use `gemini-3.5-flash` for everyday interactions and
`gemini-3.1-pro-preview` for heavier reasoning by default. To test a newer
Google model without changing the shared defaults, set only the model you want
to override in your local `.env`:

```env
ASTAKOS_GEMINI_FAST_MODEL=gemini-3.7-flash
```

Remove that line (or leave it blank) and restart Astakos to return immediately
to the tested default. `ASTAKOS_GEMINI_HEAVY_MODEL` is available separately,
but should normally be left unset.

### Vertex AI with Docker

For the release Docker deployment, Vertex AI needs a service-account JSON file that exists **inside the container**.

1. In Google Cloud Console, create or choose a service account for Vertex AI.
2. Grant it the access your project needs for Vertex AI.
3. Create a **JSON** key for that service account and download it.
4. In the same folder as `docker-compose.release.yml`, create a local folder named `credentials/`.
5. Copy the downloaded JSON file into that folder, for example:

```text
credentials/vertex-service-account.json
```

6. The included `docker-compose.release.yml` already mounts `./credentials` into the container as `/app/credentials`.

7. In the Setup Wizard or `.env`, use:

```env
LLM_PROVIDER=vertex
GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/vertex-service-account.json
PROJECT_ID=your-gcp-project-id
LOCATION=global
```

8. Restart Astakos:

```bash
docker compose -f docker-compose.release.yml up -d
```

If you do not want to mount a JSON credentials file into Docker, use `Gemini API`, `OpenAI`, or `Anthropic` instead.

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

---

## Releases and Docker Images

Every `v*` Git tag triggers GitHub Actions to build multi-architecture images for AMD64 and ARM64:

```text
ghcr.io/alexneverland/astakos-ai-agent:<version>
ghcr.io/alexneverland/astakos-ai-agent:latest
```

The release compose file tracks `latest`; Watchtower downloads a new image and restarts Astakos automatically. Versioned tags remain available for users who prefer pinned deployments.

---

## License

MIT — see [LICENSE](LICENSE).

<div align="center">

*Built with care by a Maker, for Makers.*

**[alexneverland](https://github.com/alexneverland)**

</div>

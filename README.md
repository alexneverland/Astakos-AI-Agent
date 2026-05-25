<div align="center">

# 🦞 Astakos AI Agent

**A high-performance, modular, and LLM-agnostic multi-agent framework.**
Built with a *local-first* philosophy — orchestrating specialized AI agents through a graph-based architecture for automation, technical tasks, and persistent memory management.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Gemini](https://img.shields.io/badge/Gemini-3.1_Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-FF6B35?style=for-the-badge)](https://www.trychroma.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

</div>

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 🧠 **Graph-Driven Orchestration** | Uses **LangGraph** for complex state transitions and dynamic agent routing |
| 🤖 **Multi-Agent Intelligence** | A **Supervisor** delegates to specialized sub-agents: Dev, Home, Web, Tech, Git, Mail, Chat |
| 💾 **Persistent Hybrid Memory** | SQL Checkpoints + **ChromaDB** vector store for long-term semantic retrieval |
| 🗓 **Routine Learning System** | 3-stage semantic dedup pipeline (fingerprint → difflib → embeddings cosine) with adaptive confidence scoring |
| 🔄 **Routine State Machine** | Explicit lifecycle enforcement: `LEARNED → ACTIVE → TRIGGER_PENDING → CONFIRMED/IGNORED/DISMISSED → DECAYED → ARCHIVED` |
| ⏰ **Central Scheduler** | `AstakosScheduler` — single-thread event bus with per-job watchdog, rate limiting & quiet hours |
| 🛡 **Anti-Spam Intelligence** | Per-routine adaptive cooldown (20h→40h→72h on ignore), batch notifications, per-ID dedup via DB timestamp |
| 🧩 **Formal Event Bus** | Pub/sub decoupling via `core/event_bus.py` — emits `routine_triggered`, `routine_confirmed`, `session_ended` and more |
| 📊 **Observability Dashboard** | `/debug/runtime` — scheduler heartbeat, job health, fail counts, pending confirmations, per-channel session counters |
| 🔔 **Human Override Commands** | Telegram commands: `/pause` `/mute` `/sleep N` `/resume` `/status` — persisted across restarts |
| ♻️ **Recovery After Restart** | Pending confirmations + override state persisted to SQLite/JSON — restored automatically on startup |
| 🔒 **Thread-Safe SQLite** | WAL mode + `db_write_lock` — concurrent reads, serialized writes, 3s busy timeout |
| 📊 **Structured Exceptions** | `AstakosError` hierarchy: `RoutineConflictError`, `DBWriteError`, `SchedulerCrashError`, `PendingTimeoutError` |
| 📡 **Multimodal Interfaces** | **Web UI**, **CLI**, and **Telegram Bot** with native image, voice & document processing |
| 🔀 **Hybrid Channel Memory** | Shared long-term cognitive memory (routines, facts, profiles) + isolated per-channel session history (telegram / web / terminal) |
| 💬 **Persistent Telegram History** | Telegram conversation history survives restarts — saved to `astakos_telegram_history.json`, restored automatically on startup |
| 🧠 **Skills System** | Modular skill scripts in `astakos_skills/` — flights, ferries, recipes, backups, billing and more |
| 📝 **Event Logging** | Daily JSON logs (`logs/events/YYYY-MM-DD.json`) for every scheduler action, error, and notification |
| 🏠 **Local-First** | Runs entirely on your machine — your data stays yours |

---

## 🏗 Project Structure

```
astakos/
├── 📁 api/
│   └── server.py             # FastAPI/Uvicorn Web Server + /debug/runtime observability
├── 📁 astakos_skills/        # Modular skill scripts
│   ├── calculate_bill.py
│   ├── daily_backup.py
│   ├── recipe_expert.py
│   ├── search_ferries.py
│   ├── search_flights.py
│   └── linkedin_state_manager.py
├── 📁 clients/
│   └── telegram_bot.py       # Telegram Bot — polling, handlers, AstakosScheduler
├── 📁 core/
│   ├── brain.py              # LLM initialization (Gemini)
│   ├── agents.py             # Agent nodes & supervisor router
│   ├── graph.py              # LangGraph state machine
│   ├── event_bus.py          # Formal pub/sub Event Bus (singleton)
│   ├── routine_state.py      # Routine lifecycle state machine + VALID_TRANSITIONS
│   ├── exceptions.py         # Structured exception hierarchy (AstakosError +5)
│   ├── safe_executor.py      # Safe tool execution wrapper
│   └── utils.py              # Shared utilities (clean_message, filter_messages)
├── 📁 memory/
│   ├── vector_store.py       # ChromaDB long-term memory
│   ├── working_memory.py     # Real-time context tracking ("Foreground")
│   ├── session_memory.py     # Per-channel session summaries & Memory Sifter
│   ├── routine_db.py         # SQLite routine storage — 3-stage dedup, adaptive cooldown
│   └── event_log.py          # Event logging + dedup protection (per-routine & per-text)
├── 📁 tools/
│   ├── system.py             # Files, GitHub, Gmail, IoT, Reminders, Routine learning
│   ├── web.py                # News, Weather, Google Places, Navigation, Supermarket
│   └── telegram.py           # Telegram messaging helpers
├── 📁 services/
│   ├── gemini.py             # Gemini API client
│   └── embeddings.py         # Vertex AI Embeddings + MD5 disk cache
├── 📁 logs/events/           # Daily scheduler event logs (gitignored)
├── astakos_routines.db       # SQLite: routines + pending_confirmations (gitignored)
├── scheduler_state.json      # Override state persistence (gitignored)
├── config.py                 # Central configuration
├── clean.py                  # Maintenance & cleanup script
├── read_memory.py            # Memory inspection utility
└── main.py                   # Launcher (Web / Telegram / Both)
```

---

## 🧩 Architecture Overview

```
   Telegram Bot          Web UI             CLI (terminal)
   [channel=telegram]  [channel=web]    [channel=terminal]
         │                  │                   │
         └──────────────────┼───────────────────┘
                            ▼
                    ┌─────────────┐
                    │  Supervisor │  ← Routes to the right agent
                    └──────┬──────┘
                           │
                ┌──────────▼──────────────────────────────────┐
                │  Chat · Home · Web · Tech · Git · Mail · Dev  │
                └──────────┬──────────────────────────────────┘
                           │
                ┌──────────▼──────┐     ┌────────────────────────────────┐
                │   Tool Node     │────▶│  Memory Layer (3-tier)         │
                │   (LangGraph)   │     │  ┌─ SHARED ──────────────────┐ │
                └─────────────────┘     │  │ ChromaDB (facts/routines) │ │
                                        │  │ SQLite (routines/events)  │ │
                                        │  └───────────────────────────┘ │
                                        │  ┌─ PER-CHANNEL ─────────────┐ │
                                        │  │ session history (JSON)    │ │
                                        │  │ session summaries (tagged)│ │
                                        │  └───────────────────────────┘ │
                                        └────────────────────────────────┘

Background (AstakosScheduler — daemon thread)
    ├── job_check_reminders   every 20s
    ├── job_check_routines    every 60s   ← 3-stage dedup + adaptive cooldown
    └── job_proactive_scan    every 12h   ← watch_folder analysis

Event Bus (core/event_bus.py — pub/sub singleton)
    ├── routine_triggered  (routine_id, event, confidence, batch, channel)
    ├── routine_confirmed  (routine_id, event, channel)
    ├── routine_dismissed  (routine_id, event, channel)
    ├── routine_timeout    (routine_id, event, elapsed_s, channel)
    ├── session_ended      (channel, mood, summary)
    └── proactive_sent     (source, channel)
```

---

## 🗓 Routine Learning System

Astakos passively learns your daily routines from conversation and proactively reminds you.

**3-Stage Semantic Dedup Pipeline** (prevents duplicate routines):
1. **Stage 1 — Exact Fingerprint**: MD5 hash of `day|time|event` (canonical form)
2. **Stage 2 — Fuzzy Match**: difflib ratio ≥ 0.72 for same day/time slot
3. **Stage 3 — Semantic Similarity**: VertexAI embeddings cosine ≥ 0.88

**Routine Lifecycle State Machine:**
```
LEARNED → ACTIVE → TRIGGER_PENDING → CONFIRMED → ACTIVE
                                   → IGNORED   → ACTIVE (cooldown doubled)
                                   → DISMISSED → ACTIVE (Everyday) / DECAYED (weekly)
                                   → DECAYED   → ARCHIVED
```

**Smart Dismiss for Daily Routines:**
- `Everyday` routines that are dismissed (e.g. "not today, it's raining") return to `ACTIVE` the next day
- Confidence decreases slightly on each dismiss — if ignored repeatedly, routine naturally fades to `DECAYED`

**Adaptive Cooldown** (Anti-Spam):
- Default: 20h cooldown between notifications for the same routine
- 1st ignore → 40h | 2nd ignore → 72h (max) | Respond → reset to 20h
- Multiple routines at the same time → **batched into one message**

---

## 🔔 Telegram Override Commands

| Command | Effect |
|---|---|
| `/pause` | Pause reminder notifications |
| `/mute` | Mute all proactive messages |
| `/sleep N` | Sleep for N hours (pause everything) |
| `/resume` | Clear all overrides |
| `/status` | Show scheduler status, job health, queue size |

All state is persisted to `scheduler_state.json` and restored on restart.

---

## 🛠 Setup & Installation

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file in the root directory:

```env
# ── AI Engine ─────────────────────────────────────
GOOGLE_API_KEY=your_google_api_key
GEMINI_API_KEY=your_gemini_api_key
PROJECT_ID=your_gcp_project_id
LOCATION=us-central1

# ── Telegram Bot ───────────────────────────────────
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# ── Gmail (OAuth) ──────────────────────────────────
GMAIL_CREDENTIALS_FILE=credentials.json

# ── Google Places ──────────────────────────────────
GOOGLE_PLACES_API_KEY=your_places_api_key

# ── Optional Integrations ─────────────────────────
SPOTIPY_CLIENT_ID=your_spotify_id
SPOTIPY_CLIENT_SECRET=your_spotify_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
GITHUB_TOKEN=your_github_token
VACUUM_IP=your_vacuum_ip
VACUUM_TOKEN=your_vacuum_token
```

### 3. Run

```bash
# Launcher (recommended)
python main.py
# → Choose: [1] Web Server  [2] Telegram Bot  [3] Both

# Or directly:
python -m clients.telegram_bot      # Telegram Bot
uvicorn api.server:server --reload  # Web UI → http://localhost:8000

# Observability dashboard
open http://localhost:8000/debug/runtime
```

---

## 📜 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

*Built with ❤️ by a Maker, for Makers.*

**[alexneverland](https://github.com/alexneverland)**

</div>

<div align="center">

# 🦞 Astakos AI Agent

**A high-performance, modular, and LLM-agnostic multi-agent framework.**
Built with a *local-first* philosophy — orchestrating specialized AI agents through a graph-based architecture for automation, technical tasks, and persistent memory management.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Gemini](https://img.shields.io/badge/Gemini-3.1_Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-FF6B35?style=for-the-badge)](https://www.trychroma.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

</div>

---

## ✨ Key Features

| Feature | Description |
|---|---|
| 🧠 **Graph-Driven Orchestration** | Uses **LangGraph** for complex state transitions and dynamic agent routing |
| 🤖 **Multi-Agent Intelligence** | A **Supervisor** delegates to specialized sub-agents: Dev, Home, Web, Tech, Git, Mail |
| 💾 **Persistent Hybrid Memory** | SQL Checkpoints + **ChromaDB** vector store for long-term semantic retrieval |
| ⏰ **Proactive Workers** | Background threads for reminders and proactive user engagement ("Pokes") |
| 📡 **Multimodal Interfaces** | **Web UI**, **CLI**, and **Telegram Bot** with native image & voice processing |
| 🏠 **Local-First** | Runs entirely on your machine — your data stays yours |

---

## 🏗 Project Structure

```
astakos/
├── 📁 api/               # FastAPI/Uvicorn Web Server
├── 📁 clients/           # Interface implementations (Telegram Bot)
├── 📁 core/              # The "Brain" — Graph logic, Agents, Prompts
│   ├── brain.py          # LLM initialization
│   ├── agents.py         # Agent nodes & supervisor router
│   └── graph.py          # LangGraph state machine
├── 📁 memory/            # Memory orchestration layer
│   ├── vector_store.py   # ChromaDB long-term memory
│   ├── working_memory.py # Real-time context tracking
│   └── session_memory.py # Session summaries & Memory Sifter
├── 📁 tools/             # Custom toolkits
│   ├── system.py         # Files, GitHub, Email, IoT, Reminders
│   ├── web.py            # News, Weather, Supermarket, Goldmall
│   └── telegram.py       # Telegram messaging
├── 📁 services/          # External API wrappers
│   ├── gemini.py         # Gemini API client
│   └── embeddings.py     # Vertex AI Embeddings + cache
├── config.py             # Central configuration
├── main.py               # CLI Entry Point
└── index.html            # Web Interface
```

---

## 🛠 Setup & Installation

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/alexneverland/astakos.git
cd astakos
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

# ── Optional Integrations ─────────────────────────
SPOTIPY_CLIENT_ID=your_spotify_id
SPOTIPY_CLIENT_SECRET=your_spotify_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
EMAIL_ADDRESS=your_email
EMAIL_PASSWORD=your_app_password
GITHUB_TOKEN=your_github_token
VACUUM_IP=your_vacuum_ip
VACUUM_TOKEN=your_vacuum_token
```

### 3. Run

```bash
# CLI Mode
python main.py

# Web UI  →  http://localhost:8000
uvicorn api.server:server --reload

# Telegram Bot
python clients/telegram_bot.py
```

---

## 🧩 Architecture Overview

```
User Input (CLI / Web / Telegram)
         │
         ▼
    ┌─────────────┐
    │  Supervisor │  ← Routes to the right agent
    └──────┬──────┘
           │
    ┌──────▼────────────────────────────────────┐
    │  Chat · Home · Web · Tech · Git · Mail · Dev │
    └──────┬────────────────────────────────────┘
           │
    ┌──────▼──────┐     ┌─────────────┐
    │  Tool Node  │────▶│  Memory     │
    │  (LangGraph)│     │  (ChromaDB) │
    └─────────────┘     └─────────────┘
```

---

## 📜 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

*Built with ❤️ by a Maker, for Makers.*

**[alexneverland](https://github.com/alexneverland)**

</div>
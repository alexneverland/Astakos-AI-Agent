# Astakos AI Agent 🦞

**Astakos** is a high-performance, modular, and LLM-agnostic multi-agent framework. Built with a "local-first" philosophy, it leverages a graph-based architecture to orchestrate specialized agents for automation, technical tasks, and persistent memory management.

---

## 🚀 Key Features

* **Graph-Driven Orchestration:** Uses \LangGraph\ to manage complex state transitions and agent routing.
* **Multi-Agent Intelligence:** Features a **Supervisor** that delegates tasks to specialized sub-agents (Dev, Home, Web, Tech).
* **Persistent Hybrid Memory:**
    * **SQL Checkpoints:** For session continuity and state recovery.
    * **ChromaDB Vector Store:** For long-term semantic memory and retrieval.
* **Proactive Capabilities:** Integrated workers for reminders and proactive user engagement ("Pokes").
* **Multimodal Communication:** Support for **Web UI**, **CLI**, and **Telegram Bot** with native voice processing.

---

## 🏗 Project Structure

\\\	ext
├── api/             # Flask/Uvicorn Web Server
├── clients/         # Interface implementations (Telegram Bot, etc.)
├── core/            # The "Brain" (Graph logic, Nodes, Prompts)
├── tools/           # Custom Toolkits (Web, System, IoT, Telegram)
├── memory/          # Memory orchestration (Working, Session, Vector)
├── services/        # External API wrappers (Gemini, Embeddings)
├── main.py          # CLI Entry Point
└── index.html       # Web Interface frontend
\\\

---

## 🛠 Setup & Installation

### 1. Configure Profiles
Before running, set up your identity and agent behaviors:
* Copy \stakos_profile.json.example\ to \stakos_profile.json\ and fill in your details.
* Copy \core/prompts.json.example\ to \core/prompts.json\ to customize agent personas.

### 2. Environment Variables (.env)
Create a \.env\ file in the root directory and add your keys:

\\\env
# AI Engine
GEMINI_API_KEY=your_api_key_here
GOOGLE_API_KEY=your_api_key_here

# Telegram Bot
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Optional Integrations (Spotify, Email, IoT)
SPOTIPY_CLIENT_ID=your_spotify_id
SPOTIPY_CLIENT_SECRET=your_spotify_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback
EMAIL_ADDRESS=your_email
EMAIL_PASSWORD=your_app_password
GITHUB_TOKEN=your_github_token
VACUUM_IP=your_vacuum_ip
VACUUM_TOKEN=your_vacuum_token
\\\

### 3. Execution Modes
Run the agent using your preferred interface:

\\\ash
# Start CLI Mode
python main.py

# Start Telegram Bot
python clients/telegram_bot.py

# Start Web Server
python api/server.py
\\\

---

## 📜 License
This project is licensed under the **MIT License**.

---
*Built with ❤️ by a Maker for Makers.*

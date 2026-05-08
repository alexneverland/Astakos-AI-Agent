# Astakos AI Agent 🦞

**Astakos** is a high-performance, modular, and LLM-agnostic multi-agent framework. Built with a "local-first" philosophy, it leverages a graph-based architecture to orchestrate specialized agents for automation, technical tasks, and persistent memory management.

---

## 🚀 Key Features

* **Graph-Driven Orchestration:** Uses `LangGraph` to manage complex state transitions and agent routing.
* **Multi-Agent Intelligence:** Features a **Supervisor** that delegates tasks to specialized sub-agents (Dev, Home, Web, Tech).
* **Persistent Hybrid Memory:**
    * **SQL Checkpoints:** For session continuity and state recovery.
    * **ChromaDB Vector Store:** For long-term semantic memory and retrieval.
* **Proactive Capabilities:** Integrated workers for reminders and proactive user engagement ("Pokes").
* **Multimodal Communication:** Support for **Web UI**, **CLI**, and **Telegram Bot** with native voice processing.

---

## 🏗 Project Structure

```text
├── api/             # Flask/Uvicorn Web Server
├── clients/         # Interface implementations (Telegram Bot, etc.)
├── core/            # The "Brain" (Graph logic, Nodes, Prompts)
├── tools/           # Custom Toolkits (Web, System, IoT, Telegram)
├── memory/          # Memory orchestration (Working, Session, Vector)
├── services/        # External API wrappers (Gemini, Embeddings)
├── main.py          # CLI Entry Point
└── index.html       # Web Interface frontend

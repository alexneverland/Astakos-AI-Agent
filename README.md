Astakos AI Agent 🦞
Astakos is a modular, local-first multi-agent framework designed for high-level automation, persistent memory management, and technical task execution. It uses a graph-based architecture to orchestrate specialized agents.

🚀 Architecture & Features
Graph-Based Brain: Powered by LangGraph and Gemini 3.1 Flash (LLM-agnostic design).

Domain-Specific Agents: Features specialized agents for Development, Home Automation, Web Research, and technical documentation.

Hybrid Memory System: - Working Memory: Context-aware short-term focus.

Session Memory: Persistent SQL-based checkpoints.

Long-term Memory: ChromaDB vector store for semantic retrieval.

Multi-Interface: - CLI: Direct interaction via command line.

Telegram: Full bot integration with voice message processing.

Web UI: Flask-based server for a browser interface.

Proactive Intelligence: Reminder worker and proactive "poke" system based on user interaction patterns.

🏗 Project Structure
core/: The "Engine" — includes LangGraph nodes, brain logic, and agent prompts.

api/: Flask/Uvicorn server for the Web interface.

clients/: Implementation of interfaces (e.g., telegram_bot.py).

tools/: Custom toolkit (Web search, System commands, Telegram tools, IoT/Vacuum control).

memory/: Memory management scripts (Session, Working, and Vector store).

services/: API connectors (Gemini, Embeddings).

🛠 Setup & Installation
1. Configuration
Copy the example files and fill in your details:

Copy astakos_profile.json.example to astakos_profile.json and fill in your identity.

Copy core/prompts.json.example to core/prompts.json to define agent behaviors.

2. Environment Variables (.env)
Create a .env file in the root directory and add the following keys:


# AI Keys
GEMINI_API_KEY=your_gemini_api_key_here
GOOGLE_API_KEY=your_google_api_key_here

# Telegram
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_personal_chat_id_here

# Spotify (Optional)
SPOTIPY_CLIENT_ID=your_id
SPOTIPY_CLIENT_SECRET=your_secret
SPOTIPY_REDIRECT_URI=http://localhost:8888/callback

# System & IoT (Optional)
EMAIL_ADDRESS=your_email
EMAIL_PASSWORD=your_app_password
GITHUB_TOKEN=your_github_token
VACUUM_IP=your_vacuum_ip
VACUUM_TOKEN=your_vacuum_token

3. Run the Agent
Depending on the mode you want:

CLI Mode: python main.py

Telegram Bot: python clients/telegram_bot.py

Web UI: python api/server.py

📜 License
This project is licensed under the MIT License.

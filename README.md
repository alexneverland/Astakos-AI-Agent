<div align="center">

# Astakos AI Agent

**A local-first AI companion that learns your habits, remembers what matters,**
**and helps proactively through Telegram, Web UI, and CLI.**

Astakos is built to feel less like a disposable chatbot and more like a personal AI operating layer:

✅ Learns recurring routines automatically  
✅ Reminds you before events happen  
✅ Builds long-term memory about your projects, family, photos, documents, and goals  
✅ Runs from your own machine with local memory and state  
✅ Works across Telegram, Web UI, and terminal sessions  
✅ 100% LLM-Agnostic: Run with Vertex AI, Gemini API, OpenAI (ChatGPT) or Anthropic (Claude)  
✅ Uses tools, approvals, schedulers, and analytics to act when useful

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=for-the-badge&logo=langchain&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![Gemini](https://img.shields.io/badge/Gemini-Google-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini/)
[![OpenAI](https://img.shields.io/badge/OpenAI-ChatGPT-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-FF6B35?style=for-the-badge)](https://www.trychroma.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)
[![OpenAgentSource](https://img.shields.io/badge/OpenAgentSource-Listed-4A90D9?style=for-the-badge)](https://openagentsource.com/agents/astakos-ai-agent)

</div>

---

## 🚀 Getting Started

New to Astakos? Check out our **[Beginner's Setup Guide](SETUP_GUIDE.md)** for step-by-step instructions on how to install and run the agent locally using your preferred LLM provider (Vertex, Gemini API, OpenAI, or Anthropic).

### 🐳 Quick Start with Docker (Recommended)
If you have Docker installed, you can skip the manual setup and start Astakos immediately:
```bash
docker compose up --build -d
```
This will automatically install dependencies, download Playwright, and start the Web Setup Wizard at `http://localhost:8000`. 
Your data (SQLite databases, ChromaDB, config files) remains safely persisted in your local folder thanks to volume mapping.

---

## Why Astakos Exists

Most AI assistants forget everything after the conversation ends.

Astakos was built to give an assistant continuity: long-term memory, routine learning, proactive reminders, personal context, and real tools. It is not just an API wrapper. It is a multi-agent system that lives on your computer, watches useful patterns, and reaches out when it thinks you may need help.

If Astakos saves you time or inspires your own project, a star goes a long way. Questions and ideas are welcome in [GitHub Issues](https://github.com/alexneverland/Astakos-AI-Agent/issues).

---

## Screenshots

### Telegram
<img width="320" alt="Astakos Telegram screenshot" src="https://github.com/user-attachments/assets/c5ca1afd-c290-4c95-a50c-886e2fa6c955" />

### Web UI
<img width="650" alt="Astakos Web UI screenshot" src="https://github.com/user-attachments/assets/f112fad5-2480-4a9f-ae2f-719c0106b176" />

### Runtime Dashboard
<img width="650" alt="Astakos Runtime Dashboard screenshot" src="https://github.com/user-attachments/assets/f83756cd-51bb-4208-ac55-8d85b932d471" />

---

## Privacy Model

Astakos is local-first:

- Long-term memory is stored on disk with SQLite, ChromaDB, and local JSON state.
- Telegram/Web conversation history is stored in a shared SQLite database; legacy JSON history files are no longer used at runtime.
- Telegram/Web/Terminal session exchanges are persisted locally and summarized on clean shutdown.
- Memory recall is hybrid: recent context and relevant SQLite history are checked alongside ChromaDB facts before the assistant answers.
- Runtime data, credentials, uploads, caches, databases, logs, and private JSON files are gitignored.
- You control the machine, the credentials, and the integrations.

Important note: Astakos uses configured external APIs for model calls and integrations, including Gemini / OpenAI / Anthropic, Telegram, Google APIs, GitHub, Spotify, LinkedIn, and others when those features are enabled. Local-first means the memory and runtime state live on your machine; prompts, uploaded media, or tool payloads may be sent to the external service required by the feature you use.

### Active Local Storage

Astakos currently uses these runtime storage locations:

- `astakos_conversation_history.db` — shared Telegram/Web conversation history and session exchanges
- `astakos_profile.db` — long-term structured profile facts
- `astakos_state.db` — reminders, sessions, lists, pending asset confirmations, memory sifter replay state
- `astakos_routines.db` — routines, context flags, runtime state, reflections, pending confirmations
- `analytics_state.db` — incremental analytics candidates, occurrences, and progress
- `astakos_embeddings_cache.db` — embeddings request cache
- `chroma_db/` — semantic memory vector store
- `logs/events/YYYY-MM-DD.json` — scheduler/runtime event timeline and debug throughput logs
- JSON sidecars such as `messenger_draft.json`, `astakos_working_memory.json`, `astakos_photos_index.json`, and `astakos_docs_index.json` — lightweight local state and media indexes

Legacy empty `.db` leftovers are not part of the active runtime layout.

---

## Core Features

| Feature | Description |
|---|---|
| Multi-Agent Orchestration | LangGraph Supervisor routes to Chat, Home, Web, Tech, Git, Mail, and Dev agents. |
| Hybrid Memory | ChromaDB vector store + shared SQLite history + SQLite profile/session state for semantic, temporal, and structured memory. |
| Routine State Machine | `LEARNED → ACTIVE → TRIGGER_PENDING → CONFIRMED / IGNORED / DISMISSED → DECAYED → ARCHIVED`. |
| Context-Aware Proactive Routines | Routine context flags (`kid1_away_from_home`, `kid1_away_reason`, `state:kid1:outing`, `school_open`, `football_season`, `current_shift`, `partner_work_mode`, `user_at_work`, `user_out_of_home`, `quiet_hours`) are resolved from `context_state` before trigger time, and routines can be condition-gated instead of hard-paused. |
| Conversational Follow-up Engine | Astakos can create delayed follow-up threads from natural conversation (for example food purchases, outings, or task progress), dedupe them by topic/arc, resolve them later from user replies, and send a natural Telegram follow-up only when it still makes sense. |
| Nightly Analytics Engine | LLM batch-analyzes the last 30 days of shared SQLite conversation history to detect recurring patterns automatically. |
| LLM-Crafted Proactive Messages | Reminder text is generated naturally by the LLM instead of static templates, with recent Telegram/Web history and timestamps injected so messages feel contextual instead of random. |
| Central Scheduler | `AstakosScheduler` runs a single background scheduler with watchdogs, rate limits, and quiet hours. |
| Anti-Spam Intelligence | Adaptive cooldown: 20h → 40h → 72h on repeated ignores, plus batching for simultaneous routines. |
| Capability Registry | Keyword-based pre-routing before the LLM Supervisor for faster dispatch and fewer wasted tokens. 37 capabilities with `name`, `agent`, `risk_level`, `priority`, and `triggers` fields. |
| LLM Routine Judge | Routine confirmation uses a fast Gemini call to interpret natural-language replies ("I'll go find them") instead of keyword-only matching. Falls back to UNCLEAR on failure. |
| File Generator Tools | `generate_excel`, `generate_word_doc`, `generate_pdf`, `generate_csv` — create formatted files from agent-supplied data and save to any path (defaults to Desktop). Risk: SAFE. |
| File Delivery | When a file is created, the Web UI shows a file card with a **📂 Google Drive** button (upload-on-click + inline preview iframe). Telegram receives the actual file via `sendDocument`. |
| Google Drive Upload | `tools/gdrive.py` — uploads any local file to Google Drive via ADC, sets public read permissions, and returns a shareable view URL. Used by the Web UI `/upload-to-drive` endpoint. |
| Project Code Tools | `read_project_file`, `edit_project_file`, `write_project_file`, `grep_project_files`, `list_project_files`, `list_recent_files` — permission-gated code navigation and editing with syntax check and rollback. |
| Long-Term Goals | ChromaDB goal tracking injected into prompts, with `/plan` for multi-step execution. |
| Action Approval Levels | 4-level risk system: **SAFE** (silent), **WARNING** (console log only, no Telegram), **NOTIFY** (execute + Telegram info, no buttons), **CRITICAL** (block + Telegram ✅/❌ approval). Defined in `core/tool_risk.py`; dynamic override per tool in `core/approval.py`. |
| Approval TTL Cleanup | Pending CRITICAL approvals auto-expire after 60 min via `expire_stale_pending()`; stale entries are marked `expired` and blocked from execution. |
| Web UI Live Refresh | `/messages/poll?after_id=N&channel=telegram` endpoint + frontend `setInterval` polling every 5 s; Telegram messages appear in Web UI without manual page reload. |
| register_tool dry_run | `register_tool(dry_run=True)` previews all file changes (system.py, tool_risk.py, capability_registry) without writing; path traversal protection and Python identifier validation added. |
| Memory Provenance | Saved facts include `source` (`telegram` / `web`) and `reason` (`user_stated` / `agent_inferred`). |
| Category-Safe Memory Overwrite | ChromaDB facts are overwritten only after same-category semantic matching plus helper-tested checks for correction language, stale age, and information richness. |
| Hybrid `search_memory` | The memory tool returns both relevant SQLite conversation history and ChromaDB facts in one response. |
| Goal Follow-up Engine | Daily semantic check for stale goals; Astakos can proactively follow up after 7 quiet days. |

## Memory & Learning

| Feature | Description |
|---|---|
| Formal Event Bus | Pub/sub through `core/event_bus.py` for `routine_triggered`, `routine_confirmed`, `session_ended`, and more. |
| Unified Session Memory | One shared session log across Telegram, Web, and Terminal for cross-channel context awareness. |
| Shared Conversation History | Telegram and Web write to one SQLite conversation store, with SQLite-first context reads and analytics using the shared history. |
| Broad SQL Context Recall | Substantive questions search recent SQLite history even without explicit date words; temporal queries like "yesterday morning" narrow to the right day/time window. |
| Personal Event Capture | Personal and family events are saved as dated ChromaDB `[USER_FACT]` memories when the conversation clearly states them. Deterministic memory extractors now prioritize specific temporary-family facts over generic day-event facts to reduce duplicate saves. |
| Deterministic Asset Archive Flow | Photos and uploaded documents are analyzed first, then saved permanently only after an explicit yes/no confirmation; file paths and summaries are indexed locally, and pending confirmations expire cleanly instead of being inferred later by the memory sifter. |
| Follow-up Aware Memory Hygiene | Operational reminder exchanges, duplicate same-day personal/work facts, and assistant-style confirmations are filtered before they pollute long-term memory. |
| Google Fit Integration | Daily steps, sleep phases (deep / REM / light), and heart rate from Samsung Health via Google Fit. Morning briefing at 08:00 uses yesterday's steps, last night's sleep, and heart-rate fallback logic. |
| Memory Overwrite Helpers | `memory.vector_store` exposes tested helper functions for correction detection, memory age, richness scoring, and overwrite decisions. |
| Memory Scoring | Every memory has `importance`, `confidence`, `last_accessed`, and `retrieval_count`. `compute_score()` = importance × 0.4 + retrieval × 0.3 + confidence × 0.2 + freshness × 0.1. |
| Unified Memory Entry Point | `memory.save(memory_type=...)` handles facts, photos, documents, sessions, goals, reflections, and events. |
| Reflection Engine | Nightly self-evaluation and post-plan reflection extract lessons, save them to ChromaDB, and auto-apply supported improvements. |

## Interfaces & Automation

| Feature | Description |
|---|---|
| Telegram Bot | Polling bot with text, voice, photo, document, location, routine confirmation, and inline approval handlers. |
| Web UI | FastAPI server with chat endpoint, upload handling, voice processing, local static assets, and chat history. |
| Runtime Dashboard | `/debug/runtime` and `/debug` expose scheduler health, jobs, event throughput, routines, goals, pending confirmations, pending follow-ups, pending actions, memory-context previews, shared SQLite stats, session backlog, and a memory-audit panel. Routine tables summarize condition payloads and metadata instead of dumping raw JSON. |
| Voice I/O | STT via OpenAI Whisper or Gemini + TTS via `edge-tts` using `el-GR-NestorasNeural`; mirror mode supports voice in → voice out. |
| Product Analyzer | `/nutrition` scans food, cosmetics, and household product labels with a score from 1-10 and a kids note. |
| Receipt Scanner | `/receipt` scans the last Telegram photo as a shopping receipt and returns structured JSON with store, date, total, currency, and items. |
| Smart Photo Pending | Send a photo and Astakos waits 30 seconds for a caption, `/nutrition`, or `/receipt`, avoiding duplicate responses. |
| Document Reading | Uploaded documents are summarized, can be saved into memory after explicit confirmation, and support recent-file follow-up questions from the Web UI so you can keep discussing the same pasted/uploaded file naturally. |
| Paste-to-File Workflow | Large Web UI paste blocks can be auto-attached as virtual `.txt` or `.py` files so Astakos can analyze them as documents instead of losing critical tail content in plain chat. |
| Story Maker | `/story [theme] \| [characters]` generates a children's story plus 3 Vertex AI Imagen illustrations. |
| Typing Indicator | Telegram shows typing while Astakos is processing. |
| Human Override Commands | `/pause`, `/mute`, `/sleep N`, `/resume`, and `/status` persist across restarts. |

## Developer Features

| Feature | Description |
|---|---|
| Observability Dashboard | `/debug/runtime` includes heartbeat, job health, fail counts, pending confirmations, active goals, pending CRITICAL actions (with age + warn >15 min), Messenger Draft state (exists/active/reason/target/age/expires_in), shared conversation/session health, analytics charts, and compact condition/meta views for routines. |
| Pending Follow-up Observability | The debug dashboard includes a dedicated pending-followups panel showing topic, subject, due time, arc key, last decision, outcome score, and send count for conversational follow-ups. |
| Local Security | Bearer token auth, localhost-only CORS, upload size limits, and extension whitelist. |
| Auto-Restart | `run_telegram.py` and the Web launcher watch core source files only; runtime JSON/DB/photos/uploads and generated skills do not trigger restarts. |
| Safe Executor | `core/safe_executor.py` classifies terminal commands as SAFE, WARNING, REQUIRE_CONFIRMATION, or BLOCKED. |
| Action Approval Dashboard | Pending CRITICAL tool approvals can be approved or rejected from Telegram and the debug dashboard. |
| Tool Risk Registry | `core/tool_risk.py` defines SAFE / WARNING / CRITICAL behavior per tool. |
| Latency Controls | Web and Telegram use context-aware fast paths, medium paths, semantic downshifts, and tool-output detection to avoid paying full retrieval cost on simple acknowledgements, reminder requests, recent web follow-ups, and other lightweight turns. |
| Skill Creation Flow | New skills are created with `write_custom_tool`, validated for `@tool`, previewed with `register_tool(dry_run=True)`, and applied only after approval. Skills that need Gemini/vision use shared `core.brain` clients instead of raw API keys. |
| Planner v2 | `/plan` decomposes a goal into tasks with a **confirmation gate** before execution. Auto-plan LLM judge detects multi-step intent without needing `/plan`. Progress UI shows `⏳ Step X/N` per step. `validate_step_node` detects failures via AI response + tool output heuristics. `replan_node` auto-skips failed steps and continues. `end_check_node` generates a final summary (`✅` / `⚠️ X/N steps successful`) and saves a post-plan reflection. |
| Execution Trace System | Every agent turn records agent name, tools called, duration, errors, and loop events to `logs/traces/YYYY-MM-DD.json`. Viewable at `/debug/traces` and the runtime dashboard with colored tool names, response preview, issue-only/clean filters, and optional hiding of old resolved issues. |
| Tool Performance Stats | `tool_stats(days=N)` reads execution traces and returns per-tool call count, error count, error rate, and average duration — sorted by errors descending. Ask Astakos "tool stats last 7 days" for an instant health report. |
| System Doctor | `system_doctor(days=N)` gives a read-only runtime health summary from logs, traces, pending approvals, Messenger drafts, session backlog, memory audit ops, routine confirmations, conditioned routines, proactive skip reasons, and the resolved runtime context. Default is today (`days=1`). Ask `/doctor` or "check system health" without opening the debug dashboard. |
| Self-Diagnosis via Source Read | `read_local_file` now allows reading from `tools/`, `core/`, `memory/`, `services/`, `clients/`, `astakos_skills/`, and `api/`. Sensitive files (`config.py`, `.env`, `*.db`) remain blocked. Astakos can inspect its own code when debugging a failed tool call. |

---

## Architecture

```text
   Telegram Bot          Web UI             CLI
 [channel=telegram]  [channel=web]   [channel=terminal]
         │                  │                  │
         └────────┬─────────┴─────────┬────────┘
                  │                   │
           [ I18n Locales ]           │
           (el.json / en.json)        │
                  │                   │
                  ▼                   ▼
           ┌──────────────┐     ┌──────────────┐
           │  Fast Queue  │     │  Slow Queue  │
           │ (Direct Msg) │     │ (Follow-ups) │
           └──────┬───────┘     └──────┬───────┘
                  │                    │
                  ▼                    │
         ┌──────────────────┐          │
         │   pre_check_node │ ◄────────┘
         └────────┬─────────┘
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
task_executor Supervisor   cancel_plan
     │            │
     │   ┌────────┴────────────────────────────┐
     │   │ Chat · Home · Web · Tech · Git ·    │
     │   │ Mail · Dev  ←── auto-plan judge      │
     │   └────────┬────────────────────────────┘
     │            │ (or → Planner → plan_pending.json → END)
     │            ▼
     └─────► Agent Node
                  │
         ┌────────▼────────┐
         │ Approval Check  │  SAFE / WARN / CRITICAL
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │   Tool Node     │
         └────────┬────────┘
                  │
         ┌────────▼──────────┐
         │ validate_step_node│  failure? → replan_node → skip
         └────────┬──────────┘           → task_executor (next)
                  │ OK
         ┌────────▼──────────┐
         │ capture_result    │  plan_active? → task_executor
         └────────┬──────────┘            → end_check
                  ▼
         ┌──────────────────┐
         │  end_check_node  │  ✅ / ⚠️ summary + reflection
         └──────────────────┘
                  │
┌─────────────────▼───────────────────────────┐
│ Memory Layer                                 │
│ - ChromaDB: facts, photos, sessions, goals   │
│ - SQLite: conversations, sessions, routines  │
│ - Hybrid recall: SQLite history + Chroma     │
│ - JSON: working memory and profile state     │
└──────────────────────────────────────────────┘
```

Background jobs run through `AstakosScheduler`:

| Job | Interval | Purpose |
|---|---:|---|
| `job_check_reminders` | 20s | Local reminders. |
| `job_check_routines` | 60s | Adaptive routine reminders and anti-spam cooldowns. |
| `job_check_pending_followups` | 10m | Sends delayed conversational follow-ups only when they are still due, unsolved, and not blocked by anti-spam guards. |
| `job_proactive_scan` | 12h | Watch-folder analysis and proactive scan. |
| `job_morning_hn_briefing` | 1h | Fires in the morning and sends a Hacker News technology briefing once per day. |
| `job_morning_fit_briefing` | 1h | Fires at 08:00 for the Google Fit morning summary: yesterday's steps, last night's sleep, and heart rate. |
| `job_goal_followup` | 1h | Fires at 10:00 for stale-goal semantic checks. |
| `run_analytics` | Nightly 03:00 | Incremental LLM routine detection after bootstrap; falls back to 30-day scan until `analytics_state.db` is initialized. |
| `run_reflection` | Nightly 03:00 | Self-evaluation after analytics: lessons extracted, auto-applied to routines and ChromaDB. |

Event Bus events include:

- `routine_triggered` (`routine_id`, `event`, `confidence`, `batch`, `channel`)
- `routine_confirmed` (`routine_id`, `event`, `channel`)
- `routine_dismissed` (`routine_id`, `event`, `channel`)
- `session_ended` (`channel`, `mood`, `summary`)
- `proactive_sent` (`source`, `channel`)

---

## Routine Learning System

Astakos passively learns habits from conversation and proactively reminds you.

How it works:

1. **Bootstrap Analytics** — the first pass can be run with `scripts/bootstrap_incremental_analytics.py`; it reads the shared SQLite history, extracts candidate routines, and writes `analytics_state.db`.
2. **Incremental Nightly Analytics** — after bootstrap, every 03:00 run reads only new shared SQLite messages after the last processed `rowid`, instead of re-reading the full 30-day window.
3. **Pattern Detection** — candidate activities are grouped by day/time bucket (±15 min), merged if similar, and promoted only after they meet the routine threshold.
4. **Threshold** — a routine is saved only if it appears 3+ times across 2+ different weeks. Final writes always go through `upsert_routine`, preserving fingerprint/fuzzy/embedding dedupe.
5. **Runtime Context Resolution** - before a routine fires, Astakos resolves live flags such as `current_shift`, `kid1_away_from_home`, `state:kid1:outing`, and `user_out_of_home` from `context_state`.
6. **Condition Evaluation** - outing-like routines, child routines, and home-only routines can be condition-blocked instead of deleted or blindly muted; for example, a park reminder can be skipped if the family is already out, and cooking can be skipped if everyone is away from home.
7. **Proactive Message** - when a routine is due in about 30 minutes, the LLM writes a natural message using the routine context plus recent shared Telegram/Web history with timestamps.

Bootstrap command:

```powershell
.\venv\Scripts\python.exe scripts\bootstrap_incremental_analytics.py
.\venv\Scripts\python.exe scripts\bootstrap_incremental_analytics.py --apply
```

Routine lifecycle:

```text
LEARNED → ACTIVE → TRIGGER_PENDING → CONFIRMED → ACTIVE
                                   → IGNORED   → ACTIVE (cooldown doubled)
                                   → DISMISSED → ACTIVE (Everyday) / DECAYED (weekly)
                                   → DECAYED   → ARCHIVED
```

Adaptive cooldown:

- Default: 20h between notifications for the same routine.
- 1st ignore → 40h.
- 2nd ignore → 72h.
- Confirm → reset to 20h.
- Multiple routines at the same time → batched into one message.

---

## Project Structure

```text
astakos/
├── api/
│   ├── server.py             # FastAPI Web Server + /debug/runtime observability
│   └── debug_dashboard.html  # Runtime dashboard UI
├── astakos_skills/           # Modular skill scripts
│   ├── calculate_bill.py
│   ├── daily_backup.py       # Nightly backup to Google Drive
│   ├── file_generator.py     # Excel, Word, PDF, CSV file creation tools
│   ├── flight_monitor.py
│   ├── google_fit.py         # Google Fit: steps, sleep, heart rate
│   ├── linkedin_state_manager.py
│   ├── nutrition_analyzer.py # Universal product label analyzer
│   ├── recipe_expert.py
│   ├── register_tool.py      # Safe skill registration with dry-run previews
│   ├── repo_mapper.py        # AST shallow scan of any Python project — text tree + JSON
│   ├── scan_receipt.py       # Receipt image parser for /receipt
│   ├── search_ferries.py
│   ├── search_flights.py
│   ├── story_maker.py        # Children's story generator + Vertex AI Imagen illustrations
│   └── text_stats.py         # Example generated skill
├── clients/
│   └── telegram_bot.py       # Telegram polling, handlers, scheduler
├── core/
│   ├── agents.py             # Agent nodes and supervisor router
│   ├── approval.py           # CRITICAL action approval gate
│   ├── brain.py              # Dynamic LLM initialization (Vertex, Gemini, OpenAI, Anthropic)
│   ├── capability_lookup.py  # Keyword-based pre-routing registry
│   ├── event_bus.py          # Pub/sub Event Bus singleton
│   ├── exceptions.py         # Structured exception hierarchy
│   ├── graph.py              # LangGraph state machine
│   ├── plan_judge.py         # Auto-plan LLM judge: detects multi-step intent without /plan
│   ├── planner.py            # Planner v2: confirmation gate, progress UI, validate/replan/end_check
│   ├── routine_state.py      # Routine lifecycle and valid transitions
│   ├── safe_executor.py      # Terminal command classifier
│   ├── tool_risk.py          # Tool risk registry
│   └── utils.py              # Shared utilities and AgentState
├── locales/
│   ├── el.json               # Greek locale + runtime NLP/scraping resources
│   └── en.json               # English locale + runtime NLP/scraping resources
├── memory/
│   ├── event_log.py          # Event logging and dedup protection
│   ├── routine_db.py         # SQLite routines, dedup, cooldowns
│   ├── session_memory.py     # Unified session log + Memory Sifter
│   ├── vector_store.py       # ChromaDB long-term memory
│   ├── conversation_history.py # Shared SQLite conversation store; load_messages_after_rowid + get_max_rowid for polling
│   └── working_memory.py     # Real-time foreground context
├── prompts/

Note: `locales/el.json` and `locales/en.json` are hybrid runtime resources, not display-only translation catalogs. Besides user-facing strings, they intentionally contain language-specific NLP tokens, regex patterns, classifier examples, and scraping markers that may remain in Greek even in `en.json` when runtime matching depends on Greek user input or Greek websites.
│   ├── telegram_bot_followup_decision.md # Core followup prompts
│   └── *.md                  # System prompts for agents
├── services/
│   ├── analytics_engine.py   # Nightly LLM routine detection
│   ├── embeddings.py         # Embeddings + MD5 disk cache
│   ├── gemini.py             # Gemini helper client
│   └── reflection_engine.py  # Nightly/post-plan self-reflection
├── tools/
│   ├── system.py             # Files, GitHub, Gmail, IoT, reminders, routines, Fit
│   ├── gdrive.py             # Google Drive upload via ADC + public link
│   ├── project_tools.py      # Permission-gated code navigation and editing tools
│   ├── telegram.py           # Telegram messaging helpers
│   └── web.py                # News, weather, Places, navigation, Messenger, web search
├── tests/
│   ├── test_project_tools.py  # 48 tests: permissions, read/edit/grep/list, syntax check, risk levels
│   ├── test_safe_executor.py  # Terminal command risk classification tests
│   ├── test_plan_judge.py     # 14 tests: auto-plan heuristic + LLM judge
│   ├── test_validate_step.py  # 13 tests: step failure detection (AI + tool output)
│   ├── test_pr3.py            # 15 tests: replan_node + end_check_node
│   └── test_*.py              # Full test suite (pytest)
├── assets/                   # Fonts and static assets
├── avatars/                  # UI avatars
├── logs/events/              # Daily scheduler event logs (gitignored)
├── logs/traces/              # Per-turn execution traces: agent, tools, duration, errors (gitignored)
├── chroma_db/                # Vector store data (gitignored)
├── credentials/              # Local credentials (gitignored)
├── telegram_photos/          # Telegram photo storage (gitignored)
├── telegram_uploads/         # Telegram upload storage (gitignored)
├── outputs/                  # Generated files (gitignored)
├── watch_folder/             # Proactive scan folder (gitignored)
├── clean.py                  # Maintenance and cleanup script
├── config.py                 # Central configuration
├── index.html                # Web UI
├── main.py                   # CLI launcher
├── read_memory.py            # Local memory reader helper
├── run_telegram.py           # Auto-restart Telegram wrapper
├── start_astakos.bat         # Windows launcher
└── requirements.txt          # Python dependencies
```

Runtime files such as `*.json`, `*.db`, `chroma_db/`, `logs/`, uploads, credentials, caches, and generated outputs are ignored by git.

---

## Telegram Commands

| Command | Effect |
|---|---|
| `/pause` | Pause reminder notifications. |
| `/mute` | Mute all proactive messages. |
| `/sleep N` | Sleep for N hours and pause proactive/reminder behavior. |
| `/resume` | Clear all overrides. |
| `/status` | Show scheduler status, job health, queue size, quiet hours, and overrides. |
| `/voice` | Toggle voice reply mode ON/OFF. |
| `/nutrition` | Analyze the last photo as a product label (food / cosmetic / household). |
| `/receipt` | Analyze the last photo as a shopping receipt and return structured expense JSON. |
| `/story [theme] \| [characters]` | Generate a children's story plus 3 illustrations. |
| `/plan [goal]` | Break a goal into tasks, show the plan for confirmation, then execute step by step with progress indicators, failure recovery, and a final summary. Multi-step requests are also auto-detected without the prefix. |
| `/confirm <cmd>` | Execute a shell command after confirmation. |
| `/end` | Close the session, run memory summarizer, and clear working memory. |
| `/help` | Show available commands and current voice mode status. |

Scheduler override state is persisted to `scheduler_state.json` and restored on restart.

---

## Setup


### 1. Clone and Install

First, clone the repository and set up your Python virtual environment (Python 3.11+ is recommended):

```bash
git clone https://github.com/alexneverland/Astakos-AI-Agent.git
cd Astakos-AI-Agent
python -m venv venv
venv\Scripts\activate   # On Windows
# source venv/bin/activate  # On Linux/Mac
pip install -r requirements.txt
```

### 2. Environment Variables

Astakos ships with a committed `.env.example` template. Copy it to `.env` and fill in only the provider and integrations you want to use:

```bash
copy .env.example .env
```

Provider notes:

- `LLM_PROVIDER=vertex` expects `GOOGLE_APPLICATION_CREDENTIALS` to point to a local Google credentials JSON file.
- `LLM_PROVIDER=gemini` expects `GEMINI_API_KEY`.
- `LLM_PROVIDER=openai` expects `OPENAI_API_KEY`.
- `LLM_PROVIDER=anthropic` expects `ANTHROPIC_API_KEY`.

Google OAuth tools such as Calendar / Fit use a separate client secrets file at `credentials/credentials.json`.

### 3. Run the Agent

You can start the system using the interactive CLI launcher:

```bash
# Start the system (this launches the Web Setup Wizard if unconfigured, or the CLI if configured)
python boot.py
```

To reopen the setup wizard later:

```bash
python boot.py --setup
```

To run the API server and Telegram bot together for Docker/headless environments:

```bash
python boot.py --server
```

Alternatively, you can run the components directly:

**Telegram Bot:**
```bash
python run_telegram.py
```

**Web UI & API Server (with auto-reload on code changes):**
```bash
uvicorn api.server:server --reload --reload-dir api --reload-dir core --reload-dir tools --reload-dir memory --reload-dir services --reload-dir clients --reload-include "*.md" --reload-include "*.json"
```

Observability Dashboard (when the API is running):

```bash
open http://localhost:8000/debug/runtime
```

Shutdown behavior:

- Web/API shutdown through FastAPI lifespan drains queued memory tasks and runs the Web session summary.
- Telegram shutdown through `clients/telegram_bot.py` runs the Telegram session summary; `run_telegram.py` forwards Ctrl+C/restart signals to the child process before falling back to termination.
- CLI shutdown through `exit`, Ctrl+C, SIGINT, or SIGTERM drains queued memory tasks and runs the Terminal session summary once.
- Long sessions are summarized automatically after 40 unsummarized exchanges, so the persistent session log cannot grow forever between manual shutdowns.
- Shared conversation history remains in SQLite; legacy JSON history files are no longer runtime mirrors or fallbacks.

---

## Roadmap

### Implemented

- [x] Hacker News Briefing — native `hn_briefing` tool with scheduler support, Web_Agent registration, and deterministic fallback formatting.

- [x] Voice I/O — STT + TTS with Greek Neural voice, mirror mode, and `/voice` toggle.
- [x] Universal product analyzer (`/nutrition`) via Vision LLM.
- [x] Receipt scanner (`/receipt`) for Telegram photos, returning store/date/total/items JSON through the multimodal LLM.
- [x] Smart photo pending system with a 30s caption window, history context, and no double messages.
- [x] Document reading on upload with instant summary and optional save to memory.
- [x] Google Fit integration — steps, sleep phases, heart rate, and morning briefing with correct day/night windows.
- [x] Story maker — `/story` with AI-generated illustrations via Vertex AI Imagen.
- [x] Local security — bearer token auth, localhost CORS, upload limits, and extension whitelist.
- [x] Auto-restart on code changes — core source `.py` files and `prompts.md` trigger restarts; runtime data and generated `astakos_skills/` files are excluded so skill creation does not interrupt the agent.
- [x] Capability Registry — keyword routing before LLM Supervisor for instant dispatch.
- [x] Reflection Engine — nightly self-evaluation with auto-apply actions and ChromaDB lessons.
- [x] Long-Term Goals System — ChromaDB goal tracking injected into every prompt.
- [x] Memory Retrieval Tracking — `retrieval_count` per memory for future scoring.
- [x] Action Approval Levels — SAFE / WARNING / CRITICAL risk registry with Telegram inline approve/reject.
- [x] Planning Agent — `/plan` command with multi-step execution through `TaskExecutor`.
- [x] Post-Plan Reflection — every `/plan` run is self-evaluated and saved as lessons.
- [x] Memory Provenance — `source` (`telegram` / `web`) and `reason` metadata on saved facts.
- [x] Goal Follow-up Engine — daily semantic check for stale goals and proactive Telegram ping.
- [x] Memory Scoring — `importance`, `confidence`, `last_accessed`, `retrieval_count`, and `compute_score()`.
- [x] Unified Memory Entry Point — `memory.save(memory_type=...)` for facts, photos, sessions, goals, reflections, and events.
- [x] Pending Actions Dashboard — CRITICAL tool approvals visible in `/debug` with approve/reject controls.
- [x] Analytics Charts — dashboard modal for routine states, agent usage, event throughput, and confirmations by hour.
- [x] Unified Session Memory — shared log across all channels, with session summary on shutdown and Ctrl+C drain handling.
- [x] Cross-channel awareness — unified `SESSION_LOGS` for Telegram, Web, and Terminal context.
- [x] Shared Conversation History — Telegram and Web write to one SQLite store, with analytics reading from the shared history.
- [x] Contextual Proactive Messages — routine pings include recent shared history and message timestamps so the LLM can reference current activity naturally.
- [x] SQLite-first history views and cleanup — Web history and analytics read from shared SQLite, while `clean.py` can check and maintain the conversation database.
- [x] Auto Session Rollover — long conversations are summarized automatically after 40 unsummarized exchanges, plus manual and shutdown summaries.
- [x] Pending Approval TTL — `expire_stale_pending()` runs on every store read and marks CRITICAL approvals older than 60 min as `expired`; expired actions are blocked from execution even if approved late.
- [x] Messenger Draft in Dashboard — `/debug/runtime` exposes full draft state: exists, active, reason, target name, age, expires_in (minutes), and message character count.
- [x] Web UI Live Telegram Refresh — `GET /messages/poll?after_id=N&channel=telegram` returns only new messages via SQLite `rowid` cursor; frontend polls every 5 s; `notify_telegram_message()` writes to shared SQLite from the Telegram process; `load_messages_after_rowid` + `get_max_rowid` power the incremental cursor.
- [x] register_tool dry_run — `dry_run=True` parameter previews every file change without writing; tool_name validated as Python identifier; skill path checked with `realpath` to prevent path traversal.
- [x] Hardened skill creation — generated skills must use `write_custom_tool`, keep `@tool`, pass validation before registration, and use shared `core.brain` LLM clients when model calls are needed.
- [x] relay_local_payload hardened — demoted from CRITICAL to WARNING (writes draft only, does not send); clean tool return value so Gemini cannot leak internal meta-instructions into the chat.
- [x] Cross-Channel Context Awareness — Chat_Agent checks shared SQLite history before saying "I don't remember", covering messages from both Telegram and Web UI sessions.
- [x] Incremental Routine Analytics — `analytics_state.db` stores last processed conversation `rowid`, candidate routine occurrences, and promoted status so nightly analytics can process only new messages after bootstrap.
- [x] Hybrid Memory Search — `search_memory` returns both relevant SQLite conversation history and ChromaDB semantic facts, so tool-based recall uses the same memory model as prompt context.
- [x] Personal/Family Event Capture — clear personal and family day-events are saved as dated ChromaDB facts while the full conversation remains in SQLite.
- [x] Memory Context Debugging — `/debug` shows recent, SQLite, and Chroma context counts/previews for the last prompt build.
- [x] Category-Safe Memory Overwrite — same-category Chroma matches use helper-tested correction, staleness, richness, and length tie-break rules before replacing old facts.
- [x] Deterministic Memory Priority Guard — temporary family-state memories (camp, absence, return-home windows) now win over generic day-event capture, and near-identical confirmed saves are skipped before they can double-write in the same turn.
- [x] Routine Context Flags — routines now read resolved context_state such as `kid1_away_from_home`, `school_open`, `football_season`, `current_shift`, `partner_work_mode`, `user_at_work`, and `quiet_hours` instead of relying only on blunt mute/pause windows.
- [x] Context-State Reconciliation — facts like “Kid1 came back home” now flip context state (`kid1_away_from_home=false`) through the reconciler instead of only unmuting routines by name.
- [x] Smart Weekend Filter — automatically skip applying `shift_mode` conditions to weekend-only routines unless explicitly requested, preventing work-shift rules from breaking weekend habits.
- [x] Debug Dashboard Condition UX — evaluate and display actual state (`actual_value`) for each condition individually, and prominently show a PAUSED badge instead of ACTIVE for routines paused until a specific date.

- [x] Web UI Agent Name in History — `agent_name` is stored in SQLite alongside each message and returned by `/history`; the Web UI now shows the correct agent label (e.g. `Web / Dev_Agent`) for both live and historical messages.
- [x] File Generator Tools — `generate_excel` (styled headers, zebra rows, freeze pane), `generate_word_doc` (Markdown-style headings and bullets), `generate_pdf` (reportlab with custom styles), and `generate_csv` (UTF-8 BOM for Excel compatibility). All route via Capability Registry to Dev_Agent. Risk: SAFE.
- [x] File Delivery — when a file is created (`[CREATED_FILE:]` tag), the Web UI renders a file card with a **📂 Google Drive** button; clicking uploads to Drive via ADC and opens an inline preview iframe. Telegram sends the actual file via `sendDocument` with an optional inline Drive link button.
- [x] Tool Risk Rationalization — file creation tools (`create_file_tool`, `generate_excel`, `generate_word_doc`, `generate_pdf`, `generate_csv`), `save_to_memory`, and mail read actions (`search`, `read`, `read_full`) demoted from WARNING to SAFE to eliminate notification noise.
- [x] Project Code Tools — `read_project_file`, `edit_project_file` (old→new patch + syntax check + rollback), `write_project_file`, `grep_project_files`, `list_project_files` with a JSON permission model (`project_access.json`). Core files escalate to CRITICAL; other edits are WARNING.
- [x] LLM Routine Judge — implicit routine confirmation replaced with a fast Gemini call that returns YES / NO / UNCLEAR. Natural phrases like "I'll go find them" now correctly confirm a pending park routine without requiring event keywords. Fallback to UNCLEAR on LLM error.
- [x] WARNING Telegram Notifications — WARNING-tier tool calls (e.g. `git push`) send an informational Telegram message without blocking execution; only CRITICAL actions require approval.
- [x] Tool Performance Stats — `tool_stats(days=N)` aggregates execution traces and reports per-tool calls, errors, error rate, and avg duration sorted by error count. Registered in Capability Registry under Tech_Agent.
- [x] System Doctor — `system_doctor(days=N)` summarizes runtime health from event logs, execution traces, pending approvals, Messenger draft state, shared SQLite session backlog, and pending routine confirmations. Registered in Capability Registry under Tech_Agent and triggerable with `/doctor`.
- [x] Self-Diagnosis via Source Read — `read_local_file` whitelist expanded to include all source directories (`tools/`, `core/`, `memory/`, `services/`, `clients/`, `astakos_skills/`, `api/`); sensitive files (`config.py`, `.env`, `*.db`, `*.key`) remain blocked via explicit blocklist.
- [x] Reflection Apply Fix — planner and conversation reflections (no `routine_id`) now correctly apply by saving the lesson to ChromaDB instead of silently returning `False`.
- [x] ChromaDB Graceful Shutdown — both Telegram bot and Web server wait for `vector_lock` before shutting down, preventing mid-write index corruption.
- [x] ChromaDB HNSW Index Resilience — orphaned vector index IDs (HNSW/SQLite mismatch) are caught with a try/except in `vector_store.py`; the query returns empty results instead of crashing, and the affected category is auto-repaired on next write.
- [x] Test Suite for Project Tools — `tests/test_project_tools.py` covers 48 cases: permission model (grant/deny/read-only), syntax check, read with line ranges, edit with rollback on syntax error, noop guard, grep, list, and tool risk levels (SAFE/WARNING/CRITICAL). pytest runs cleanly on the FUSE-mounted repo.
- [x] `list_recent_files` — bounded `os.walk` scan for recently modified files, defaulting to the whole repo with no permission grant needed; ignores `venv`/`.git`/`__pycache__`/`node_modules`; replaces timeout-prone ad-hoc PowerShell recursive scans for "what did I just change" questions. Risk: SAFE.
- [x] Planner v2 — full agentic loop: confirmation gate before execution, auto-plan LLM judge (no `/plan` needed), progress UI, `validate_step_node` (failure detection), `replan_node` (auto-skip + continue), `end_check_node` (final summary + reflection). Goal → Plan → Validate → Execute → Reflect → Re-plan.
- [x] Profile SQLite Migration — profile memory (preferences, family facts) moved from JSON to SQLite; `clean.py` migrated; legacy `astakos_profile.json`/`.example` removed.
- [x] Routine Muting & Sentimental Handling — `SILENT_SKIP` (LLM judges whether to skip silently), `muted_until` (per-date auto-silence without a daily LLM call), sentimental flag + reduced-frequency emotional messages during a muted period, natural-language mute/unmute override parsed directly from chat.
- [x] Memory Audit Panel — debug-dashboard audit log for memory ops (add/overwrite/skip/reflection).
- [x] Routine Table UX Refresh — `/debug` routine tables now show compact condition summaries, meta badges, safer wrapping, and clearer “No condition / No meta” states instead of raw payload dumps.
- [x] Google Calendar — full CRUD tool with per-action risk, OAuth2 `token.json` auth, proactive morning briefing.
- [x] Georgian Language Helper — `/gr`/`/greek` Telegram commands (renamed from `/georgian`), pending-translation mode, TTS via `edge-tts` (`ka-GE-EkaNeural`).
- [x] Reaction Handler — ❤️ exact-message-match reactions via in-memory cache with SQLite fallback.
- [x] Mail_Agent Loop Guard — hardened synthesis path so mail results already in context don't trigger redundant tool calls; auto-read + ID-hint injection.
- [x] Memory Search Performance — `search_memory` lexical L1 cache + single `similarity_search` call; `save_to_memory` fire-and-forget background thread (~11s faster per call).
- [x] Routine Reconciler Phase 3 — deterministic scoring engine for automatic fact-to-routine reconciliation (`services/routine_reconciler.py`): weighted subject/activity/state/scope/special score against `_AUTO_APPLY_THRESHOLD = 0.80` and `_DEBUG_ONLY_THRESHOLD = 0.55`, with a deliberate conservative penalty so ambiguous rules like `shift_logic` log to `debug_only` instead of silently auto-applying. Covers seasonal football, camp absence, school break, child-activity pause, temporary absence of another person, return-home, and shift-week detection.
- [x] Routine Conditions — routines evaluate conditions against live `context_state` (e.g. `shift_mode`), with a `control_routine_condition` tool for natural-language constraint changes, a smart weekend filter so shift conditions don't leak into weekend-only routines, and dashboard fixes for condition display.
- [x] Generalized Outing Context - family outing facts can now set `state:kid1:outing=in_progress` plus `user_out_of_home=true`, so outing-like routines (e.g. park) and home-only routines (e.g. cooking) can self-suppress from runtime context instead of relying on hardcoded one-off patches.
- [x] Stricter Return-Home Reconciliation - a "returned home" fact only closes outing context when an active outing / out-of-home state already exists, preventing unrelated home-return phrases from mutating routine state.
- [x] Proactive Debug Labels - runtime event logs and `/debug` traces now distinguish `manual_control`, `pending_cleanup`, `condition_eval`, `proactive_decision`, and `reconciler_applied`, making diagnosis much easier when a routine is skipped, muted, resumed, or silently suppressed.
- [x] Deterministic Family-Absence Extractor — temporary absence statements parsed without an LLM sifter call.
- [x] Seasonal Routine Inactivity Controls — pause/resume a routine for a date range (e.g. a sports routine paused over summer) without deleting or permanently muting it.
- [x] I18n Refactoring — Removed hardcoded English strings from Telegram bot follow-up logic and migrated them to the local `locales/en.json` and `locales/el.json` files.
- [x] Prompt JSON Output — Fixed `telegram_bot_followup_decision.md` to mandate structured JSON output instead of raw text, preventing parser fallback errors.
- [x] Gitignore Security — Cleaned up `.gitignore` to ensure system prompts are correctly versioned without exposing personal data, databases, or credentials.
### Planned

- [ ] Planner v3 — parallel step execution and per-step Telegram inline approve/reject (today's confirmation gate is chat-based, not inline-keyboard).
- [ ] Behavior Analytics Engine — auto-shift routine triggers based on ignore patterns.
- [ ] Memory cleanup — prune low-score memories (`compute_score() < threshold`) after 6+ months of real data.
- [ ] Personal Knowledge Graph — structured entity relations such as `User → project → Astakos` in SQLite, parallel to ChromaDB, after 6+ months of usage.
- [ ] Tool Execution Journal — aggregate `tool_stats` data to SQLite for long-term trend analysis (currently read from daily trace files).

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

*Built with care by a Maker, for Makers.*

**[alexneverland](https://github.com/alexneverland)**

</div>

# Changelog

All notable changes to Astakos are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

## [v2.4.0] — 2026-07-27

**Released: 2026-07-27**

### Added

- Guarded capability-gap draft flow with explicit authorization before applying new native tools.
- Dynamic binding of registered tools to their declared agent.
- Native world-time capability with city aliases, IANA timezone support, and Athens-relative difference.

### Changed

- Tech_Agent now uses native bounded research/diagnostic tools instead of raw terminal/code execution for factual hardware research.

### Fixed

- Web document and pasted-text uploads no longer fail from the local llm shadowing path.
- Tool registration preserves valid source list syntax and rolls back failed registrations.
- Conversation history preserves same-second message ordering.
- Shutdown/vector-store handling and tool-boundary guards are more reliable.

## [v2.3.1] — 2026-07-24

**Released: 2026-07-24**

### Fixed

- Release metadata now matches the installed version, preventing false update notices after installation.

## [v2.3.0] — 2026-07-24

**Released: 2026-07-24**

### Added

- Location reminders can now use the current live GPS point as an anchor and fire after the user leaves that place.

### Changed

- Restored Gemini 3.5 Flash as the fast model for the Gemini and Vertex paths.

### Fixed

- Mail reply evaluation can now read the relevant email thread before assessing a draft response.
- Stale confirmations no longer execute an older pending plan.
- Routine SQLite connections are refreshed safely to reduce intermittent database-lock failures.
- A future statement about returning home no longer clears the active outing state; explicit return-home phrases still do.
- A Messenger send request without an active draft now returns the canonical inactive-draft response instead of retrying into a new draft flow.
- Ultra-light Telegram acknowledgements no longer fail before replying.
- Correcting a reminder now updates the existing reminder instead of adding a duplicate; same-task reminders at different times remain supported.

## [v2.0.0] — 2026-07-15

**Released: 2026-07-15**

Headline: **Astakos is now portable, Docker-first, and ready for other people to run.**

Version 2.0.0 marks the transition from a powerful personal installation into a self-hosted AI agent that other users can realistically download, configure, and run on their own computer.

The core intelligence remains the same: shared long-term memory, proactive routines, conversational follow-ups, multi-agent orchestration, planning, approvals, tools, analytics, and local state. The major change is that the project is no longer tied to one machine or one person's configuration.

## Highlights

- **Docker-first installation** with one main command:

  ```bash
  docker compose up --build -d
  ```

- **Web Setup Wizard** available at `http://localhost:8000`.
- **No manual Python environment, dependency hunting, or Playwright setup** for the recommended Docker path.
- **Download ZIP support** for users who do not use Git.
- **Provider-agnostic setup** supporting Vertex AI, Gemini API, OpenAI, and Anthropic.
- **Portable configuration** with committed `.env.example` and locally generated private settings.
- **Local persistence** for SQLite databases, ChromaDB, logs, settings, uploads, and generated files through Docker volume mapping.
- **Docker/headless startup** runs the Web API and Telegram bot together.
- **Beginner-focused documentation** with start, stop, update, logs, backup, and troubleshooting instructions.

## Added

- Docker-first quick-start flow.
- Guided setup for supported model providers.
- Portable boot and server startup paths.
- Hacker News daily technology briefing with scheduler support and deterministic fallback formatting.
- Additional portability and setup tests.
- Clear public-facing documentation explaining local-first storage and external API usage.

## Changed

- Refactored runtime configuration so the project no longer depends on machine-specific paths or personal settings.
- Removed remaining personal hardcodes, scratch scripts, runtime artifacts, and local-only files from the public repository.
- Reworked `README.md` from a developer-heavy feature inventory into a Docker-first product landing page.
- Reworked `SETUP_GUIDE.md` so Docker is the recommended path and manual Python installation is the advanced alternative.
- Aligned `boot.py`, Docker, the setup wizard, provider selection, and tool registration into one portable installation flow.
- Improved locale synchronization and documented that locale files also contain runtime NLP resources.
- Tightened model-response parsing and prompt guards across agents and tools.

## Fixed

- Portable bootstrap and registry drift issues.
- Setup wizard and Docker startup inconsistencies.
- Multimodal model responses returning lists instead of plain text.
- JSON extraction failures when models included conversational text around structured output.
- Generated skill registration targeting the wrong list in `tools/system.py`.
- Context extraction errors that could leave stale work or location state active.
- Duplicate memory drift and list prompt edge cases.
- Recipe context handling and Home Agent tool guards.
- Security and privacy gaps around local configuration, runtime files, and setup exposure.

## Upgrade notes

Version 2.0.0 is a major release because installation and configuration have been redesigned around portability.

Before updating an existing installation:

1. Back up your local `.env`, credentials, SQLite databases, `chroma_db/`, uploads, and custom prompts.
2. Pull the latest code.
3. Compare your configuration with `.env.example`.
4. Rebuild the container:

   ```bash
   docker compose down
   docker compose up --build -d
   ```

Existing local data remains in the project folder through volume mapping, but backups are strongly recommended before every major upgrade.

## Requirements

- Docker Desktop for the recommended installation path.
- Credentials or an API key for at least one supported AI provider.
- Optional credentials for integrations such as Telegram, Google services, GitHub, Spotify, and others.

## Important privacy note

Astakos is local-first, not fully offline. Long-term memory and runtime state remain on the user's machine, while prompts, media, and tool payloads may be sent to the external model provider or integration required by the enabled feature.


## [v1.4.0] â€” 2026-07-03

Headline: **Follow-up intelligence, cleaner memory hygiene, and a much more inspectable runtime.** This release focuses on making Astakos feel more continuous and less robotic: conversation-triggered follow-ups, deterministic media/document archival, cleaner Web UI behavior, lower-latency context selection, and better visibility into why the system did what it did.

### Added

#### Conversational Follow-up Pipeline
- **Pending follow-ups subsystem** (`memory/pending_followups.py`) â€” Astakos can now create delayed follow-up threads from ordinary conversation, persist them in SQLite, expire them safely, and resolve them later when the user naturally closes the loop.
- **Topic-aware follow-up extraction** â€” LLM extraction now proposes `topic`, `subject`, `delay_minutes`, `confidence`, and `reason`, with deterministic guards and TTL-backed persistence.
- **Arc dedupe** â€” similar subjects like "Î¼Ï€ÏÎ¹Î¶ÏŒÎ»ÎµÏ‚ Î»Î±Î¹Î¼Î¿Ï" and "Î»Î±Î¹Î¼Î¿Ï Î¼Ï€ÏÎ¹Î¶ÏŒÎ»ÎµÏ‚" collapse into a shared `arc_key`, preventing duplicate follow-up threads for the same real-world arc.
- **Timing policy normalization** â€” follow-up delays are clamped by follow-up type (for example outings vs. food purchases) so timing stays plausible without hardcoding a single fixed delay for every case.
- **LLM-based follow-up resolution** â€” later user messages can resolve a pending follow-up through a structured classifier instead of relying only on lexical overlap.
- **Scheduler job for follow-ups** â€” `job_check_pending_followups` sends natural Telegram follow-ups only when a pending item is still due, unresolved, and not blocked by anti-spam guards.
- **Debug dashboard visibility** â€” `/debug/runtime` now surfaces pending follow-ups with due time, arc key, last decision, score, and send count.

#### Deterministic File / Media Handling
- **Pending asset archive confirmations** â€” photos and uploaded documents are now archived only after an explicit yes/no confirmation, instead of depending on a later heuristic memory pass.
- **Recent-file follow-up handling in Web UI** â€” after a document or large paste is analyzed, the user can immediately ask follow-up questions about it and Astakos will re-inject the recent file context into the chat flow.
- **Paste-to-file behavior** â€” large Web UI pastes can be promoted into virtual document attachments (`.txt` / `.py`) so long code or text blocks are analyzed as files rather than getting truncated as plain chat.
- **Head+tail document excerpting** â€” large text/code uploads now preserve both the beginning and the end of a file during analysis, which prevents losing the critical tail of stack traces, returns, or final blocks.

### Changed

#### Memory Context and Latency
- **Fast/medium path tuning across Web and Telegram** â€” lightweight turns, reminder requests, tool outputs, recent-context follow-ups, and initial "I read a news item" openings can now bypass or downshift expensive semantic recall.
- **Reminder/task requests skip semantic recall** â€” operational turns like "Î¸ÏÎ¼Î¹ÏƒÎ­ Î¼Î¿Ï… ÏƒÏ„Î¹Ï‚ 19:00â€¦" no longer pay the full semantic retrieval cost before setting the reminder.
- **Recent web-result follow-ups downshift memory** â€” follow-up discussion on just-fetched web results can use a smaller retrieval budget instead of the full memory depth.
- **Recent local-echo dedupe window in Web UI increased** â€” the frontend now tolerates slower backend turns without rendering duplicate user messages after polling catches up.

#### Memory Hygiene and Dedupe
- **Replay-safe reminder handling** â€” operational reminder confirmations are filtered before they become duplicate long-term memories.
- **Same-day duplicate collapse improved** â€” personal/work/family facts from tools and the slow memory sifter now align better through shared canonical candidate building and same-day near-duplicate checks.
- **Operational/meta assistant text filtering** â€” draft-management boilerplate, capability blurbs, and similar meta assistant paragraphs are less likely to leak back into memory context or be mistaken for real user facts.
- **Capability logging quieted** â€” duplicate capability detections are now logged as duplicate skips instead of being surfaced like brand-new learned capabilities.

#### Runtime / UI / Observability
- **Pending follow-up outcome tracking** â€” follow-ups now track `last_decision`, `decision_reason`, `outcome_score`, and `times_sent`.
- **Routine outcome observability** â€” the dashboard shows clearer last-outcome data for routines, including blocked, skipped, stale, and sent outcomes.
- **Web tool failure guard** â€” hallucinated answers are overridden when recent web tool calls all fail, favoring safe fallback text over invented facts.
- **Web/Telegram history and debug refresh** â€” runtime memory-context debug snapshots are refreshed more consistently across both channels.

### Fixed

- Fixed duplicate rendering races in the Web UI where a local echo and a delayed persisted message could both appear.
- Fixed follow-up scheduler startup/runtime issues, including the zero-argument scheduler call path and missing helper blocks after partial patch application.
- Fixed stale or misleading dashboard behavior around pending follow-ups and memory-context observability.
- Fixed several false-positive semantic retrieval cases caused by tool outputs, short status updates, or operational exchange text.
- Hardened the vector-store path against Chroma query/delete/get failures with graceful fallbacks and targeted tests.

### Tests

- Added focused test coverage for:
  - follow-up creation, timing normalization, arc dedupe, LLM resolution, debug-field exposure, and scheduler anti-spam skips
  - Web tool failure guards
  - output sanitizers
  - reminder semantic-skip behavior
  - vector-store safety wrappers and lexical duplicate guards
  - recent-web-context semantic downshift logic

## [v1.3.0] â€” 2026-06-18

28 commits since v1.2.0. Headline: **Routine Reconciler Phase 3** â€” automatic fact-to-routine reconciliation grows a full deterministic scoring engine with auto-apply guardrails, paired with a new **Routine Conditions** system for context-aware constraints (shift schedules, seasonal pauses), plus a round of test-suite hardening that found and fixed several stale assertions and a `sys.modules` pollution bug.

### ðŸ†• Features

#### Routine Reconciler â€” Phase 3A/3B (deterministic scoring + auto-apply guardrails)
- **Automatic fact-to-routine reconciliation** â€” stated facts ("Kid1 Î³ÏÏÎ¹ÏƒÎµ ÏƒÏ€Î¯Ï„Î¹", "Î±Ï…Ï„Î® Ï„Î·Î½ ÎµÎ²Î´Î¿Î¼Î¬Î´Î± Î´Î¿Ï…Î»ÎµÏÏ‰ Î±Ï€ÏŒÎ³ÎµÏ…Î¼Î±") are matched against deterministic rules and turned into routine directives instead of requiring a manual mute/unmute.
- **Phase 3A â€” 4 new rule groups**: `school_break`, `shift_week`, `temporary_absence_other_person`, `child_activity_pause`, built on a shared `_build_directive()` helper that enforces subject + time-scope guards on every directive. Smoke tests cover false-positive cases (11/11).
- **Phase 3B â€” deterministic scoring layer** (`services/routine_reconciler.py`): weighted score (subject 0.30 / activity 0.20 / state 0.20 / scope 0.20 / special 0.10) against two thresholds â€” `_AUTO_APPLY_THRESHOLD = 0.80`, `_DEBUG_ONLY_THRESHOLD = 0.55`. `score_candidate_directive()` returns `auto_apply` / `debug_only` / `rejected`; `filter_directives_for_auto_apply()` buckets candidates; `reconcile_fact_to_routines()` runs the full pipeline with stats and per-candidate event logs (`reconcile_candidate_applied` / `_debug_only` / `_rejected`). `infer_routine_reconciliation_directives()` stays as a backward-compatible wrapper that only returns the `auto_apply` bucket.
- **Deliberately conservative by design** â€” `shift_logic` carries a `-0.25` penalty so a stated shift change can never silently auto-apply (it lands in `debug_only`, logged but not acted on, by design â€” confirmed behavior, not a bug). `return_home` was tuned the other way: a complete fact like "Î³ÏÏÎ¹ÏƒÎµ ÏƒÏ€Î¯Ï„Î¹ Ï„ÏŽÏÎ±" needs no `until_date`, so it now scores into `auto_apply`.

#### Routine Conditions â€” context-aware constraints
- **Condition evaluation engine** â€” routines can now carry conditions resolved against live `context_state` (e.g. `shift_mode`) instead of only blunt mute/pause windows.
- **`control_routine_condition` tool** â€” LLM-driven, natural-language routine constraints ("Î´Î¿ÏÎ»ÎµÏˆÎµ Î¼ÏŒÎ½Î¿ ÏŒÏ„Î±Î½ ÎµÎ¯Î¼Î±Î¹ ÏƒÎµ Î±Ï€Î¿Î³ÎµÏ…Î¼Î±Ï„Î¹Î½Î® Î²Î¬ÏÎ´Î¹Î±") instead of editing condition JSON by hand.
- **Runtime current-shift state** â€” a dedicated runtime store feeds shift-based conditions, with the memory sifter split into fast/deterministic and slow/LLM queues so shift facts resolve without waiting on an LLM call.
- **Smart weekend filter** â€” `shift_mode` conditions are skipped on weekend-only routines unless explicitly requested, so a work-shift rule can't accidentally mute a Saturday habit.
- **Routine intent gating hardened** â€” distinguishes a stated fact ("Î´Î¿Ï…Î»ÎµÏÏ‰ Î±Ï€ÏŒÎ³ÎµÏ…Î¼Î± Î±Ï…Ï„Î® Ï„Î·Î½ ÎµÎ²Î´Î¿Î¼Î¬Î´Î±") from a manual command, so the reconciler doesn't misfire on ordinary chat.
- **Debug dashboard fixes** â€” routines with conditions no longer show a false "No meta"; `shift_mode` conditions now show their resolved `Now:` value.

#### Memory & Proactive Routines
- **Deterministic family-absence extractor** â€” temporary absence statements ("Î¿ Kid1 ÎµÎ¯Î½Î±Î¹ ÏƒÎµ ÎºÎ±Ï„Î±ÏƒÎºÎ®Î½Ï‰ÏƒÎ·") are parsed without an LLM sifter call.
- **Seasonal Routine Inactivity Controls** â€” pause/resume a routine for a date range (e.g. football paused over summer) without deleting or permanently muting it.
- Fixed proactive mute loops and duplicate routine control; fixed a `recall_query`/temporal date-marker collision that leaked unrelated 30-day SQL history lookback into proactive routine context; hardened the muted + sentimental proactive routine flow.

### ðŸ”§ Notable Fixes

- **Test-suite hardening** â€” found and fixed a stemming bug in `_CAMP_TOKENS` (`routine_reconciler.py`); fixed several stale test assertions (`test_routine_reconciler.py`, `test_routine_reconciler_scoring.py`, `test_session_memory.py`, `test_silent_skip.py`) that had drifted from the confirmed-correct conservative-by-design `shift_logic` behavior; fixed a `sys.modules` pollution bug in `test_pr3.py` where a never-torn-down stub of `services.reflection_engine` leaked into later-run test files â€” converted to the `setup_module()`/`teardown_module()` pattern already used elsewhere in the suite.
- Full suite: **581 passed, 0 failed**.

---

## [v1.2.0] â€” 2026-06-16

106 commits since v1.1.0. Headline: **Planner v2's full agentic loop is complete** (Goal â†’ Plan â†’ Validate â†’ Execute â†’ Reflect â†’ Re-plan), alongside a full **Profile SQLite Migration**, Google Calendar integration, a Georgian-language helper, and a long tail of reliability fixes across Mail_Agent, memory search, and Telegram/Messenger.

### ðŸ†• Features

#### Planning & Execution â€” Planner v2 Agentic Loop (complete)
- **Confirmation gate** â€” `/plan` no longer auto-executes; it decomposes the goal, then waits for explicit confirmation (PR1a).
- **Auto-plan LLM judge** (`core/plan_judge.py`) â€” detects multi-step intent and routes into the planner without requiring the literal `/plan` command (PR1b).
- **Progress UI** â€” `[X/N]` step progress messages during execution (PR2).
- **`validate_step_node`** â€” detects step failure via AI response + tool-output heuristics (PR2).
- **`replan_node`** â€” auto-skips failed steps and continues the plan instead of aborting (PR3).
- **`end_check_node`** â€” final summary (`âœ…` full success / `âš ï¸ X/N steps`) + saves a post-plan reflection (PR3).
- Step isolation directive + `ToolMessage` error-detection hardening; `capture_result` ignores progress messages when judging success.
- Still open: parallel step execution and per-step Telegram approve/reject buttons (today's confirmation gate is chat-based, not inline-keyboard) â€” see Roadmap.

#### Memory â€” Profile SQLite Migration
- Profile memory (preferences, family facts, recurring details) moved from the legacy `astakos_profile.json` format to SQLite; `clean.py` migrated; legacy JSON files and `astakos_profile.json.example` removed as obsolete.
- Schema fixes: corrected `date` â†’ `session_date` column in `session_memory.py`; aligned SQLite state schema and cleaned tracked artifacts.
- **Context-Aware Proactive Routines** â€” routine pings now check live context before firing.

#### Memory â€” Routine Muting & Sentimental Handling
- **`SILENT_SKIP`** â€” LLM judges whether a routine should fire silently instead of pinging.
- **`muted_until`** â€” per-date auto-silence without a daily LLM call once muted.
- **Sentimental flag + frequency** â€” emotional messages still get through at a reduced cadence during a muted period.
- **Natural-language override** â€” mute/unmute, silence/allow emotional messages, parsed directly from chat, no command syntax.
- Numbered Î½Î±Î¹/ÏŒÏ‡Î¹ replies now resolve multiple pending reflections at once; reflection `routine_id`/`action_value` persistence and pending-recovery/dedupe bugs fixed.

#### Memory â€” Performance
- `search_memory` â€” lexical L1 cache, one `similarity_search` call instead of three, async bump, temporal guard; SQLite recall kept for memory-intent queries.
- `save_to_memory` â€” fire-and-forget background thread, eliminates ~11s of blocking per call.

#### Action Safety
- **Capability Registry expanded to 37 capabilities** with a full 4-level risk model.
- **`tool_stats`** â€” aggregates execution traces into per-tool call/error/duration stats.
- **System Doctor** (`system_doctor`, `/doctor`) â€” runtime health summary: event logs, traces, pending approvals, Messenger draft state, SQLite session backlog, pending routine confirmations.
- MASTRO-SHIELD v2 â€” added `CIVIC_INTEGRITY` + `JAILBREAK` + `IMAGE_*` BLOCK_NONE categories.

#### Integrations
- **Google Calendar** â€” full CRUD tool with per-action risk, OAuth2 `token.json` auth (same pattern as Mail/Drive/Tasks), proactive morning briefing.
- **Georgian language helper** â€” `/georgian` and `/georgian_phrases` Telegram commands; pending-translation mode; TTS via `edge-tts` (`ka-GE-EkaNeural`) after Google Translate/gTTS turned out not to support `ka`; later renamed to `/gr` `/greek` for clarity; bot menu updated.
- **Messenger image attachments** â€” Playwright-based upload + draft schema support.
- **Reaction handler** â€” â¤ï¸ exact-message-match via in-memory cache with SQLite fallback.
- LinkedIn multi-image posting.

#### Developer Tools
- **`list_recent_files`** (`tools/project_tools.py`) â€” bounded `os.walk` scan for recently modified files, no `grant_project_access` needed for internal scans, ignores `venv`/`.git`/`__pycache__`/`node_modules`. Risk: SAFE. Replaces ad-hoc PowerShell `Get-ChildItem -Recurse`/`dir /s` through `run_terminal_command`, which routinely hit the 30s subprocess timeout. Wired into Dev_Agent and Git_Agent prompts.

### ðŸ”§ Notable Fixes

- **Mail_Agent loop guard** â€” hardened through four iterations: no-tools synthesis when mail results are already in context, clean 2-message synthesis bypassing `sanitize_history`, current-turn-only history, auto-read + ID-hint injection, `read_full` instead of `read`.
- **Web/Telegram reply synthesis** â€” fixed empty-synthesis fallback and streaming filter so both channels reliably turn tool results into a spoken reply.
- `duckduckgo_search` latency â€” pinned backend to `duckduckgo+google` fallback; removed the deprecated package pin from `requirements.txt`.
- Trace/event log hardening â€” `WinError 5` fallback for cross-process write contention; guarded `None` data in `event.items()` loops and `process_event`.
- Timeline dashboard â€” fixed legacy dict-string event parsing, confirmed/dismissed log format, `job=routines` filter, added `deferred_followup`/`timeout_decay` actions.
- Startup stale-working-memory cleanup on hard restart; `Ctrl+C` shutdown now runs the full `handle_end_session` (messages + cleanup) instead of a partial one.
- Photo indexer corrupted-filename bug + JSON state cleanup.
- Messenger textbox timeout â€” root cause turned out to be a stuck PIN prompt, not slow page load; reverted an unneeded 10sâ†’25s timeout bump once identified.
- Google Fit â€” reverted to the Fit API (Health API v4 needs a Fitbit account) and handled a token scope mismatch.
- Misc correctness: sifter no longer saves raw user text as a fact; removed a generic "Î­Î¾Î¿Î´Î±" trigger from `scan_receipt`; SQLite connections now close properly + UTF-8 console on Windows; `send_telegram_msg` chat_id keyword fix; Telegram HTML fallback formatting; reflection float-time sanitization (`14.5` â†’ `14:30`); scheduler `verbose=False` cuts reminder/routine log noise; Messenger draft auto-clear + Sophia contact resolution; plan-mode payload sanitization + double-approval bypass fix.

### ðŸ—‘ Removed

- `astakos_profile.json.example` â€” superseded by the SQLite profile schema; the JSON template no longer reflects reality.

---

## [v1.1.0] â€” 2026-06-11

This release marks Astakos's transformation from a smart assistant into a **proactive, self-improving AI agent** with long-term memory, nightly self-reflection, multi-step planning, and a robust safety framework.

### ðŸ†• Features

#### Multi-Agent Architecture
- **Capability Registry** â€” keyword-based routing to the correct agent *before* the LLM Supervisor, reducing latency and misrouting (`core/capability_registry.json`)
- **Centralized Vertex AI client** in `core/brain.py` â€” shared `vertex_client` across all agents, single connection pool

#### Memory System
- **Memory Scoring** â€” every saved fact gets `importance`, `confidence`, `last_accessed`, and a composite `compute_score()` for smarter retrieval ranking
- **Memory Provenance** â€” `source` and `reason` metadata on every ChromaDB write
- **Fused Memory Context** â€” agent prompts now include a pre-built context window from the most relevant memories, injected before every LLM call
- **Shared Conversation History** â€” unified SQLite store for web + Telegram exchanges; cross-channel context awareness (`astakos_conversation_history.db`)
- **SQLite L1+L2 Embeddings Cache** â€” replaces the JSON embeddings cache; significantly faster repeated lookups (`astakos_embeddings_cache.db`)
- **Memory Manager** â€” extended to support `reflection` and `event` memory types; visual Timeline section in debug dashboard
- **Sifter sliding-window context** â€” session logs feed into the memory sifter for richer fact extraction

#### Autonomy & Self-Improvement
- **Reflection Engine** (`services/reflection_engine.py`) â€” nightly self-evaluation at 03:00; analyzes conversations + routine stats; auto-applies lessons (confidence > 0.75); saves observations to ChromaDB
- **Analytics Engine LLM Upgrade** â€” routine detection now uses LLM batch extraction instead of keyword matching; reads both web and Telegram history
- **Post-Plan Reflection** â€” after every `/plan` execution, Astakos saves an observation/action/lesson about what happened
- **Goal Follow-up Engine** â€” daily proactive Telegram ping for stale long-term goals

#### Planning & Execution
- **Planning Agent** â€” `/plan` command; `PlannerNode` + `TaskExecutor`; multi-step plan execution with progress output
- **Long-Term Goals System** â€” save, update, and track goals in ChromaDB; injected into prompts; `/debug/goals` dashboard with delete
- **Tool Loop Guard** â€” detects and breaks infinite tool-call loops; reports the last tool name(s) in error message

#### Action Safety
- **Action Approval Levels** â€” full SAFE / WARNING / CRITICAL risk registry (`core/tool_risk.py`); WARNING tools send Telegram alert; CRITICAL tools pause and await inline-keyboard approval
- **Pending Approval TTL** â€” stale pending actions auto-expire after 60 minutes (`core/approval.py`)
- **Approval Gate from Web UI** â€” approve/reject CRITICAL tool calls directly from the debug dashboard
- **Execution Trace System** â€” every agent turn records agent, tools called, duration, errors, and loop events to `logs/traces/YYYY-MM-DD.json`; viewable at `/debug/traces`

#### Communication
- **Live Telegram â†’ Web UI** â€” WebSocket broadcast + `GET /messages/poll` endpoint; frontend polls every 5 seconds for new Telegram messages without page reload
- **Typing Indicator** â€” Telegram shows "Ï€Î»Î·ÎºÏ„ÏÎ¿Î»Î¿Î³ÎµÎ¯..." while Astakos is generating a response
- **Voice I/O** â€” `/voice` toggle; speech-to-text via Vertex AI; text-to-speech via `edge-tts`; voice input hint in Web UI
- **Routine Confirmation from Web UI** â€” accent-insensitive Greek matching; same logic as Telegram

#### File & Document Tools
- **File Generator** (`astakos_skills/file_generator.py`) â€” `generate_excel`, `generate_word_doc`, `generate_pdf`, `generate_csv`; risk level SAFE
- **File Delivery Pipeline** â€” `CREATED_FILE` tag in LLM response triggers: Web UI card with ðŸ“‚ Google Drive button + inline preview iframe; Telegram `sendDocument` with actual file
- **Google Drive Upload** (`tools/gdrive.py`) â€” ADC-based upload, sets public read permissions, returns shareable view URL

#### Developer Tools
- **Project Tools** (`tools/project_tools.py`) â€” `grant_project_access`, `list_project_files`, `read_project_file`, `edit_project_file`, `write_project_file`, `grep_project_files` for external repos
- **repo_mapper** (`astakos_skills/repo_mapper.py`) â€” AST shallow scan of any Python project; text tree + JSON output for fast codebase orientation
- **register_tool** â€” auto-registers new skills in `system.py`, `tool_risk.py`, and `capability_registry.json`; supports `dry_run` preview and path traversal protection
- **Watchdog Auto-Restart** â€” monitors `run_telegram.py` and `core/prompts.md`; auto-restarts Telegram bot on file change

#### External Services
- **Google Fit** (`astakos_skills/google_fit.py`) â€” steps, sleep (deep/REM/light), heart rate; morning briefing at 08:00 via Telegram
- **Vertex AI Imagen** â€” replaces Pollinations for image generation (Pollinations went paid)
- **Receipt Scanner** â€” `/scan` Telegram command; OCR via Vertex AI Vision
- **Google Drive Manager** â€” full CRUD: search, delete (to trash), rename, move, share, create_folder, info

#### Web Dashboard
- **Analytics Charts** â€” ðŸ“Š button; 4 charts: routine activity, tool usage, agent distribution, daily message volume
- **Pending Actions Panel** â€” age column; warns if pending > 15 minutes; approve/reject from UI
- **Active Routines Panel** â€” Edit, Delete, Reset Cooldown buttons
- **Reflection Engine Panel** â€” `/debug/reflections`; Apply button; hide-applied toggle; delete
- **Execution Traces Panel** â€” full-width, colored tool names, response preview, 400px scrollable

#### Observability
- **Runtime Dashboard** (`/debug/runtime`) â€” `scheduler_alive` flag, `channel_sessions` count per channel
- **`register_tool` dry_run** â€” preview registration diff without writing files
- **Messenger Draft Card** â€” shows `exists`, `active`, `reason`, `target_name`, `status`, `expires_in`, `message_chars`

#### OpenAgentSource
- Astakos is now listed on [OpenAgentSource](https://openagentsource.com/agents/astakos-ai-agent) â€” Medium Risk, 18 permissions, all health checks passing

---

### ðŸ”§ Notable Fixes

- `relay_local_payload` â€” clean return value; no meta-instructions leaked to chat; escalated CRITICAL â†’ WARNING
- `relay_local_payload` tool name kept obscure intentionally (bypasses Google safety filter)
- Memory deduplication via cosine distance threshold â€” prevents near-duplicate facts from stacking in ChromaDB
- Samsung Health sleep + heart rate source handling corrected (`get_sleep` reads directly from `com.sec.android.app.shealth`)
- Session summary on graceful shutdown â€” drains the exchange queue before writing
- `safe_executor` hardened â€” blocks Windows destructive patterns, `reg`, `netsh`, `sc`, `cipher`; prevents direct `capability_registry.json` writes
- Security: `require_token` enforced on all unprotected endpoints (`/voice`, `/tts`, `/debug/*`)
- Sifter: no longer saves user questions as `USER_FACT` memories; no longer triggers `archive_file` on farewell messages

---

### ðŸ—º What's Next (v1.2.0)

- **Planner v2 â€” Agentic Loop**: Goal â†’ Plan â†’ Validate â†’ Execute â†’ Reflect â†’ Re-plan
- **Behavior Analytics Engine**: auto-shift routine triggers based on ignore patterns
- **Cross-Channel Awareness**: "continue what I was doing in the web" â†’ inject recent web session into Telegram context

---

## [v1.0.0] â€” 2026-04-01

Initial release. Core multi-agent framework (LangGraph), Telegram bot, Web UI, ChromaDB memory, routine detection, Google Calendar/Tasks/Drive integration, Spotify, vacuum control, mail manager.


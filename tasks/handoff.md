# Astakos: new-session handoff

Snapshot: 2026-10-08, after merging PR #236. This is orientation, not a substitute
for current code, runtime evidence or a new task's approval. Refresh when state changes.

## Start here

1. Read root `AGENTS.md`, then this short handoff.
2. Check `git status --short`, current branch and recent commits. Preserve unrelated work.
3. Ask for/identify the current task; inspect only related code, tests and specs.
   Do not reread every historic plan/spec or reimplement completed slices.
4. Follow the vendored `using-agent-skills` router and only the needed workflows.

## Verified Git checkpoint

- Repository: `alexneverland/Astakos-AI-Agent`, workspace `C:\astakos_v2`.
- Local `main` and `origin/main`: `39611b874928009b392956381c65bf601560333c`.
- Working tree was clean before this documentation-only handoff edit.
- PR #236 merged; `codex/behavioral-identity-resolution` deleted locally/remotely.
- No open owner feature PR in the GitHub listing; open Dependabot PRs #4-19
  are separate, not approved dependency upgrades. Recheck before any Git action.
- Owner authorized publishing these handoff/doc edits on 2026-10-08 in a separate
  documentation PR; merge remains a separate instruction.

## Collaboration and safety

- Discuss in Greek, practically and concisely. Diagnose read-only first; implement
  the scoped change when explicitly requested/approved (e.g. "πάμε").
- Token-conscious work: no subagents by default; explain the benefit and ask before
  delegation. Focused tests only; no repeated full-suite runs or endless review loops.
- Meaning is semantic: no hardcoded phrase/alias lists to patch user language.
  Reuse canonical resolvers, bounded trusted history and validated model output.
- Never expose/edit credentials, `.env` or `config.py`; do not touch real DBs,
  Chroma, Docker/runtime/watchdogs or migrate/reset data without specific authority.
  Use `memory/` abstractions, never raw SQL against live stores.
- Offline tests mock provider/transport boundaries and use temporary data.
  Passing fixtures do not prove live model quality or real hardware behavior.
- PR creation is not merge authorization. Review both top-level and inline comments.
  Commit scoped files only; no force push, reset/clean, releases or unrelated branches.

## Architecture and decisions to preserve

- Shared Web/Telegram/Matrix conversation and history; actual delivery uses the
  selected external channel. Verify current routing rather than assuming a channel.
- Critical external actions retain approval gates. Owner accepts Matrix approval
  by exact Reply; do not restore reaction approval or copy legacy `/confirm` behavior.
- Bug proposals are not missing-capability proposals: diagnosis and code repair
  require separate user instructions. Keep read-only diagnosis tool boundaries.
- Behavioral patterns are NOT event followups or automatic routine creation.
  Intake follows trusted messages; conversational comments and spontaneous openers
  are distinct. Initial initiative policy: at most one opener/day, seven-day topic
  suppression, at least 15 minutes idle plus existing quiet/mute/reminder/budget gates.
- Context questions, ordinary conversation and dated routine feedback coexist.
  Mixed answers must retain additional facts, memory and unrelated tool requests.
  GPS proves only owner whereabouts, not partner/child presence. Preserve provenance,
  event times, freshness/version checks and canonical final dispatch eligibility.
- Reflection stays disabled/unscheduled by owner decision. Do not activate it.
- Generated/file media are not to be mirrored as raw HTML/local paths across channels.

## Latest completed slices / where to look

- #236 behavioral identity: `services/behavioral_event_extractor.py`,
  `prompts/behavioral_event_extraction.md`, `services/behavioral_pattern_aggregator.py`,
  `services/behavioral_conversation_initiative.py`; contract
  `tasks/behavioral-entity-identity-spec.md`. Generic entity/action resolution,
  validated prior references, specific-action grouping, existing topic hashes retained.
  175 related offline tests passed before merge; Gemini CLEAN reported by owner.
  Historical events unchanged: stricter grouping yielded 3 patterns instead of 4
  in the inspected 111-event snapshot. No backfill; live semantics still to observe.
- #235 goal updates: existing partial goal tools for Chat/Dev, recorded activity
  timestamps and provenance. Scores are milestones, not invented completion percentages.
  See the goal sections in `tasks/plan.md` / `tasks/todo.md` and related goal tests.
- #233 daily inference / #234 optional routine notes: source-timed shared context,
  guarded writes and fresh delivery. A blocked activity can receive a 30%-gated
  relevant comment, not the blocked action; work is not a blanket comment mute.
  See `daily-context-inference-spec.md` and `routine-context-notes-spec.md` in tasks.
- #227 dated routine rollout/reset completed, followed by #228-232 conversational
  continuity, wording, completion and re-question fixes. Recorded reset was cooldown
  0/confidence 1.0 for 12 routines on 2026-10-07, NOT a claim of current live values.
  Never repeat it. Refer to `tasks/routine-feedback-spec.md` and newer top-level status.

## Remaining work, not automatic authorization

- Natural observation: behavioral entity/action accuracy, comments/opener/preferences,
  diagnostics; project-update tool selection; routine/context wording and mixed replies;
  GPS renewal/races, shift boundary, memory provenance, vacuum/Web behavior.
- Isolated application recovery rehearsal for data-only backup; separately verify
  Element keys and replacement-host recovery. Prior backup success is not full recovery.
- Deferred two legacy missed-routine tests with transport isolation problems:
  `tests/test_event_log_and_missed_routines.py`. Do not turn them into live sends.
- Future Web exact-reply UI / schedule-context inference need their own agreed scope.
- Old Chroma cleanup and historical behavioral reclassification are explicitly deferred.

`tasks/todo.md` retains detailed observation items. Older "not activated/reset pending"
paragraphs are historical checkpoints, superseded by the completed rollout sections.
No runtime, database, provider or scheduled backup was reverified for this handoff.

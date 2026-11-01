# Using agent-skills with Oh My Pi

[Oh My Pi (OMP)](https://github.com/can1357/oh-my-pi) installs Claude Code marketplace plugins, so it uses this repository's existing `.claude-plugin/` manifests and the root `skills/` directory. No OMP-specific files are needed.

## Install

```bash
omp plugin marketplace add addyosmani/agent-skills
omp plugin install agent-skills@addy-agent-skills
```

The first command registers this repository as the `addy-agent-skills` marketplace. The second installs the `agent-skills` plugin from it. Restart OMP, or run `/reload-plugins` in an open session, so the skills are discovered.

Local clones work too:

```bash
omp plugin marketplace add /path/to/your/clone
omp plugin install agent-skills@addy-agent-skills
```

Check the result with `omp plugin list`.

## Usage

Describe the task and let OMP pick the skill. OMP lists each skill's `name` and `description` in its system prompt and loads the full `SKILL.md` only when a skill is selected. To select a skill explicitly, use `/skill:spec-driven-development` (available unless `skills.enableSkillCommands` is disabled), or ask the agent to read `skill://spec-driven-development`.

OMP already routes skills natively. Do not also paste `using-agent-skills/SKILL.md` into `AGENTS.md`, `APPEND_SYSTEM.md`, a rule, or an extension that adds it to every run. That stacks the pack's meta-router on OMP's own router; see [Getting Started](getting-started.md).

The same install also loads the slash commands and the personas in `agents/`. OMP namespaces plugin commands, so run `/agent-skills:spec`, `/agent-skills:ship`, and so on; a bare `/spec` is not expanded. The personas (`code-reviewer`, `security-auditor`, `test-engineer`, `web-performance-auditor`) are listed as `task` agents, which `/agent-skills:ship` and `/agent-skills:webperf` dispatch.

## Tool mapping

Skills and docs in this pack use Claude Code tool names. In OMP, use the native equivalents:

| Skill instruction | OMP equivalent |
| --- | --- |
| Invoke another skill | `read` on `skill://<name>`, or `/skill:<name>` from the prompt |
| Spawn a subagent (`Agent` tool) | the `task` tool; only use agents OMP lists |
| Track tasks (`TodoWrite`) | the `todo` tool |
| Ask the user a question (`AskUserQuestion`) | the `ask` tool |
| Read, edit, write, search files | the native `read`, `edit`, `write`, `grep`, and `glob` tools |

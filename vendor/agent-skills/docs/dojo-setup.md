# ⛩️ Using agent-skills with Dojo Workspace

Dojo Workspace is a desktop app that reads skills from the standard `.agents/skills/` folders. Installing it also puts the `dojo` command on your PATH.

If `dojo` is not found, add its install folder to your PATH, or run it by its full path:

| OS | Folder to add to PATH | Full path |
| --- | --- | --- |
| macOS / Linux | `~/.local/bin` | `~/.local/bin/dojo` |
| Windows | `%LOCALAPPDATA%\dojo\bin` | `%LOCALAPPDATA%\dojo\bin\dojo.exe` |

Open a new terminal after the first app launch so the PATH change is picked up.

## Install for all projects

```bash
dojo skills add addyosmani/agent-skills
```

Skills install into `~/.agents/skills/` and appear in the **Skills** panel under the `addyosmani-agent-skills` group. Enable the ones you want for each lane (Dojo Solo or Dojo Duo).

## Install for one project

Run from the project root:

```bash
dojo skills add -p addyosmani/agent-skills
```

Skills install into the project's `.agents/skills/` and are enabled for that project. Commit `skills-lock.json` to share them with your team.

## Manage

```bash
dojo skills list                      # add -p for the current project
dojo skills remove addyosmani/agent-skills
```

`remove` takes a whole repo or a single skill name.

## How skills load

Only each skill's name and description are listed for the model. The full `SKILL.md` loads on demand when a task matches, so enabling many skills stays cheap. Dojo also reads project instructions from `AGENTS.md`.

If you'd rather add skills through the app's UI, [here is how](https://heydojo.ai/learn/dojo-skills-teach-your-agent-new-workflows).

---
name: astakos-skill-authoring
description: Guides agents through safe custom Astakos skill drafting and registration. Use when a user asks for a new Astakos tool or an agent identifies a capability gap.
---

# Astakos Skill Authoring

## Overview

This skill keeps a requested capability separate from its activation. It requires a user-reviewed draft and preserves the existing approval boundary for registration.

## When to Use

- Use when a user asks to add a new Astakos tool or a capability gap is identified.
- Do not use to modify an already registered core tool; follow the relevant existing engineering workflow instead.

## Process

1. Propose the tool in plain language: purpose, parameters, risk, and expected behavior. Do not write code yet.
2. Wait for an explicit localized draft authorization in the newest user message. Do not infer authorization from history, tool arguments, or a question.
3. Read this skill, then call `write_custom_tool` once. The skill must expose exactly one top-level `@tool` function whose name matches its filename.
4. Call `register_tool(..., dry_run=True)` and direct the user to the generated diff artifact under `outputs/`.
5. Wait for the user to review the artifact and explicitly authorize apply. Then call `register_tool(..., dry_run=False)`; that action remains subject to CRITICAL approval.

### Code Requirements

- Do not bypass `write_custom_tool` with direct file writes, temporary scripts, terminal commands, or manual edits to registration files.
- Do not use blocklisted filesystem, network, process, dynamic-execution, or unsafe-import libraries. Use existing Astakos abstractions instead.
- Use `core.i18n.t()` for all tool return text, add missing keys to both locale files, include type hints, and write a descriptive Google-style docstring.
- Return translated error strings rather than `None`; handle expected failures without crashing the LangGraph node.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "The request is obvious, so I can write the tool now." | A proposal is not authorization to write a file. Wait for the explicit draft command. |
| "The code is only a draft, so registration can happen too." | A draft file stays dormant; registration is a separate user-reviewed step. |
| "I can edit system.py directly because the change is small." | `register_tool` owns registration and keeps the change previewable and approval-gated. |

## Red Flags

- A tool call to `write_custom_tool` appears before explicit newest-message authorization.
- A dry run is skipped, its artifact is not shown to the user, or registration is attempted without apply authorization.
- User-visible strings are hardcoded or a custom skill writes directly to protected project files.

## Verification

- [ ] The proposal preceded draft creation and the newest user message explicitly authorized it.
- [ ] The skill passes `write_custom_tool` validation and contains one correctly named `@tool` function.
- [ ] `register_tool(..., dry_run=True)` produced a diff artifact with no registration files changed.
- [ ] Apply occurred only after user review and CRITICAL approval.

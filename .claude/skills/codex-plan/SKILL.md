---
name: codex-plan
description: Dispatch a Codex worker to produce an implementation plan before coding. Use for multi-file tasks or unfamiliar modules.
argument-hint: [task description]
---

# Codex Plan

Worker is read-only — returns a plan, never modifies files.

## Workflow

### 1) Gather context

- Read relevant code and `CLAUDE.md`.
- Identify files, interfaces, and constraints the task touches.

### 2) Dispatch

```bash
codex exec --full-auto -C "$WORKING_DIR" "$PROMPT"
```

Worker prompt must include:
- Task description and why
- Files to read first
- Output format: **Approach** (2-3 sentences), **File changes** (file + one-line summary), **Execution order**, **Risks**, **Testing strategy**
- "Do not modify any files. Be concrete — name files and functions, not vague concepts."

### 3) Synthesize

- Compare worker's plan with your own understanding.
- Present a unified plan to the user. Call out risks you hadn't considered.

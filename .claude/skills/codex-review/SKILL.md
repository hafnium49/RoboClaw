---
name: codex-review
description: Dispatch Codex workers to review changed code for bugs, security issues, logic errors, and pattern violations. Use after writing code, before committing.
argument-hint: [scope — e.g. "staged", "HEAD~1", branch name, or file paths]
---

# Codex Review

Workers are read-only — they return findings only, never modify files.

## Workflow

### 1) Identify the change set

- `git diff HEAD` for tracked changes; `git ls-files --others --exclude-standard` for untracked new files.
- If the user passes `staged`, use `git diff --cached`; if a branch name, use `git diff <branch>...HEAD`.
- No diff and no untracked files → nothing to review, tell the user.

### 2) Dispatch workers

- Group changed files by module/feature. Small diffs → one worker. Cross-module diffs → split by boundary.
- You must tell the worker the intent of the changes — what you were trying to accomplish and why. Without intent the worker cannot judge whether the code achieves its goal.
- Each worker gets: the intent, the diff, full content of changed files, and relevant `CLAUDE.md` rules.
- `codex exec --full-auto -C "$WORKING_DIR" "$PROMPT"`
- Tell the worker to check: intent alignment, correctness, security, integration breakage, and unnecessary complexity.
- Tell the worker to ignore: style nitpicks, missing docs on unchanged code, hypothetical future problems.
- Worker output: findings as `[CRITICAL|WARNING|NIT] title — file:line — issue — suggested fix`.

### 3) Report

- Deduplicate and sort by severity.
- Present grouped by CRITICAL / WARNING / NIT.
- If CRITICAL findings exist, recommend fixing before commit.
- Ask whether to fix or proceed.
- No issues → state the code looks clean.

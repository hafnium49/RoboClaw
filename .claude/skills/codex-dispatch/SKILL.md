---
name: codex-dispatch
description: Split work into concrete parallel sub-tasks and delegate each one to a Codex worker. Use when independent file/module ownership is clear.
argument-hint: [task description]
---

# Codex Dispatch

You are the manager. Each `codex exec` call is a fresh Codex worker with no prior context.

## Core rules

- Read the code yourself before dispatching.
- Do the immediate blocking work yourself; delegate sidecar work.
- Parallelize only tasks with disjoint ownership or read-only scopes.
- Prefer 2-3 solid workers over many tiny ones.
- Every worker prompt must be self-contained. Never rely on "as discussed" or hidden context.
- You are the quality gate: review, integrate, and validate before reporting success.

## Workflow

### 1. Inspect and split

- Read the relevant files and `CLAUDE.md` if it exists.
- Identify natural file/module boundaries.
- Do not parallelize dependent tasks.

Show the user a short breakdown only when the work is large, risky, or needs approval. Otherwise, dispatch directly.

### 2. Dispatch workers

Run each independent task with:

```bash
codex exec --full-auto -C "$WORKING_DIR" "$PROMPT"
```

Add `--add-dir <dir>` only when the worker needs extra paths.

## Worker prompt template

Use this shape and keep it concise:

```text
You are working in [repo or workdir].

Task:
[one concrete outcome]

Read first:
- [file path] — [why it matters]
- [file path] — [pattern or API to follow]
- CLAUDE.md — [only if present and relevant]

Ownership:
- You may modify only:
  - [file path]
  - [file path]

Constraints:
- You are not alone in the codebase. Do not revert unrelated changes.
- Do not modify files outside the ownership list.
- Follow existing patterns from the read-first files.
- [project-specific rule]

Verification:
- Run: [test/lint/typecheck command]

Final response:
- List changed files
- Summarize what changed
- Report verification results
- Note remaining risks or blockers
```

## Prompt-writing guidance

- Give exact file ownership. This matters more than long background sections.
- Include enough "why" to make design decisions sane, but do not write essays.
- Tell the worker what to read first instead of pasting huge amounts of context.
- If the task is review-only, say "do not edit files; return findings only."
- If the task is implementation, give a concrete success condition.
- If two workers might touch the same file, do not run them in parallel.

## After dispatch

- Read the worker outputs and inspect changed files.
- Resolve conflicts or incomplete work yourself, or re-dispatch with a tighter prompt.
- Run final validation after integration.

## Heuristics

- Good worker task: bounded, concrete, one owner, clear finish line.
- Bad worker task: vague, cross-cutting, tightly coupled, or blocked on another worker's output.
- When in doubt, simplify the split and keep more work in the manager.

---
name: roboclaw-jira
description: Reference for managing the RoboClaw development thread in the Humanoid Jira project via the Atlassian MCP. Use when the user asks to create, edit, query, transition, or link RoboClaw cards in Jira; or when planning new work that should be tracked there. Covers cloudId, project key HUM, RoboClaw label convention, Japanese issue type names, the standalone card template, dependency wiring, status transitions, and known content-encoding gotchas.
---

# RoboClaw Jira management skill

This skill is the procedural companion to the `roboclaw-deployment` skill. Where `roboclaw-deployment` covers **execution** of the RoboClaw stack, this skill covers **planning and tracking** that execution through Jira.

The Atlassian MCP server exposes tools prefixed `mcp__atlassian__*`. Load schemas via `ToolSearch` before calling — schemas are deferred by default.

## §1 Site / project / labelling — constants

| Field | Value |
|---|---|
| `cloudId` | `acc85cb6-501c-40e0-b26f-9c882f12cc22` (site `hafnium.atlassian.net`) |
| Project key | `HUM` (name: `Humanoid`, software / next-gen / kanban) |
| Thread label | `RoboClaw` (case-sensitive in JQL) |
| Parent Epic | `HUM-1` — _RoboClaw — embodied SO-101 deployment thread_ |
| Board URL | `https://hafnium.atlassian.net/jira/software/projects/HUM/boards` |

**Always set `labels: ["RoboClaw"]` on any card you create for this thread.** Cards without the label won't appear on the board's RoboClaw filter.

## §2 Issue types — Japanese names

This Jira project uses Japanese issue-type names. When calling `createJiraIssue`, pass the Japanese string as `issueTypeName`:

| Hierarchy | English | Japanese (use this string) | ID |
|---|---|---|---|
| 1 | Epic | `エピック` | 10048 |
| 0 | Task | `タスク` | 10047 |
| −1 | Sub-task | `サブタスク` | 10049 |

For RoboClaw cards: use `タスク` and set `parent: "HUM-1"` to nest under the existing Epic.

## §3 Card template — the standalone six-section shape

Every Task must be readable by a fresh Claude Code session with no prior conversation context. Use this exact six-section template:

```markdown
## Context

<who runs this card, where it fits in the flow, what state is assumed>

## Inputs (read first)

- `path/to/file:line` — what it tells you
- `docs/...md` §N — section to consult
- (cross-link to prior cards' outputs)

## Steps

<numbered or sectioned procedure with exact commands>

## Acceptance criteria

<paste-runnable verification commands with expected output; this is the "done" definition>

## Out of scope

<explicit anti-scope to prevent agent drift>

## Hand-off conditions

<when human-in-the-loop is required: physical hardware, OAuth browser flow, etc.>
```

The card summary should follow `[RoboClaw T<N>] <imperative title>` so the board reads like a checklist.

## §4 Content-format gotchas (load-bearing)

When passing card descriptions via `contentFormat: "markdown"`:

### 4.1 Multi-line Python inside bash code blocks BREAKS

A bash code block containing `python3 -c "..."` with multi-line Python inside the double quotes will mangle in Jira's markdown→ADF conversion. The newlines inside the bash command get re-interpreted as top-level paragraphs.

**Do not** write `python3 -c "\nimport json\n..."` in a bash block.

**Instead** stage the Python to a tempfile and invoke it with a single short bash line:

````
```python
# /tmp/probe.py
import json
print(json.dumps({...}))
```

```bash
docker cp /tmp/probe.py container:/tmp/probe.py && docker exec container python3 /tmp/probe.py
```
````

The two code blocks render cleanly and the executing agent gets a clearer separation of concerns.

### 4.2 Heredocs in bash blocks survive

Heredocs (`<<'EOF' ... EOF`) inside bash code blocks render fine because the closing token is unambiguous. Use heredocs over multi-line `-c` whenever you need inline content.

### 4.3 Code-fence languages matter

Use `bash`, `python`, `json` etc. as code-fence language tags — Jira's renderer picks syntax highlighting and table layout from these hints. Untagged code blocks render as plain text without indentation preservation.

## §5 Workflow operations — recipes

### 5.1 Create a new RoboClaw card

Always:
1. Set `projectKey: "HUM"`, `issueTypeName: "タスク"`, `parent: "HUM-1"`.
2. Apply the label at creation via `additional_fields: {"labels": ["RoboClaw"]}` — avoids a second round-trip edit.
3. Use `contentFormat: "markdown"`.
4. Follow the six-section template (§3).

Example call shape:

```
mcp__atlassian__createJiraIssue(
  cloudId = "acc85cb6-501c-40e0-b26f-9c882f12cc22",
  projectKey = "HUM",
  issueTypeName = "タスク",
  parent = "HUM-1",
  summary = "[RoboClaw T10] <imperative title>",
  contentFormat = "markdown",
  description = "## Context\n\n...\n\n## Inputs (read first)\n\n...",
  additional_fields = { "labels": ["RoboClaw"] }
)
```

### 5.2 Edit a card's description

Use `editJiraIssue` with `contentFormat: "markdown"`. The `description` field in `fields` is the full body — partial replacement is not supported.

```
mcp__atlassian__editJiraIssue(
  cloudId = "...",
  issueIdOrKey = "HUM-N",
  contentFormat = "markdown",
  fields = { "description": "...new full body..." }
)
```

For label additions, send the full target array (replace, not append):

```
fields = { "labels": ["RoboClaw", "<new-label>"] }
```

### 5.3 Wire a Blocks dependency

Per `createIssueLink` semantics: `inwardIssue` is the **blocker**, `outwardIssue` is the **blocked**. "HUM-2 blocks HUM-3" reads as "HUM-3 is blocked by HUM-2" → `inwardIssue: HUM-2, outwardIssue: HUM-3`.

```
mcp__atlassian__createIssueLink(
  cloudId = "...",
  type = "Blocks",
  inwardIssue = "HUM-2",   # blocker
  outwardIssue = "HUM-3"   # blocked
)
```

Available link types in this Jira: `Blocks`, `Cloners`, `Duplicate`, `Relates`.

### 5.4 Transition status (To Do → In Progress → Done)

Status IDs are project-specific. Use `getTransitionsForJiraIssue` first to find them. Common pattern: when starting work on a card, look up the "Start" or "In Progress" transition; when finishing, look up "Done".

```
t = mcp__atlassian__getTransitionsForJiraIssue(cloudId=..., issueIdOrKey="HUM-N")
# returns array of {id, name} pairs

mcp__atlassian__transitionJiraIssue(
  cloudId = "...", issueIdOrKey = "HUM-N",
  transition = { "id": "<found-id>" }
)
```

### 5.5 List the RoboClaw thread

```
mcp__atlassian__searchJiraIssuesUsingJql(
  cloudId = "...",
  jql = 'project = HUM AND labels = "RoboClaw" ORDER BY key ASC',
  fields = ["summary", "status", "issuelinks"],
  maxResults = 50
)
```

**Note**: result payloads can exceed the MCP response cap (~80 KB). If the call returns a file path instead of inline data, use `python3` (no `jq`) to parse the saved file:

```python
import json
with open("<saved-file-path>") as f:
    data = json.load(f)
for it in data["issues"]["nodes"]:
    print(it["key"], it["fields"]["status"]["name"], it["fields"]["summary"])
```

### 5.6 Post a progress comment

When the executing agent makes partial progress (passed step 1, still working on step 2), it should comment on the card rather than only changing status. Keep comments short and evidence-first:

```
mcp__atlassian__addCommentToJiraIssue(
  cloudId = "...", issueIdOrKey = "HUM-N",
  contentFormat = "markdown",
  body = "Step 1 verified: `/api/health` returns ok. Proceeding to step 2."
)
```

## §6 The current 10-card layout (snapshot as of 2026-05-19)

```
HUM-1 (Epic)  RoboClaw — embodied SO-101 deployment thread
 ├─ HUM-2  T1 Day-N resume (USB + container)
 │   ├─ HUM-3  T2 Bind 4 arms to manifest
 │   │   ├─ HUM-5  T4 Calibrate arms (operator-required)
 │   │   │   └─ HUM-9  T8 First bimanual teleop smoke test
 │   │   │       └─ HUM-10 T9 First dataset recording
 │   │   └─ HUM-9  (same — also blocks T8)
 │   ├─ HUM-4  T3 Bind 3 cameras to manifest
 │   │   └─ HUM-9
 │   ├─ HUM-7  T6 3-camera bandwidth validation
 │   │   └─ HUM-9
 │   └─ HUM-8  T7 30 Hz teleop jitter measurement
 │       └─ HUM-9
 └─ HUM-6  T5 Evaluate upstream auto-calibration (independent; relates HUM-5)
```

T1 is the only unblocked starting task on the hardware path. T5 (HUM-6) is unblocked and read-only — safe parallel work.

## §7 When to add a new card vs. amend an existing one

| Trigger | Action |
|---|---|
| Operator request introduces work not covered by any existing card | New card under HUM-1 with the next `T<N>` number |
| Existing card's acceptance criteria change due to new constraints | Edit the existing card; add a comment summarizing why |
| Sub-decision arises during execution of a card (e.g. "should we use auto-cal?") | Card already covers it (T5/HUM-6) — link with `Relates` not `Blocks` |
| Discovered a regression in already-Done work | New card; link `Relates` to the originally-Done card |

## §8 Anti-patterns to avoid

- Creating cards without the `RoboClaw` label — they vanish from the board's filtered view.
- Using English issue-type names (`Task`, `Epic`) — this project requires the Japanese strings.
- Writing card descriptions that reference *this* conversation ("as we discussed", "from yesterday"). A fresh agent must be able to execute cold. State context explicitly.
- Pre-running acceptance probes for a card and pasting results inside the card — that conflates the brief (what TO do) with the run (what WAS done). Acceptance commands belong as commands; their results belong in comments after the run.
- Modifying upstream code as a side effect of executing a task. Each card declares its anti-scope; respect it.

## §9 Related artifacts

- **Skill** [`roboclaw-deployment`](file:///home/hafnium/.claude/skills/roboclaw-deployment/SKILL.md) — operator runbook for the stack itself.
- **Agent** `roboclaw-jira-coordinator` (at `.claude/agents/roboclaw-jira-coordinator.md`) — spawnable subagent that takes a card key (HUM-N) and drives it end-to-end through the Jira lifecycle.
- **Repo docs** `docs/WSL2_DOCKER_DEPLOYMENT.md`, `docs/FORK_PROGRESS_REPORT.md`, `docs/SO101_BIMANUAL_DRIVER.md` — referenced by individual cards.

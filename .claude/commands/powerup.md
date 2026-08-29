---
description: Interactive lessons teaching Claude Code features with animated demos — pick a power-up to learn what you've been missing
argument-hint: [power-up number 1-10, or leave blank for the menu]
---

# Power-ups

Interactive lessons that teach one Claude Code feature per session — features most people miss. Introduced in v2.1.90.

Reference: [`best-practice/claude-power-ups.md`](../best-practice/claude-power-ups.md)

---

## Phase 1: Select a Power-up

If `$ARGUMENTS` is a number between 1 and 10, jump directly to that power-up in Phase 2.

Otherwise, use the AskUserQuestion tool to present the menu:

**Question:** "Which power-up do you want to learn?"
**Options (show all 10):**

| # | Power-up | Topics |
|---|----------|--------|
| 1 | Talk to your codebase | `@` files, line refs |
| 2 | Steer with modes | `shift+tab`, plan, auto |
| 3 | Undo anything | `/rewind`, `Esc-Esc` |
| 4 | Run in the background | tasks, `/tasks` |
| 5 | Teach Claude your rules | `CLAUDE.md`, `/memory` |
| 6 | Extend with tools | MCP, `/mcp` |
| 7 | Automate your workflow | skills, hooks |
| 8 | Multiply yourself | subagents, `/agents` |
| 9 | Code from anywhere | `/remote-control`, `/teleport` |
| 10 | Dial the model | `/model`, `/effort` |

---

## Phase 2: Teach the Power-up

Deliver the selected lesson using the guide below. Each lesson has:
- **What it is** — one-sentence summary
- **Try it** — a concrete action the user can take right now
- **Pro tip** — a deeper insight most users miss
- **Learn more** — reference to docs or best-practice file

---

### Power-up 1 — Talk to your codebase

**What it is:** Reference files, symbols, and line ranges in your prompt using `@` so Claude reads exactly what you mean.

**Try it:**
```
@src/auth.js:42-60 What does this function do?
@CLAUDE.md Summarize my project rules in one sentence.
```

**Pro tip:** `@` works on URLs too — paste a GitHub file URL and Claude fetches the raw content. Combine multiple `@` references in one prompt to cross-reference files without copy-pasting.

**Learn more:** [CLI Reference — @ file paths](https://code.claude.com/docs/en/cli-reference#file-references)

---

### Power-up 2 — Steer with modes

**What it is:** Three permission modes let you control how much Claude acts vs. plans vs. decides autonomously.

**Try it:**
Press `Shift+Tab` to cycle between modes:
- **Default** — asks for permission on risky actions
- **Plan** — no file edits, only plans (safe exploration)
- **Auto** — background classifier decides what's safe

Or launch directly: `claude --permission-mode plan`

**Pro tip:** Use Plan mode when exploring a large refactor — get a full implementation plan before any file is touched. Switch to Auto mode for routine tasks where permission prompts slow you down.

**Learn more:** [Permission Modes](https://code.claude.com/docs/en/permission-modes)

---

### Power-up 3 — Undo anything

**What it is:** Claude checkpoints every file edit via git. You can rewind to any earlier state without losing your work.

**Try it:**
- Press `Esc Esc` to stop the current task and rewind the last edit
- Type `/rewind` to choose a specific checkpoint to restore

**Pro tip:** Checkpointing is automatic and git-based — each edit creates a snapshot. You can rewind one step or jump back five edits. The working tree is restored exactly, including partial edits mid-task.

**Learn more:** [Checkpointing](https://code.claude.com/docs/en/checkpointing)

---

### Power-up 4 — Run in the background

**What it is:** Start long-running tasks as background agents so you can continue working while Claude handles the heavy lifting.

**Try it:**
```
/tasks          # view all running background tasks
```
Or ask: "Run the full test suite in the background and tell me when it's done."

**Pro tip:** Background tasks use the Agent tool internally and send a notification when complete. You can have multiple tasks running in parallel — each in its own isolated context.

**Learn more:** [Tasks](https://code.claude.com/docs/en/tasks), [Scheduled Tasks](https://code.claude.com/docs/en/scheduled-tasks)

---

### Power-up 5 — Teach Claude your rules

**What it is:** `CLAUDE.md` files inject persistent instructions into every session — your house rules that Claude always follows.

**Try it:**
```
/memory         # view and edit your current memory
```
Or create `.claude/rules/my-rules.md` with project-specific conventions (naming, commit style, forbidden patterns).

**Pro tip:** Scope rules with glob patterns in the frontmatter — `# Glob: **/*.test.ts` means the rule only activates when test files are in context. Layer global (`~/.claude/CLAUDE.md`), project (`.claude/`), and directory-specific rules.

**Learn more:** [`best-practice/claude-memory.md`](../best-practice/claude-memory.md), [Memory docs](https://code.claude.com/docs/en/memory)

---

### Power-up 6 — Extend with tools

**What it is:** MCP (Model Context Protocol) connects Claude to external systems — databases, APIs, Slack, GitHub, your own services.

**Try it:**
```
/mcp            # list connected MCP servers and their tools
```
Then run: `claude mcp add <server-name>` to connect a new server.

**Pro tip:** MCP servers appear as native tools — Claude can call them directly without any glue code. Check the [MCP marketplace](https://code.claude.com/docs/en/mcp-marketplace) for ready-made connectors.

**Learn more:** [`best-practice/claude-mcp.md`](../best-practice/claude-mcp.md), [MCP docs](https://code.claude.com/docs/en/mcp)

---

### Power-up 7 — Automate your workflow

**What it is:** Skills inject reusable instructions on demand; hooks run shell scripts automatically on events like file saves, commits, or session start.

**Try it:**
- Invoke a skill: `/code-review` to review the current diff
- See active hooks: read `.claude/settings.json` → `hooks` section

**Pro tip:** Skills can be preloaded into subagents (via `skills:` frontmatter) so agents always have context-specific knowledge. Hooks let you play a sound, post to Slack, or run tests — without Claude needing to ask.

**Learn more:** [`best-practice/claude-skills.md`](../best-practice/claude-skills.md), [Hooks](https://code.claude.com/docs/en/hooks)

---

### Power-up 8 — Multiply yourself

**What it is:** Subagents are autonomous actors that run in isolated contexts with their own tools, model, and permissions. Spawn multiple in parallel.

**Try it:**
```
/agents         # list defined subagents
```
Or ask: "Spawn two agents in parallel — one to write tests, one to write docs for this module."

**Pro tip:** Subagents inherit nothing from the parent session by default. Use the `skills:` frontmatter to preload knowledge, `tools:` to restrict what they can touch, and `model: haiku` for fast/cheap subtasks.

**Learn more:** [`best-practice/claude-subagents.md`](../best-practice/claude-subagents.md), [Subagents docs](https://code.claude.com/docs/en/sub-agents)

---

### Power-up 9 — Code from anywhere

**What it is:** Remote Control lets you continue a local Claude Code session from any device — phone, tablet, or browser.

**Try it:**
```
/remote-control    # start sharing this session
/rc                # shorthand
```
Or use `/teleport` to move a local session to Claude Code Web for cloud execution.

**Pro tip:** Remote Control generates a shareable link. Open it on your phone to send messages to the local session, view output, and approve permission prompts — all without being at your desk.

**Learn more:** [Remote Control](https://code.claude.com/docs/en/remote-control), [Teleport](https://code.claude.com/docs/en/teleport)

---

### Power-up 10 — Dial the model

**What it is:** Switch models and effort levels mid-session to trade speed for intelligence (or vice versa) on a per-task basis.

**Try it:**
```
/model          # pick a model interactively
/effort high    # maximize reasoning depth for the next task
/effort low     # fastest response, minimal reasoning
```
Or launch with: `claude --model claude-opus-5`

**Pro tip:** Use `/effort max` before asking Claude to design an architecture or debug a subtle race condition — it unlocks extended thinking. Drop back to `/effort low` for quick edits and lookups to save time and cost.

**Learn more:** [Model Config](https://code.claude.com/docs/en/model-config), [Effort levels](https://code.claude.com/docs/en/effort)

---

## Phase 3: Offer Next Steps

After delivering the lesson, ask the user:

> "Want to try another power-up, or shall we apply what you just learned to your current project?"

If they pick another power-up, return to Phase 1. If they want to apply it, help them do so in context.

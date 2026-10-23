---
name: agents-report
description: Analyze local AI coding agent sessions (Claude Code, Codex, Hermes, Pi, OpenCode) for cost, token usage, prompt-cache efficiency, context contents, tool calls, subagents and compaction, and recommend evidence-backed improvements. Use when the user asks what their agent usage costs, why a session was expensive or slow, what is filling the context window, how to cut token spend, to debug or review a past session, or to open the agent observability dashboard.
license: MIT (see LICENSE.txt)
compatibility: Python 3.10+ standard library only (3.14+ or the zstd CLI to read Codex logs). Reads ~/.claude, ~/.codex, ~/.hermes, ~/.pi and ~/.local/share/opencode on the local machine; makes no network calls.
metadata:
  version: "0.1.0"
---

# Agents Report

Deterministic analysis of the agent transcripts already on this machine, with a local visual
dashboard. The scripts gather the data, rank the findings and write the answer; your job is to pick
the command for the question and relay what it prints.

All commands: `python3 scripts/agents_report.py <command>` (run from this skill's directory, or use the
script's absolute path). Every command accepts `--json`. Filters: `--days N`, `--agent claude-code|codex|hermes|pi|opencode`,
`--project NAME`, `--here` (sessions started in the current directory). A session can be named by
its id prefix (`693b1d8d`) or `latest`.

## One command per question

Each question has one command that gathers the data, opens the matching dashboard view, and prints a
finished answer with the dashboard URL in it. Run it and pass its output on. Don't stitch several
commands together or redo its arithmetic.

| The user asks | Run | Then |
| --- | --- | --- |
| Nothing specific (`/agents-report` alone), "open the dashboard", "show me my usage" | `dashboard`, then `brief --days 30 --no-dashboard` | Lead with the dashboard URL (the main view), then relay the brief as is. |
| "What does it cost", "how do I spend less" (or a period: "this week") | `brief --days 30` (or the period they name; omit `--days` for all time) | Relay the output as is. Offer the fix for a recommendation from [references/recommendations.md](references/recommendations.md) if they want it. |
| "Why was this session expensive / slow?" | `explain <session>` (`latest` = most recent here; find others with `sessions --here`) | Relay the output: findings are already ranked by cost and cite request numbers. |
| "What is in my context?" | `context latest`, and `dashboard --session latest --req <N>` with N from its first line | Name the three largest groups exactly as printed. |
| A specific session's numbers | `show <session>` | Quote the lines asked about. |
| A full written report | `report --days 30 --out report.md` | Give the path. |
| A specific dashboard view | `dashboard` (`--view sessions\|recommendations\|sources`, `--session <id>`, `--req N`) | Give the URL it prints. |

The output is deterministic: the same logs give the same text. `--now 2026-10-01` (or `AGENTS_REPORT_NOW`)
pins the clock for a report "as of" a date. Every command accepts `--json`; the answer commands put the
finished text under `"text"`. Filters: `--days N`, `--agent claude-code|codex|hermes|pi|opencode`,
`--project NAME`, `--here`. A session can be named by its id prefix (`693b1d8d`) or `latest`.

All commands: `python3 scripts/agents_report.py <command>` (run from this skill's directory, or use the
script's absolute path). `brief`, `explain` and `dashboard` start or reuse the local dashboard server and
open the browser; add `--no-open` when there is no browser (SSH, CI). They return immediately; don't wrap
them in `&`. The server stops itself about 20 s after the last dashboard tab closes; run `stop` only
when the user asks to stop it now.

Other commands: `sessions [--limit 30]` (list), `recommend` (all recommendations), `doctor` (which agents
were found, parse errors), `package [--out file.zip]` (zip this skill for another agent).

## Rules

- **Relay, don't recompute.** Quote numbers and findings from the output; never compute, round or
  invent your own. If a figure is not in the output, say it is unavailable.
- **Keep the basis.** Say "measured" for values read from logs (tokens, Claude Code's cost meter,
  timestamps) and "estimated" for computed ones (cost from list prices, context shares, savings).
  A dash or `null` means unavailable, not zero. Codex costs are unavailable unless the user adds a
  price file (see [references/metrics.md](references/metrics.md)).
- **Use the shipped dashboard.** `assets/ui/` is prebuilt and served as-is by `dashboard`. Never
  write your own HTML, charts or report page; link the user to the right dashboard view instead.
- **Recommendations are proposals.** Before editing the user's config (CLAUDE.md, AGENTS.md,
  settings.json hooks, MCP servers, subagent definitions), show the change and ask.
- Transcripts can contain secrets and personal data. Summarize; don't paste large raw excerpts,
  and never send them anywhere.

## More

- Metric definitions, cost method and data sources: [references/metrics.md](references/metrics.md)
- Every recommendation rule, its threshold, and the concrete fix: [references/recommendations.md](references/recommendations.md)
- Adding another agent (log format adapter): [references/adapters.md](references/adapters.md)

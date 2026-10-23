# Recommendation rules

Each rule is deterministic (`scripts/agentobs/analyze.py`). When you present one, give the evidence
it lists and the concrete change below. Ask before editing any config file.

| id | Fires when | Concrete change to propose |
| --- | --- | --- |
| `cache-idle-rebuild` | A cache rebuild follows a gap longer than the cache TTL | Finish or `/compact` before long breaks; on return start a fresh session with a short handoff note rather than resuming a 100k+ context. |
| `cache-prefix-change` | ≥3 rebuilds with no idle gap, compaction or model switch | Find what changed early in the prompt: MCP servers connecting mid-session, plugin/skill toggles, CLAUDE.md/AGENTS.md edits, effort or model changes. Keep them stable during a task. |
| `large-tool-outputs` | A tool result over ~40k characters (~10k tokens) | Read with offset/limit, grep for the needed part, cap command output (`| head`, quiet flags), or delegate bulk reading to a subagent that returns a summary. Add a line to CLAUDE.md/AGENTS.md if a specific command is the culprit. |
| `hook-injection` | A hook injects ≥2,000 characters on average | Trim the hook's output in `settings.json` (or the plugin providing it); move long guidance into a skill so it loads only when relevant. |
| `harness-listings` | The skills / MCP / agent / deferred-tool listings average ≥8,000 characters per session | Uninstall or disable unused plugins, skills and MCP servers (`/plugin`, `/mcp`, `settings.json`). Compare against how often the Skill tool and each MCP server were actually used. |
| `subagent-model` | Subagents ran on Opus/Fable with ≥$0.50 re-priceable at a cheaper tier | Set `model: sonnet` (or `haiku`) in the subagent's definition, or pass `model` when spawning. Savings assume equal quality — suggest trying it on a few tasks. |
| `long-context` | Any request over 250k prompt tokens | `/clear` between unrelated tasks; one task per session; hand off with a summary. |
| `tool-errors` | A tool with ≥5 errors and ≥15% error rate | Open the failing calls in the timeline; typical fixes are permission allowlists, correct paths, or toolchain notes in project instructions. |
| `repeated-calls` | A read-only call (Read, Grep, Glob, WebFetch…) repeated with identical input and no file-changing call in between | Usually a sign of lost context after compaction or in a long session; smaller sessions help. |
| `unlogged-spend` | Claude Code's meter exceeds the logged estimate by >$0.25 | Informational: per-request analysis is a lower bound for those sessions. |

Severity: `high` = estimated savings over $5; `medium` = a recurring pattern with cost impact;
`low` = quality or efficiency signal; `info` = context for reading the numbers.

## Interpreting beyond the rules

The rules find patterns; you add judgment. Good questions to ask the data with `show` and `context`:
- Is a large contributor necessary for this kind of work (a loaded skill used once, an MCP server
  whose tools are never called)?
- Did the agent re-read what it already had after a compaction?
- Is one project consistently heavier than others, and is its CLAUDE.md/AGENTS.md the reason?

State which parts are your interpretation and which are measured.

# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-22

First stable release.

### Added

- **Claude Code plugin and skill.** `/agents-report` opens the local dashboard and summarizes the last
  30 days; Claude also uses the skill on its own for questions about cost, tokens, context or a past
  session. The skill follows the agentskills.io format, so Codex and other agents can use it too.
- **Agents supported:** Claude Code (including subagents, exact API requests and its own cost meter),
  Codex, Hermes, Pi and OpenCode.
- **Dashboard** on 127.0.0.1, with no build step and no network access:
  - Overview: spend per day by agent, activity graph, cache hit rate, top sessions.
  - Sessions: timeline with a lane per project (sortable by recent or cost) and a spend-per-day strip
    to pan and zoom; the list can be grouped by project.
  - Session trace: prompts, model calls, tool calls and subagents as a span tree on one clock, with
    duration and cost per span, SLOWEST / PRICIEST / ERROR badges, zoom, a details panel and live
    refresh.
  - Context inspector: rebuilds what any past request put in the context window, by contributor.
  - Recommendations: deterministic rules with evidence, estimated savings and the fix.
- **Answers in one command:** `brief` (spend, cache, top recommendations) and `explain <session>`
  (findings ranked by cost). Output is deterministic; `--now` pins the clock.
- **`agents-report` command,** installable with `uv tool install` or `pipx install`.
- Every number is labelled measured, estimated or unavailable; unknown prices are never shown as $0.

[1.0.0]: https://github.com/viniciusestevam/agents-report/releases/tag/v1.0.0

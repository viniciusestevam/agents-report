# Metrics and method

## Basis of every number

| Basis | Meaning | Examples |
| --- | --- | --- |
| measured | Read from the agent's own logs | Token counts per API response, Claude Code `cost-state.totalCostUSD`, Codex thread `tokens_used`, timestamps, turn durations |
| estimated | Computed by this tool | Cost = tokens × list price; context share by contributor; savings; latency between log lines |
| unavailable | Not in the logs, or no verified price | Codex cost without a price file; tool definitions in transcript-only sessions |

Unavailable values are `null` in JSON and a dash in text. They are never treated as zero.

## Token buckets (normalized across agents)

- `input`: uncached input tokens.
- `cache_read`: prompt tokens served from the prompt cache.
- `cache_write_5m` / `cache_write_1h`: prompt tokens written to the cache, by TTL.
- `output`: output tokens (includes reasoning). `reasoning` is the reasoning share, where logged.
- **Prompt tokens** = input + cache_read + cache writes = everything the model read for a request.
- **Cache hit rate** = cache_read ÷ prompt tokens.

Claude Code writes one log line per content block and repeats the response's usage on each, so usage
is counted once per `message.id`. Codex reports `cached_input_tokens` and `cache_write_input_tokens`
as parts of `input_tokens` (OpenAI convention); they are subtracted to get disjoint buckets.

## Cost

Estimated cost = Σ bucket × price per token for the request's model, with fast mode at 2× and web
searches at $0.01 each. Claude prices come from Anthropic's published rates (see
`scripts/agentobs/pricing.py` for the table and its date): cache writes cost 1.25× (5 min) or 2× (1 h)
the input price; cache reads have a model-specific rate (0.05× on Opus 5.5).

Measured cost (Claude Code only) is the agent's own meter. It includes calls that are not written to
the transcript (titles, classifiers, background work), so it is usually a little higher than the
estimate. Codex logs no cost. To price other models, create `~/.config/agents-report/prices.json`:

```json
{"gpt-6-astra": {"input": 1.25, "output": 10.0, "cache_read": 0.125}}
```

(USD per million tokens; illustrative values — use your provider's published prices.)

## Session metrics

- **Baseline context**: prompt tokens of the first request (system prompt, tools, instructions, first message).
- **Peak context**: largest prompt of any request.
- **Cache rebuild**: a request after the first that writes ≥10k tokens to cache while reading fewer than
  it writes. Cause: `compaction`, `model switch`, `idle gap > TTL`, otherwise `prefix changed`.
  Avoidable cost = rewritten tokens × (write rate − read rate).
- **Carried cost** of a context item (large tool result, hook output) = one cache write + a cache read
  on every later request until the next compaction.
- **Active time**: sum of Claude Code `turn_duration` / Codex `task_complete` durations.
- **Median response gap** (estimated): time from the previous logged event to the first block of a response.

## Context inspector

- `exact-request` basis: Claude Code ≥ 2.1.30x logs every API request as a shape (system + tools) and a
  chain of message hashes (`messages = base.messages[:keep] + tail`). Messages it does not store again
  (the previous response, some tool results) are rebuilt from the transcript. Characters per
  contributor are scaled so they sum to the measured prompt total; the scale factor is reported.
- `transcript` basis: older Claude Code and Codex. Contributors come from logged events and injected
  context; tokens are chars/4, and the gap to the measured total is shown as unattributed.

## Data sources

| Agent | Location | Notes |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/<project>/<session>.jsonl`, subagents in `<session>/subagents/` | `CLAUDE_CONFIG_DIR` overrides `~/.claude` |
| Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl.zst`, titles from `state_*.sqlite` (read-only) | `CODEX_HOME` overrides `~/.codex` |

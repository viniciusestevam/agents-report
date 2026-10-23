# Adding an agent

An adapter is one module in `scripts/agentobs/adapters/` with:

- `AGENT`: a short id (`"claude-code"`).
- `ROOT`: the default log directory (respect an environment override).
- `discover(root=None) -> list[Path]`: one path per session file, or one database holding many sessions (Hermes, OpenCode).
  `util.new_session`, `util.add_event`, `util.request` and `util.sqlite_ro` build the shapes below.
- `parse(path, with_api_log=False) -> list[session]`: the main session first, then any subagents.

Register it in `ADAPTERS` in `scripts/agentobs/store.py` and remove it from `KNOWN_UNSUPPORTED`.

## Session shape

```python
{
  "key": "agent:id", "agent": AGENT, "id": "...", "path": "...", "title": str | None, "first_prompt": str | None,
  "cwd": str | None, "branch": str | None, "version": str | None, "started": epoch | None, "ended": epoch | None,
  "parent_key": None, "subagent": None | {"type", "description", "tool_use_id"}, "children": [keys],
  "requests": [{"msg_id", "request_ref", "request_id", "t", "t_end", "model", "usage", "speed", "web_searches",
                "stop_reason", "effort", "cost", "latency_s", "aggregate"}],   # aggregate=N: a total over N calls (agent logs no per-call usage)
  "events": [{"i", "kind", "t", ...}],   # kind: user | assistant | thinking | tool_call | hook | meta | system | compaction | error
  "compactions": [{"t", "pre_tokens", "trigger"}], "turns": [{"t", "duration_ms"}],
  "context_sources": [{"kind", "name", "chars", "t"}],   # text the harness injected into context
  "measured": None | {"cost_usd", ...}, "stats": {"bad_lines", "records"},
}
```

`usage` uses disjoint buckets: `input, output, cache_read, cache_write_5m, cache_write_1h, reasoning`.
Set `cost` with `pricing.cost(model, usage)`; it returns `None` for unknown models.

## Rules

- Never crash on one bad line or file: count it in `stats`.
- One API response = one entry in `requests`. Deduplicate if the format repeats usage.
- Unknown values are `None`, not 0.
- Add a fixture with hand-computed answers to `tests/fixtures.py` and tests to `tests/test_core.py`.

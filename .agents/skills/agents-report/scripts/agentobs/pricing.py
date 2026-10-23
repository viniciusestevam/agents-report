"""Per-model prices (USD per million tokens). Unknown model -> None, never 0.

Source: Anthropic claude-api skill pricing table (cached 2026-10-06) and prompt-caching
economics (5m write 1.25x input, 1h write 2x input, model-specific read rates).
Verified against Claude Code's own cost-state records by evals/run_evals.py.
Users can add/override prices (e.g. OpenAI models) in ~/.config/agents-report/prices.json:
  {"gpt-6-astra": {"input": 1.0, "output": 8.0, "cache_read": 0.1}}
"""
import json
import os
import re
from pathlib import Path

SOURCE = "Anthropic pricing via claude-api skill, cached 2026-10-06"

# model prefix -> (input, output, cache_read)
_CLAUDE = {
    "claude-fable-5-1": (10, 50, 0.25),
    "claude-mythos-5-1": (10, 50, 0.25),
    "claude-fable-5": (10, 50, 1.0),
    "claude-mythos-5": (10, 50, 1.0),
    "claude-opus-5-5": (4, 20, 0.20),
    "claude-opus-5": (5, 25, 0.50),
    "claude-opus-4-8": (5, 25, 0.50),
    "claude-opus-4-7": (5, 25, 0.50),
    "claude-opus-4-6": (5, 25, 0.50),
    "claude-opus-4-5": (5, 25, 0.50),
    "claude-opus-4-1": (15, 75, 1.50),
    "claude-opus-4": (15, 75, 1.50),
    "claude-sonnet-5-5": (2, 10, 0.20),
    "claude-sonnet-5": (2, 10, 0.20),
    "claude-sonnet-4-6": (3, 15, 0.30),
    "claude-sonnet-4-5": (3, 15, 0.30),
    "claude-sonnet-4": (3, 15, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),  # <=100K prompt; above: 0.50/2.50 (handled below)
    "claude-haiku-4-5": (1, 5, 0.10),
    "claude-3-5-haiku": (0.80, 4, 0.08),
}
FAST_MULTIPLIER = 2.0  # fast mode (Opus 5/5.5/4.8) is 2x standard
WEB_SEARCH_PER_REQUEST = 0.01  # $10 per 1,000 searches


def _user_prices():
    p = Path(os.environ.get("AGENTOBS_PRICES", Path.home() / ".config/agents-report/prices.json"))
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


_USER = _user_prices()


def rates(model):
    """Return dict(input, output, cache_read, cache_write_5m, cache_write_1h, source) or None."""
    if not model:
        return None
    m = model.lower()
    m = re.sub(r"^(us\.|eu\.|global\.)?anthropic\.", "", m)  # bedrock prefixes
    m = re.sub(r"(-\d{8}|@\d{8})(-v\d+:\d+)?$", "", m)  # date suffixes
    m = m.replace("[1m]", "")
    for key, r in _USER.items():
        if m == key.lower() or m.startswith(key.lower() + "-"):
            inp = r["input"]
            return {"input": inp, "output": r["output"], "cache_read": r.get("cache_read", inp * 0.1),
                    "cache_write_5m": r.get("cache_write_5m", inp * 1.25), "cache_write_1h": r.get("cache_write_1h", inp * 2),
                    "source": "user prices.json"}
    for key in sorted(_CLAUDE, key=len, reverse=True):
        if m == key or m.startswith(key + "-"):
            inp, out, read = _CLAUDE[key]
            return {"input": inp, "output": out, "cache_read": read,
                    "cache_write_5m": inp * 1.25, "cache_write_1h": inp * 2, "source": SOURCE}
    return None


def cost(model, usage, speed=None, web_searches=0):
    """USD for one request's normalized usage, or None if the model is unpriced."""
    r = rates(model)
    if r is None:
        return None
    if model and "haiku-5-5" in model and (usage["input"] + usage["cache_read"] + usage["cache_write_5m"] + usage["cache_write_1h"]) > 100_000:
        r = dict(r, input=0.5, output=2.5, cache_read=0.05, cache_write_5m=0.625, cache_write_1h=1.0)
    usd = (usage["input"] * r["input"] + usage["output"] * r["output"] + usage["cache_read"] * r["cache_read"]
           + usage["cache_write_5m"] * r["cache_write_5m"] + usage["cache_write_1h"] * r["cache_write_1h"]) / 1e6
    if speed == "fast":
        usd *= FAST_MULTIPLIER
    return usd + (web_searches or 0) * WEB_SEARCH_PER_REQUEST

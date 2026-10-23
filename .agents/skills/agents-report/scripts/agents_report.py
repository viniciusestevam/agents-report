#!/usr/bin/env python3
"""Agents Report CLI. Run `python3 agents_report.py --help`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agentobs.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

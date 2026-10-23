#!/usr/bin/env python3
"""Check commit messages against Conventional Commits (https://www.conventionalcommits.org).

    python3 tools/check_commits.py --file .git/COMMIT_EDITMSG   # one message (the commit-msg hook)
    python3 tools/check_commits.py --range origin/main..HEAD     # every commit in a range (CI)
"""
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "style", "refactor", "perf", "test", "build", "ci", "chore", "revert")
SUBJECT = re.compile(rf"^({'|'.join(TYPES)})(\([a-z0-9][a-z0-9-]*\))?!?: \S")
MAX = 72
SKIP = ("Merge ", "Revert \"", "fixup! ", "squash! ", "amend! ")  # written by git itself


def problem(msg):
    subject = msg.strip().splitlines()[0] if msg.strip() else ""
    if subject.startswith(SKIP):
        return None
    if not SUBJECT.match(subject):
        return f"{subject!r}: start with <type>(<optional scope>): <summary>, type one of {', '.join(TYPES)}"
    if len(subject) > MAX:
        return f"{subject!r}: subject is {len(subject)} characters; keep it to {MAX}"
    return None


def main(argv):
    if len(argv) == 2 and argv[0] == "--file":
        text = open(argv[1], encoding="utf-8").read()
        msgs = [("this commit", "\n".join(ln for ln in text.splitlines() if not ln.startswith("#")))]
    elif len(argv) == 2 and argv[0] == "--range":
        out = subprocess.run(["git", "log", "--format=%h%x00%B%x01", argv[1]], capture_output=True, text=True, check=True).stdout
        msgs = [tuple(c.strip("\n").split("\x00", 1)) for c in out.split("\x01") if c.strip()]
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    bad = [(ref, p) for ref, m in msgs if (p := problem(m))]
    for ref, p in bad:
        print(f"{ref}: {p}", file=sys.stderr)
    if bad:
        print("See CONTRIBUTING.md#commit-messages.", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

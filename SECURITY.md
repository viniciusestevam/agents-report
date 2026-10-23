# Security policy

Agents Report reads agent transcripts, which can contain source code, secrets and personal data. It is
built to keep them on your machine:

- it makes no network calls;
- the dashboard listens on 127.0.0.1 only, rejects requests whose `Host` header isn't local (DNS
  rebinding), serves only its own files, and sets a strict Content-Security-Policy;
- SQLite stores (Hermes, OpenCode, Codex) are opened read-only.

## Reporting a vulnerability

Please report security issues privately through
[GitHub's private vulnerability reporting](https://github.com/viniciusestevam/agents-report/security/advisories/new)
rather than in a public issue. Include the version (`version` in `skills/agents-report/SKILL.md`),
your OS and Python version, and steps to reproduce. Expect a first reply within a few days.

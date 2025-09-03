# WeDash

Minimal TUI to auto-discover microservices (dirs with both `.we.pid` and `Makefile`) and follow their logs by default.

Quick start (dev):

- Create venv: `uv venv && source .venv/bin/activate`
- Install: `uv pip install -e .`
- Run (minimal columns): `we-dash --root /path/to/repo`
- Run (full columns): `we-dash --columns full`

Key bindings: F/Enter follow, U/D/R up/down/restart, J journal, L last logs, Ctrl+R refresh, Q quit.

Header tabs filter by Active/Failed/All. Search matches name | unit | project (substring, case-insensitive).

# Repository Guidelines

## Project Structure & Modules
- `we_dash/`: Python package.
  - `app.py`: TUI entrypoint and CLI (`we-dash`).
  - `discovery.py`: scans `--root` for services (`.we.pid` + `Makefile`).
  - `commands.py`: wraps `make`/`journalctl`/`systemctl` calls.
  - `models.py`: simple data models.  
  - `app.tcss`: Textual styles.
- Root: `pyproject.toml` (hatchling), `README.md`, `deploy.sh`.

## Build, Run, and Dev
- Create venv: `uv venv && source .venv/bin/activate`
- Editable install: `uv pip install -e .`
- Run locally: `we-dash --root /path/to/monorepo --columns full`
- Build wheel: `hatch build -t wheel` (requires `hatch`), or `python -m build` if using `build`.

CLI flags: `--root` (repeatable), `--max-depth`, `--last`, `--columns minimal|full`.

## Coding Style & Naming
- Python 3.11+, type hints preferred (PEP 484). 4‑space indent, PEP 8 naming: `snake_case` for functions/modules, `CapWords` for classes, `UPPER_SNAKE` for constants.
- Imports local to `we_dash` using absolute package paths.
- Optional tools (not enforced): `ruff` and `black` (line length 88). Example: `ruff check . && black .`.

## Testing Guidelines
- No test suite yet. If adding tests, use `pytest` under `tests/` with files named `test_*.py`. Run via: `pytest -q`.
- Prefer fast, isolated tests; stub external commands where possible.

## Commit & PR Guidelines
- Conventional Commits style is used (e.g., `feat: add X`, `fix: handle Y`, `chore(release): v0.1.4`).
- PRs should include: concise description, linked issues, manual test steps (commands used), and a short TUI screenshot/gif when UI changes.
- Keep changes focused; update `README.md` if flags/usage change. Version bumps and releases are handled during maintainership chores.

## Security & Environment Notes
- WeDash executes `make` targets and queries `systemd`/`journalctl` (user scope). Run against trusted repos only.
- Requires GNU Make and a systemd user session. Limit scans with `--root` and `--max-depth` to avoid traversing large/untrusted trees.

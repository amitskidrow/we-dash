# WeDash — Product Requirements Document (v1)

**Status:** Draft → Finalized layout approved (25% process list / 75% logs)
**Owner:** you
**Editor:** assistant
**Platform:** Python 3.11+, Textual 1.x, Arch Linux (CachyOS) primary, cross‑platform where sane
**Install modes:** `uvx` or `pipx` (git URL), mirrors `watchexec-systemd` `deploy.sh`

---

## 1. Problem & Goals

We need a minimal, robust terminal UI that auto‑discovers running microservices (identified by **presence of both `.we.pid` and `Makefile` in a directory**), lists them, and **by default follows logs** (`make follow`) on open. Operators (humans or agentic CLIs) must be able to trigger a small, fixed set of actions (up/down/restart/logs/journal) without leaving the dashboard.

### Goals

* **Zero‑config discovery** of microservices via filesystem scan (≤ depth 5).
* **Default behavior:** on launch, select first service and run **`make follow`**; stream logs live.
* **Simple, keyboard‑driven UX** with predictable bindings, low moving parts.
* **Fallback logging path:** use run.log tail or `journalctl -f` if `make follow` not present.
* **Portable shell‑outs** (no daemon).

### Non‑Goals

* Process orchestration beyond exposed Makefile targets.
* Metrics/telemetry dashboards (may arrive later).
* Browser UI (Textual Web view possible later but not in v1).

---

## 2. Users & Use Cases

**Primary:** Developer/operator on Arch Linux (terminal), also headless CI hosts.
**Use cases:**

1. Quickly see services discovered in a repo and tail logs immediately.
2. Restart a failed service and keep following its logs.
3. Switch between services with arrow keys; follow/journal with single keys.
4. Filter to Active/Failed; search by name/unit/project.

---

## 3. High‑Level Solution

A Textual TUI app with a **fixed 25/75 split**:

* **Left (25%)**: table of discovered services (Status, Service, PID; optional columns behind horizontal scroll if kept).
* **Right (75%)**: live log pane that auto‑tails `make follow` for the selected service.
* **Header**: Tabs (All/Active/Failed) + Search input.
* **Footer**: visible keybindings.

On selection change or action, a background worker cancels the prior tail and starts a new one. All long‑running work is async subprocess I/O.

---

## 4. Discovery Specification

* **Roots:** by default `cwd`. Optional CLI `--root` args accept multiple paths.
* **Depth:** recursive scan for files named `.we.pid` with **max relative depth = 5**; directories beyond are ignored.
* **Service predicate:** directory qualifies as a *microservice* **iff** it contains both `.we.pid` and `Makefile`.
* **Service name:** parse `SERVICE := <name>` or `SERVICE = <name>` from Makefile; **fallback** to directory name.
* **Derived unit:** format `we-{service}-{hash8}` where `hash8 = sha1(abs_path)[:8]`.
* **PID:** integer from `.we.pid` file if parseable; else 0.
* **Run log:** `<dir>/.we/<service>/run.log` if present.
* **Status probe (lazy):** on row focus or manual refresh run `systemctl --user show -p ActiveState,MainPID --value <unit>` or `is-active` for booleans.

**Edge cases:**

* Multiple `.we.pid` in nested dirs: each directory is a distinct service row.
* Invalid PID contents: treat as unknown (0).
* Missing Makefile: do **not** list (fails predicate).
* Permission errors: skip dir; surface non‑fatal warning in a notifications area.

---

## 5. Command Adapter (Shell‑Out Contract)

All commands execute **in the service’s directory** via `asyncio.create_subprocess_exec`.

**Verbs:**

* **follow** (default): `make follow`. If missing → fallbacks (below).
* **up**: `make up`
* **down**: `make down`
* **restart**: `make restart` (if not present, emulate as down→up only if both exist; otherwise show error)
* **logs (last)**: `make logs` or `journalctl --user -u <unit> -n 200` if missing
* **journal (live)**: `journalctl --user -f -u <unit>`
* **doctor**, **unit**, **ps**: optional buttons/keys; no-op if missing

**Follow fallbacks:**

1. `make follow` (preferred)
2. `tail -F .we/<service>/run.log`
3. `journalctl --user -f -u <unit>`

**Error contract:**

* Missing target: present inline toast and suggest the fallback taken.
* Non‑zero exit: show last N stderr lines in log pane and preserve prior output.

---

## 6. UI/UX Specification

### 6.1 Layout (approved)

* **Grid:** two columns, fixed **25% / 75%**.
* **Header:** title left; right: Tabs \[All | Active | Failed], Search input.
* **Left panel (Table):**

  * Minimal columns for narrow width: **Status, Service, PID** (default).
  * Expandable mode exposes: Unit, Project, Log Path, Updated (horizontal scroll).
  * Row selection with arrows; clicking selects on terminals that support mouse.
* **Right panel (Logs):** sticky toolbar with action buttons; below is streaming log area.
* **Footer:** keybind legends.

### 6.2 Keybindings (defaults)

* **Enter / F:** Follow (start or restart log tail)
* **U / D / R:** Up / Down / Restart
* **J:** Journal (live via systemd)
* **L:** Last logs (200 lines)
* **/**: Focus search
* **Ctrl+R:** Refresh discovery & statuses
* **Q:** Quit

### 6.3 Filtering & Search

* Tabs filter by computed status (Active/Failed/All).
* Search applies to `name | unit | project` (substring, case‑insensitive).

### 6.4 States & Transitions (selection‑centric)

* **Idle → Following:** user selects row or app starts → spawn follow worker.
* **Following → Switching:** user changes row → cancel worker → spawn new follow.
* **Following → Restarting:** user hits **R** → cancel worker → run `make restart` → upon success → resume follow.
* **Error:** surface toast; remain on last stable state; user can retry.

---

## 7. Data Model (in‑memory)

```text
Service {
  name: str
  dir: Path
  pid: int           # from .we.pid, optional/0
  unit: str          # we-{name}-{hash8}
  runlog: Path?      # .we/<name>/run.log if exists
  active: str?       # ActiveState (lazy)
  updated_at: ts?    # computed, for UI only
}
AppState {
  roots: [Path]
  services: [Service]
  selected_index: int
  filter: {'all','active','failed'}
  search: str
}
```

---

## 8. Performance & Robustness

* **Streaming:** async buffered reads; append batched lines to the log widget at \~30–60Hz to avoid UI thrash.
* **Cancellation:** always cancel prior worker before starting a new one to prevent zombie tails.
* **Status probe:** on focus or on a debounce timer (e.g., every 10s) to avoid spamming systemd.
* **Large logs:** limit initial fetch (`-n 200`) and rely on `-F` follow; provide a “Clear” action in the toolbar.

---

## 9. Security & Safety

* Shell‑outs are confined to discovered service directories.
* Do not interpolate untrusted values directly; pass argv arrays to `create_subprocess_exec`.
* No elevation; user‑level `systemctl --user` only.

---

## 10. Configuration

* **CLI flags:**

  * `--root PATH` (repeatable)
  * `--max-depth INT` (default 5)
  * `--columns minimal|full` (default minimal)
  * `--follow-cmd CMD` (advanced override; default `make follow`)
  * `--last N` (default 200)
* **Env:** none required.
* **Config file (later):** TOML under `~/.config/we-dash/config.toml` for keymap/theme.

---

## 11. Packaging & Distribution

* **uvx:** publish as `we-dash` with entry point `we_dash.app:main`.
* **pipx:** `pipx install git+<repo-url>#subdirectory=we-dashboard`
* **Binary name:** `we-dash`
* **Dependencies:** `textual>=1.0,<2`, stdlib only; optional `systemd` available by shell.

---

## 12. Deploy Workflow

- Provide a `deploy.sh` (same mechanism as in `watchexec-systemd`) that:
  - Bumps patch version in `pyproject.toml` (and updates any `--version` echo in shell entrypoints if present).
  - Commits and pushes to `main` with a timestamped message (e.g., `chore(release): vX.Y.Z (YYYY-MM-DD HH:MM:SS)`).
  - Waits briefly for the remote to update, then smoke‑tests install paths:
    - Ephemeral: `uvx --from <origin_vcs_spec> we-dash --version`.
    - Preferred global: `uv tool install --force --from <origin_vcs_spec> we-dash`.
    - Fallback global: `pipx install --force --spec <origin_vcs_spec> we-dash`.
  - Prints `we-dash --version` and shows all PATH candidates for diagnostics.
- Environment toggles (optional, for local ops parity):
  - `WE_DASH_FORCE_CLEAN=1` → uninstall prior global installs (uv, pipx, pip) and remove shims before reinstalling.
  - `WE_DASH_CLEAN_LOCAL_VENV=1` → if an active virtualenv shadows `we-dash`, uninstall from that venv.
- The `<origin_vcs_spec>` is derived from `git remote get-url origin`, normalized as `git+https://...@main` if needed, identical to the normalization used in `watchexec-systemd`.

---

## 12. Accessibility & Theming

* Works on dark terminals; provide high‑contrast theme option.
* All actions accessible via keyboard; mouse optional.

---

## 13. Telemetry & Logging (optional, off by default)

* Local debug log via `--debug` to stderr.
* No remote telemetry.

---

## 14. Testing Strategy

* **Unit:** discovery parser, Makefile `SERVICE` extraction, unit derivation, fallback ladder selection.
* **Integration (hermetic):** spawn dummy `tail -f` subprocess and ensure worker cancellation/respawn works.
* **End‑to‑end (manual):** run against sample monorepo; validate keybinds, fallbacks, and error toasts.

**Acceptance Criteria (MVP):**

1. Launch in a repo with 2+ services; first service auto‑follows logs.
2. Arrow selection + Enter switches follow without hangs or leaks.
3. When `make follow` is absent, tool tails run.log or journal automatically.
4. U/D/R/J/L perform the documented commands in the right directory.
5. Tabs & search filter the table without breaking follow.
6. Exits cleanly; no orphaned child processes.

---

## 15. Release Plan

* **v0 (MVP):** discovery, table, follow default, actions, fallbacks, search/tabs, keybinds.
* **v1:** per‑service tabs, periodic status refresh, runtime keymap config, minimal theming.
* **v2:** multi‑root switcher, persisted layout, optional metrics row (PID, uptime, restarts).

---

## 16. Open Questions

* Should we persist last selected service per root (dotfile) to restore follow on next launch?
* Do we want an explicit refresh key **Ctrl+R** or rely only on focus/selection probes?
* Minimal vs full columns default — keep minimal for the 25% pane?

---

## 17. Appendix — UI Wireframe (text)

```
┌ Header: [All][Active][Failed]  Search: [           ]              ┐
│                                                                    │
├─ Services (25%) ─────────────────┬────────────── Logs (75%) ───────┤
│  Status  Service            PID   │  [Follow][Up][Down][Restart]    │
│  ●active market-data-svc   31472 │  [Journal][Last]                 │
│  ●active indicator-svc     31890 │  ─────────────────────────────   │
│  ●failed single-agent         0  │  2025-09-01T12:00Z INFO ...      │
│  ○inact  pnl-svc               0 │  ... (streaming)                 │
├──────────────────────────────────┴──────────────────────────────────┤
│ Footer: Enter/F Follow · U Up · D Down · R Restart · J Journal · / │
└────────────────────────────────────────────────────────────────────┘
```

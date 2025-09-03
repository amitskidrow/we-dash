from __future__ import annotations

import argparse
import asyncio
from asyncio import Task
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.widgets import DataTable, Footer, Input, Tabs, Tab, RichLog, Label

from .discovery import discover_services
from .models import AppState, Service
from .commands import (
    follow_argv,
    last_logs_argv,
    up_argv,
    down_argv,
    restart_sequence,
    run_command,
    probe_status,
)


class WeDashApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("enter", "do_follow", "Follow"),
        Binding("f", "do_follow", "Follow"),
        Binding("u", "do_up", "Up"),
        Binding("d", "do_down", "Down"),
        Binding("r", "do_restart", "Restart"),
        Binding("j", "do_journal", "Journal"),
        Binding("l", "do_last", "Last logs"),
        Binding("/", "focus_search", "Search"),
        Binding("ctrl+r", "do_refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, state: AppState, last: int = 200, columns: str = "minimal") -> None:
        super().__init__()
        self.state = state
        self.last = last
        self.columns_mode = columns
        self.table: DataTable | None = None
        # Avoid clashing with Textual App.log (read-only property)
        self.log_widget: RichLog | None = None
        self._rows: list[int] = []  # maps row index -> service index
        self._follow_task: Task | None = None
        self._status_task: Task | None = None

    def compose(self) -> ComposeResult:
        with Container(id="header"):
            with Horizontal():
                yield Label("WeDash", id="title")
                yield Tabs(
                    Tab("All", id="tab-all"),
                    Tab("Active", id="tab-active"),
                    Tab("Failed", id="tab-failed"),
                    id="tabs",
                    active="tab-all",
                )
                yield Input(placeholder="Search name|unit|project", id="search")

        with Container(id="content-left"):
            self.table = DataTable(zebra_stripes=True, cursor_type="row")
            if self.columns_mode == "full":
                self.table.add_columns("Status", "Service", "PID", "Unit", "Project", "Log Path", "Updated")
            else:
                self.table.add_columns("Status", "Service", "PID")
            yield self.table

        with Container(id="content-right"):
            self.log_widget = RichLog(highlight=False, markup=False, wrap=False)
            self.log_widget.write("WeDash — select a service to follow logs…")
            yield self.log_widget

        yield Footer(id="footer")

    async def on_mount(self) -> None:
        # Populate table
        self._rebuild_table(select_same=False)
        if self.state.services:
            self._select_row(0)
            await self._start_follow(self.state.services[0])
        # Periodic status refresher
        self._status_task = asyncio.create_task(self._periodic_status_refresh())

    async def on_unmount(self) -> None:
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
            with suppress(Exception):
                await self._follow_task
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
            with suppress(Exception):
                await self._status_task

    def _rebuild_table(self, select_same: bool = True) -> None:
        assert self.table
        cur_idx = self.state.selected_index
        self.table.clear(columns=False)
        self._rows = []
        for idx in self._visible_indices():
            svc = self.state.services[idx]
            self._add_row(idx, svc)
            self._rows.append(idx)
        # try keep selection
        if select_same and self._rows:
            try:
                row = self._rows.index(cur_idx)
            except ValueError:
                row = 0
            self._select_row(row)

    def _select_row(self, row_index: int) -> None:
        assert self.table
        if 0 <= row_index < len(self._rows):
            self.table.cursor_coordinate = (row_index, 0)
            self.state.selected_index = self._rows[row_index]

    def _selected_service(self) -> Service | None:
        if not self.table:
            return None
        row = self.table.cursor_row
        if row is None:
            return None
        if 0 <= row < len(self._rows):
            svc_idx = self._rows[row]
            return self.state.services[svc_idx]
        return None

    async def action_do_follow(self) -> None:
        svc = self._selected_service()
        if svc:
            await self._start_follow(svc)

    @on(DataTable.RowHighlighted)
    async def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # Update selected index
        # Textual changed the event attribute from `row_index` -> `cursor_row`.
        # Support both to avoid crashes across versions.
        row = getattr(event, "row_index", None)
        if row is None:
            row = getattr(event, "cursor_row", None)
        if row is None and self.table is not None:
            row = self.table.cursor_row
        if row is None:
            return
        if not (0 <= row < len(self._rows)):
            return
        idx = self._rows[row]
        self.state.selected_index = idx
        # Probe and update status lazily
        if 0 <= idx < len(self.state.services):
            svc = self.state.services[idx]
            active, pid = await probe_status(svc)
            if active:
                svc.active = active
                if pid is not None:
                    svc.pid = pid
            # Update table row
            self._update_row_by_row(row, svc)
            # Auto-follow when moving selection
            await self._start_follow(svc)

    def _add_row(self, idx: int, svc: Service) -> None:
        assert self.table
        status = svc.active or "?"
        if self.columns_mode == "full":
            log_path = str(svc.runlog) if svc.runlog else "-"
            updated = self._format_updated(svc)
            self.table.add_row(status, svc.name, str(svc.pid), svc.unit, svc.project or "-", log_path, updated)
        else:
            self.table.add_row(status, svc.name, str(svc.pid))

    def _update_row_by_row(self, row: int, svc: Service) -> None:
        assert self.table
        status = svc.active or "?"
        self.table.update_cell_at((row, 0), status)
        self.table.update_cell_at((row, 1), svc.name)
        self.table.update_cell_at((row, 2), str(svc.pid))
        if self.columns_mode == "full":
            self.table.update_cell_at((row, 3), svc.unit)
            self.table.update_cell_at((row, 4), svc.project or "-")
            self.table.update_cell_at((row, 5), str(svc.runlog) if svc.runlog else "-")
            self.table.update_cell_at((row, 6), self._format_updated(svc))

    async def action_do_last(self) -> None:
        svc = self._selected_service()
        if not svc:
            return
        argv = last_logs_argv(svc, last=self.last)
        await self._run_one_shot(argv, svc)

    async def action_do_journal(self) -> None:
        svc = self._selected_service()
        if svc:
            await self._start_follow(svc, force_journal=True)

    async def action_do_up(self) -> None:
        from .commands import has_target
        svc = self._selected_service()
        if not svc:
            return
        if not has_target(svc, "up"):
            self._toast("Missing 'up' target in Makefile")
            return
        await self._run_one_shot(up_argv(svc), svc)

    async def action_do_down(self) -> None:
        from .commands import has_target
        svc = self._selected_service()
        if not svc:
            return
        if not has_target(svc, "down"):
            self._toast("Missing 'down' target in Makefile")
            return
        await self._run_one_shot(down_argv(svc), svc)

    async def action_do_restart(self) -> None:
        svc = self._selected_service()
        if not svc:
            return
        seq = await restart_sequence(svc)
        if not seq:
            self._toast("Restart not supported; missing targets")
            return
        if len(seq) == 2:
            self._toast("Emulating restart: down → up")
        for argv in seq:
            rc = await self._run_one_shot(argv, svc)
            if rc != 0:
                break

    async def action_focus_search(self) -> None:
        # Placeholder until search widget exists
        self._toast("Search not implemented yet")

    async def action_do_refresh(self) -> None:
        # Re-discover services and refresh table
        self.state.services = discover_services(self.state.roots)
        self._rebuild_table(select_same=True)
        if self.state.services:
            if not self._rows:
                return
            self._select_row(0)

    @on(Tabs.TabActivated)
    def _on_tabs_changed(self, event: Tabs.TabActivated) -> None:
        tab_id = event.tab.id or "tab-all"
        if tab_id.endswith("all"):
            self.state.filter = "all"
        elif tab_id.endswith("active"):
            self.state.filter = "active"
        elif tab_id.endswith("failed"):
            self.state.filter = "failed"
        self._rebuild_table(select_same=True)

    @on(Input.Changed)
    def _on_search_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.state.search = event.value
            self._rebuild_table(select_same=True)

    async def _start_follow(self, svc: Service, force_journal: bool = False) -> None:
        # Cancel previous task
        if self._follow_task and not self._follow_task.done():
            self._follow_task.cancel()
            with suppress(Exception):
                await self._follow_task

        assert self.log_widget
        self.log_widget.clear()
        if force_journal:
            argv = ["journalctl", "--user", "-f", "-u", svc.unit]
        else:
            argv = follow_argv(svc)
        self.log_widget.write(f"$ {' '.join(argv)}\n")

        async def _runner():
            def _out(line: str):
                assert self.log_widget
                self.log_widget.write(line.rstrip("\n"))

            def _err(line: str):
                assert self.log_widget
                self.log_widget.write(line.rstrip("\n"))

            try:
                rc = await run_command(argv, cwd=svc.dir, on_stdout_line=_out, on_stderr_line=_err)
                self.log_widget.write(f"\n[exit {rc}]")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.log_widget.write(f"\n[error: {e}]")

        self._follow_task = asyncio.create_task(_runner())

    async def _run_one_shot(self, argv: list[str], svc: Service) -> int:
        assert self.log_widget
        self.log_widget.write(f"$ {' '.join(argv)}\n")

        lines: list[str] = []

        def _out(line: str):
            lines.append(line.rstrip("\n"))

        def _err(line: str):
            lines.append(line.rstrip("\n"))

        rc = await run_command(argv, cwd=svc.dir, on_stdout_line=_out, on_stderr_line=_err)
        for ln in lines:
            self.log_widget.write(ln)
        self.log_widget.write(f"\n[exit {rc}]")
        return rc

    def _toast(self, msg: str) -> None:
        # Minimal inline notification
        assert self.log_widget
        self.log_widget.write(f"[note] {msg}")

    def _visible_indices(self) -> list[int]:
        # Compute visible based on filter + search
        def matches_search(svc: Service) -> bool:
            q = self.state.search.strip().lower()
            if not q:
                return True
            hay = " ".join(filter(None, [svc.name, svc.unit, svc.project or ""]))
            return q in hay.lower()

        def matches_filter(svc: Service) -> bool:
            f = self.state.filter
            a = (svc.active or "").lower()
            if f == "all":
                return True
            if f == "active":
                return a == "active"
            if f == "failed":
                return a == "failed"
            return True

        return [i for i, s in enumerate(self.state.services) if matches_search(s) and matches_filter(s)]

    def _format_updated(self, svc: Service) -> str:
        import time
        if not svc.updated_at:
            return "-"
        return time.strftime("%H:%M:%S", time.localtime(svc.updated_at))

    async def _periodic_status_refresh(self) -> None:
        import time
        while True:
            try:
                await asyncio.sleep(10)
                # Probe visible services
                rows = list(range(len(self._rows)))
                # Limit concurrency
                sem = asyncio.Semaphore(4)

                async def probe_row(row: int):
                    async with sem:
                        idx = self._rows[row]
                        svc = self.state.services[idx]
                        active, pid = await probe_status(svc)
                        changed = False
                        if active and active != svc.active:
                            svc.active = active
                            changed = True
                        if pid is not None and pid != svc.pid:
                            svc.pid = pid
                            changed = True
                        if changed:
                            svc.updated_at = time.time()
                            self._update_row_by_row(row, svc)

                await asyncio.gather(*(probe_row(r) for r in rows))
            except asyncio.CancelledError:
                break
            except Exception:
                # Non-fatal
                continue


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="we-dash", description="WeDash TUI")
    p.add_argument("--root", action="append", default=[Path.cwd()], type=Path, help="Root path to scan (repeatable)")
    p.add_argument("--max-depth", type=int, default=5, help="Max scan depth")
    p.add_argument("--last", type=int, default=200, help="Last N lines for logs()")
    p.add_argument("--columns", choices=["minimal", "full"], default="minimal")
    return p.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    ns = parse_args(argv)
    roots = [Path(r) for r in ns.root]
    state = AppState(roots=roots)
    state.services = discover_services(roots, max_depth=ns.max_depth)
    app = WeDashApp(state=state, last=ns.last, columns=ns.columns)
    app.run()


if __name__ == "__main__":
    main()

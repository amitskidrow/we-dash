from __future__ import annotations

import asyncio
import re
from asyncio.subprocess import PIPE
from pathlib import Path
from functools import lru_cache
from typing import Iterable

from .models import Service


_TARGET_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:\s*")


@lru_cache(maxsize=512)
def _cached_targets(path_str: str, mtime: float) -> set[str]:
    """LRU-cached parser for Makefile targets keyed by path + mtime."""
    p = Path(path_str)
    targets: set[str] = set()
    try:
        for line in p.read_text(errors="ignore").splitlines():
            m = _TARGET_RE.match(line)
            if m:
                targets.add(m.group(1))
    except Exception:
        # On any error, return empty set and cache it; mtime key invalidates later
        return set()
    return targets


def _make_targets(makefile: Path) -> set[str]:
    try:
        st = makefile.stat()
        mtime = st.st_mtime
    except Exception:
        return set()
    return _cached_targets(str(makefile), mtime)


def has_target(service: Service, target: str) -> bool:
    return target in _make_targets(service.dir / "Makefile")


def follow_argv(service: Service) -> list[str]:
    """Return argv for follow with fallbacks: make follow -> tail run.log -> journalctl."""
    if has_target(service, "follow"):
        return ["make", "follow"]
    if service.runlog is not None:
        return ["tail", "-F", str(service.runlog)]
    return [
        "journalctl",
        "--user",
        "-f",
        "-u",
        service.unit,
    ]


def last_logs_argv(service: Service, last: int = 200) -> list[str]:
    if has_target(service, "logs"):
        return ["make", "logs"]
    return [
        "journalctl",
        "--user",
        "-n",
        str(last),
        "-u",
        service.unit,
    ]


def up_argv(service: Service) -> list[str]:
    return ["make", "up"]


def down_argv(service: Service) -> list[str]:
    return ["make", "down"]


async def restart_sequence(service: Service) -> list[list[str]] | None:
    """Return sequence of argv to emulate restart if target missing.

    - If `restart` target exists, run that as a single step.
    - Else if both `down` and `up` exist, emulate restart with two steps.
    - Else return None to signal unsupported.
    """
    if has_target(service, "restart"):
        return [["make", "restart"]]
    targets = _make_targets(service.dir / "Makefile")
    if {"down", "up"}.issubset(targets):
        return [["make", "down"], ["make", "up"]]
    return None


async def run_command(
    argv: list[str],
    cwd: Path,
    on_stdout_line: callable | None = None,
    on_stderr_line: callable | None = None,
) -> int:
    """Run a command streaming output via provided callbacks."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), stdout=PIPE, stderr=PIPE
    )

    async def _stream(reader, cb):
        if cb is None:
            # Drain
            while True:
                b = await reader.readline()
                if not b:
                    break
        else:
            while True:
                b = await reader.readline()
                if not b:
                    break
                try:
                    cb(b.decode(errors="ignore"))
                except Exception:
                    pass

    await asyncio.gather(_stream(proc.stdout, on_stdout_line), _stream(proc.stderr, on_stderr_line))
    return await proc.wait()


async def probe_status(service: Service) -> tuple[str | None, int | None]:
    """Return (ActiveState, MainPID) via systemctl --user show.

    On error, returns (None, None).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl",
            "--user",
            "show",
            "-p",
            "ActiveState,MainPID",
            service.unit,
            stdout=PIPE,
            stderr=PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            return None, None
        active = None
        pid = None
        for line in out.decode(errors="ignore").splitlines():
            if line.startswith("ActiveState="):
                active = line.split("=", 1)[1].strip()
            elif line.startswith("MainPID="):
                val = line.split("=", 1)[1].strip()
                pid = int(val) if val.isdigit() else None
        return active, pid
    except Exception:
        return None, None

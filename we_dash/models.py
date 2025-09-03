from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class Service:
    name: str
    dir: Path
    pid: int
    unit: str
    runlog: Path | None
    project: str | None = None
    active: str | None = None
    updated_at: float | None = None


Filter = Literal["all", "active", "failed"]


@dataclass(slots=True)
class AppState:
    roots: list[Path] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    selected_index: int = 0
    filter: Filter = "all"
    search: str = ""

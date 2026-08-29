"""Runner contract: every compute target implements Runner.launch()."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.models import Notebook, Run


@dataclass
class LaunchResult:
    status: str
    external_url: str = ""
    logs: str = ""
    error: str = ""
    metrics: dict = field(default_factory=dict)
    instructions: list[str] = field(default_factory=list)


class Runner(Protocol):
    name: str

    def launch(self, run: Run, notebook: Notebook) -> LaunchResult: ...

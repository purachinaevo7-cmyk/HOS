"""Notification interfaces for HOS Investment Agent."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class Notifier(Protocol):
    def notify(self, report: str) -> None: ...


class ConsoleNotifier:
    def notify(self, report: str) -> None:
        print(report)


class GitHubSummaryNotifier:
    def __init__(self, summary_path: str | None = None) -> None:
        self.summary_path = summary_path or os.getenv("GITHUB_STEP_SUMMARY")

    def notify(self, report: str) -> None:
        if not self.summary_path:
            return
        Path(self.summary_path).write_text(f"## Investment Agent Report\n\n```text\n{report}\n```\n", encoding="utf-8")

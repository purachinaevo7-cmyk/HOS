"""Notification interfaces for HOS Investment Agent."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol
from urllib import request


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


class DiscordNotifier:
    """Send investment reports to Discord when a webhook URL is configured."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")

    def notify(self, report: str) -> None:
        if not self.webhook_url:
            return

        payload = json.dumps({"content": self._format_message(report)}).encode("utf-8")
        webhook_request = request.Request(
            self.webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "HOS Investment Agent"},
            method="POST",
        )
        with request.urlopen(webhook_request, timeout=10) as response:
            response.read()

    @staticmethod
    def _format_message(report: str) -> str:
        # Discord's content limit is 2,000 characters. Keep room for code fences.
        max_report_length = 1_980
        trimmed_report = report if len(report) <= max_report_length else f"{report[: max_report_length - 20]}\n...（省略）"
        return f"```text\n{trimmed_report}\n```"

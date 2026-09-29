"""Notification interface. Discord now; Slack / LINE implement the same Protocol."""

from __future__ import annotations

from typing import Protocol

from usmarket.models import DailySummary


class Notifier(Protocol):
    name: str

    def send(self, summary: DailySummary, page_url: str, *, dry_run: bool = False) -> dict[str, object]:
        """Send the daily digest. Returns the payload that was (or would be) sent."""
        ...

    def send_error(self, message: str, *, dry_run: bool = False, run_url: str | None = None) -> None: ...

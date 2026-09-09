"""Lightweight progress reporting shared by application entry points."""

from __future__ import annotations

from collections.abc import Callable

ProgressCallback = Callable[[str], None]


def report_progress(callback: ProgressCallback | None, message: str) -> None:
    """Publish a calculation milestone when a caller requested progress.

    :param callback: Optional sink such as a server-console reporter.
    :param message: Human-readable step and progress detail.
    :return: None.
    """

    if callback is not None:
        callback(message)

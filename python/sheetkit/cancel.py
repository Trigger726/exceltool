"""Cooperative cancellation shared by the engine and the desktop bridge.

Long jobs check the flag between rows, so stopping one is immediate and the
already finished work is simply thrown away. Nothing is left half written:
the exporters write to a temporary file and move it into place at the end.
"""

from __future__ import annotations

import threading

from .errors import TaskCancelledError


def raise_if_cancelled(cancel: threading.Event | None, stage: str = '') -> None:
    if cancel is not None and cancel.is_set():
        suffix = f'（{stage}）' if stage else ''
        raise TaskCancelledError(f'操作已取消{suffix}')

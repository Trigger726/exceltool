"""In-memory storage for the desktop bridge.

A merge of 50k rows must never be pushed through the JSON boundary, so the
engine keeps its result objects here and the bridge hands the frontend one page
of text rows at a time. Nothing is written to disk, and everything is dropped
when the window closes, so no business data survives the session.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .values import display_text

MAX_RESULTS = 8
DEFAULT_PAGE = 50
MAX_PAGE = 500


@dataclass
class ResultTable:
    """One pageable, filterable table inside a result."""

    columns: list[str]
    rows: list[list[Any]]

    def page(
        self, offset: int = 0, limit: int = DEFAULT_PAGE, filter_text: str = ''
    ) -> dict:
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), MAX_PAGE))
        needle = (filter_text or '').strip().casefold()

        rows = self.rows
        if needle:
            rows = [
                row
                for row in rows
                if any(needle in display_text(cell).casefold() for cell in row)
            ]
        window = rows[offset : offset + limit]
        return {
            'columns': list(self.columns),
            'rows': [[display_text(cell) for cell in row] for row in window],
            'offset': offset,
            'limit': limit,
            'total': len(rows),
            'unfiltered_total': len(self.rows),
            'filter': filter_text or '',
        }


@dataclass
class StoredResult:
    kind: str
    summary: dict
    tables: dict[str, ResultTable] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class ResultStore:
    """Bounded registry of the results the frontend may still page through."""

    def __init__(self, limit: int = MAX_RESULTS) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[str, StoredResult] = OrderedDict()
        self._counter = 0
        self._limit = limit

    def put(self, result: StoredResult) -> str:
        with self._lock:
            self._counter += 1
            key = f'result-{self._counter}'
            self._items[key] = result
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
            return key

    def get(self, key: str) -> StoredResult | None:
        with self._lock:
            return self._items.get(key)

    def drop(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

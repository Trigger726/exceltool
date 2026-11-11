"""Shared fixtures: workbook/CSV factories and a real Windows file lock."""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Any, Iterable, Sequence

import pytest
from openpyxl import Workbook

WINDOWS = sys.platform == 'win32'
GENERIC_READ = 0x80000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def write_xlsx(
    path: str,
    headers: Sequence[Any],
    rows: Iterable[Sequence[Any]],
    *,
    sheet: str = '数据',
    preamble_rows: Iterable[Sequence[Any]] = (),
    extra_sheets: dict[str, tuple[Sequence[Any], Iterable[Sequence[Any]]]] | None = None,
) -> str:
    """Create a workbook whose header sits after `preamble_rows`."""
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in preamble_rows:
        worksheet.append(list(row))
    worksheet.append(list(headers))
    for row in rows:
        worksheet.append(list(row))
    for name, (head, body) in (extra_sheets or {}).items():
        extra = workbook.create_sheet(name)
        extra.append(list(head))
        for row in body:
            extra.append(list(row))
    workbook.save(path)
    return path


def write_csv(
    path: str,
    headers: Sequence[Any],
    rows: Iterable[Sequence[Any]],
    *,
    encoding: str = 'utf-8-sig',
    delimiter: str = ',',
    preamble_rows: Iterable[Sequence[str]] = (),
) -> str:
    lines: list[str] = []
    for row in preamble_rows:
        lines.append(delimiter.join(str(cell) for cell in row))
    lines.append(delimiter.join(str(cell) for cell in headers))
    for row in rows:
        lines.append(delimiter.join('' if cell is None else str(cell) for cell in row))
    with open(path, 'w', encoding=encoding, newline='') as handle:
        handle.write('\r\n'.join(lines) + '\r\n')
    return path


@pytest.fixture
def xlsx(tmp_path):
    def factory(name: str, *args, **kwargs) -> str:
        return write_xlsx(str(tmp_path / name), *args, **kwargs)

    return factory


@pytest.fixture
def csv_file(tmp_path):
    def factory(name: str, *args, **kwargs) -> str:
        return write_csv(str(tmp_path / name), *args, **kwargs)

    return factory


@pytest.fixture
def lock_marker():
    """Create the "~$file.xlsx" owner marker Excel/WPS leave behind."""

    def factory(path: str) -> str:
        folder, name = os.path.split(path)
        marker = os.path.join(folder, '~$' + name)
        with open(marker, 'wb') as handle:
            handle.write(b'\x00' * 162)
        return marker

    return factory


@pytest.fixture
def exclusive_lock():
    """Hold a real share-deny-all handle on a file, the way Excel does.

    Returns None when the platform has no CreateFileW, so tests can skip.
    """
    handles: list[int] = []

    def factory(path: str):
        if not WINDOWS:
            pytest.skip('exclusive file locking is Windows specific')
        handle = ctypes.windll.kernel32.CreateFileW(  # type: ignore[attr-defined]
            path,
            GENERIC_READ,
            0,  # no sharing at all
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle is None:
            pytest.fail(f'could not acquire exclusive lock on {path}')
        handles.append(handle)
        return handle

    yield factory

    for handle in handles:
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]

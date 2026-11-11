"""Safe .xlsx export for all three features.

Guarantees enforced here:

* Inputs are never opened for writing. The destination is validated against the
  input list, so exporting onto a source file is refused.
* Text that begins with "=" is written with an explicit string data type, so a
  cell value such as `=cmd|'/C calc'!A0` can never become a live formula.
* Integers longer than Excel's 15 significant digits are written as text instead
  of being silently rounded.
* The file is written to a temporary sibling and moved into place, so a failure
  half-way through never leaves a truncated report behind.
"""

from __future__ import annotations

import atexit
import datetime as dt
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .cancel import raise_if_cancelled
from .errors import ExportError, TaskCancelledError
from .values import display_text
from . import validators

MAX_SHEET_ROWS = 1_048_575
MAX_SAFE_INTEGER_DIGITS = 15
FORMULA_PREFIX = '='

HEADER_FILL = 'FFF1F2F4'
HEADER_FONT_COLOR = 'FF3F444C'
BORDER_COLOR = 'FFDCE0E4'

TINTS: dict[str, str] = {
    'added': 'FFE9F7EE',
    'deleted': 'FFFDECEC',
    'modified': 'FFFDF4E3',
    'anomaly': 'FFF1F2F4',
    'neutral': '00000000',
}

_INVALID_SHEET_NAME = re.compile(r'[\\/*?:\[\]]')

TEMP_PREFIX = '.sheetkit-'
TEMP_SUFFIX = '.tmp'
# A temporary file older than this can only come from a run that was killed
# outright, so it is safe to remove.
STALE_TEMP_SECONDS = 24 * 3600

_active_temps: set[str] = set()


def _cleanup_temps() -> None:
    for path in list(_active_temps):
        _discard(path)
    _active_temps.clear()


atexit.register(_cleanup_temps)


def _sweep_stale_temps(folder: str) -> None:
    """Remove leftovers from a run that was killed before it could tidy up."""
    try:
        entries = os.listdir(folder)
    except OSError:
        return
    now = time.time()
    for name in entries:
        if not (name.startswith(TEMP_PREFIX) and name.endswith(TEMP_SUFFIX)):
            continue
        full = os.path.join(folder, name)
        try:
            if now - os.path.getmtime(full) < STALE_TEMP_SECONDS:
                continue
            os.remove(full)
        except OSError:
            continue


@dataclass
class SheetSpec:
    name: str
    headers: list[str]
    rows: Sequence[Sequence[Any]] | Iterable[Sequence[Any]]
    tint: Callable[[int, Sequence[Any]], str] | None = None
    widths: list[float] | None = None
    freeze_header: bool = True
    wrap_columns: tuple[int, ...] = ()
    # Tinting builds a styled cell object per cell, which is far slower than
    # appending plain values. Very large sheets keep the colour for the leading
    # rows and fall back to the fast path instead of taking minutes to export.
    tint_row_limit: int = 20000

    def iter_rows(self) -> Iterable[Sequence[Any]]:
        return self.rows


@dataclass
class WorkbookSpec:
    sheets: list[SheetSpec] = field(default_factory=list)
    properties_title: str = 'SheetKit'

    def add(self, spec: SheetSpec) -> 'WorkbookSpec':
        self.sheets.append(spec)
        return self


def safe_sheet_name(name: str, used: set[str]) -> str:
    cleaned = _INVALID_SHEET_NAME.sub('_', str(name)).strip() or 'Sheet'
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 2
    while candidate.lower() in used:
        tail = f'_{suffix}'
        candidate = cleaned[: 31 - len(tail)] + tail
        suffix += 1
    used.add(candidate.lower())
    return candidate


def _display_width(value: Any) -> float:
    text = display_text(value)
    width = 0.0
    for char in text:
        width += 2.0 if ord(char) > 0x2E80 else 1.0
    return width


def auto_widths(
    headers: Sequence[str], rows: Iterable[Sequence[Any]], *, sample: int = 300
) -> list[float]:
    """Estimate column widths from the header and a bounded row sample."""
    widths = [min(max(_display_width(header) + 2, 9.0), 52.0) for header in headers]
    for count, row in enumerate(rows):
        if count >= sample:
            break
        for index, value in enumerate(row):
            if index >= len(widths):
                break
            needed = min(_display_width(value) + 2, 52.0)
            if needed > widths[index]:
                widths[index] = needed
    return widths


def _prepare_value(value: Any) -> Any:
    """Normalise one value for openpyxl without changing its meaning."""
    if value is None or isinstance(value, (bool, str, dt.datetime, dt.date, dt.time)):
        return value
    if isinstance(value, int):
        if abs(value) >= 10**MAX_SAFE_INTEGER_DIGITS:
            # Excel cannot hold more than 15 significant digits; keep every digit
            # by storing the identifier as text instead of rounding it.
            return str(value)
        return value
    if isinstance(value, float):
        if value != value or value in (float('inf'), float('-inf')):
            return None
        return value
    if isinstance(value, Decimal):
        return str(value) if abs(value) >= Decimal(10) ** MAX_SAFE_INTEGER_DIGITS else float(value)
    return display_text(value)


def _make_cell(
    worksheet, value: Any, *, fill: str | None = None, header: bool = False, wrap: bool = False
) -> WriteOnlyCell:
    cell = WriteOnlyCell(worksheet)
    prepared = _prepare_value(value)

    if isinstance(prepared, str) and prepared.startswith(FORMULA_PREFIX):
        cell.value = prepared
        # Overrides openpyxl's formula detection: the payload stays literal text.
        cell.data_type = 's'
        cell.number_format = '@'
    else:
        cell.value = prepared

    if header:
        cell.font = Font(bold=True, size=11, color=HEADER_FONT_COLOR)
        cell.fill = PatternFill('solid', start_color=HEADER_FILL)
        cell.border = Border(bottom=Side(style='thin', color=BORDER_COLOR))
        cell.alignment = Alignment(vertical='center', horizontal='left', wrap_text=False)
    else:
        if fill and fill != TINTS['neutral']:
            cell.fill = PatternFill('solid', start_color=fill)
        if wrap:
            cell.alignment = Alignment(vertical='top', wrap_text=True)
        elif isinstance(prepared, str):
            cell.alignment = Alignment(vertical='top')
    return cell


def write_workbook(
    destination: Any,
    spec: WorkbookSpec,
    *,
    input_paths: Sequence[str] = (),
    progress: Callable[[str, float], None] | None = None,
    cancel: threading.Event | None = None,
) -> str:
    """Write the report to `destination` and return the resolved path."""
    out_path = validators.validate_output_path(destination, input_paths, label='输出文件')

    if progress:
        progress('写入工作簿', 0.05)

    folder = os.path.dirname(out_path)
    _sweep_stale_temps(folder)
    temp_path = os.path.join(folder, f'{TEMP_PREFIX}{uuid.uuid4().hex[:10]}{TEMP_SUFFIX}')
    _active_temps.add(temp_path)

    workbook = Workbook(write_only=True)
    workbook.properties.title = spec.properties_title
    workbook.properties.creator = 'SheetKit'
    workbook.properties.lastModifiedBy = 'SheetKit'

    used_names: set[str] = set()
    try:
        total = len(spec.sheets) or 1
        for position, sheet in enumerate(spec.sheets, start=1):
            if progress:
                progress(f'写入 {sheet.name}', 0.05 + 0.85 * ((position - 1) / total))
            raise_if_cancelled(cancel, f'写入 {sheet.name}')
            _write_sheet(workbook, sheet, safe_sheet_name(sheet.name, used_names), cancel=cancel)
        if progress:
            progress('保存文件', 0.92)
        workbook.save(temp_path)
    except ExportError:
        _discard(temp_path)
        raise
    except TaskCancelledError:
        _discard(temp_path)
        raise
    except Exception as exc:
        _discard(temp_path)
        raise ExportError(f'导出失败：{exc}', detail=out_path) from exc
    finally:
        workbook.close()

    try:
        os.replace(temp_path, out_path)
    except PermissionError as exc:
        _discard(temp_path)
        raise ExportError(
            f'目标文件被占用，无法写入。请先关闭已打开的 {os.path.basename(out_path)} 后重试',
            detail=out_path,
        ) from exc
    except OSError as exc:
        _discard(temp_path)
        raise ExportError(f'写入文件失败：{exc.strerror or exc}', detail=out_path) from exc
    finally:
        _active_temps.discard(temp_path)

    if progress:
        progress('完成', 1.0)
    return out_path


def _looks_like_formula(row: Sequence[Any]) -> bool:
    """True when a row holds text Excel would try to evaluate."""
    return any(
        isinstance(value, str) and value.startswith(FORMULA_PREFIX)
        for value in row
    )


def _write_sheet(
    workbook: Workbook,
    sheet: SheetSpec,
    name: str,
    cancel: threading.Event | None = None,
) -> None:
    worksheet = workbook.create_sheet(title=name)

    rows = list(sheet.iter_rows())
    if len(rows) + 1 > MAX_SHEET_ROWS:
        raise ExportError(
            f'工作表“{name}”共 {len(rows)} 行，超过 Excel 单表上限 {MAX_SHEET_ROWS - 1} 行，请拆分后导出'
        )

    widths = sheet.widths or auto_widths(sheet.headers, rows)
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = float(width)
    if sheet.freeze_header and sheet.headers:
        worksheet.freeze_panes = 'A2'

    worksheet.append(
        [_make_cell(worksheet, header, header=True) for header in sheet.headers]
    )

    tint = sheet.tint
    wrap_columns = set(sheet.wrap_columns)
    for row_index, row in enumerate(rows):
        raise_if_cancelled(cancel, f'写入 {name}')
        fill = tint(row_index, row) if tint and row_index < sheet.tint_row_limit else None
        # The plain-append path is much faster but lets openpyxl decide the cell
        # type, so it may only be used for rows that hold no formula-like text.
        if fill is None and not wrap_columns and not _looks_like_formula(row):
            worksheet.append([_prepare_value(value) for value in row])
            continue
        worksheet.append(
            [
                _make_cell(worksheet, value, fill=fill, wrap=index in wrap_columns)
                for index, value in enumerate(row)
            ]
        )


def _discard(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def summary_sheet(title: str, items: Iterable[tuple[str, Any]]) -> SheetSpec:
    return SheetSpec(
        name=title,
        headers=['项目', '内容'],
        rows=[[key, _summary_text(value)] for key, value in items],
        widths=[26.0, 96.0],
        wrap_columns=(1,),
    )


def _summary_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, (list, tuple)):
        return '、'.join(display_text(item) for item in value) if value else '无'
    if isinstance(value, dict):
        return '；'.join(f'{k}={_summary_text(v)}' for k, v in value.items())
    if isinstance(value, float):
        return f'{value:g}'
    return display_text(value)

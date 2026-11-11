"""Shared workbook reading for all three features.

Design rules enforced here:

* Values keep the type Excel/WPS stored. Text "00123" never becomes 123 and a
  19-digit order number never becomes a float, because the reader does not run
  type inference on business columns.
* CSV is read as text for the same reason, with encoding auto-detection that
  covers the GB18030 files Chinese Windows tools produce.
* Formulas are never evaluated. Cached results are used when present; a formula
  with no cached result is reported instead of being silently treated as empty.
* Macro workbooks are read as data only. openpyxl cannot execute VBA and this
  module never asks it to.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterator

from .errors import CorruptFileError, SheetNotFoundError, ValidationError
from .values import dedupe_names, normalize_header, row_is_blank
from . import validators

MAX_TOTAL_ROWS = 2_000_000
DEFAULT_PREVIEW_ROWS = 50
_CSV_SAMPLE_BYTES = 256 * 1024
_CSV_ENCODINGS = ('utf-8-sig', 'utf-8', 'gb18030', 'big5', 'cp1252')
_CSV_DELIMITERS = (',', ';', '\t', '|')
# GB18030 assigns the byte ranges it does not define to the Private Use Area,
# so PUA characters are the fingerprint of a wrong encoding guess.
_PRIVATE_USE_AREA = re.compile('[\ue000-\uf8ff]')


@dataclass
class SheetSummary:
    name: str
    max_row: int | None
    max_column: int | None


@dataclass
class FileProfile:
    path: str
    name: str
    kind: str
    sheets: list[SheetSummary] = field(default_factory=list)
    has_macros: bool = False
    warnings: list[str] = field(default_factory=list)
    encoding: str | None = None
    delimiter: str | None = None
    maybe_open_elsewhere: bool = False


@dataclass
class TableData:
    path: str
    name: str
    kind: str
    sheet: str | None
    header_row: int
    columns: list[str]
    rows: list[list[Any]]
    row_numbers: list[int]
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    formula_cells: int = 0
    uncached_formula_cells: int = 0
    blank_rows: int = 0
    encoding: str | None = None
    delimiter: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def column_index(self, name: str) -> int:
        return self.columns.index(name)

    def preview(self, limit: int = 20) -> list[list[str]]:
        from .values import display_text

        return [[display_text(cell) for cell in row] for row in self.rows[:limit]]


def profile_file(path: Any, *, label: str = '文件') -> FileProfile:
    """Cheap structural read: sheet names, macro presence, encoding, warnings."""
    resolved, kind = validators.open_input(path, label=label)
    profile = FileProfile(
        path=resolved,
        name=os.path.basename(resolved),
        kind=kind,
        maybe_open_elsewhere=validators.is_likely_open_elsewhere(resolved),
    )

    if profile.maybe_open_elsewhere:
        profile.warnings.append('该文件可能正被 Excel/WPS 打开，读取到的是上次保存的内容')

    if kind == 'csv':
        profile.encoding, profile.delimiter = _detect_csv_format(resolved)
        profile.sheets = [SheetSummary(name='(CSV 无工作表)', max_row=None, max_column=None)]
        return profile

    from openpyxl import load_workbook

    try:
        workbook = load_workbook(resolved, read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many zip/XML errors
        raise CorruptFileError(
            f'无法解析 {profile.name}，文件可能已损坏或不是有效的 Excel 工作簿',
            detail=str(exc),
        ) from exc

    try:
        profile.has_macros = kind == 'xlsm' or getattr(workbook, 'vba_archive', None) is not None
        for name in workbook.sheetnames:
            worksheet = workbook[name]
            profile.sheets.append(
                SheetSummary(
                    name=name,
                    max_row=getattr(worksheet, 'max_row', None),
                    max_column=getattr(worksheet, 'max_column', None),
                )
            )
    finally:
        workbook.close()

    if profile.has_macros:
        profile.warnings.append('该文件包含宏（VBA）。SheetKit 只读取数据，不会执行任何宏')
    if not profile.sheets:
        profile.warnings.append('工作簿中没有工作表')
    hidden = _hidden_sheet_names(resolved)
    if hidden:
        profile.warnings.append('包含隐藏工作表：' + ', '.join(hidden[:6]))
    return profile


def _hidden_sheet_names(path: str) -> list[str]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=False, data_only=True)
    except Exception:
        return []
    try:
        return [ws.title for ws in workbook.worksheets if ws.sheet_state != 'visible']
    finally:
        workbook.close()


def read_table(
    path: Any,
    *,
    sheet: str | None = None,
    header_row: int = 1,
    limit: int | None = None,
    keep_blank_rows: bool = False,
    label: str = '文件',
) -> TableData:
    """Read a table with the header on `header_row` (1-based).

    `limit` caps the number of data rows returned and sets `truncated`; it is
    used for previews so a 100k-row file never materialises in memory just to
    show 50 rows. Blank rows are dropped by default because they are not
    records; the cleaning feature passes `keep_blank_rows=True` so that its
    "删除空白行" rule is a real choice rather than something already done.
    """
    resolved, kind = validators.open_input(path, label=label)
    header_row = validators.require_int(
        header_row, '表头行', minimum=1, maximum=10000, default=1
    )

    if kind == 'csv':
        table = _read_csv(
            resolved,
            header_row=header_row,
            limit=limit,
            keep_blank_rows=keep_blank_rows,
            label=label,
        )
    else:
        table = _read_xlsx(
            resolved,
            kind=kind,
            sheet=sheet,
            header_row=header_row,
            limit=limit,
            keep_blank_rows=keep_blank_rows,
            label=label,
        )

    if validators.is_likely_open_elsewhere(resolved):
        table.warnings.append('该文件可能正被 Excel/WPS 打开，读取到的是上次保存的内容')
    if table.uncached_formula_cells:
        table.warnings.append(
            f'有 {table.uncached_formula_cells} 个公式单元格没有缓存结果，已按空值处理'
            '（SheetKit 不计算公式）'
        )
    if table.formula_cells:
        table.warnings.append(
            f'检测到 {table.formula_cells} 个公式单元格，使用其上次保存的计算结果'
        )
    return table


def _resolve_sheet(
    available: list[str], requested: str | None, *, label: str
) -> str:
    if not available:
        raise ValidationError(f'{label}中没有可用的工作表')
    if requested is None or not str(requested).strip():
        return available[0]
    name = str(requested).strip()
    if name not in available:
        raise SheetNotFoundError(
            f'{label}中不存在工作表 "{name}"，可选：{", ".join(available)}',
        )
    return name


def _workbook_has_formulas(path: str) -> bool:
    """Does any worksheet hold a formula?

    Reading a workbook twice is the single most expensive thing the reader
    does, and most business workbooks have no formulas at all. Scanning the
    raw sheet XML for a formula tag is far cheaper than a second parse, so the
    second pass only happens when there is something to find. Any doubt about
    the file answers "yes" and keeps the careful path.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.startswith('xl/worksheets/') and name.endswith('.xml')
            ]
            for name in names:
                with archive.open(name) as handle:
                    tail = b''
                    while True:
                        chunk = handle.read(1 << 20)
                        if not chunk:
                            break
                        if b'<f' in tail + chunk:
                            return True
                        tail = chunk[-2:]
    except (OSError, zipfile.BadZipFile, KeyError):
        return True
    return False


def _read_xlsx(
    path: str,
    *,
    kind: str,
    sheet: str | None,
    header_row: int,
    limit: int | None,
    keep_blank_rows: bool,
    label: str,
) -> TableData:
    from openpyxl import load_workbook

    try:
        value_book = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise CorruptFileError(
            f'无法解析 {os.path.basename(path)}，文件可能已损坏', detail=str(exc)
        ) from exc

    formula_book = None
    warnings: list[str] = []
    try:
        sheet_name = _resolve_sheet(value_book.sheetnames, sheet, label=label)
        formula_sheet = None
        if _workbook_has_formulas(path):
            try:
                formula_book = load_workbook(path, read_only=True, data_only=False)
                formula_sheet = formula_book[sheet_name]
            except Exception:
                formula_book = None
                formula_sheet = None
                warnings.append('无法读取公式信息，公式列可能显示为计算结果或空值')

        value_sheet = value_book[sheet_name]
        value_rows = value_sheet.iter_rows(values_only=True)
        formula_rows = (
            formula_sheet.iter_rows(values_only=True) if formula_sheet is not None else None
        )

        table = _consume_rows(
            value_rows,
            formula_rows,
            path=path,
            name=os.path.basename(path),
            kind=kind,
            sheet=sheet_name,
            header_row=header_row,
            limit=limit,
            keep_blank_rows=keep_blank_rows,
            warnings=warnings,
        )
        if kind == 'xlsm' or getattr(value_book, 'vba_archive', None) is not None:
            table.warnings.append('该文件包含宏（VBA）。SheetKit 只读取数据，不会执行任何宏')
        return table
    finally:
        value_book.close()
        if formula_book is not None:
            formula_book.close()


def _consume_rows(
    value_rows: Iterator[tuple],
    formula_rows: Iterator[tuple] | None,
    *,
    path: str,
    name: str,
    kind: str,
    sheet: str | None,
    header_row: int,
    limit: int | None,
    keep_blank_rows: bool,
    warnings: list[str],
) -> TableData:
    header_raw: tuple | None = None
    rows: list[list[Any]] = []
    row_numbers: list[int] = []
    formula_cells = 0
    uncached_formula_cells = 0
    blank_seen = 0
    truncated = False
    width = 0

    for index, raw in enumerate(value_rows, start=1):
        raw_formula = next(formula_rows, None) if formula_rows is not None else None
        if index < header_row:
            continue
        if index == header_row:
            header_raw = raw
            width = len(raw)
            continue

        cells, cell_formulas, cell_uncached = _normalize_row(raw, raw_formula)
        formula_cells += cell_formulas
        uncached_formula_cells += cell_uncached

        if row_is_blank(cells):
            blank_seen += 1
            if not keep_blank_rows:
                continue

        if limit is not None and len(rows) >= limit:
            truncated = True
            break

        rows.append(cells)
        row_numbers.append(index)

        if len(rows) >= MAX_TOTAL_ROWS:
            raise ValidationError(
                f'数据行数超过上限 {MAX_TOTAL_ROWS}，请拆分文件后重试', detail=name
            )

    if header_raw is None:
        raise ValidationError(
            f'表头行 {header_row} 超出文件实际行数，请检查表头行设置', detail=name
        )

    header_cells = [normalize_header(cell) for cell in header_raw]
    while len(header_cells) < width:
        header_cells.append('')
    columns = dedupe_names(header_cells[:width])
    unnamed = sum(1 for cell in header_cells[:width] if not cell)
    if unnamed:
        warnings.append(f'表头有 {unnamed} 个空白列名，已用“未命名列”占位')

    rows = [row + [None] * (width - len(row)) for row in rows]

    if not rows:
        warnings.append('表头之后没有读取到任何数据行')

    return TableData(
        path=path,
        name=name,
        kind=kind,
        sheet=sheet,
        header_row=header_row,
        columns=columns,
        rows=rows,
        row_numbers=row_numbers,
        warnings=list(dict.fromkeys(warnings)),
        truncated=truncated,
        formula_cells=formula_cells,
        uncached_formula_cells=uncached_formula_cells,
        blank_rows=blank_seen,
    )


def _normalize_row(
    raw: tuple, raw_formula: tuple | None
) -> tuple[list[Any], int, int]:
    """Flatten one sheet row, splitting cached values from formula text."""
    cells: list[Any] = []
    formulas = 0
    uncached = 0
    source = raw or ()
    for position, value in enumerate(source):
        formula_value = raw_formula[position] if raw_formula and position < len(raw_formula) else None
        is_formula = (
            isinstance(formula_value, str)
            and formula_value.startswith('=')
            and formula_value != value
        )
        if is_formula:
            formulas += 1
            if value is None:
                uncached += 1
        cells.append(_coerce_cell(value))
    return cells, formulas, uncached


def _coerce_cell(value: Any) -> Any:
    """Keep Excel types; only trim the values pandas/openpyxl cannot represent."""
    if value is None or isinstance(value, (bool, int, str, dt.datetime, dt.date, dt.time)):
        return value
    if isinstance(value, float):
        return value
    return str(value)


def _detect_csv_format(path: str) -> tuple[str, str]:
    with open(path, 'rb') as handle:
        sample = handle.read(_CSV_SAMPLE_BYTES)

    encoding = 'utf-8'
    if sample.startswith(b'\xef\xbb\xbf'):
        encoding = 'utf-8-sig'
    elif sample.startswith(b'\xff\xfe'):
        encoding = 'utf-16-le'
    elif sample.startswith(b'\xfe\xff'):
        encoding = 'utf-16-be'
    else:
        encoding = _guess_csv_encoding(sample)

    try:
        text = sample.decode(encoding, errors='replace')
    except (UnicodeDecodeError, LookupError):
        text = sample.decode('latin-1', errors='replace')

    first_line = next((line for line in text.splitlines() if line.strip()), '')
    delimiter = ','
    if first_line:
        counts = {char: first_line.count(char) for char in _CSV_DELIMITERS}
        best = max(counts, key=lambda char: counts[char])
        if counts[best] > 0:
            delimiter = best
    return encoding, delimiter


def _guess_csv_encoding(sample: bytes) -> str:
    """Pick the candidate whose strict decode looks least like mojibake.

    Trying candidates in a fixed order cannot work: every valid Big5 byte
    sequence is also valid GB18030, so GB18030 always wins and a traditional
    Chinese file silently turns into junk. Ranking by Private Use Area
    characters breaks the tie, because that is where GB18030 puts byte ranges
    it has no real character for.
    """
    # A sample cut at the cap may split one multi-byte character; drop the tail
    # so the strict decode is not made to fail by our own truncation.
    probe = sample[:-4] if len(sample) >= _CSV_SAMPLE_BYTES else sample

    chosen = 'latin-1'
    best_score = -1
    for candidate in _CSV_ENCODINGS:
        try:
            decoded = probe.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
        score = len(_PRIVATE_USE_AREA.findall(decoded))
        if best_score < 0 or score < best_score:
            chosen, best_score = candidate, score
        if score == 0:
            break
    return chosen


def _read_csv(
    path: str, *, header_row: int, limit: int | None, keep_blank_rows: bool, label: str
) -> TableData:
    encoding, delimiter = _detect_csv_format(path)
    warnings: list[str] = []
    if encoding == 'latin-1':
        warnings.append('无法识别 CSV 编码，已按 Latin-1 读取，中文可能显示为乱码')
    elif encoding not in ('utf-8', 'utf-8-sig'):
        warnings.append(f'CSV 编码识别为 {encoding}')

    rows: list[list[Any]] = []
    row_numbers: list[int] = []
    header_raw: list[str] | None = None
    width = 0
    truncated = False
    blank_seen = 0
    wider_than_header = False

    try:
        with open(path, 'r', encoding=encoding, errors='replace', newline='') as handle:
            reader = csv.reader(handle, delimiter=delimiter, quotechar='"')
            for index, raw in enumerate(reader, start=1):
                if index < header_row:
                    continue
                if index == header_row:
                    header_raw = list(raw)
                    width = len(raw)
                    continue
                cells = [(cell if cell != '' else None) for cell in raw]
                if row_is_blank(cells):
                    blank_seen += 1
                    if not keep_blank_rows:
                        continue
                if limit is not None and len(rows) >= limit:
                    truncated = True
                    break
                if len(cells) > width:
                    wider_than_header = True
                    width = len(cells)
                rows.append(cells)
                row_numbers.append(index)
                if len(rows) >= MAX_TOTAL_ROWS:
                    raise ValidationError(
                        f'数据行数超过上限 {MAX_TOTAL_ROWS}，请拆分文件后重试', detail=path
                    )
    except UnicodeError as exc:
        raise CorruptFileError(f'CSV 解码失败：{exc}', detail=path) from exc
    except csv.Error as exc:
        raise CorruptFileError(f'CSV 解析失败：{exc}', detail=path) from exc
    except OSError as exc:
        raise CorruptFileError(f'CSV 读取失败：{exc.strerror or exc}', detail=path) from exc

    if header_raw is None:
        raise ValidationError(
            f'表头行 {header_row} 超出文件实际行数，请检查表头行设置',
            detail=os.path.basename(path),
        )

    header_cells = [normalize_header(cell) for cell in header_raw]
    while len(header_cells) < width:
        header_cells.append('')
    columns = dedupe_names(header_cells[:width])
    if wider_than_header:
        warnings.append('存在超出表头列数的数据，已按“未命名列”追加')
    unnamed = sum(1 for cell in header_cells[:width] if not cell)
    if unnamed:
        warnings.append(f'表头有 {unnamed} 个空白列名，已用“未命名列”占位')

    rows = [row + [None] * (width - len(row)) for row in rows]
    warnings.append('CSV 中的所有列均按文本读取，以保留前导零与长数字')

    return TableData(
        path=path,
        name=os.path.basename(path),
        kind='csv',
        sheet=None,
        header_row=header_row,
        columns=columns,
        rows=rows,
        row_numbers=row_numbers,
        warnings=list(dict.fromkeys(warnings)),
        truncated=truncated,
        blank_rows=blank_seen,
        encoding=encoding,
        delimiter=delimiter,
    )


def read_many(
    paths: list[str],
    *,
    sheets: dict[str, str | None] | None = None,
    header_rows: dict[str, int] | None = None,
    label: str = '文件',
) -> list[TableData]:
    """Read a batch of files, keeping the caller's order."""
    sheets = sheets or {}
    header_rows = header_rows or {}
    tables: list[TableData] = []
    for path in paths:
        tables.append(
            read_table(
                path,
                sheet=sheets.get(path),
                header_row=header_rows.get(path, 1),
                label=label,
            )
        )
    return tables

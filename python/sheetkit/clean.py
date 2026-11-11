"""Data cleaning: blank rows, whitespace, duplicates, required fields, formats.

Destructive duplicate handling is refused unless the caller passes an explicit
confirmation, and the impact is computed first so the UI can show what will be
deleted before the user agrees. Suspected duplicates are never removed
silently.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .cancel import raise_if_cancelled
from .errors import ConfirmationRequiredError, ValidationError
from .reader import TableData, read_table
from .values import (
    date_is_implausible,
    display_text,
    is_blank,
    key_text,
    parse_date,
    row_is_blank,
    to_decimal,
)
from . import validators

ProgressFn = Callable[[str, float], None]

DUPLICATE_FLAG = '重复标记'
REQUIRED_FLAG = '必填缺失'
FORMAT_FLAG = '格式异常'
SOURCE_ROW_COLUMN = '原始行号'

DUPLICATE_ACTIONS = ('none', 'mark', 'keep_first', 'remove_all')
DESTRUCTIVE_ACTIONS = ('keep_first', 'remove_all')
ACTION_LABELS = {
    'none': '不处理',
    'mark': '仅标记',
    'keep_first': '删除重复项（保留首次出现）',
    'remove_all': '删除整组重复数据',
}


@dataclass(frozen=True)
class CleanOptions:
    remove_blank_rows: bool = True
    strip_columns: tuple[str, ...] = ()
    duplicate_key_columns: tuple[str, ...] = ()
    duplicate_action: str = 'mark'
    confirmed: bool = False
    required_columns: tuple[str, ...] = ()
    date_columns: tuple[str, ...] = ()
    number_columns: tuple[str, ...] = ()

    @classmethod
    def from_payload(cls, payload: Any, available: Sequence[str]) -> 'CleanOptions':
        payload = payload if isinstance(payload, dict) else {}

        def columns(key: str, label: str) -> tuple[str, ...]:
            return tuple(
                validators.validate_columns(
                    validators.require_str_list(payload.get(key), label), available, label=label
                )
            )

        action = str(payload.get('duplicate_action') or 'mark').strip()
        if action not in DUPLICATE_ACTIONS:
            raise ValidationError(
                f'重复数据处理方式无效，可选：{", ".join(DUPLICATE_ACTIONS)}'
            )

        duplicate_keys = columns('duplicate_key_columns', '重复判断字段')
        if action != 'none' and not duplicate_keys:
            # Judging duplicates over every column is a legitimate rule (exact
            # duplicate rows), so an empty selection means "all columns".
            duplicate_keys = tuple(available)

        return cls(
            remove_blank_rows=validators.require_bool(
                payload.get('remove_blank_rows'), '删除空白行', default=True
            ),
            strip_columns=columns('strip_columns', '去空格字段'),
            duplicate_key_columns=duplicate_keys,
            duplicate_action=action,
            confirmed=validators.require_bool(payload.get('confirmed'), '删除确认', default=False),
            required_columns=columns('required_columns', '必填字段'),
            date_columns=columns('date_columns', '日期检查字段'),
            number_columns=columns('number_columns', '数字检查字段'),
        )


@dataclass
class CleanResult:
    path: str
    name: str
    sheet: str | None
    body_columns: list[str]
    flag_columns: list[str]
    rows: list[list[Any]] = field(default_factory=list)
    duplicate_rows: list[list[Any]] = field(default_factory=list)
    anomaly_rows: list[list[Any]] = field(default_factory=list)
    duplicate_groups: int = 0
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    stats: dict[str, int] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return self.body_columns + self.flag_columns + [SOURCE_ROW_COLUMN]

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def summary(self) -> dict:
        return {
            'file': self.name,
            'sheet': self.sheet or '',
            'original_rows': self.stats.get('original_rows', 0),
            'result_rows': self.row_count,
            'blank_rows': self.stats.get('blank_rows', 0),
            'stripped_cells': self.stats.get('stripped_cells', 0),
            'duplicate_groups': self.duplicate_groups,
            'duplicate_rows': self.stats.get('duplicate_rows', 0),
            'removed_duplicate_rows': self.stats.get('removed_duplicate_rows', 0),
            'missing_required_rows': self.stats.get('missing_required_rows', 0),
            'missing_required_cells': self.stats.get('missing_required_cells', 0),
            'format_anomaly_rows': self.stats.get('format_anomaly_rows', 0),
            'format_anomaly_cells': self.stats.get('format_anomaly_cells', 0),
            'anomaly_rows': len(self.anomaly_rows),
            'duplicate_action': self.stats.get('duplicate_action', 'mark'),
            'duplicate_action_label': ACTION_LABELS.get(
                str(self.stats.get('duplicate_action', 'mark')), '仅标记'
            ),
            'duplicate_key_columns': self.stats.get('duplicate_key_columns', []),
            'flag_columns': list(self.flag_columns),
            'columns': self.columns,
            'warnings': list(self.warnings),
            'timings': dict(self.timings),
        }


def duplicate_impact(table: TableData, options: CleanOptions) -> dict:
    """How many rows each duplicate rule would remove, for the confirm dialog."""
    groups = _duplicate_groups(table, options)
    total_in_groups = sum(len(positions) for positions in groups.values())
    removable_tail = sum(len(positions) - 1 for positions in groups.values())
    return {
        'key_columns': list(_duplicate_keys(table, options)),
        'groups': len(groups),
        'rows_in_groups': total_in_groups,
        'extra_occurrences': removable_tail,
        'keep_first_removes': removable_tail,
        'remove_all_removes': total_in_groups,
        'result_rows': {
            'mark': table.row_count,
            'keep_first': table.row_count - removable_tail,
            'remove_all': table.row_count - total_in_groups,
        },
    }


def _duplicate_keys(table: TableData, options: CleanOptions) -> tuple[str, ...]:
    """An empty selection means "identical whole rows", not "check nothing"."""
    if options.duplicate_action == 'none':
        return ()
    return options.duplicate_key_columns or tuple(table.columns)


def _duplicate_groups(table: TableData, options: CleanOptions) -> dict[str, list[int]]:
    """Group row positions whose key columns hold identical text.

    Whitespace is ignored for grouping because the strip rule normally runs in
    the same pass, and "A1 " and "A1" are the same order to a human reader.
    """
    names = _duplicate_keys(table, options)
    if not names:
        return {}
    indices = [table.column_index(name) for name in names]
    groups: dict[str, list[int]] = {}
    for position, row in enumerate(table.rows):
        signature = '\x1f'.join(
            key_text(row[i] if i < len(row) else None, ignore_whitespace=True)
            for i in indices
        )
        groups.setdefault(signature, []).append(position)
    return {signature: positions for signature, positions in groups.items() if len(positions) > 1}


def _strip_row(
    row: list[Any], strip_indices: Sequence[int]
) -> tuple[list[Any], int]:
    changed = 0
    if not strip_indices:
        return row, 0
    out = list(row)
    for index in strip_indices:
        if index >= len(out):
            continue
        value = out[index]
        if isinstance(value, str) and value != value.strip():
            out[index] = value.strip()
            changed += 1
    return out, changed


def _prepare(
    table: TableData, options: CleanOptions
) -> tuple[TableData, int, int]:
    """Apply the strip and blank-row rules.

    The impact preview and the real run share this step, so the number of rows
    the user is shown before confirming is the number that will actually go.
    """
    strip_indices = [table.column_index(name) for name in options.strip_columns]
    rows: list[list[Any]] = []
    row_numbers: list[int] = []
    stripped_cells = 0
    blank_rows = 0

    for position, row in enumerate(table.rows):
        cleaned, changed = _strip_row(list(row), strip_indices)
        stripped_cells += changed
        if row_is_blank(cleaned):
            blank_rows += 1
            if options.remove_blank_rows:
                continue
        rows.append(cleaned)
        row_numbers.append(table.row_numbers[position])

    work = TableData(
        path=table.path,
        name=table.name,
        kind=table.kind,
        sheet=table.sheet,
        header_row=table.header_row,
        columns=list(table.columns),
        rows=rows,
        row_numbers=row_numbers,
        warnings=list(table.warnings),
    )
    return work, stripped_cells, blank_rows


def clean_impact(
    path: str,
    options: CleanOptions | dict,
    *,
    sheet: str | None = None,
    header_row: int = 1,
) -> dict:
    """How many rows the selected duplicate rule would remove.

    Uses the same preparation as the real run, so the preview the user
    confirms against is never optimistic.
    """
    table = read_table(
        path, sheet=sheet, header_row=header_row, keep_blank_rows=True
    )
    parsed = (
        CleanOptions.from_payload(options, table.columns)
        if isinstance(options, dict)
        else options
    )
    work, _stripped, _blanks = _prepare(table, parsed)
    return duplicate_impact(work, parsed)


def clean_table(
    table: TableData,
    options: CleanOptions,
    *,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> CleanResult:
    started = time.perf_counter()

    def report(stage: str, ratio: float) -> None:
        if progress:
            progress(stage, max(0.0, min(1.0, ratio)))

    report('清理空格', 0.1)
    work, stripped_cells, blank_rows = _prepare(table, options)

    if options.duplicate_action in DESTRUCTIVE_ACTIONS and not options.confirmed:
        impact = duplicate_impact(work, options)
        raise ConfirmationRequiredError(
            f'“{ACTION_LABELS[options.duplicate_action]}”会删除 '
            f'{impact["keep_first_removes"] if options.duplicate_action == "keep_first" else impact["remove_all_removes"]} 行数据，'
            '请先预览影响并确认',
            impact=impact,
        )

    report('检测重复', 0.35)
    groups = _duplicate_groups(work, options)
    flags_by_position: dict[int, str] = {}
    group_of_position: dict[int, list[int]] = {}
    for positions in groups.values():
        total = len(positions)
        for occurrence, position in enumerate(positions, start=1):
            group_of_position[position] = positions
            label = '首次出现' if occurrence == 1 else f'第 {occurrence} 次出现'
            flags_by_position[position] = f'重复（{label}，共 {total} 条）'

    keep: list[int] = []
    removed_duplicates = 0
    for position in range(len(work.rows)):
        group = group_of_position.get(position)
        if group is not None:
            if options.duplicate_action == 'remove_all':
                removed_duplicates += 1
                continue
            if options.duplicate_action == 'keep_first' and group[0] != position:
                removed_duplicates += 1
                continue
        keep.append(position)

    report('检查必填与格式', 0.6)
    required_indices = [
        (name, work.column_index(name)) for name in options.required_columns
    ]
    date_indices = [(name, work.column_index(name)) for name in options.date_columns]
    number_indices = [(name, work.column_index(name)) for name in options.number_columns]

    flag_columns: list[str] = []
    if options.duplicate_action in ('mark', 'keep_first', 'remove_all'):
        flag_columns.append(DUPLICATE_FLAG)
    if options.required_columns:
        flag_columns.append(REQUIRED_FLAG)
    if options.date_columns or options.number_columns:
        flag_columns.append(FORMAT_FLAG)

    has_duplicate_flag = DUPLICATE_FLAG in flag_columns
    required_positions_in_flag = REQUIRED_FLAG in flag_columns
    format_positions_in_flag = FORMAT_FLAG in flag_columns

    out_rows: list[list[Any]] = []
    duplicate_out: list[list[Any]] = []
    anomaly_out: list[list[Any]] = []
    missing_required_rows = 0
    missing_required_cells = 0
    format_anomaly_rows = 0
    format_anomaly_cells = 0

    total = len(keep) or 1
    for step, position in enumerate(keep, start=1):
        if step % 1000 == 0:
            report('检查必填与格式', 0.6 + 0.35 * (step / total))
        raise_if_cancelled(cancel, '检查必填与格式')
        row = work.rows[position]

        missing = [name for name, index in required_indices if _is_missing(row, index)]
        problems: list[str] = []
        for name, index in date_indices:
            problem = _check_date(row, index, name)
            if problem:
                problems.append(problem)
        for name, index in number_indices:
            problem = _check_number(row, index, name)
            if problem:
                problems.append(problem)

        if missing:
            missing_required_rows += 1
            missing_required_cells += len(missing)
        if problems:
            format_anomaly_rows += 1
            format_anomaly_cells += len(problems)

        flags: list[Any] = []
        if has_duplicate_flag:
            flags.append(flags_by_position.get(position, ''))
        if required_positions_in_flag:
            flags.append('、'.join(missing))
        if format_positions_in_flag:
            flags.append('；'.join(problems))

        out_row = list(row) + flags + [work.row_numbers[position]]
        out_rows.append(out_row)

        if position in group_of_position:
            duplicate_out.append(out_row)
        if missing or problems:
            anomaly_out.append(out_row)

    warnings = list(table.warnings)
    if options.duplicate_action != 'none' and not options.duplicate_key_columns:
        warnings.append('未选择重复判断字段，已按全部字段判断完全重复行')
    if removed_duplicates:
        warnings.append(
            f'已按“{ACTION_LABELS[options.duplicate_action]}”删除 {removed_duplicates} 行重复数据'
        )

    report('完成', 1.0)
    return CleanResult(
        path=table.path,
        name=table.name,
        sheet=table.sheet,
        body_columns=list(work.columns),
        flag_columns=flag_columns,
        rows=out_rows,
        duplicate_rows=duplicate_out,
        anomaly_rows=anomaly_out,
        duplicate_groups=len(groups),
        warnings=list(dict.fromkeys(warnings)),
        timings={'total': round(time.perf_counter() - started, 3)},
        stats={
            'original_rows': table.row_count,
            'blank_rows': blank_rows,
            'stripped_cells': stripped_cells,
            'duplicate_rows': len(group_of_position),
            'removed_duplicate_rows': removed_duplicates,
            'missing_required_rows': missing_required_rows,
            'missing_required_cells': missing_required_cells,
            'format_anomaly_rows': format_anomaly_rows,
            'format_anomaly_cells': format_anomaly_cells,
            'duplicate_action': options.duplicate_action,
            'duplicate_key_columns': list(_duplicate_keys(work, options)),
        },
    )


def _is_missing(row: Sequence[Any], index: int) -> bool:
    return index >= len(row) or is_blank(row[index])


def _check_date(row: Sequence[Any], index: int, name: str) -> str | None:
    if index >= len(row):
        return None
    value = row[index]
    if is_blank(value):
        return None
    parsed = parse_date(value)
    if parsed is None:
        return f'{name} 不是有效日期（{display_text(value)[:40]}）'
    if date_is_implausible(parsed):
        return f'{name} 日期超出合理范围（{parsed.isoformat()}）'
    return None


def _check_number(row: Sequence[Any], index: int, name: str) -> str | None:
    if index >= len(row):
        return None
    value = row[index]
    if is_blank(value):
        return None
    if isinstance(value, str):
        parsed = to_decimal(value)
        if parsed is None:
            return f'{name} 不是有效数字（{value.strip()[:40]}）'
        return f'{name} 数字以文本形式存储（{value.strip()[:40]}）'
    if to_decimal(value) is None:
        return f'{name} 不是有效数字（{display_text(value)[:40]}）'
    return None


def clean_file(
    path: str,
    options: CleanOptions | dict,
    *,
    sheet: str | None = None,
    header_row: int = 1,
    progress: ProgressFn | None = None,
    label: str = '文件',
    cancel: threading.Event | None = None,
) -> CleanResult:
    """Read a file keeping blank rows, then apply the selected cleaning rules."""
    if progress:
        progress('读取文件', 0.0)
    table = read_table(
        path,
        sheet=sheet,
        header_row=header_row,
        keep_blank_rows=True,
        label=label,
    )
    parsed = (
        CleanOptions.from_payload(options, table.columns)
        if isinstance(options, dict)
        else options
    )
    # Reading is the slow part on a large file, so the cleaning stages are
    # scaled into the remaining 95% to keep the bar moving forwards.
    scaled = None if progress is None else (
        lambda stage, ratio: progress(stage, 0.05 + 0.95 * ratio)
    )
    return clean_table(table, parsed, progress=scaled, cancel=cancel)

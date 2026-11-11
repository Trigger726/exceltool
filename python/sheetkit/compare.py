"""Excel difference comparison by business key.

Rows are matched on the user-selected unique key (single or composite), never on
row position, so a re-sorted file with identical data reports "no change".

Rows whose key is blank or duplicated are refused instead of guessed: they are
collected as anomalies and excluded from matching, and a key that is anomalous
on one side is never reported as added/deleted on the other, because that claim
could not be verified.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

from .cancel import raise_if_cancelled
from .errors import ValidationError
from .reader import TableData, read_table
from .values import display_text, is_blank, key_text, to_decimal
from . import validators

ProgressFn = Callable[[str, float], None]

KEY_SEPARATOR = ' | '
UNMATCHED_BECAUSE_OLD_ANOMALY = 'old_anomaly'
UNMATCHED_BECAUSE_NEW_ANOMALY = 'new_anomaly'


@dataclass(frozen=True)
class CompareOptions:
    ignore_whitespace: bool = True
    ignore_case: bool = False
    numeric_columns: tuple[str, ...] = ()
    numeric_tolerance: Decimal = Decimal('0')
    compare_columns: tuple[str, ...] = ()
    include_unchanged: bool = False

    @classmethod
    def from_payload(cls, payload: Any, available: Sequence[str]) -> 'CompareOptions':
        payload = payload if isinstance(payload, dict) else {}
        numeric = validators.validate_columns(
            validators.require_str_list(payload.get('numeric_columns'), '数值比较字段'),
            available,
            label='数值比较字段',
        )
        compare_cols = validators.validate_columns(
            validators.require_str_list(payload.get('compare_columns'), '参与比较的字段'),
            available,
            label='参与比较的字段',
        )
        raw_tolerance = payload.get('numeric_tolerance')
        if raw_tolerance in (None, ''):
            tolerance = Decimal('0')
        else:
            tolerance = to_decimal(raw_tolerance)
            if tolerance is None or tolerance < 0:
                raise ValidationError('数值容差必须是不小于 0 的数字')
        return cls(
            ignore_whitespace=validators.require_bool(
                payload.get('ignore_whitespace'), '忽略首尾空格', default=True
            ),
            ignore_case=validators.require_bool(
                payload.get('ignore_case'), '忽略大小写', default=False
            ),
            numeric_columns=tuple(numeric),
            numeric_tolerance=tolerance,
            compare_columns=tuple(compare_cols),
            include_unchanged=validators.require_bool(payload.get('include_unchanged'), '保留未变化记录', default=False),
        )


@dataclass
class KeyAnomaly:
    side: str  # 'old' | 'new'
    reason: str  # 'blank' | 'duplicate'
    key_display: str
    row_number: int
    values: list[Any] = field(default_factory=list)
    duplicate_count: int = 0


@dataclass
class UnmatchedRow:
    side: str
    reason: str
    key_display: str
    row_number: int
    values: list[Any] = field(default_factory=list)


@dataclass
class FieldChange:
    column: str
    old_value: Any
    new_value: Any
    numeric: bool = False
    numeric_parse_failed: bool = False
    accepted_difference: str | None = None


@dataclass
class ChangedRow:
    key_display: str
    old_row: int
    new_row: int
    changes: list[FieldChange] = field(default_factory=list)


@dataclass
class CompareResult:
    old_path: str
    new_path: str
    old_name: str
    new_name: str
    old_sheet: str | None
    new_sheet: str | None
    keys: list[str]
    columns: list[str]
    old_columns: list[str]
    new_columns: list[str]
    shared_columns: list[str]
    only_in_old: list[str]
    only_in_new: list[str]
    column_order_differs: bool
    old_total_rows: int = 0
    new_total_rows: int = 0
    added: list[tuple[str, int, list[Any]]] = field(default_factory=list)
    deleted: list[tuple[str, int, list[Any]]] = field(default_factory=list)
    changed: list[ChangedRow] = field(default_factory=list)
    anomalies: list[KeyAnomaly] = field(default_factory=list)
    unmatched: list[UnmatchedRow] = field(default_factory=list)
    unchanged_count: int = 0
    warnings: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    minor: list[ChangedRow] = field(default_factory=list)
    strict_modified_rows: int = 0
    unchanged_rows: list[tuple[list[Any], int, int]] | None = None

    @property
    def changed_field_count(self) -> int:
        return sum(len(row.changes) for row in self.changed)

    @property
    def modification_records(self) -> list[dict]:
        """Flat 匹配字段 / 修改列 / 旧值 / 新值 / 原始行号 rows for UI and export."""
        return self._records(self.changed)

    @property
    def minor_records(self) -> list[dict]:
        return self._records(self.minor)

    @staticmethod
    def _records(rows: list[ChangedRow]) -> list[dict]:
        records: list[dict] = []
        for row in rows:
            for change in row.changes:
                records.append(
                    {
                        'key': row.key_display,
                        'column': change.column,
                        'old_value': change.old_value,
                        'new_value': change.new_value,
                        'old_row': row.old_row,
                        'new_row': row.new_row,
                        'numeric': change.numeric,
                        'numeric_parse_failed': change.numeric_parse_failed,
                        **({'accepted_difference': change.accepted_difference} if change.accepted_difference else {}),
                    }
                )
        return records

    def summary(self) -> dict:
        return {
            'old_file': self.old_name,
            'new_file': self.new_name,
            'old_sheet': self.old_sheet or '',
            'new_sheet': self.new_sheet or '',
            'keys': list(self.keys),
            'old_rows': self.old_total_rows,
            'new_rows': self.new_total_rows,
            'compared_rows': self.unchanged_count + len(self.changed),
            'added': len(self.added),
            'deleted': len(self.deleted),
            'modified_rows': len(self.changed),
            'modified_fields': self.changed_field_count,
            'minor_rows': len(self.minor),
            'minor_fields': sum(len(row.changes) for row in self.minor),
            'strict_modified_rows': self.strict_modified_rows,
            'unchanged': self.unchanged_count,
            'anomalies': len(self.anomalies),
            'unmatched': len(self.unmatched),
            'only_in_old_columns': list(self.only_in_old),
            'only_in_new_columns': list(self.only_in_new),
            'column_order_differs': self.column_order_differs,
            'shared_columns': list(self.shared_columns),
            'warnings': list(self.warnings),
            'timings': dict(self.timings),
        }


def _key_indices(table: TableData, keys: Sequence[str]) -> list[int]:
    return [table.column_index(name) for name in keys]


def _index_by_key(
    table: TableData,
    keys: Sequence[str],
    options: CompareOptions,
    side: str,
) -> tuple[dict[str, int], list[KeyAnomaly], set[str]]:
    """Group rows by key text.

    Returns (unique key -> row position, anomalies, keys that were duplicated).
    Blank and duplicated keys are refused rather than matched.
    """
    indices = _key_indices(table, keys)
    positions: dict[str, list[int]] = {}
    anomalies: list[KeyAnomaly] = []

    for position, row in enumerate(table.rows):
        parts = [
            key_text(
                row[i] if i < len(row) else None,
                ignore_whitespace=options.ignore_whitespace,
                ignore_case=options.ignore_case,
            )
            for i in indices
        ]
        key_display = KEY_SEPARATOR.join(parts)

        blank_columns = [keys[n] for n, part in enumerate(parts) if is_blank(part)]
        if blank_columns:
            anomalies.append(
                KeyAnomaly(
                    side=side,
                    reason='blank',
                    key_display=(key_display or '(空)')
                    + f'　[空白字段: {", ".join(blank_columns)}]',
                    row_number=table.row_numbers[position],
                    values=list(row),
                )
            )
            continue

        positions.setdefault(key_display, []).append(position)

    duplicate_keys = {key for key, found in positions.items() if len(found) > 1}
    for key_display in duplicate_keys:
        found = positions[key_display]
        for position in found:
            anomalies.append(
                KeyAnomaly(
                    side=side,
                    reason='duplicate',
                    key_display=f'{key_display}　[重复 {len(found)} 次]',
                    row_number=table.row_numbers[position],
                    values=list(table.rows[position]),
                    duplicate_count=len(found),
                )
            )

    unique = {key: found[0] for key, found in positions.items() if len(found) == 1}
    return unique, anomalies, duplicate_keys


def _values_differ(
    old_value: Any, new_value: Any, column: str, options: CompareOptions
) -> FieldChange | None:
    if old_value is new_value or (type(old_value) is type(new_value) and old_value == new_value):
        return None
    if is_blank(old_value) and is_blank(new_value):
        return _text_difference(old_value, new_value, column, options)

    if column in options.numeric_columns:
        left = to_decimal(old_value)
        right = to_decimal(new_value)
        if left is not None and right is not None:
            if abs(left - right) <= options.numeric_tolerance:
                if display_text(old_value) == display_text(new_value):
                    return None
                reason = '数值相同，表达不同' if left == right else '数值在设定容差内'
                return FieldChange(column, old_value, new_value, numeric=True, accepted_difference=reason)
            return FieldChange(column, old_value, new_value, numeric=True)
        # One side is not a number: fall back to text so the difference is still
        # reported, and flag that numeric comparison was not possible.
        if key_text(old_value, ignore_whitespace=options.ignore_whitespace,
                    ignore_case=options.ignore_case) == key_text(
                        new_value, ignore_whitespace=options.ignore_whitespace,
                        ignore_case=options.ignore_case):
            return _text_difference(old_value, new_value, column, options)
        return FieldChange(column, old_value, new_value, numeric=False, numeric_parse_failed=True)

    left_text = key_text(
        old_value,
        ignore_whitespace=options.ignore_whitespace,
        ignore_case=options.ignore_case,
    )
    right_text = key_text(
        new_value,
        ignore_whitespace=options.ignore_whitespace,
        ignore_case=options.ignore_case,
    )
    if left_text == right_text:
        return _text_difference(old_value, new_value, column, options)
    return FieldChange(column, old_value, new_value, numeric=False)


def _text_difference(old_value: Any, new_value: Any, column: str, options: CompareOptions) -> FieldChange | None:
    left, right = display_text(old_value), display_text(new_value)
    if left == right:
        return None
    reasons = []
    if options.ignore_whitespace and (left != left.strip() or right != right.strip()):
        reasons.append('首尾空格')
        left, right = left.strip(), right.strip()
    if options.ignore_case and left != right and left.casefold() == right.casefold():
        reasons.append('大小写')
    if reasons and (left == right or options.ignore_case and left.casefold() == right.casefold()):
        return FieldChange(column, old_value, new_value, accepted_difference=' / '.join(reasons))
    return None


def _shift(progress: ProgressFn | None, start: float, end: float) -> ProgressFn | None:
    """Remap a nested stage's 0..1 progress into a slice of the outer bar.

    Without this the reading stages and the comparison stages each start from
    their own zero and the progress bar visibly jumps backwards.
    """
    if progress is None:
        return None
    return lambda stage, ratio: progress(stage, start + (end - start) * ratio)


def compare_tables(
    old_table: TableData,
    new_table: TableData,
    keys: Sequence[str],
    options: CompareOptions | None = None,
    *,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> CompareResult:
    options = options or CompareOptions()
    started = time.perf_counter()

    def report(stage: str, ratio: float) -> None:
        if progress:
            progress(stage, ratio)

    validators.validate_key_columns(keys, old_table.columns, label='匹配字段')
    validators.validate_common_columns(
        keys, old_table.columns, new_table.columns, label='匹配字段'
    )

    report('分析列结构', 0.0)
    old_set = list(old_table.columns)
    new_set = list(new_table.columns)
    old_name_set = set(old_set)
    new_name_set = set(new_set)
    shared = [name for name in old_set if name in new_name_set]
    only_in_old = [name for name in old_set if name not in new_name_set]
    only_in_new = [name for name in new_set if name not in old_name_set]
    order_differs = shared != [name for name in new_set if name in old_name_set]

    warnings: list[str] = []
    if only_in_old:
        warnings.append('仅旧版存在的字段：' + ', '.join(only_in_old[:10]))
    if only_in_new:
        warnings.append('仅新版存在的字段：' + ', '.join(only_in_new[:10]))
    if order_differs:
        warnings.append('两个文件的列顺序不同，已按列名对应，不影响结果')
    for table in (old_table, new_table):
        warnings.extend(f'{table.name}：{item}' for item in table.warnings)

    compare_columns = list(options.compare_columns) or [
        name for name in shared if name not in keys
    ]
    if not compare_columns:
        warnings.append('除匹配字段外没有可比较的列，将只判断记录是否存在')

    report('建立索引', 0.2)
    old_unique, old_anomalies, old_dup_keys = _index_by_key(old_table, keys, options, 'old')
    new_unique, new_anomalies, new_dup_keys = _index_by_key(new_table, keys, options, 'new')

    unmatched: list[UnmatchedRow] = []
    old_columns = list(old_table.columns)
    new_columns = list(new_table.columns)

    added: list[tuple[str, int, list[Any]]] = []
    deleted: list[tuple[str, int, list[Any]]] = []
    changed: list[ChangedRow] = []
    unchanged = 0
    unchanged_rows = [] if options.include_unchanged else None
    minor: list[ChangedRow] = []
    strict_modified_rows = 0

    report('匹配记录', 0.4)
    old_keys = set(old_unique)
    new_keys = set(new_unique)

    for key_display in new_keys - old_keys:
        position = new_unique[key_display]
        row = new_table.rows[position]
        if key_display in old_dup_keys:
            unmatched.append(
                UnmatchedRow('new', UNMATCHED_BECAUSE_OLD_ANOMALY, key_display,
                             new_table.row_numbers[position], list(row))
            )
        else:
            added.append((key_display, new_table.row_numbers[position], list(row)))

    for key_display in old_keys - new_keys:
        position = old_unique[key_display]
        row = old_table.rows[position]
        if key_display in new_dup_keys:
            unmatched.append(
                UnmatchedRow('old', UNMATCHED_BECAUSE_NEW_ANOMALY, key_display,
                             old_table.row_numbers[position], list(row))
            )
        else:
            deleted.append((key_display, old_table.row_numbers[position], list(row)))

    report('比较字段', 0.5)
    common = old_keys & new_keys
    old_index_map = {name: i for i, name in enumerate(old_columns)}
    new_index_map = {name: i for i, name in enumerate(new_columns)}
    selected = set(compare_columns)
    columns_to_check = [(column, old_index_map[column], new_index_map[column], column in selected)
                        for column in dict.fromkeys([*compare_columns, *keys])
                        if column in old_index_map and column in new_index_map]
    total = len(common) or 1

    for step, key_display in enumerate(sorted(common), start=1):
        if step % 500 == 0:
            report('比较字段', 0.5 + 0.45 * (step / total))
        raise_if_cancelled(cancel, '比较字段')
        old_position = old_unique[key_display]
        new_position = new_unique[key_display]
        old_row = old_table.rows[old_position]
        new_row = new_table.rows[new_position]

        changes: list[FieldChange] = []
        minor_changes: list[FieldChange] = []
        for column, old_i, new_i, compare_content in columns_to_check:
            old_value = old_row[old_i] if old_i < len(old_row) else None
            new_value = new_row[new_i] if new_i < len(new_row) else None
            change = (_values_differ(old_value, new_value, column, options) if compare_content
                      else _text_difference(old_value, new_value, column, options))
            if change is not None:
                (minor_changes if change.accepted_difference else changes).append(change)

        if minor_changes:
            minor.append(ChangedRow(key_display, old_table.row_numbers[old_position],
                                    new_table.row_numbers[new_position], minor_changes))
        if changes or minor_changes:
            strict_modified_rows += 1

        if changes:
            changed.append(
                ChangedRow(
                    key_display=key_display,
                    old_row=old_table.row_numbers[old_position],
                    new_row=new_table.row_numbers[new_position],
                    changes=changes,
                )
            )
        else:
            unchanged += 1
            if unchanged_rows is not None:
                unchanged_rows.append((new_row, old_table.row_numbers[old_position], new_table.row_numbers[new_position]))

    if old_anomalies or new_anomalies:
        warnings.append(
            f'有 {len(old_anomalies) + len(new_anomalies)} 行因匹配字段为空或重复未参与比对，'
            '请在“异常记录”中处理后再对比'
        )
    if unmatched:
        warnings.append(
            f'有 {len(unmatched)} 行因对侧存在重复匹配字段而无法判定新增或删除'
        )

    report('完成', 1.0)
    result = CompareResult(
        old_path=old_table.path,
        new_path=new_table.path,
        old_name=old_table.name,
        new_name=new_table.name,
        old_sheet=old_table.sheet,
        new_sheet=new_table.sheet,
        keys=list(keys),
        columns=shared,
        old_columns=old_columns,
        new_columns=new_columns,
        shared_columns=shared,
        only_in_old=only_in_old,
        only_in_new=only_in_new,
        column_order_differs=order_differs,
        old_total_rows=old_table.row_count,
        new_total_rows=new_table.row_count,
        added=added,
        deleted=deleted,
        changed=changed,
        anomalies=old_anomalies + new_anomalies,
        unmatched=unmatched,
        unchanged_count=unchanged,
        minor=minor,
        strict_modified_rows=strict_modified_rows,
        unchanged_rows=unchanged_rows,
        warnings=list(dict.fromkeys(warnings)),
        timings={'total': round(time.perf_counter() - started, 3)},
    )
    return result


def compare_files(
    old_path: str,
    new_path: str,
    *,
    keys: Sequence[str],
    old_sheet: str | None = None,
    new_sheet: str | None = None,
    header_row: int = 1,
    old_header_row: int | None = None,
    new_header_row: int | None = None,
    options: CompareOptions | dict | None = None,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> CompareResult:
    """Read both files and compare them. `options` may be a raw UI payload."""
    if progress:
        progress('读取旧版文件', 0.0)
    old_table = read_table(
        old_path, sheet=old_sheet, header_row=old_header_row if old_header_row is not None else header_row,
        label='旧版文件', cancel=cancel,
    )
    if progress:
        progress('读取新版文件', 0.1)
    new_table = read_table(
        new_path, sheet=new_sheet, header_row=new_header_row if new_header_row is not None else header_row,
        label='新版文件', cancel=cancel,
    )

    if isinstance(options, dict):
        parsed = CompareOptions.from_payload(options, old_table.columns)
        missing = [name for name in parsed.numeric_columns if name not in new_table.columns]
        if missing:
            raise ValidationError('数值比较字段在新版文件中不存在：' + ', '.join(missing))
    elif options is None:
        parsed = CompareOptions()
    else:
        parsed = options

    return compare_tables(
        old_table, new_table, keys, parsed, progress=_shift(progress, 0.2, 1.0), cancel=cancel
    )


def anomaly_display(anomaly: KeyAnomaly) -> dict:
    return {
        'side': anomaly.side,
        'reason': anomaly.reason,
        'key': anomaly.key_display,
        'row': anomaly.row_number,
        'values': [display_text(value) for value in anomaly.values],
    }

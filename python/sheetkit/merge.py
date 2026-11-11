"""Vertical merge of several workbooks, aligned by column name.

Columns are matched by name, never by position, so a file whose columns are
reordered or partially missing still merges correctly. Missing fields stay
empty; nothing is deduplicated and no column of differing meaning is silently
combined — a mapping conflict is reported instead of resolved automatically.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .cancel import raise_if_cancelled
from .errors import ValidationError
from .reader import TableData, read_table
from .values import normalize_header
from . import validators

ProgressFn = Callable[[str, float], None]

SOURCE_FILE_COLUMN = '来源文件'
SOURCE_SHEET_COLUMN = '来源工作表'
SOURCE_ROW_COLUMN = '原始行号'
SOURCE_COLUMN_BASES = (SOURCE_FILE_COLUMN, SOURCE_SHEET_COLUMN, SOURCE_ROW_COLUMN)


@dataclass
class MergeSource:
    path: str
    sheet: str | None = None
    header_row: int = 1
    mapping: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @classmethod
    def from_payload(cls, payload: Any) -> 'MergeSource':
        if not isinstance(payload, dict):
            raise ValidationError('合并文件项必须是对象')
        mapping_raw = payload.get('mapping') or {}
        if not isinstance(mapping_raw, dict):
            raise ValidationError('字段映射必须是对象')
        mapping = {
            normalize_header(key): normalize_header(value)
            for key, value in mapping_raw.items()
            if normalize_header(key) and normalize_header(value)
        }
        return cls(
            path=validators.require_text(payload.get('path'), '文件路径'),
            sheet=payload.get('sheet') or None,
            header_row=validators.require_int(
                payload.get('header_row'), '表头行', minimum=1, maximum=10000, default=1
            ),
            mapping=mapping,
            enabled=validators.require_bool(payload.get('enabled'), '是否参与合并', default=True),
        )


@dataclass
class SourceReport:
    path: str
    name: str
    sheet: str | None
    header_row: int
    columns: list[str]
    mapped_columns: list[str]
    row_count: int
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'path': self.path,
            'name': self.name,
            'sheet': self.sheet or '',
            'header_row': self.header_row,
            'columns': list(self.columns),
            'mapped_columns': list(self.mapped_columns),
            'rows': self.row_count,
            'skipped': self.skipped,
            'warnings': list(self.warnings),
        }


@dataclass
class MergePlan:
    """Column layout computed from the sources, before any row is written."""

    sources: list[SourceReport]
    body_columns: list[str]
    source_columns: list[str]
    partial_columns: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def target_columns(self) -> list[str]:
        return self.body_columns + self.source_columns

    def to_dict(self) -> dict:
        return {
            'sources': [item.to_dict() for item in self.sources],
            'body_columns': list(self.body_columns),
            'source_columns': list(self.source_columns),
            'target_columns': self.target_columns,
            'partial_columns': list(self.partial_columns),
            'warnings': list(self.warnings),
        }


@dataclass
class MergeResult:
    plan: MergePlan
    rows: list[list[Any]]
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def columns(self) -> list[str]:
        return self.plan.target_columns

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def summary(self) -> dict:
        payload = self.plan.to_dict()
        payload.update(
            {
                'total_rows': self.row_count,
                'total_columns': len(self.columns),
                'file_count': len(self.plan.sources),
                'merged_file_count': sum(1 for item in self.plan.sources if not item.skipped),
                'timings': dict(self.timings),
            }
        )
        return payload


@dataclass
class _LoadedSource:
    source: MergeSource
    table: TableData
    effective_columns: list[str]


def _effective_columns(table: TableData, mapping: dict[str, str]) -> list[str]:
    """Apply a rename mapping and refuse collisions inside a single source.

    Two source columns landing on the same target would silently mix data of
    different meaning, so the user is asked to fix the mapping instead.
    """
    unknown = [name for name in mapping if name not in table.columns]
    if unknown:
        raise ValidationError(
            f'{table.name} 中不存在被映射的字段：{", ".join(unknown[:6])}', detail=table.path
        )

    owners: dict[str, str] = {}
    effective: list[str] = []
    conflicts: list[str] = []

    for original in table.columns:
        target = mapping.get(original, original)
        previous = owners.get(target)
        if previous is not None and previous != original:
            conflicts.append(f'“{original}”与“{previous}”都映射到“{target}”')
        owners[target] = original
        effective.append(target)

    if conflicts:
        raise ValidationError(
            f'{table.name} 字段映射冲突：' + '；'.join(conflicts[:5])
            + ('…' if len(conflicts) > 5 else ''),
            detail=table.path,
        )
    return effective


def _load_sources(
    sources: Sequence[MergeSource], *, progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> tuple[list[_LoadedSource], list[SourceReport]]:
    if not sources:
        raise ValidationError('请至少添加一个文件')

    loaded: list[_LoadedSource] = []
    reports: list[SourceReport] = []
    # Reading dominates the wall-clock time of a 50k-row merge, so progress is
    # reported per file here rather than only once for the whole batch.
    total = len(sources)

    for index, source in enumerate(sources):
        if not source.enabled:
            reports.append(
                SourceReport(
                    path=source.path,
                    name=source.name,
                    sheet=source.sheet,
                    header_row=source.header_row,
                    columns=[],
                    mapped_columns=[],
                    row_count=0,
                    skipped=True,
                    warnings=['已取消勾选，不参与合并'],
                )
            )
            continue

        if progress:
            progress(f'读取 {source.name}', 0.05 + 0.15 * (index / total))
        table = read_table(
            source.path,
            sheet=source.sheet,
            header_row=source.header_row,
            label=source.name,
            cancel=cancel,
        )
        effective = _effective_columns(table, source.mapping)
        loaded.append(_LoadedSource(source=source, table=table, effective_columns=effective))
        reports.append(
            SourceReport(
                path=table.path,
                name=table.name,
                sheet=table.sheet,
                header_row=table.header_row,
                columns=list(table.columns),
                mapped_columns=effective,
                row_count=table.row_count,
                warnings=list(table.warnings),
            )
        )

    if not loaded:
        raise ValidationError('没有参与合并的文件，请至少勾选一个')
    return loaded, reports


def _build_plan(
    loaded: Sequence[_LoadedSource],
    reports: Sequence[SourceReport],
    *,
    add_source_columns: bool,
) -> MergePlan:
    order: list[str] = []
    seen: set[str] = set()
    per_column_sources: dict[str, int] = {}
    warnings: list[str] = []

    for item in loaded:
        for name in item.effective_columns:
            if name not in seen:
                seen.add(name)
                order.append(name)
            per_column_sources[name] = per_column_sources.get(name, 0) + 1

    partial = [name for name in order if per_column_sources[name] < len(loaded)]
    if partial:
        warnings.append(
            f'{len(partial)} 个字段只在部分文件中出现，缺失处将保留空值：'
            + ', '.join(partial[:8])
            + ('…' if len(partial) > 8 else '')
        )

    source_columns: list[str] = []
    if add_source_columns:
        for base in SOURCE_COLUMN_BASES:
            if base in seen:
                warnings.append(f'源数据已存在“{base}”列，为避免覆盖改用“{base}(来源)”')
                source_columns.append(f'{base}(来源)')
            else:
                source_columns.append(base)

    for report in reports:
        warnings.extend(f'{report.name}：{item}' for item in report.warnings)

    return MergePlan(
        sources=list(reports),
        body_columns=order,
        source_columns=source_columns,
        partial_columns=partial,
        warnings=list(dict.fromkeys(warnings)),
    )


def plan_merge(sources: Sequence[MergeSource], *, add_source_columns: bool = True) -> MergePlan:
    """Inspect the sources and return the target layout for the mapping UI."""
    loaded, reports = _load_sources(sources)
    return _build_plan(loaded, reports, add_source_columns=add_source_columns)


def merge_sources(
    sources: Sequence[MergeSource],
    *,
    add_source_columns: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> MergeResult:
    """Read every source once and stack the rows on the shared column layout."""
    started = time.perf_counter()

    def report(stage: str, ratio: float) -> None:
        if progress:
            progress(stage, max(0.0, min(1.0, ratio)))

    report('读取文件', 0.0)
    loaded, reports = _load_sources(sources, progress=progress, cancel=cancel)
    plan = _build_plan(loaded, reports, add_source_columns=add_source_columns)

    slots = {name: index for index, name in enumerate(plan.body_columns)}
    width = len(plan.body_columns) + len(plan.source_columns)
    provenance_base = len(plan.body_columns)

    total_rows = sum(item.table.row_count for item in loaded) or 1
    rows: list[list[Any]] = []
    done = 0

    for item in loaded:
        table = item.table
        # Slot per source column, resolved once per file instead of per row.
        target_slots = [slots.get(name) for name in item.effective_columns]
        report(f'合并 {table.name}', 0.2 + 0.75 * (done / total_rows))

        for position, row in enumerate(table.rows):
            raise_if_cancelled(cancel, f'合并 {table.name}')
            out: list[Any] = [None] * width
            for source_index, target_slot in enumerate(target_slots):
                if target_slot is None or source_index >= len(row):
                    continue
                out[target_slot] = row[source_index]

            if plan.source_columns:
                out[provenance_base] = table.name
                out[provenance_base + 1] = table.sheet or ''
                out[provenance_base + 2] = table.row_numbers[position]

            rows.append(out)
            done += 1

    report('完成', 1.0)
    return MergeResult(
        plan=plan,
        rows=rows,
        timings={'total': round(time.perf_counter() - started, 3), 'rows': len(rows)},
    )


def merge_files(
    paths: Iterable[str],
    *,
    sheets: dict[str, str | None] | None = None,
    header_rows: dict[str, int] | None = None,
    mappings: dict[str, dict[str, str]] | None = None,
    add_source_columns: bool = True,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> MergeResult:
    """Convenience wrapper for tests and script use."""
    sheets = sheets or {}
    header_rows = header_rows or {}
    mappings = mappings or {}
    sources = [
        MergeSource(
            path=path,
            sheet=sheets.get(path),
            header_row=header_rows.get(path, 1),
            mapping=mappings.get(path, {}),
        )
        for path in paths
    ]
    return merge_sources(
        sources,
        add_source_columns=add_source_columns,
        progress=progress,
        cancel=cancel,
    )

"""The bridge between the Vue frontend and the Python engine.

Every method takes one JSON object and returns one JSON object. Expected
failures come back as ``{"ok": false, "error": {...}}`` so the UI can show the
message directly instead of handling a rejected promise for every case.

The bridge never sends a whole table to the frontend: results stay in this
process and the UI asks for one page at a time.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

from .clean import CleanOptions, clean_file, clean_impact
from .compare import CompareOptions, compare_files
from .errors import SheetKitError, ValidationError
from .exporter import write_workbook
from .merge import MergeSource, merge_sources, plan_merge
from .reader import profile_file, read_table
from .reports import clean_report, compare_report, merge_report
from .results import DEFAULT_PAGE, ResultStore, ResultTable, StoredResult
from . import validators

logger = logging.getLogger('sheetkit.api')

ACTIONS = ('compare', 'merge', 'clean')
EXPORT_KINDS = ('compare', 'merge', 'clean')

EXCEL_FILE_TYPES = ('Excel 或 CSV 文件 (*.xlsx;*.xlsm;*.csv)', '所有文件 (*.*)')


def _guard(func: Callable[..., dict]) -> Callable[..., dict]:
    """Turn expected failures into a normal response envelope."""

    @functools.wraps(func)
    def wrapper(self, payload: Any) -> dict:
        try:
            return func(self, payload if isinstance(payload, dict) else {})
        except SheetKitError as exc:
            return {'ok': False, 'error': exc.to_dict()}
        except Exception as exc:  # noqa: BLE001 - the bridge must never leak a traceback
            # Only the failure kind is logged; the payload may hold business data.
            logger.error('sheetkit api %s failed: %s', func.__name__, type(exc).__name__)
            return {
                'ok': False,
                'error': {
                    'code': 'E_INTERNAL',
                    'message': f'操作失败：{exc}',
                },
            }

    return wrapper


class SheetKitApi:
    """Everything the frontend may ask the engine to do."""

    def __init__(self, window: Any = None) -> None:
        # The window must stay private: pywebview walks the public attributes
        # of the API object to publish it to JavaScript, and the WinForms
        # object graph behind the window is far too much to expose.
        self._window = window
        self._store = ResultStore()
        self._tables: OrderedDict[tuple, tuple] = OrderedDict()
        self._jobs: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._table_cache_limit = 4

    def _attach(self, window: Any) -> None:
        self._window = window

    def _cancel_event(self, job_id: str) -> threading.Event:
        """Register the cancel flag for a job before the work starts.

        The frontend picks the id so that it can cancel a job that is still
        running, which is exactly when cancelling matters. An event that is
        already registered is reused, so a cancel that arrives a moment before
        the job does is not lost.
        """
        with self._lock:
            event = self._jobs.get(job_id)
            if event is None:
                event = threading.Event()
                self._jobs[job_id] = event
            return event

    def _release_job(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    # ------------------------------------------------------------------ files

    @_guard
    def choose_files(self, payload: dict) -> dict:
        """Open a native file or folder picker."""
        kind = str(payload.get('kind') or 'open')
        default_path = str(payload.get('default_path') or '')
        save_name = str(payload.get('save_name') or '')

        if self._window is None:
            return {'ok': False, 'error': {'code': 'E_INTERNAL', 'message': '窗口尚未就绪'}}

        import webview

        if kind == 'folder':
            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER, directory=default_path
            )
        elif kind == 'save':
            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=default_path,
                save_filename=save_name or 'SheetKit导出.xlsx',
                file_types=('Excel 文件 (*.xlsx)',),
            )
        else:
            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=default_path,
                allow_multiple=kind == 'multi',
                file_types=EXCEL_FILE_TYPES,
            )

        if not selected:
            return {'ok': True, 'paths': []}
        paths = [str(item) for item in selected]
        return {'ok': True, 'paths': paths}

    @_guard
    def list_folder(self, payload: dict) -> dict:
        """List the mergeable files inside a folder."""
        folder = str(payload.get('path') or '')
        if not folder:
            raise ValidationError('请先选择文件夹')
        if not os.path.isdir(folder):
            raise ValidationError('所选路径不是文件夹')
        paths = []
        for name in sorted(os.listdir(folder)):
            full = os.path.join(folder, name)
            if not os.path.isfile(full):
                continue
            if os.path.splitext(name)[1].lower() in validators.READABLE_EXTS:
                paths.append(full)
        return {'ok': True, 'paths': paths}

    @_guard
    def describe(self, payload: dict) -> dict:
        """Cheap structural read: sheet names, warnings, encoding."""
        profile = profile_file(payload.get('path'))
        return {
            'ok': True,
            'file': {
                'path': profile.path,
                'name': profile.name,
                'kind': profile.kind,
                'sheets': [
                    {'name': item.name, 'max_row': item.max_row, 'max_column': item.max_column}
                    for item in profile.sheets
                ],
                'has_macros': profile.has_macros,
                'maybe_open_elsewhere': profile.maybe_open_elsewhere,
                'encoding': profile.encoding,
                'delimiter': profile.delimiter,
                'warnings': list(profile.warnings),
            },
        }

    @_guard
    def preview(self, payload: dict) -> dict:
        """One page of a file, for the preview table."""
        path = payload.get('path')
        sheet = payload.get('sheet') or None
        header_row = int(payload.get('header_row') or 1)
        offset = int(payload.get('offset') or 0)
        limit = int(payload.get('limit') or DEFAULT_PAGE)

        table = self._load_table(path, sheet, header_row)
        page = ResultTable(columns=list(table.columns), rows=table.rows).page(offset, limit)
        page['row_numbers'] = table.row_numbers[offset : offset + page['limit']]
        page['sheet'] = table.sheet
        page['header_row'] = table.header_row
        page['blank_rows'] = table.blank_rows
        page['warnings'] = list(table.warnings)
        page['truncated'] = table.truncated
        page['name'] = table.name
        return {'ok': True, 'table': page}

    def _load_table(self, path: Any, sheet: str | None, header_row: int):
        """Read a table, reusing the previous read while the file is unchanged."""
        resolved, _kind = validators.open_input(path, label='文件')
        key = (os.path.normcase(resolved), sheet, header_row)
        try:
            stat = os.stat(resolved)
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None

        with self._lock:
            cached = self._tables.get(key)
            if cached is not None and cached[0] == stamp:
                self._tables.move_to_end(key)
                return cached[1]

        table = read_table(resolved, sheet=sheet, header_row=header_row)
        with self._lock:
            self._tables[key] = (stamp, table)
            while len(self._tables) > self._table_cache_limit:
                self._tables.popitem(last=False)
        return table

    # ------------------------------------------------------------------ merge

    @_guard
    def plan(self, payload: dict) -> dict:
        """Inspect the merge sources and return the target column layout."""
        sources = self._merge_sources(payload.get('sources'))
        plan = plan_merge(sources)
        return {'ok': True, 'plan': plan.to_dict()}

    # ---------------------------------------------------------------- analysis

    @_guard
    def analyze(self, payload: dict) -> dict:
        """Run compare, merge or clean and return a summary plus the first page."""
        action = str(payload.get('action') or '')
        if action not in ACTIONS:
            return {
                'ok': False,
                'error': {'code': 'E_VALIDATION', 'message': f'不支持的操作：{action}'},
            }

        job_id = str(payload.get('job_id') or '')
        cancel = self._cancel_event(job_id) if job_id else None
        progress = self._progress_reporter()
        try:
            if action == 'compare':
                stored = self._run_compare(payload, progress, cancel)
            elif action == 'merge':
                stored = self._run_merge(payload, progress, cancel)
            else:
                stored = self._run_clean(payload, progress, cancel)
        finally:
            if job_id:
                self._release_job(job_id)

        result_id = self._store.put(stored)
        return {
            'ok': True,
            'result_id': result_id,
            'kind': stored.kind,
            'summary': stored.summary,
            'warnings': list(stored.warnings),
            'tables': {
                name: {'columns': table.columns, 'total': len(table.rows)}
                for name, table in stored.tables.items()
            },
            'preview': {
                name: table.page(0, DEFAULT_PAGE) for name, table in stored.tables.items()
            },
        }

    def _run_compare(self, payload: dict, progress, cancel=None) -> StoredResult:
        options = payload.get('options')
        if options is None:
            options = CompareOptions()
        elif not isinstance(options, dict):
            options = CompareOptions()
        result = compare_files(
            str(payload.get('old_path') or ''),
            str(payload.get('new_path') or ''),
            keys=[str(key) for key in (payload.get('keys') or [])],
            old_sheet=payload.get('old_sheet') or None,
            new_sheet=payload.get('new_sheet') or None,
            header_row=int(payload.get('header_row') or 1),
            options=options if isinstance(options, dict) else CompareOptions(),
            progress=progress,
            cancel=cancel,
        )

        added = ResultTable(
            columns=[*result.new_columns, '新版行号'],
            rows=[[*values, number] for _key, number, values in result.added],
        )
        deleted = ResultTable(
            columns=[*result.old_columns, '旧版行号'],
            rows=[[*values, number] for _key, number, values in result.deleted],
        )
        changed = ResultTable(
            columns=['匹配字段', '修改列', '旧值', '新值', '旧版行号', '新版行号', '比较方式'],
            rows=[
                [
                    record['key'],
                    record['column'],
                    record['old_value'],
                    record['new_value'],
                    record['old_row'],
                    record['new_row'],
                    '数值比较失败，按文本比较'
                    if record['numeric_parse_failed']
                    else ('十进制数值比较' if record['numeric'] else '文本比较'),
                ]
                for record in result.modification_records
            ],
        )
        union = list(result.old_columns) + [
            name for name in result.new_columns if name not in set(result.old_columns)
        ]
        anomaly_rows: list[list[Any]] = []
        for item in result.anomalies:
            columns = result.new_columns if item.side == 'new' else result.old_columns
            anomaly_rows.append(
                [
                    '新版' if item.side == 'new' else '旧版',
                    '匹配字段为空' if item.reason == 'blank' else '匹配字段重复',
                    item.key_display,
                    item.row_number,
                    *_align(item.values, columns, union),
                ]
            )
        for item in result.unmatched:
            columns = result.new_columns if item.side == 'new' else result.old_columns
            anomaly_rows.append(
                [
                    '新版' if item.side == 'new' else '旧版',
                    '旧版匹配字段重复，无法判定'
                    if item.side == 'new'
                    else '新版匹配字段重复，无法判定',
                    item.key_display,
                    item.row_number,
                    *_align(item.values, columns, union),
                ]
            )
        anomaly = ResultTable(
            columns=['来源', '异常类型', '匹配字段', '原始行号', *union], rows=anomaly_rows
        )

        return StoredResult(
            kind='compare',
            summary=result.summary(),
            tables={'added': added, 'deleted': deleted, 'changed': changed, 'anomaly': anomaly},
            warnings=list(result.warnings),
            source_paths=[result.old_path, result.new_path],
            meta={'engine': result},
        )

    def _run_merge(self, payload: dict, progress, cancel=None) -> StoredResult:
        sources = self._merge_sources(payload.get('sources'))
        result = merge_sources(sources, progress=progress, cancel=cancel)
        table = ResultTable(columns=list(result.columns), rows=result.rows)
        return StoredResult(
            kind='merge',
            summary=result.summary(),
            tables={'merged': table},
            warnings=list(result.plan.warnings),
            source_paths=[item.path for item in result.plan.sources],
            meta={'engine': result},
        )

    def _run_clean(self, payload: dict, progress, cancel=None) -> StoredResult:
        options = payload.get('options')
        if options is None or not isinstance(options, dict):
            options = CleanOptions()
        result = clean_file(
            str(payload.get('path') or ''),
            options,
            sheet=payload.get('sheet') or None,
            header_row=int(payload.get('header_row') or 1),
            progress=progress,
            cancel=cancel,
        )
        columns = list(result.columns)
        return StoredResult(
            kind='clean',
            summary=result.summary(),
            tables={
                'cleaned': ResultTable(columns=columns, rows=result.rows),
                'duplicates': ResultTable(columns=columns, rows=result.duplicate_rows),
                'anomalies': ResultTable(columns=columns, rows=result.anomaly_rows),
            },
            warnings=list(result.warnings),
            source_paths=[result.path],
            meta={'engine': result},
        )

    def _merge_sources(self, raw: Any) -> list[MergeSource]:
        if not isinstance(raw, list) or not raw:
            raise ValidationError('请至少添加一个文件')
        return [MergeSource.from_payload(item) for item in raw]

    # ------------------------------------------------------------------ paging

    @_guard
    def page(self, payload: dict) -> dict:
        """Fetch another page of a stored result."""
        stored = self._store.get(str(payload.get('result_id') or ''))
        if stored is None:
            return {
                'ok': False,
                'error': {'code': 'E_RESULT_EXPIRED', 'message': '结果已过期，请重新执行'},
            }
        table = stored.tables.get(str(payload.get('table') or ''))
        if table is None:
            return {
                'ok': False,
                'error': {'code': 'E_VALIDATION', 'message': '没有这个数据表'},
            }
        offset = int(payload.get('offset') or 0)
        limit = int(payload.get('limit') or DEFAULT_PAGE)
        filter_text = str(payload.get('filter') or '')
        return {'ok': True, 'table': table.page(offset, limit, filter_text)}

    @_guard
    def cancel(self, payload: dict) -> dict:
        """Ask a running job to stop.

        A cancel for a job that has not registered yet is remembered, so the
        order in which the two calls arrive does not matter.
        """
        job_id = str(payload.get('job_id') or '')
        if not job_id:
            return {'ok': True, 'cancelled': False}
        self._cancel_event(job_id).set()
        return {'ok': True, 'cancelled': True}

    @_guard
    def impact(self, payload: dict) -> dict:
        """Show how many rows a destructive duplicate rule would remove."""
        options = payload.get('options') or {}
        impact = clean_impact(
            str(payload.get('path') or ''),
            options if isinstance(options, dict) else CleanOptions(),
            sheet=payload.get('sheet') or None,
            header_row=int(payload.get('header_row') or 1),
        )
        return {'ok': True, 'impact': impact}

    # ------------------------------------------------------------------ export

    @_guard
    def export(self, payload: dict) -> dict:
        """Write a result to a new .xlsx file."""
        kind = str(payload.get('kind') or '')
        if kind not in EXPORT_KINDS:
            return {
                'ok': False,
                'error': {'code': 'E_VALIDATION', 'message': f'不支持的导出类型：{kind}'},
            }
        stored = self._store.get(str(payload.get('result_id') or ''))
        if stored is None:
            return {
                'ok': False,
                'error': {'code': 'E_RESULT_EXPIRED', 'message': '结果已过期，请重新执行'},
            }

        engine = stored.meta.get('engine')
        if kind == 'compare':
            spec = compare_report(engine)
        elif kind == 'merge':
            spec = merge_report(engine)
        else:
            spec = clean_report(engine)

        destination = payload.get('destination')
        job_id = str(payload.get('job_id') or '')
        cancel = self._cancel_event(job_id) if job_id else None
        try:
            written = write_workbook(
                destination,
                spec,
                input_paths=stored.source_paths,
                progress=self._progress_reporter(),
                cancel=cancel,
            )
        finally:
            if job_id:
                self._release_job(job_id)
        return {'ok': True, 'path': written}

    @_guard
    def release(self, payload: dict) -> dict:
        """Drop a stored result as soon as the user is done with it."""
        self._store.drop(str(payload.get('result_id') or ''))
        return {'ok': True}

    # ----------------------------------------------------------------- helpers

    def _progress_reporter(self) -> Callable[[str, float], None] | None:
        window = self._window
        if window is None:
            return None

        def report(stage: str, ratio: float) -> None:
            payload = json.dumps(
                {'stage': stage, 'ratio': round(max(0.0, min(1.0, ratio)), 4)},
                ensure_ascii=False,
            )
            try:
                window.evaluate_js(
                    f'window.sheetkitProgress && window.sheetkitProgress({payload})'
                )
            except Exception:  # noqa: BLE001 - progress must never break the job
                pass

        return report

    def shutdown(self) -> None:
        """Forget everything the session held."""
        self._store.clear()
        with self._lock:
            self._tables.clear()
            for event in self._jobs.values():
                event.set()
            self._jobs.clear()


def _align(values: list, source_columns: list[str], target_columns: list[str]) -> list:
    """Move a row from its own column layout onto the shared layout."""
    index = {name: position for position, name in enumerate(source_columns)}
    out: list = []
    for name in target_columns:
        position = index.get(name)
        out.append(values[position] if position is not None and position < len(values) else None)
    return out

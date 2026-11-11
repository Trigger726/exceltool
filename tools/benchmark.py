"""Workload benchmark for the SheetKit engine.

Measures the three workloads the product brief names — a 10k-row file, a
50k-row multi-file merge and a 10k-row comparison — and reports read,
processing and export time plus peak Python memory.

Timing and memory are measured in separate passes: tracemalloc traces every
allocation and would otherwise multiply the reported times several times over.

    .venv\\Scripts\\python.exe tools\\benchmark.py
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import tracemalloc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python'))

from openpyxl import Workbook  # noqa: E402

from sheetkit.clean import clean_file  # noqa: E402
from sheetkit.compare import compare_files  # noqa: E402
from sheetkit.exporter import write_workbook  # noqa: E402
from sheetkit.merge import MergeSource, merge_sources  # noqa: E402
from sheetkit.reader import read_table  # noqa: E402
from sheetkit.reports import clean_report, compare_report, merge_report  # noqa: E402

WORK = os.path.join(ROOT, 'tools', '_bench')
HEADERS = ['物料编码', '品名', '规格型号', '数量', '单价', '金额', '交期', '备注']


def build(path: str, rows: int, *, offset: int = 0) -> str:
    book = Workbook(write_only=True)
    sheet = book.create_sheet('数据')
    sheet.append(HEADERS)
    for index in range(rows):
        number = index + offset
        sheet.append(
            [
                f'{number:06d}',
                f'物料{number % 997}',
                f'M{number % 40} x {number % 9 + 1}',
                number % 500,
                round(1.5 + (number % 100) / 10, 2),
                round((number % 500) * (1.5 + (number % 100) / 10), 2),
                f'2024-{(number % 12) + 1:02d}-{(number % 28) + 1:02d}',
                '备注内容',
            ]
        )
    book.save(path)
    return path


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)

    print('building workloads...', flush=True)
    old = build(os.path.join(WORK, 'old.xlsx'), 10_000)
    new = build(os.path.join(WORK, 'new.xlsx'), 10_000, offset=120)
    parts = [build(os.path.join(WORK, f'part{i}.xlsx'), 10_000, offset=i * 10_000) for i in range(5)]

    engines: dict = {}

    def run_compare():
        result = compare_files(old, new, keys=['物料编码'])
        engines['compare'] = result
        return {
            'added': len(result.added),
            'deleted': len(result.deleted),
            'modified': len(result.changed),
        }

    def run_merge():
        result = merge_sources([MergeSource(path=part) for part in parts])
        engines['merge'] = result
        return {'rows': result.row_count, 'columns': len(result.columns)}

    def run_clean():
        result = clean_file(
            old,
            {
                'duplicate_key_columns': ['物料编码'],
                'required_columns': ['品名'],
                'date_columns': ['交期'],
                'number_columns': ['数量'],
            },
        )
        engines['clean'] = result
        return {'rows': result.row_count, 'duplicates': result.stats['duplicate_rows']}

    workloads = [
        ('read 10k-row file', lambda: read_table(old).row_count),
        ('compare two 10k-row files', run_compare),
        ('merge 5 files / 50k rows', run_merge),
        ('clean 10k-row file', run_clean),
    ]

    print('timing...', flush=True)
    timings: list[tuple[str, float, object]] = []
    for label, func in workloads:
        started = time.perf_counter()
        result = func()
        timings.append((label, time.perf_counter() - started, result))

    exports = [
        (
            'export compare report',
            lambda: write_workbook(
                os.path.join(WORK, 'compare-report.xlsx'),
                compare_report(engines['compare']),
                input_paths=[old, new],
            ),
        ),
        (
            'export merge report',
            lambda: write_workbook(
                os.path.join(WORK, 'merge-report.xlsx'),
                merge_report(engines['merge']),
                input_paths=parts,
            ),
        ),
        (
            'export clean report',
            lambda: write_workbook(
                os.path.join(WORK, 'clean-report.xlsx'),
                clean_report(engines['clean']),
                input_paths=[old],
            ),
        ),
    ]
    for label, func in exports:
        started = time.perf_counter()
        result = func()
        timings.append((label, time.perf_counter() - started, result))

    print('measuring memory...', flush=True)
    memory: list[tuple[str, float]] = []
    for label, func in workloads:
        tracemalloc.start()
        func()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        memory.append((label, peak / 1024 / 1024))

    print()
    print(f'{"workload":<32} {"seconds":>9} {"peak MiB":>10}  result')
    print('-' * 84)
    for label, seconds, result in timings:
        peak = next((value for name, value in memory if name == label), None)
        peak_text = f'{peak:.1f}' if peak is not None else '-'
        print(f'{label:<32} {seconds:>9.3f} {peak_text:>10}  {result}')

    print()
    for name in ('old.xlsx', 'new.xlsx', 'part0.xlsx'):
        path = os.path.join(WORK, name)
        print(f'{name}: {os.path.getsize(path) / 1024 / 1024:.2f} MiB')
    for name in ('compare-report.xlsx', 'merge-report.xlsx', 'clean-report.xlsx'):
        path = os.path.join(WORK, name)
        print(f'{name}: {os.path.getsize(path) / 1024 / 1024:.2f} MiB')

    return 0


if __name__ == '__main__':
    sys.exit(main())

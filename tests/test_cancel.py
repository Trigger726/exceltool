"""Cancellation of running jobs, and filtering of the result tables."""

from __future__ import annotations

import threading

import pytest

from sheetkit.cancel import raise_if_cancelled
from sheetkit.clean import CleanOptions, clean_table
from sheetkit.compare import compare_tables
from sheetkit.errors import TaskCancelledError
from sheetkit.exporter import SheetSpec, WorkbookSpec, write_workbook
from sheetkit.merge import MergeSource, merge_sources
from sheetkit.reader import read_table
from sheetkit.results import ResultTable

HEADERS = ['物料编码', '品名', '数量']


def test_raise_if_cancelled_is_a_no_op_without_a_flag():
    raise_if_cancelled(None)
    raise_if_cancelled(threading.Event())


def test_raise_if_cancelled_reports_the_stage():
    event = threading.Event()
    event.set()
    with pytest.raises(TaskCancelledError) as info:
        raise_if_cancelled(event, '比较字段')
    assert '比较字段' in info.value.message
    assert info.value.code == 'E_CANCELLED'


def test_a_cancelled_comparison_stops(xlsx):
    old = read_table(xlsx('old.xlsx', HEADERS, [['A1', '甲', 1], ['B2', '乙', 2]]))
    new = read_table(xlsx('new.xlsx', HEADERS, [['A1', '甲', 9]]))
    event = threading.Event()
    event.set()
    with pytest.raises(TaskCancelledError):
        compare_tables(old, new, ['物料编码'], cancel=event)


def test_a_cancelled_merge_stops(xlsx):
    path = xlsx('a.xlsx', HEADERS, [['A1', '甲', 1]])
    event = threading.Event()
    event.set()
    with pytest.raises(TaskCancelledError):
        merge_sources([MergeSource(path=path)], cancel=event)


def test_a_cancelled_clean_stops(xlsx):
    path = xlsx('a.xlsx', HEADERS, [['A1', '甲', 1]])
    table = read_table(path)
    event = threading.Event()
    event.set()
    with pytest.raises(TaskCancelledError):
        clean_table(table, CleanOptions(duplicate_action='none'), cancel=event)


def test_a_cancelled_export_leaves_no_output(tmp_path):
    event = threading.Event()
    event.set()
    out = tmp_path / 'report.xlsx'
    with pytest.raises(TaskCancelledError):
        write_workbook(
            str(out),
            WorkbookSpec().add(SheetSpec(name='S', headers=['a'], rows=[[1]])),
            cancel=event,
        )
    assert not out.exists()


def test_a_job_that_is_not_cancelled_finishes_normally(xlsx):
    old = read_table(xlsx('old.xlsx', HEADERS, [['A1', '甲', 1]]))
    new = read_table(xlsx('new.xlsx', HEADERS, [['A1', '甲', 1]]))
    result = compare_tables(old, new, ['物料编码'], cancel=threading.Event())
    assert result.unchanged_count == 1


def test_result_table_filters_rows():
    table = ResultTable(
        columns=['编码', '品名'],
        rows=[['A1', '甲'], ['B2', '乙'], ['C3', '甲乙']],
    )
    page = table.page(0, 10, '甲')
    assert page['total'] == 2
    assert page['unfiltered_total'] == 3
    assert page['filter'] == '甲'
    assert [row[0] for row in page['rows']] == ['A1', 'C3']


def test_result_table_filter_is_case_insensitive():
    table = ResultTable(columns=['编码'], rows=[['a1'], ['B2']])
    assert table.page(0, 10, 'A')['total'] == 1


def test_result_table_filter_matches_any_column():
    table = ResultTable(columns=['编码', '品名'], rows=[['A1', '甲'], ['B2', '乙']])
    assert table.page(0, 10, '乙')['total'] == 1


def test_result_table_filter_that_matches_nothing():
    table = ResultTable(columns=['编码'], rows=[['A1']])
    page = table.page(0, 10, 'zzz')
    assert page['total'] == 0
    assert page['rows'] == []


def test_result_table_filter_keeps_paging_consistent():
    rows = [[f'A{index}', '甲'] for index in range(10)]
    table = ResultTable(columns=['编码', '品名'], rows=rows)
    page = table.page(4, 3, '甲')
    assert len(page['rows']) == 3
    assert page['offset'] == 4
    assert page['total'] == 10


def test_an_empty_filter_is_ignored():
    table = ResultTable(columns=['编码'], rows=[['A1']])
    assert table.page(0, 10, '  ')['total'] == 1

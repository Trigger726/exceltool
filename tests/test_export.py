"""Export safety: no clobbering, no live formulas, no lost digits."""

from __future__ import annotations

import os

import pytest
from openpyxl import load_workbook

from sheetkit.clean import CleanOptions, clean_table
from sheetkit.compare import compare_tables
from sheetkit.errors import ExportError, OutputConflictError, UnsupportedFormatError
from sheetkit.exporter import (
    TINTS,
    SheetSpec,
    WorkbookSpec,
    auto_widths,
    safe_sheet_name,
    summary_sheet,
    write_workbook,
)
from sheetkit.merge import MergeSource, merge_sources
from sheetkit.reader import read_table
from sheetkit.reports import clean_report, compare_report, merge_report


def simple_spec(name='报告', headers=('列一', '列二'), rows=(('甲', 1),)):
    return (
        WorkbookSpec()
        .add(SheetSpec(name=name, headers=list(headers), rows=[list(row) for row in rows]))
    )


def read_sheet(path: str, name: str) -> list[list]:
    book = load_workbook(path, read_only=True, data_only=False)
    try:
        sheet = book[name]
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        book.close()


def test_writes_a_readable_workbook(tmp_path):
    out = tmp_path / 'report.xlsx'
    written = write_workbook(str(out), simple_spec())
    assert written == str(out)
    assert out.exists()
    rows = read_sheet(str(out), '报告')
    assert rows[0] == ['列一', '列二']
    assert rows[1] == ['甲', 1]


def test_creates_every_sheet_in_order(tmp_path):
    out = tmp_path / 'report.xlsx'
    spec = (
        WorkbookSpec()
        .add(SheetSpec(name='一', headers=['a'], rows=[[1]]))
        .add(SheetSpec(name='二', headers=['b'], rows=[[2]]))
        .add(SheetSpec(name='三', headers=['c'], rows=[[3]]))
    )
    write_workbook(str(out), spec)
    book = load_workbook(str(out), read_only=True)
    try:
        assert book.sheetnames == ['一', '二', '三']
    finally:
        book.close()


def test_refuses_to_overwrite_an_input_file(tmp_path, xlsx):
    source = xlsx('source.xlsx', ['编码'], [['00123']])
    before = open(source, 'rb').read()
    with pytest.raises(OutputConflictError, match='不能与输入文件相同'):
        write_workbook(source, simple_spec(), input_paths=[source])
    assert open(source, 'rb').read() == before


def test_refuses_a_non_xlsx_destination(tmp_path):
    with pytest.raises(UnsupportedFormatError, match='必须是 .xlsx'):
        write_workbook(str(tmp_path / 'report.csv'), simple_spec())


def test_refuses_a_folder_destination(tmp_path):
    with pytest.raises(OutputConflictError, match='文件夹'):
        write_workbook(str(tmp_path), simple_spec())


def test_refuses_a_destination_in_a_missing_folder(tmp_path):
    with pytest.raises(OutputConflictError, match='文件夹不存在'):
        write_workbook(str(tmp_path / 'nope' / 'report.xlsx'), simple_spec())


def test_overwriting_an_unrelated_existing_file_is_allowed(tmp_path):
    out = tmp_path / 'report.xlsx'
    out.write_bytes(b'old content')
    write_workbook(str(out), simple_spec())
    assert read_sheet(str(out), '报告')[0] == ['列一', '列二']


def test_text_that_looks_like_a_formula_stays_text(tmp_path):
    # A cell such as =cmd|'/C calc'!A0 must never become a live formula.
    payload = "=cmd|'/C calc'!A0"
    out = tmp_path / 'report.xlsx'
    write_workbook(
        str(out),
        WorkbookSpec().add(SheetSpec(name='S', headers=['内容'], rows=[[payload]])),
    )
    book = load_workbook(str(out), read_only=False, data_only=False)
    try:
        cell = book['S']['A2']
        assert cell.value == payload
        assert cell.data_type == 's'
    finally:
        book.close()


def test_leading_equals_and_plus_are_also_kept_as_text(tmp_path):
    out = tmp_path / 'report.xlsx'
    write_workbook(
        str(out),
        WorkbookSpec().add(
            SheetSpec(name='S', headers=['a'], rows=[['=1+1'], ['+1'], ['-1']])
        ),
    )
    book = load_workbook(str(out), read_only=False, data_only=False)
    try:
        sheet = book['S']
        assert sheet['A2'].value == '=1+1'
        assert sheet['A2'].data_type == 's'
        assert sheet['A3'].value == '+1'
        assert sheet['A4'].value == '-1'
    finally:
        book.close()


def test_integers_beyond_excel_precision_are_written_as_text(tmp_path):
    out = tmp_path / 'report.xlsx'
    write_workbook(
        str(out),
        WorkbookSpec().add(
            SheetSpec(name='S', headers=['大数'], rows=[[9007199254740993]])
        ),
    )
    book = load_workbook(str(out), read_only=False)
    try:
        cell = book['S']['A2']
        assert cell.value == '9007199254740993'
        assert cell.data_type == 's'
    finally:
        book.close()


def test_integers_inside_excel_precision_stay_numbers(tmp_path):
    out = tmp_path / 'report.xlsx'
    write_workbook(
        str(out), WorkbookSpec().add(SheetSpec(name='S', headers=['n'], rows=[[999999999999999]]))
    )
    book = load_workbook(str(out), read_only=False)
    try:
        cell = book['S']['A2']
        assert cell.value == 999999999999999
        assert cell.data_type == 'n'
    finally:
        book.close()


def test_a_failed_write_leaves_no_output_and_no_temporary_file(tmp_path):
    class Boom:
        def __iter__(self):
            yield ['a']
            raise RuntimeError('boom')

    out = tmp_path / 'report.xlsx'
    spec = WorkbookSpec().add(SheetSpec(name='S', headers=['a'], rows=Boom()))
    with pytest.raises(ExportError):
        write_workbook(str(out), spec)
    assert not out.exists()
    assert [name for name in os.listdir(tmp_path) if name.startswith('.sheetkit-')] == []


def test_a_successful_write_leaves_no_temporary_file(tmp_path):
    out = tmp_path / 'report.xlsx'
    write_workbook(str(out), simple_spec())
    assert [name for name in os.listdir(tmp_path) if name.startswith('.sheetkit-')] == []


def test_an_occupied_destination_reports_a_clear_message(tmp_path, exclusive_lock):
    out = tmp_path / 'report.xlsx'
    out.write_bytes(b'locked')
    exclusive_lock(str(out))
    with pytest.raises(ExportError, match='被占用'):
        write_workbook(str(out), simple_spec())


def test_sheet_names_are_sanitised_and_deduplicated():
    used: set[str] = set()
    assert safe_sheet_name('a/b\\c*d?e:f[g]', used) == 'a_b_c_d_e_f_g_'
    assert safe_sheet_name('报表', used) == '报表'
    assert safe_sheet_name('报表', used) == '报表_2'
    assert len(safe_sheet_name('x' * 40, used)) == 31


def test_auto_widths_are_bounded():
    widths = auto_widths(['短', '很长很长的列名' * 4], [['x' * 100, 'y']])
    assert widths[0] <= 52.0
    assert widths[1] <= 52.0
    assert all(width >= 9.0 for width in widths)


def test_summary_sheet_renders_values_as_text():
    spec = summary_sheet('摘要', [('名称', '甲'), ('数量', 3), ('空', None), ('开关', True)])
    assert spec.headers == ['项目', '内容']
    assert spec.rows[0] == ['名称', '甲']
    assert spec.rows[1] == ['数量', '3']
    assert spec.rows[2] == ['空', '']
    assert spec.rows[3] == ['开关', '是']


def test_progress_is_monotonic(tmp_path):
    seen: list[float] = []
    spec = (
        WorkbookSpec()
        .add(SheetSpec(name='一', headers=['a'], rows=[[1]]))
        .add(SheetSpec(name='二', headers=['b'], rows=[[2]]))
    )
    write_workbook(str(tmp_path / 'r.xlsx'), spec, progress=lambda s, r: seen.append(r))
    assert seen == sorted(seen)
    assert seen[0] == 0.05
    assert seen[-1] == 1.0


def test_compare_report_contains_every_required_sheet(tmp_path, xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '数量'], [['A1', 1], ['B2', 2]]))
    new = read_table(xlsx('new.xlsx', ['物料编码', '数量'], [['A1', 9], ['C3', 3]]))
    result = compare_tables(old, new, ['物料编码'])

    out = tmp_path / 'diff.xlsx'
    write_workbook(str(out), compare_report(result))
    book = load_workbook(str(out), read_only=True)
    try:
        assert book.sheetnames == ['对比摘要', '新增记录', '删除记录', '修改明细', '异常记录']
    finally:
        book.close()

    assert read_sheet(str(out), '新增记录')[1][:2] == ['C3', 3]
    assert read_sheet(str(out), '删除记录')[1][:2] == ['B2', 2]
    modified = read_sheet(str(out), '修改明细')
    assert modified[0] == ['匹配字段', '修改列', '旧值', '新值', '旧版行号', '新版行号', '比较方式']
    assert modified[1][:4] == ['A1', '数量', '1', '9']


def test_compare_report_summary_lists_the_counts(tmp_path, xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '数量'], [['A1', 1], ['B2', 2]]))
    new = read_table(xlsx('new.xlsx', ['物料编码', '数量'], [['A1', 9], ['C3', 3]]))
    out = tmp_path / 'diff.xlsx'
    write_workbook(str(out), compare_report(compare_tables(old, new, ['物料编码'])))

    summary = {row[0]: row[1] for row in read_sheet(str(out), '对比摘要')[1:]}
    assert summary['旧版记录数'] == '2'
    assert summary['新版记录数'] == '2'
    assert summary['新增记录数'] == '1'
    assert summary['删除记录数'] == '1'
    assert summary['修改记录数'] == '1'
    assert summary['匹配字段'] == '物料编码'


def test_merge_report_lists_sources_and_total(tmp_path, xlsx):
    first = xlsx('a.xlsx', ['物料编码', '数量'], [['A1', 1], ['A2', 2]])
    second = xlsx('b.xlsx', ['物料编码', '数量'], [['B1', 3]])
    result = merge_sources([MergeSource(path=first), MergeSource(path=second)])

    out = tmp_path / 'merged.xlsx'
    write_workbook(str(out), merge_report(result))
    book = load_workbook(str(out), read_only=True)
    try:
        assert book.sheetnames[:2] == ['合并结果', '合并摘要']
    finally:
        book.close()

    summary = read_sheet(str(out), '合并摘要')
    assert summary[0] == ['来源文件', '来源工作表', '表头行', '字段数', '记录数', '状态', '提示']
    assert [row[0] for row in summary[1:]] == ['a.xlsx', 'b.xlsx', '合计']
    assert [row[4] for row in summary[1:]] == [2, 1, 3]


def test_clean_report_contains_every_required_sheet(tmp_path, xlsx):
    path = xlsx(
        'orders.xlsx',
        ['订单编号', '物料编码', '数量'],
        [['A1', 'M1', 1], ['A1', None, 2], ['B1', 'M2', '待定']],
    )
    table = read_table(path)
    result = clean_table(
        table,
        CleanOptions(
            duplicate_key_columns=('订单编号',),
            required_columns=('物料编码',),
            number_columns=('数量',),
        ),
    )
    out = tmp_path / 'clean.xlsx'
    write_workbook(str(out), clean_report(result))
    book = load_workbook(str(out), read_only=True)
    try:
        assert book.sheetnames == ['清洗结果', '重复数据', '异常数据', '清洗摘要']
    finally:
        book.close()

    assert len(read_sheet(str(out), '清洗结果')) == 4
    assert len(read_sheet(str(out), '重复数据')) == 3
    assert len(read_sheet(str(out), '异常数据')) == 3


def test_colour_coding_is_applied_per_change_type(tmp_path, xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码'], [['A1'], ['B2']]))
    new = read_table(xlsx('new.xlsx', ['物料编码'], [['A1'], ['C3']]))
    spec = compare_report(compare_tables(old, new, ['物料编码']))
    out = tmp_path / 'diff.xlsx'
    write_workbook(str(out), spec)

    book = load_workbook(str(out))
    try:
        assert book['新增记录']['A2'].fill.start_color.rgb == TINTS['added']
        assert book['删除记录']['A2'].fill.start_color.rgb == TINTS['deleted']
    finally:
        book.close()


def test_exporting_does_not_touch_the_input_workbook(tmp_path, xlsx):
    source = xlsx('source.xlsx', ['物料编码', '数量'], [['00123', 5]])
    before = open(source, 'rb').read()
    out = tmp_path / 'report.xlsx'
    write_workbook(str(out), simple_spec(), input_paths=[source])
    assert open(source, 'rb').read() == before
    assert read_table(source).rows == [['00123', 5]]


def test_workbook_properties_record_the_tool_as_the_author(tmp_path):
    out = tmp_path / 'report.xlsx'
    write_workbook(str(out), simple_spec())
    book = load_workbook(str(out))
    try:
        assert book.properties.creator == 'SheetKit'
        assert book.properties.title == 'SheetKit'
    finally:
        book.close()

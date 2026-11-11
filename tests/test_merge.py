"""Vertical merge: name-based column alignment, mapping, provenance, no dedup."""

from __future__ import annotations

import pytest

from sheetkit.errors import SheetNotFoundError, ValidationError
from sheetkit.merge import (
    SOURCE_COLUMN_BASES,
    MergeSource,
    merge_files,
    merge_sources,
    plan_merge,
)

SHIP_HEADERS = ['物料编码', '品名', '数量']


def source(xlsx, name, headers, rows, **kwargs) -> MergeSource:
    return MergeSource(path=xlsx(name, headers, rows), **kwargs)


def test_columns_are_matched_by_name_not_by_position(xlsx):
    sources = [
        source(xlsx, '1月.xlsx', ['物料编码', '品名', '数量'], [['A1', '甲', 1]]),
        source(xlsx, '2月.xlsx', ['品名', '数量', '物料编码'], [['乙', 2, 'B2']]),
    ]
    result = merge_sources(sources)
    assert result.columns[:3] == ['物料编码', '品名', '数量']
    assert result.rows[0][:3] == ['A1', '甲', 1]
    # The second file's columns were reordered; the values still land by name.
    assert result.rows[1][:3] == ['B2', '乙', 2]


def test_missing_fields_stay_empty(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', ['物料编码', '品名'], [['A1', '甲']]),
        source(xlsx, 'b.xlsx', ['物料编码', '数量'], [['B2', 7]]),
    ]
    result = merge_sources(sources)
    assert result.columns[:3] == ['物料编码', '品名', '数量']
    assert result.rows[0][:3] == ['A1', '甲', None]
    assert result.rows[1][:3] == ['B2', None, 7]
    assert result.plan.partial_columns == ['品名', '数量']
    assert any('只在部分文件中出现' in item for item in result.plan.warnings)


def test_differently_named_columns_are_not_merged_automatically(xlsx):
    # 出货日期 and 发货日期 may or may not mean the same thing. Without an
    # explicit mapping they stay separate rather than being guessed together.
    sources = [
        source(xlsx, 'a.xlsx', ['编码', '出货日期'], [['A1', '2024-01-05']]),
        source(xlsx, 'b.xlsx', ['编码', '发货日期'], [['B2', '2024-02-06']]),
    ]
    result = merge_sources(sources)
    assert result.columns[:3] == ['编码', '出货日期', '发货日期']
    assert result.rows[0][:3] == ['A1', '2024-01-05', None]
    assert result.rows[1][:3] == ['B2', None, '2024-02-06']


def test_explicit_mapping_combines_renamed_columns(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', ['编码', '出货日期'], [['A1', '2024-01-05']]),
        source(
            xlsx,
            'b.xlsx',
            ['编码', '发货日期'],
            [['B2', '2024-02-06']],
            mapping={'发货日期': '出货日期'},
        ),
    ]
    result = merge_sources(sources)
    assert result.columns[:2] == ['编码', '出货日期']
    assert result.rows[0][:2] == ['A1', '2024-01-05']
    assert result.rows[1][:2] == ['B2', '2024-02-06']
    assert result.plan.partial_columns == []


def test_mapping_keys_are_normalised(xlsx):
    path = xlsx('b.xlsx', ['物料编号'], [['B2']])
    parsed = MergeSource.from_payload(
        {'path': path, 'mapping': {'  物料编号 ': ' 物料编码 '}}
    )
    assert parsed.mapping == {'物料编号': '物料编码'}
    assert merge_sources([parsed]).columns[0] == '物料编码'


def test_mapping_conflict_is_reported_not_resolved(xlsx):
    sources = [
        source(
            xlsx,
            'a.xlsx',
            ['出货日期', '发货日期'],
            [['2024-01-05', '2024-01-06']],
            mapping={'出货日期': '发货日期'},
        )
    ]
    with pytest.raises(ValidationError) as info:
        merge_sources(sources)
    assert '字段映射冲突' in str(info.value)
    assert '都映射到“发货日期”' in str(info.value)


def test_mapping_an_absent_column_is_refused(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', ['物料编码'], [['A1']], mapping={'物料编号': '物料编码'})
    ]
    with pytest.raises(ValidationError, match='不存在被映射的字段'):
        merge_sources(sources)


def test_duplicate_rows_are_kept_because_there_is_no_auto_dedup(xlsx):
    rows = [['A1', '甲', 1], ['A1', '甲', 1]]
    sources = [
        source(xlsx, 'a.xlsx', SHIP_HEADERS, rows),
        source(xlsx, 'b.xlsx', SHIP_HEADERS, rows),
    ]
    result = merge_sources(sources)
    assert result.row_count == 4
    assert [row[0] for row in result.rows] == ['A1'] * 4


def test_provenance_columns_record_file_sheet_and_source_row(xlsx):
    sources = [
        MergeSource(
            path=xlsx('1月.xlsx', SHIP_HEADERS, [['A1', '甲', 1], ['B2', '乙', 2]], sheet='一月'),
            sheet='一月',
        ),
        MergeSource(
            path=xlsx('2月.xlsx', SHIP_HEADERS, [['C3', '丙', 3]], sheet='二月'),
            sheet='二月',
        ),
    ]
    result = merge_sources(sources)
    assert result.columns[3:] == list(SOURCE_COLUMN_BASES)
    assert result.rows[0][3:] == ['1月.xlsx', '一月', 2]
    assert result.rows[1][3:] == ['1月.xlsx', '一月', 3]
    assert result.rows[2][3:] == ['2月.xlsx', '二月', 2]


def test_a_missing_sheet_names_the_offending_file(xlsx):
    good = xlsx('a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])
    with pytest.raises(SheetNotFoundError, match='b.xlsx中不存在工作表 "三月"'):
        merge_sources([MergeSource(path=good), MergeSource(path=xlsx(
            'b.xlsx', SHIP_HEADERS, [['B2', '乙', 2]], sheet='数据'), sheet='三月')])


def test_provenance_columns_can_be_turned_off(xlsx):
    sources = [source(xlsx, 'a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])]
    result = merge_sources(sources, add_source_columns=False)
    assert result.columns == SHIP_HEADERS
    assert result.rows == [['A1', '甲', 1]]


def test_existing_source_column_is_not_overwritten(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', ['物料编码', '来源文件'], [['A1', '原始值']])
    ]
    result = merge_sources(sources)
    assert result.columns == ['物料编码', '来源文件', '来源文件(来源)', '来源工作表', '原始行号']
    assert result.rows[0][1] == '原始值'
    assert result.rows[0][2] == 'a.xlsx'
    assert any('为避免覆盖改用' in item for item in result.plan.warnings)


def test_source_row_numbers_follow_a_per_file_header_offset(xlsx):
    path = xlsx(
        'titled.xlsx',
        SHIP_HEADERS,
        [['A1', '甲', 1]],
        preamble_rows=[['某公司出货表'], ['制表人：张三']],
    )
    result = merge_sources([MergeSource(path=path, header_row=3)])
    assert result.rows[0][:3] == ['A1', '甲', 1]
    assert result.rows[0][5] == 4


def test_sheet_can_be_chosen_per_source(xlsx):
    path = xlsx(
        'multi.xlsx',
        SHIP_HEADERS,
        [['A1', '甲', 1]],
        sheet='一月',
        extra_sheets={'二月': (SHIP_HEADERS, [['B2', '乙', 2]])},
    )
    result = merge_sources(
        [
            MergeSource(path=path, sheet='一月'),
            MergeSource(path=path, sheet='二月'),
        ]
    )
    assert result.row_count == 2
    assert [row[4] for row in result.rows] == ['一月', '二月']


def test_disabled_source_is_skipped_but_still_reported(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]]),
        source(xlsx, 'b.xlsx', SHIP_HEADERS, [['B2', '乙', 2]], enabled=False),
    ]
    result = merge_sources(sources)
    assert result.row_count == 1
    reports = result.plan.sources
    assert [item.name for item in reports] == ['a.xlsx', 'b.xlsx']
    assert reports[1].skipped is True
    assert reports[1].row_count == 0
    assert reports[1].warnings == ['已取消勾选，不参与合并']
    assert result.summary()['file_count'] == 2
    assert result.summary()['merged_file_count'] == 1


def test_every_source_disabled_is_refused(xlsx):
    sources = [source(xlsx, 'a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]], enabled=False)]
    with pytest.raises(ValidationError, match='没有参与合并的文件'):
        merge_sources(sources)


def test_empty_source_list_is_refused():
    with pytest.raises(ValidationError, match='至少添加一个文件'):
        merge_sources([])


def test_leading_zeros_and_long_numbers_survive_the_merge(xlsx):
    sources = [
        source(
            xlsx,
            'codes.xlsx',
            ['物料编码', '订单编号'],
            [['00123', '9007199254740993']],
        )
    ]
    row = merge_sources(sources).rows[0]
    assert row[0] == '00123'
    assert row[1] == '9007199254740993'


def test_csv_and_xlsx_sources_merge_together(xlsx, csv_file):
    sources = [
        MergeSource(path=xlsx('a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])),
        MergeSource(path=csv_file('b.csv', SHIP_HEADERS, [['B2', '乙', '2']])),
    ]
    result = merge_sources(sources)
    assert result.row_count == 2
    assert result.rows[1][0] == 'B2'
    assert result.rows[1][3:] == ['b.csv', '', 2]
    assert any('b.csv：CSV 中的所有列均按文本读取' in item for item in result.plan.warnings)


def test_plan_merge_describes_the_layout_without_merging(xlsx):
    sources = [
        source(xlsx, 'a.xlsx', ['物料编码', '品名'], [['A1', '甲'], ['A2', '乙']]),
        source(xlsx, 'b.xlsx', ['品名', '数量'], [['丙', 3]]),
    ]
    plan = plan_merge(sources)
    assert plan.body_columns == ['物料编码', '品名', '数量']
    assert plan.source_columns == list(SOURCE_COLUMN_BASES)
    assert plan.target_columns == plan.body_columns + list(SOURCE_COLUMN_BASES)
    assert [item.row_count for item in plan.sources] == [2, 1]
    payload = plan.to_dict()
    assert payload['partial_columns'] == ['物料编码', '数量']
    assert payload['sources'][0]['columns'] == ['物料编码', '品名']
    assert payload['sources'][0]['mapped_columns'] == ['物料编码', '品名']


def test_summary_reports_per_source_rows_and_the_final_total(xlsx):
    sources = [
        source(xlsx, '1月.xlsx', SHIP_HEADERS, [['A1', '甲', 1], ['B2', '乙', 2]]),
        source(xlsx, '2月.xlsx', SHIP_HEADERS, [['C3', '丙', 3]]),
        source(xlsx, '3月.xlsx', SHIP_HEADERS, [['D4', '丁', 4], ['E5', '戊', 5]]),
    ]
    summary = merge_sources(sources).summary()
    assert [(item['name'], item['rows']) for item in summary['sources']] == [
        ('1月.xlsx', 2),
        ('2月.xlsx', 1),
        ('3月.xlsx', 2),
    ]
    assert summary['total_rows'] == 5
    assert summary['file_count'] == 3
    assert summary['merged_file_count'] == 3
    assert summary['total_columns'] == len(SHIP_HEADERS) + len(SOURCE_COLUMN_BASES)


def test_merge_files_convenience_wrapper(xlsx):
    first = xlsx('a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])
    second = xlsx('b.xlsx', SHIP_HEADERS, [['B2', '乙', 2]])
    result = merge_files([first, second], mappings={second: {'品名': '名称'}})
    # The renamed column is new to the layout, so it is appended after the
    # columns the first file already established.
    assert result.columns[:4] == ['物料编码', '品名', '数量', '名称']
    assert result.rows[0][1] == '甲'
    assert result.rows[1][3] == '乙'


def test_progress_is_monotonic(xlsx):
    sources = [
        source(xlsx, f'{name}.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])
        for name in ('a', 'b', 'c')
    ]
    seen: list[float] = []
    merge_sources(sources, progress=lambda stage, ratio: seen.append(ratio))
    assert seen == sorted(seen)
    assert seen[0] == 0.0
    assert seen[-1] == 1.0


def test_merge_source_from_payload(xlsx):
    path = xlsx('a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])
    parsed = MergeSource.from_payload(
        {
            'path': path,
            'sheet': '数据',
            'header_row': '1',
            'mapping': {' 品名 ': '名称 '},
            'enabled': 'true',
        }
    )
    assert parsed.sheet == '数据'
    assert parsed.header_row == 1
    assert parsed.mapping == {'品名': '名称'}
    assert parsed.enabled is True
    assert parsed.name == 'a.xlsx'


def test_merge_source_from_payload_rejects_junk():
    with pytest.raises(ValidationError, match='合并文件项必须是对象'):
        MergeSource.from_payload('a.xlsx')
    with pytest.raises(ValidationError, match='字段映射必须是对象'):
        MergeSource.from_payload({'path': 'a.xlsx', 'mapping': ['品名']})


def test_timings_are_recorded(xlsx):
    sources = [source(xlsx, 'a.xlsx', SHIP_HEADERS, [['A1', '甲', 1]])]
    result = merge_sources(sources)
    assert result.timings['rows'] == 1
    assert result.timings['total'] >= 0

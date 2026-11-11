"""Data cleaning rules, and the confirmation gate on destructive dedup."""

from __future__ import annotations

import datetime as dt

import pytest

from sheetkit.clean import (
    DUPLICATE_FLAG,
    FORMAT_FLAG,
    REQUIRED_FLAG,
    SOURCE_ROW_COLUMN,
    CleanOptions,
    clean_file,
    clean_table,
    duplicate_impact,
)
from sheetkit.errors import ConfirmationRequiredError, ValidationError
from sheetkit.reader import read_table

ORDER_HEADERS = ['订单编号', '物料编码', '数量', '交期']


def table(xlsx, rows, *, headers=ORDER_HEADERS, name='orders.xlsx', **kwargs):
    return read_table(xlsx(name, headers, rows), keep_blank_rows=True, **kwargs)


def test_blank_rows_are_removed_by_default(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, '2024-01-05'], [None, None, None, None], ['A2', 'M2', 2, '2024-01-06']])
    result = clean_table(work, CleanOptions(duplicate_action='none'))
    assert result.row_count == 2
    assert result.stats['blank_rows'] == 1
    assert result.summary()['original_rows'] == 3


def test_blank_rows_are_kept_when_the_rule_is_off(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, '2024-01-05'], [None, None, None, None]])
    result = clean_table(
        work, CleanOptions(remove_blank_rows=False, duplicate_action='none')
    )
    assert result.row_count == 2
    assert result.stats['blank_rows'] == 1


def test_whitespace_is_stripped_only_from_the_chosen_columns(xlsx):
    work = table(xlsx, [['  A1 ', ' M1 ', 1, ' 2024-01-05 ']])
    result = clean_table(
        work,
        CleanOptions(strip_columns=('订单编号', '物料编码'), duplicate_action='none'),
    )
    assert result.rows[0][:4] == ['A1', 'M1', 1, ' 2024-01-05 ']
    assert result.stats['stripped_cells'] == 2


def test_stripping_never_touches_non_text_values(xlsx):
    work = table(xlsx, [['A1', 'M1', 1.5, dt.datetime(2024, 1, 5)]])
    result = clean_table(
        work,
        CleanOptions(strip_columns=tuple(ORDER_HEADERS), duplicate_action='none'),
    )
    assert result.rows[0][2] == 1.5
    assert result.rows[0][3] == dt.datetime(2024, 1, 5)
    assert result.stats['stripped_cells'] == 0


def test_duplicates_are_marked_and_never_removed_by_default(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, '2024-01-05'],
            ['A1', 'M1', 2, '2024-01-06'],
            ['A2', 'M2', 3, '2024-01-07'],
        ],
    )
    result = clean_table(work, CleanOptions(duplicate_key_columns=('订单编号',)))
    # The default rule is mark-only: every input row survives.
    assert result.row_count == 3
    assert result.stats['removed_duplicate_rows'] == 0
    assert result.duplicate_groups == 1
    assert result.stats['duplicate_rows'] == 2
    assert DUPLICATE_FLAG in result.flag_columns
    flags = [row[len(ORDER_HEADERS)] for row in result.rows]
    assert flags == ['重复（首次出现，共 2 条）', '重复（第 2 次出现，共 2 条）', '']
    assert len(result.duplicate_rows) == 2


def test_duplicate_detection_can_use_several_fields(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, '2024-01-05'],
            ['A1', 'M2', 1, '2024-01-05'],
            ['A1', 'M1', 9, '2024-09-09'],
        ],
    )
    result = clean_table(
        work, CleanOptions(duplicate_key_columns=('订单编号', '物料编码'))
    )
    assert result.duplicate_groups == 1
    assert result.stats['duplicate_rows'] == 2
    flags = [row[len(ORDER_HEADERS)] for row in result.rows]
    assert flags[1] == ''
    assert flags[2].startswith('重复（第 2 次出现')


def test_duplicate_key_matching_ignores_whitespace(xlsx):
    work = table(xlsx, [[' A1', 'M1', 1, 'x'], ['A1 ', 'M1', 2, 'y']])
    result = clean_table(work, CleanOptions(duplicate_key_columns=('订单编号',)))
    assert result.stats['duplicate_rows'] == 2


def test_no_duplicate_flag_column_when_the_rule_is_off(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x'], ['A1', 'M1', 1, 'x']])
    result = clean_table(work, CleanOptions(duplicate_action='none'))
    assert result.flag_columns == []
    assert result.columns == ORDER_HEADERS + [SOURCE_ROW_COLUMN]
    assert result.row_count == 2
    assert result.duplicate_groups == 0


def test_empty_key_selection_means_identical_whole_rows(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            ['A1', 'M1', 1, 'x'],
            ['A1', 'M1', 2, 'x'],
        ],
    )
    result = clean_table(work, CleanOptions())
    assert result.stats['duplicate_rows'] == 2
    assert result.summary()['duplicate_key_columns'] == ORDER_HEADERS
    assert any('已按全部字段判断完全重复行' in item for item in result.warnings)


def test_keep_first_is_refused_without_confirmation(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            ['A1', 'M1', 2, 'y'],
            ['A1', 'M1', 3, 'z'],
            ['A2', 'M2', 4, 'w'],
        ],
    )
    options = CleanOptions(
        duplicate_key_columns=('订单编号',), duplicate_action='keep_first'
    )
    with pytest.raises(ConfirmationRequiredError) as info:
        clean_table(work, options)

    error = info.value
    assert error.code == 'E_CONFIRMATION_REQUIRED'
    assert '会删除 2 行数据' in error.message
    impact = error.context['impact']
    assert impact['key_columns'] == ['订单编号']
    assert impact['groups'] == 1
    assert impact['rows_in_groups'] == 3
    assert impact['keep_first_removes'] == 2
    assert impact['remove_all_removes'] == 3
    assert impact['result_rows'] == {'mark': 4, 'keep_first': 2, 'remove_all': 1}


def test_remove_all_is_refused_without_confirmation(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x'], ['A1', 'M1', 2, 'y']])
    with pytest.raises(ConfirmationRequiredError, match='会删除 2 行数据'):
        clean_table(
            work,
            CleanOptions(duplicate_key_columns=('订单编号',), duplicate_action='remove_all'),
        )


def test_keep_first_removes_later_occurrences_once_confirmed(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            ['A2', 'M2', 2, 'y'],
            ['A1', 'M1', 3, 'z'],
            ['A1', 'M1', 4, 'w'],
        ],
    )
    result = clean_table(
        work,
        CleanOptions(
            duplicate_key_columns=('订单编号',),
            duplicate_action='keep_first',
            confirmed=True,
        ),
    )
    assert [row[0] for row in result.rows] == ['A1', 'A2']
    # The surviving A1 is the first occurrence, with its own quantity intact.
    assert result.rows[0][2] == 1
    assert result.stats['removed_duplicate_rows'] == 2
    assert [row[-1] for row in result.rows] == [2, 3]
    assert any('删除 2 行重复数据' in item for item in result.warnings)


def test_remove_all_drops_whole_groups_once_confirmed(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            ['A2', 'M2', 2, 'y'],
            ['A1', 'M1', 3, 'z'],
        ],
    )
    result = clean_table(
        work,
        CleanOptions(
            duplicate_key_columns=('订单编号',),
            duplicate_action='remove_all',
            confirmed=True,
        ),
    )
    assert [row[0] for row in result.rows] == ['A2']
    assert result.stats['removed_duplicate_rows'] == 2


def test_duplicate_impact_matches_what_the_confirmed_run_actually_removes(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            ['A1', 'M1', 2, 'y'],
            ['B1', 'M9', 3, 'z'],
            ['B1', 'M9', 4, 'w'],
            ['B1', 'M9', 5, 'v'],
            ['C1', 'M2', 6, 'u'],
        ],
    )
    options = CleanOptions(duplicate_key_columns=('订单编号',))
    impact = duplicate_impact(work, options)
    assert impact['groups'] == 2
    assert impact['keep_first_removes'] == 3
    assert impact['remove_all_removes'] == 5

    kept = clean_table(
        work,
        CleanOptions(
            duplicate_key_columns=('订单编号',),
            duplicate_action='keep_first',
            confirmed=True,
        ),
    )
    assert kept.row_count == impact['result_rows']['keep_first'] == 3
    wiped = clean_table(
        work,
        CleanOptions(
            duplicate_key_columns=('订单编号',),
            duplicate_action='remove_all',
            confirmed=True,
        ),
    )
    assert wiped.row_count == impact['result_rows']['remove_all'] == 1


def test_required_columns_are_flagged_not_filled_in(xlsx):
    work = table(
        xlsx,
        [
            ['A1', None, 1, '2024-01-05'],
            ['  ', 'M2', 2, '   '],
            ['A3', 'M3', 3, '2024-01-07'],
        ],
    )
    result = clean_table(
        work,
        CleanOptions(
            duplicate_action='none',
            required_columns=('订单编号', '物料编码', '交期'),
        ),
    )
    assert result.flag_columns == [REQUIRED_FLAG]
    flags = [row[len(ORDER_HEADERS)] for row in result.rows]
    assert flags == ['物料编码', '订单编号、交期', '']
    assert result.stats['missing_required_rows'] == 2
    assert result.stats['missing_required_cells'] == 3
    assert len(result.anomaly_rows) == 2


def test_date_anomalies_are_reported(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, '2024-01-05'],
            ['A2', 'M2', 2, '2024-13-45'],
            ['A3', 'M3', 3, '待定'],
            ['A4', 'M4', 4, '1899-01-01'],
            ['A5', 'M5', 5, None],
            ['A6', 'M6', 6, dt.datetime(2024, 6, 1)],
        ],
    )
    result = clean_table(work, CleanOptions(duplicate_action='none', date_columns=('交期',)))
    assert result.flag_columns == [FORMAT_FLAG]
    flags = [row[len(ORDER_HEADERS)] for row in result.rows]
    assert flags[0] == ''
    assert '不是有效日期' in flags[1]
    assert '不是有效日期' in flags[2]
    assert '日期超出合理范围' in flags[3]
    assert flags[4] == ''
    assert flags[5] == ''
    assert result.stats['format_anomaly_rows'] == 3
    assert result.stats['format_anomaly_cells'] == 3


def test_number_anomalies_are_reported_without_converting_anything(xlsx):
    work = table(xlsx, [['A1', 'M1', 12, 'x'], ['A2', 'M2', '34', 'x'], ['A3', 'M3', '待定', 'x']])
    result = clean_table(work, CleanOptions(duplicate_action='none', number_columns=('数量',)))
    flags = [row[len(ORDER_HEADERS)] for row in result.rows]
    assert flags[0] == ''
    assert '数字以文本形式存储' in flags[1]
    assert '不是有效数字' in flags[2]
    # Reporting an anomaly must not rewrite the cell.
    assert result.rows[1][2] == '34'
    assert result.rows[2][2] == '待定'


def test_both_flag_columns_are_present_together(xlsx):
    work = table(xlsx, [['A1', None, '待定', 'x']])
    result = clean_table(
        work,
        CleanOptions(
            duplicate_action='none',
            required_columns=('物料编码',),
            number_columns=('数量',),
        ),
    )
    assert result.flag_columns == [REQUIRED_FLAG, FORMAT_FLAG]
    assert result.columns == ORDER_HEADERS + [REQUIRED_FLAG, FORMAT_FLAG, SOURCE_ROW_COLUMN]
    assert result.rows[0][4] == '物料编码'
    assert '不是有效数字' in result.rows[0][5]
    assert len(result.anomaly_rows) == 1


def test_source_row_numbers_survive_cleaning(xlsx):
    work = table(
        xlsx,
        [
            ['A1', 'M1', 1, 'x'],
            [None, None, None, None],
            ['A2', 'M2', 2, 'x'],
        ],
    )
    result = clean_table(work, CleanOptions(duplicate_action='none'))
    assert result.columns[-1] == SOURCE_ROW_COLUMN
    assert [row[-1] for row in result.rows] == [2, 4]


def test_leading_zeros_are_not_converted_by_cleaning(xlsx):
    work = table(xlsx, [['00123', ' 007 ', '9007199254740993', 'x']])
    result = clean_table(
        work, CleanOptions(strip_columns=('物料编码',), duplicate_action='none')
    )
    assert result.rows[0][0] == '00123'
    assert result.rows[0][1] == '007'
    assert result.rows[0][2] == '9007199254740993'


def test_summary_reports_every_counter(xlsx):
    work = table(
        xlsx,
        [
            ['  A1 ', None, '待定', '2024-13-45'],
            [None, None, None, None],
            ['A1', 'M1', 5, '2024-01-05'],
        ],
    )
    summary = clean_table(
        work,
        CleanOptions(
            strip_columns=('订单编号',),
            duplicate_key_columns=('订单编号',),
            required_columns=('物料编码',),
            date_columns=('交期',),
            number_columns=('数量',),
        ),
    ).summary()
    assert summary['file'] == 'orders.xlsx'
    assert summary['original_rows'] == 3
    assert summary['result_rows'] == 2
    assert summary['blank_rows'] == 1
    assert summary['stripped_cells'] == 1
    assert summary['duplicate_groups'] == 1
    assert summary['duplicate_rows'] == 2
    assert summary['removed_duplicate_rows'] == 0
    assert summary['missing_required_rows'] == 1
    assert summary['missing_required_cells'] == 1
    # One row carries both a bad date and a bad number.
    assert summary['format_anomaly_rows'] == 1
    assert summary['format_anomaly_cells'] == 2
    assert summary['duplicate_action'] == 'mark'
    assert summary['duplicate_action_label'] == '仅标记'


def test_from_payload_defaults_duplicate_keys_to_all_columns(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    options = CleanOptions.from_payload({'duplicate_action': 'mark'}, work.columns)
    assert options.duplicate_key_columns == tuple(work.columns)
    assert options.remove_blank_rows is True
    assert options.confirmed is False


def test_from_payload_leaves_keys_empty_when_duplicates_are_ignored(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    options = CleanOptions.from_payload({'duplicate_action': 'none'}, work.columns)
    assert options.duplicate_key_columns == ()


def test_from_payload_rejects_an_unknown_action(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    with pytest.raises(ValidationError, match='重复数据处理方式无效'):
        CleanOptions.from_payload({'duplicate_action': 'delete'}, work.columns)


def test_from_payload_rejects_unknown_columns(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    with pytest.raises(ValidationError, match='必填字段不存在于当前表格'):
        CleanOptions.from_payload({'required_columns': ['金额']}, work.columns)


def test_from_payload_parses_a_raw_ui_payload(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    options = CleanOptions.from_payload(
        {
            'remove_blank_rows': 'false',
            'strip_columns': ['订单编号'],
            'duplicate_action': 'keep_first',
            'duplicate_key_columns': '订单编号',
            'confirmed': 'true',
            'required_columns': [],
            'date_columns': ['交期'],
            'number_columns': ['数量'],
        },
        work.columns,
    )
    assert options.remove_blank_rows is False
    assert options.strip_columns == ('订单编号',)
    assert options.duplicate_action == 'keep_first'
    assert options.duplicate_key_columns == ('订单编号',)
    assert options.confirmed is True
    assert options.date_columns == ('交期',)


def test_clean_file_reads_keeps_blank_rows_and_cleans(xlsx):
    path = xlsx(
        'orders.xlsx',
        ORDER_HEADERS,
        [
            ['A1', 'M1', 1, '2024-01-05'],
            [None, None, None, None],
            ['A1', 'M1', 2, '2024-01-06'],
        ],
    )
    result = clean_file(path, {'duplicate_key_columns': ['订单编号']})
    assert result.summary()['original_rows'] == 3
    assert result.row_count == 2
    assert result.stats['duplicate_rows'] == 2
    assert result.name == 'orders.xlsx'
    assert result.sheet == '数据'


def test_clean_file_propagates_the_confirmation_gate(xlsx):
    path = xlsx('orders.xlsx', ORDER_HEADERS, [['A1', 'M1', 1, 'x'], ['A1', 'M1', 2, 'y']])
    with pytest.raises(ConfirmationRequiredError) as info:
        clean_file(path, {'duplicate_action': 'keep_first', 'duplicate_key_columns': ['订单编号']})
    assert info.value.context['impact']['keep_first_removes'] == 1

    confirmed = clean_file(
        path,
        {
            'duplicate_action': 'keep_first',
            'duplicate_key_columns': ['订单编号'],
            'confirmed': True,
        },
    )
    assert confirmed.row_count == 1


def test_clean_file_progress_is_monotonic(xlsx):
    path = xlsx('orders.xlsx', ORDER_HEADERS, [['A1', 'M1', 1, 'x']])
    seen: list[float] = []
    clean_file(path, {'duplicate_action': 'none'}, progress=lambda stage, ratio: seen.append(ratio))
    assert seen == sorted(seen)
    assert seen[0] == 0.0
    assert seen[-1] == 1.0


def test_clean_file_accepts_a_header_offset_and_sheet(xlsx):
    path = xlsx(
        'titled.xlsx',
        ORDER_HEADERS,
        [['A1', 'M1', 1, 'x']],
        sheet='一月',
        preamble_rows=[['某公司订单表']],
    )
    result = clean_file(path, {'duplicate_action': 'none'}, sheet='一月', header_row=2)
    assert result.rows[0][-1] == 3
    assert result.sheet == '一月'


def test_reader_warnings_are_carried_into_the_result(xlsx, csv_file):
    path = csv_file('orders.csv', ORDER_HEADERS, [['00123', 'M1', '1', 'x']])
    result = clean_file(path, {'duplicate_action': 'none'})
    assert result.rows[0][0] == '00123'
    assert any('CSV 中的所有列均按文本读取' in item for item in result.warnings)


def test_timings_are_recorded(xlsx):
    work = table(xlsx, [['A1', 'M1', 1, 'x']])
    assert clean_table(work, CleanOptions(duplicate_action='none')).timings['total'] >= 0

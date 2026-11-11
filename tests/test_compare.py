"""Key-based difference comparison."""

from __future__ import annotations

from decimal import Decimal

import pytest

from sheetkit.compare import (
    UNMATCHED_BECAUSE_NEW_ANOMALY,
    UNMATCHED_BECAUSE_OLD_ANOMALY,
    CompareOptions,
    compare_files,
    compare_tables,
)
from sheetkit.errors import ValidationError
from sheetkit.reader import read_table

CODE_HEADERS = ['物料编码', '品名', '数量']


def tables(xlsx, old_rows, new_rows, *, headers=CODE_HEADERS, old_name='old.xlsx', new_name='new.xlsx'):
    """Build two real workbooks and read them back through the shared reader."""
    old = read_table(xlsx(old_name, headers, old_rows))
    new = read_table(xlsx(new_name, headers, new_rows))
    return old, new


def test_reordered_identical_data_is_unchanged(xlsx):
    # Row position must not matter: only the business key does.
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['B2', '乙', 2], ['C3', '丙', 3]],
        [['C3', '丙', 3], ['A1', '甲', 1], ['B2', '乙', 2]],
    )
    result = compare_tables(old, new, ['物料编码'])
    assert (len(result.added), len(result.deleted), len(result.changed)) == (0, 0, 0)
    assert result.unchanged_count == 3
    assert result.anomalies == []


def test_added_deleted_and_modified_are_separated(xlsx):
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['B2', '乙', 2], ['C3', '丙', 3]],
        [['B2', '乙', 9], ['C3', '丙', 3], ['D4', '丁', 4]],
    )
    result = compare_tables(old, new, ['物料编码'])
    assert [item[0] for item in result.added] == ['D4']
    assert [item[0] for item in result.deleted] == ['A1']
    assert [row.key_display for row in result.changed] == ['B2']
    assert result.unchanged_count == 1


def test_modification_detail_carries_column_values_and_source_rows(xlsx):
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['B2', '乙', 2]],
        [['B2', '乙二', 5], ['A1', '甲', 1]],
    )
    result = compare_tables(old, new, ['物料编码'])
    row = result.changed[0]
    assert row.key_display == 'B2'
    assert row.old_row == 3
    assert row.new_row == 2
    assert [(c.column, c.old_value, c.new_value) for c in row.changes] == [
        ('品名', '乙', '乙二'),
        ('数量', 2, 5),
    ]
    assert result.changed_field_count == 2


def test_modification_records_are_flat_rows_for_ui_and_export(xlsx):
    old, new = tables(xlsx, [['B2', '乙', 2]], [['B2', '乙', 5]])
    record = compare_tables(old, new, ['物料编码']).modification_records[0]
    assert record == {
        'key': 'B2',
        'column': '数量',
        'old_value': 2,
        'new_value': 5,
        'old_row': 2,
        'new_row': 2,
        'numeric': False,
        'numeric_parse_failed': False,
    }


def test_composite_key_treats_each_combination_as_one_record(xlsx):
    old, new = tables(
        xlsx,
        [['A1', 'M8', 1], ['A1', 'M10', 2]],
        [['A1', 'M10', 2], ['A1', 'M8', 7]],
        headers=['物料编码', '规格型号', '数量'],
    )
    result = compare_tables(old, new, ['物料编码', '规格型号'])
    assert len(result.added) == len(result.deleted) == 0
    assert [row.key_display for row in result.changed] == ['A1 | M8']
    assert result.unchanged_count == 1


def test_composite_key_does_not_merge_different_specifications(xlsx):
    old, new = tables(
        xlsx,
        [['A1', 'M8', 1]],
        [['A1', 'M10', 1]],
        headers=['物料编码', '规格型号', '数量'],
    )
    result = compare_tables(old, new, ['物料编码', '规格型号'])
    assert [item[0] for item in result.added] == ['A1 | M10']
    assert [item[0] for item in result.deleted] == ['A1 | M8']


def test_duplicate_key_is_refused_and_reported_not_guessed(xlsx):
    # Two rows share a key in the old file. Neither may be matched against the
    # single new row, and the new row may not be claimed as "added".
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['A1', '甲二', 2]],
        [['A1', '甲', 1]],
    )
    result = compare_tables(old, new, ['物料编码'])
    assert result.added == [] and result.deleted == [] and result.changed == []
    assert result.unchanged_count == 0
    duplicates = [a for a in result.anomalies if a.reason == 'duplicate']
    assert [(a.side, a.row_number, a.duplicate_count) for a in duplicates] == [
        ('old', 2, 2),
        ('old', 3, 2),
    ]
    assert '重复 2 次' in duplicates[0].key_display
    assert [(u.side, u.reason, u.row_number) for u in result.unmatched] == [
        ('new', UNMATCHED_BECAUSE_OLD_ANOMALY, 2)
    ]


def test_duplicate_key_on_the_new_side_blocks_a_false_deletion(xlsx):
    old, new = tables(
        xlsx,
        [['A1', '甲', 1]],
        [['A1', '甲', 1], ['A1', '甲二', 2]],
    )
    result = compare_tables(old, new, ['物料编码'])
    assert result.deleted == [] and result.added == []
    assert [(u.side, u.reason) for u in result.unmatched] == [
        ('old', UNMATCHED_BECAUSE_NEW_ANOMALY)
    ]


def test_key_duplicated_on_both_sides_produces_only_anomalies(xlsx):
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['A1', '乙', 2]],
        [['A1', '丙', 3], ['A1', '丁', 4]],
    )
    result = compare_tables(old, new, ['物料编码'])
    assert len(result.anomalies) == 4
    assert result.unmatched == []
    assert (len(result.added), len(result.deleted), len(result.changed)) == (0, 0, 0)


def test_blank_key_is_an_anomaly_and_never_matches_another_blank(xlsx):
    # Two blank keys are not "the same record"; matching them would be a guess.
    old, new = tables(
        xlsx,
        [[None, '甲', 1], ['', '乙', 2], ['A1', '丙', 3]],
        [['  ', '戊', 5], ['A1', '丙', 3]],
    )
    result = compare_tables(old, new, ['物料编码'])
    blanks = [a for a in result.anomalies if a.reason == 'blank']
    assert [(a.side, a.row_number) for a in blanks] == [('old', 2), ('old', 3), ('new', 2)]
    assert '空白字段: 物料编码' in blanks[0].key_display
    assert result.added == [] and result.deleted == []
    assert result.unchanged_count == 1


def test_blank_key_in_a_composite_names_the_offending_column(xlsx):
    old, new = tables(
        xlsx,
        [['A1', None, 1]],
        [['A1', 'M8', 1]],
        headers=['物料编码', '规格型号', '数量'],
    )
    result = compare_tables(old, new, ['物料编码', '规格型号'])
    assert result.anomalies[0].reason == 'blank'
    assert '空白字段: 规格型号' in result.anomalies[0].key_display


def test_different_column_order_is_matched_by_name(xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '品名', '数量'], [['A1', '甲', 1]]))
    new = read_table(xlsx('new.xlsx', ['数量', '物料编码', '品名'], [[7, 'A1', '甲']]))
    result = compare_tables(old, new, ['物料编码'])
    assert result.column_order_differs is True
    assert result.shared_columns == ['物料编码', '品名', '数量']
    assert [(c.column, c.old_value, c.new_value) for c in result.changed[0].changes] == [
        ('数量', 1, 7)
    ]
    assert any('列顺序不同' in item for item in result.warnings)


def test_missing_columns_are_flagged_as_structure_differences(xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '数量', '备注'], [['A1', 1, 'x']]))
    new = read_table(xlsx('new.xlsx', ['物料编码', '数量', '状态'], [['A1', 1, 'y']]))
    result = compare_tables(old, new, ['物料编码'])
    assert result.only_in_old == ['备注']
    assert result.only_in_new == ['状态']
    assert result.unchanged_count == 1
    assert any('仅旧版存在的字段：备注' in item for item in result.warnings)
    assert any('仅新版存在的字段：状态' in item for item in result.warnings)


def test_a_column_only_in_one_file_is_not_compared(xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '备注'], [['A1', 'x']]))
    new = read_table(xlsx('new.xlsx', ['物料编码', '状态'], [['A1', 'y']]))
    result = compare_tables(old, new, ['物料编码'])
    assert result.changed == []
    assert result.unchanged_count == 1


def test_whitespace_in_values_is_ignored_by_default(xlsx):
    old, new = tables(xlsx, [['A1', ' 甲 ', 1]], [['A1', '甲', 1]])
    assert compare_tables(old, new, ['物料编码']).unchanged_count == 1
    strict = compare_tables(
        old, new, ['物料编码'], CompareOptions(ignore_whitespace=False)
    )
    assert strict.changed[0].changes[0].column == '品名'


def test_whitespace_in_keys_is_ignored_by_default(xlsx):
    old, new = tables(xlsx, [['  A1', '甲', 1]], [['A1  ', '甲', 1]])
    result = compare_tables(old, new, ['物料编码'])
    assert result.unchanged_count == 1
    assert result.anomalies == []


def test_case_is_not_ignored_unless_asked(xlsx):
    old, new = tables(xlsx, [['a1', '甲', 1]], [['A1', '甲', 1]])
    result = compare_tables(old, new, ['物料编码'])
    assert [item[0] for item in result.added] == ['A1']
    assert [item[0] for item in result.deleted] == ['a1']

    folded = compare_tables(
        old, new, ['物料编码'], CompareOptions(ignore_case=True)
    )
    assert folded.unchanged_count == 1


def test_leading_zeros_are_not_coerced_into_a_different_key(xlsx):
    # "00123" and 123 are different business identifiers. Collapsing them would
    # be a silent type conversion the user never asked for.
    old, new = tables(xlsx, [['00123', '甲', 1]], [[123, '甲', 1]])
    result = compare_tables(old, new, ['物料编码'])
    assert [item[0] for item in result.added] == ['123']
    assert [item[0] for item in result.deleted] == ['00123']


def test_numeric_columns_compare_by_value_not_by_text(xlsx):
    old, new = tables(xlsx, [['A1', '甲', '1,000']], [['A1', '甲', 1000]])
    options = CompareOptions(numeric_columns=('数量',))
    assert compare_tables(old, new, ['物料编码']).changed != []
    assert compare_tables(old, new, ['物料编码'], options).unchanged_count == 1


def test_numeric_tolerance_absorbs_rounding_noise(xlsx):
    old, new = tables(xlsx, [['A1', '甲', 1.0]], [['A1', '甲', 1.4]])
    tight = CompareOptions(numeric_columns=('数量',), numeric_tolerance=Decimal('0.5'))
    assert compare_tables(old, new, ['物料编码'], tight).unchanged_count == 1

    old2, new2 = tables(xlsx, [['A1', '甲', 1.0]], [['A1', '甲', 1.6]])
    result = compare_tables(old2, new2, ['物料编码'], tight)
    change = result.changed[0].changes[0]
    assert change.numeric is True
    assert change.numeric_parse_failed is False


def test_numeric_column_with_unparseable_text_falls_back_and_says_so(xlsx):
    old, new = tables(xlsx, [['A1', '甲', '待定']], [['A1', '甲', 'TBD']])
    result = compare_tables(
        old, new, ['物料编码'], CompareOptions(numeric_columns=('数量',))
    )
    change = result.changed[0].changes[0]
    assert change.numeric_parse_failed is True
    assert change.old_value == '待定' and change.new_value == 'TBD'


def test_numeric_column_with_identical_unparseable_text_is_unchanged(xlsx):
    old, new = tables(xlsx, [['A1', '甲', '待定']], [['A1', '甲', ' 待定 ']])
    result = compare_tables(
        old, new, ['物料编码'], CompareOptions(numeric_columns=('数量',))
    )
    assert result.unchanged_count == 1


def test_compare_columns_restricts_what_is_compared(xlsx):
    old, new = tables(xlsx, [['A1', '甲', 1]], [['A1', '乙', 9]])
    result = compare_tables(
        old, new, ['物料编码'], CompareOptions(compare_columns=('品名',))
    )
    assert [c.column for c in result.changed[0].changes] == ['品名']
    assert result.changed_field_count == 1


def test_key_only_file_reports_existence_without_comparing(xlsx):
    old, new = tables(xlsx, [['A1'], ['B2']], [['A1']], headers=['物料编码'])
    result = compare_tables(old, new, ['物料编码'])
    assert result.unchanged_count == 1
    assert len(result.deleted) == 1
    assert any('没有可比较的列' in item for item in result.warnings)


def test_both_blank_values_are_not_a_change(xlsx):
    old, new = tables(xlsx, [['A1', None, 1]], [['A1', '   ', 1]])
    assert compare_tables(old, new, ['物料编码']).unchanged_count == 1


def test_summary_reports_record_counts(xlsx):
    old, new = tables(
        xlsx,
        [['A1', '甲', 1], ['B2', '乙', 2], ['DUP', '丙', 3], ['DUP', '丁', 4]],
        [['B2', '乙', 5], ['C3', '丙', 6]],
    )
    summary = compare_tables(old, new, ['物料编码']).summary()
    assert summary['old_rows'] == 4
    assert summary['new_rows'] == 2
    assert summary['added'] == 1
    assert summary['deleted'] == 1
    assert summary['modified_rows'] == 1
    assert summary['modified_fields'] == 1
    assert summary['unchanged'] == 0
    assert summary['anomalies'] == 2
    assert summary['unmatched'] == 0
    # Only rows that actually took part in matching are counted as compared.
    assert summary['compared_rows'] == 1
    assert summary['keys'] == ['物料编码']


def test_key_missing_from_one_file_is_refused(xlsx):
    old = read_table(xlsx('old.xlsx', ['物料编码', '品名'], [['A1', '甲']]))
    new = read_table(xlsx('new.xlsx', ['编码', '品名'], [['A1', '甲']]))
    with pytest.raises(ValidationError, match='新版缺少 物料编码'):
        compare_tables(old, new, ['物料编码'])


def test_no_key_is_refused(xlsx):
    old, new = tables(xlsx, [['A1', '甲', 1]], [['A1', '甲', 1]])
    with pytest.raises(ValidationError, match='至少选择一个匹配字段'):
        compare_tables(old, new, [])


def test_compare_files_reads_both_workbooks(xlsx, tmp_path):
    old_path = xlsx('报价旧.xlsx', CODE_HEADERS, [['A1', '甲', 1], ['B2', '乙', 2]])
    new_path = xlsx('报价新.xlsx', CODE_HEADERS, [['A1', '甲', 1], ['B2', '乙', 9]])
    result = compare_files(old_path, new_path, keys=['物料编码'])
    assert result.old_name == '报价旧.xlsx'
    assert result.new_name == '报价新.xlsx'
    assert result.changed[0].changes[0].new_value == 9
    assert result.summary()['modified_rows'] == 1


def test_compare_files_accepts_a_raw_ui_payload(xlsx):
    old_path = xlsx('a.xlsx', CODE_HEADERS, [['A1', ' 甲 ', '1,000']])
    new_path = xlsx('b.xlsx', CODE_HEADERS, [['A1', '甲', 1000]])
    payload = {
        'ignore_whitespace': False,
        'numeric_columns': ['数量'],
        'numeric_tolerance': '0.5',
        'compare_columns': ['数量'],
    }
    result = compare_files(old_path, new_path, keys=['物料编码'], options=payload)
    # 品名 differs only by whitespace but is excluded from comparison.
    assert result.unchanged_count == 1


def test_compare_files_rejects_a_numeric_column_absent_from_the_new_file(xlsx):
    old_path = xlsx('a.xlsx', CODE_HEADERS, [['A1', '甲', 1]])
    new_path = xlsx('b.xlsx', ['物料编码', '品名', '金额'], [['A1', '甲', 1]])
    with pytest.raises(ValidationError, match='数值比较字段在新版文件中不存在'):
        compare_files(
            old_path, new_path, keys=['物料编码'], options={'numeric_columns': ['数量']}
        )


def test_compare_files_reports_progress_stages(xlsx):
    old_path = xlsx('a.xlsx', CODE_HEADERS, [['A1', '甲', 1]])
    new_path = xlsx('b.xlsx', CODE_HEADERS, [['A1', '甲', 1]])
    seen: list[tuple[str, float]] = []
    compare_files(
        old_path, new_path, keys=['物料编码'], progress=lambda stage, ratio: seen.append((stage, ratio))
    )
    stages = [stage for stage, _ in seen]
    ratios = [ratio for _, ratio in seen]
    assert stages[0] == '读取旧版文件'
    assert stages[-1] == '完成'
    assert ratios == sorted(ratios)
    assert ratios[-1] == 1.0


def test_source_row_numbers_survive_a_header_offset(xlsx):
    old_path = xlsx(
        'a.xlsx',
        CODE_HEADERS,
        [['A1', '甲', 1]],
        preamble_rows=[['某公司报价表'], ['制表人：张三']],
    )
    new_path = xlsx(
        'b.xlsx',
        CODE_HEADERS,
        [['A1', '甲', 2]],
        preamble_rows=[['某公司报价表'], ['制表人：李四']],
    )
    result = compare_files(old_path, new_path, keys=['物料编码'], header_row=3)
    assert result.changed[0].old_row == 4
    assert result.changed[0].new_row == 4
    assert result.old_total_rows == 1


def test_csv_inputs_compare_with_text_semantics(csv_file):
    old_path = csv_file('old.csv', CODE_HEADERS, [['00123', '甲', '1']])
    new_path = csv_file('new.csv', CODE_HEADERS, [['00123', '甲', '2']])
    result = compare_files(old_path, new_path, keys=['物料编码'])
    assert result.changed[0].changes[0].old_value == '1'
    assert result.changed[0].changes[0].new_value == '2'


def test_timings_are_recorded(xlsx):
    old, new = tables(xlsx, [['A1', '甲', 1]], [['A1', '甲', 1]])
    result = compare_tables(old, new, ['物料编码'])
    assert result.timings['total'] >= 0


def test_reader_warnings_are_carried_into_the_result(xlsx, csv_file):
    old_path = csv_file('old.csv', CODE_HEADERS, [['A1', '甲', '1']])
    new_path = xlsx('new.xlsx', CODE_HEADERS, [['A1', '甲', 1]])
    result = compare_files(old_path, new_path, keys=['物料编码'])
    assert result.unchanged_count == 1
    assert any('old.csv：CSV 中的所有列均按文本读取' in item for item in result.warnings)
    assert result.summary()['warnings'] == result.warnings

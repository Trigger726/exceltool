"""Recommendations, reports, and templates exercised through the desktop API."""

import pytest
from openpyxl import load_workbook

from sheetkit.api import SheetKitApi


def source(path, header=1):
    return {'path': path, 'header_row': header}


@pytest.mark.parametrize(('title', 'header'), [([], 1), ([['台账']], 2), ([[None], ['台账']], 3)])
def test_header_recommendation_skips_titles_and_blanks(xlsx, title, header):
    columns = ['物料编码', 'Qty', 2026]
    path = xlsx('table.xlsx', title[0] if title else columns,
                [*title[1:], columns, ['0001', 20, 5]] if title else [['0001', 20, 5]])
    response = SheetKitApi().recommend({'kind': 'header', 'path': path})
    assert response['suggestion']['row'] == header


def test_header_recommendation_leaves_ambiguous_rows_for_review(xlsx):
    path = xlsx('table.xlsx', ['甲', '乙'], [['丙', '丁']])
    assert SheetKitApi().recommend({'kind': 'header', 'path': path})['suggestion']['row'] is None


def test_match_recommendation_verifies_a_composite_and_accepts_distinct_headers(xlsx):
    old = xlsx('old.xlsx', ['物料编码', '规格型号', '数量'], [['001', 'S', 1], ['001', 'L', 2]])
    new = xlsx('new.xlsx', ['库存台账'], [
        ['物料编码', '规格型号', '数量'], ['001', 'L', 3], ['001', 'S', 1],
    ])
    api = SheetKitApi()
    recommendation = api.recommend({'kind': 'match', 'old': source(old), 'new': source(new, 2)})
    assert recommendation['suggestion']['keys'] == ['物料编码', '规格型号']
    result = api.analyze({
        'action': 'compare', 'old_path': old, 'new_path': new, 'new_header_row': 2,
        'keys': recommendation['suggestion']['keys'],
    })
    assert result['summary']['modified_rows'] == 1
    assert result['summary']['unchanged'] == 1


def test_match_recommendation_checks_beyond_sample(xlsx):
    values = [[str(i), i] for i in range(220)]
    old = xlsx('old.xlsx', ['订单号', '数量'], [*values, ['0', 300]])
    new = xlsx('new.xlsx', ['订单号', '数量'], values)
    result = SheetKitApi().recommend({'kind': 'match', 'old': source(old), 'new': source(new)})
    assert not result['suggestion']['keys']
    assert '手动选择' in result['suggestion']['reason']


def test_match_recommendation_rejects_blank_identifiers(xlsx):
    old = xlsx('old.xlsx', ['订单号', '数量'], [['001', 2], [None, 3]])
    new = xlsx('new.xlsx', ['订单号', '数量'], [['001', 2], ['002', 3]])
    result = SheetKitApi().recommend({'kind': 'match', 'old': source(old), 'new': source(new)})
    assert not result['suggestion']['keys']


def test_minor_differences_are_secondary_and_exported(tmp_path, xlsx):
    columns = ['ID', '数量', '名称', '状态']
    old = xlsx('old.xlsx', columns, [['A', '1.10', ' 甲', 'OPEN'], ['B', 3, ' 乙', 'OK']])
    new = xlsx('new.xlsx', columns, [['A', '1.1', '甲', 'open'], ['B', 5, '乙', 'OK']])
    api = SheetKitApi()
    response = api.analyze({
        'action': 'compare', 'old_path': old, 'new_path': new, 'keys': ['ID'],
        'options': {'numeric_columns': ['数量'], 'ignore_case': True},
    })
    stats = response['summary']
    assert (stats['modified_rows'], stats['unchanged'], stats['strict_modified_rows']) == (1, 1, 2)
    assert (stats['minor_rows'], stats['minor_fields']) == (2, 4)
    assert {row[-1] for row in response['preview']['minor']['rows']} == {'数值相同，表达不同', '首尾空格', '大小写'}

    output = tmp_path / 'report.xlsx'
    assert api.export({'kind': 'compare', 'result_id': response['result_id'], 'destination': str(output)})['ok']
    book = load_workbook(output)
    try:
        assert book['细微差异'].auto_filter.ref == 'A1:G5'
        assert book['细微差异'].freeze_panes == 'A2'
        assert book['细微差异']['C2'].value == '1.10'
    finally:
        book.close()


def test_merge_aliases_are_suggestions_until_applied(xlsx):
    a = xlsx('a.xlsx', ['物料编码', '发货日期'], [['00001', '2026-01-01']])
    b = xlsx('b.xlsx', ['出货日期', '物料编号'], [['2026-02-02', '1234567890123456789']])
    api = SheetKitApi()
    plan = api.plan({'sources': [source(a), source(b)]})['plan']
    assert len(plan['body_columns']) == 4
    assert set((item['column'], item['target']) for item in plan['suggestions']) == {
        ('物料编号', '物料编码'), ('出货日期', '发货日期'),
    }
    mapping = {item['column']: item['target'] for item in plan['suggestions']}
    result = api.analyze({'action': 'merge', 'sources': [source(a), {**source(b), 'mapping': mapping}]})
    assert result['summary']['body_columns'] == ['物料编码', '发货日期']
    rows = result['preview']['merged']['rows']
    assert [row[0] for row in rows] == ['00001', '1234567890123456789']
    assert rows[1][-1] == '2'


def test_merge_aliases_require_manual_review_if_both_columns_exist(xlsx):
    a = xlsx('a.xlsx', ['发货日期', '出货日期'], [['2026-01-01', '2026-01-05']])
    b = xlsx('b.xlsx', ['出货日期'], [['2026-02-01']])
    result = SheetKitApi().plan({'sources': [source(a), source(b)]})
    assert result['plan']['suggestions'] == []


def test_cleanup_suggestions_tint_filtered_rows_and_project_saved_columns(tmp_path, xlsx, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    path = xlsx('work.xlsx', ['订单号', '名称', '日期', '数量'], [
        ['001', ' 甲 ', '无效日期', '未知'],
        ['001', '乙', '2026-01-01', 2],
        ['002', '丙', '2026-01-01', 3],
    ])
    api = SheetKitApi()
    recommendations = api.recommend({'kind': 'clean', 'path': path})['suggestion']
    assert recommendations == {
        'strip_columns': ['名称'], 'duplicate_key_columns': ['订单号'],
        'date_columns': ['日期'], 'number_columns': ['数量'],
    }
    result = api.analyze({'action': 'clean', 'path': path, 'options': recommendations})
    assert result['preview']['cleaned']['row_status'] == ['anomaly', 'duplicate', '']
    assert result['summary']['date_anomaly_cells'] == 1
    assert result['summary']['number_anomaly_cells'] == 1
    page = api.page({'result_id': result['result_id'], 'table': 'cleaned', 'filter': '乙'})['table']
    assert page['row_status'] == ['duplicate']

    assert api.templates({'kind': 'clean', 'name': '月报', 'rule': ['名称', '订单号']})['ok']
    saved = SheetKitApi().templates({'kind': 'clean'})['templates']['月报']
    out = tmp_path / 'clean.xlsx'
    export = {'kind': 'clean', 'result_id': result['result_id'], 'destination': str(out)}
    assert not api.export({**export, 'output_columns': ['不存在']})['ok']
    assert api.export({**export, 'output_columns': saved})['ok']
    book = load_workbook(out)
    try:
        for name in ('清洗结果', '重复数据', '异常数据'):
            assert [cell.value for cell in book[name][1]][:2] == saved
            assert '日期' not in [cell.value for cell in book[name][1]]
        assert book['清洗结果']['A2'].fill.fgColor.rgb == 'FFFDECEC'
        assert book['清洗结果']['A3'].fill.fgColor.rgb == 'FFFDF4E3'
        assert book['清洗结果']['B2'].value == '001'
    finally:
        book.close()


def test_merge_template_only_persists_named_rules(tmp_path, monkeypatch, xlsx):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    api = SheetKitApi()
    assert api.templates({'kind': 'merge', 'name': '月度台账', 'rule': {'物料编号': '物料编码'}})['ok']
    rule = SheetKitApi().templates({'kind': 'merge'})['templates']['月度台账']
    path = xlsx('monthly.xlsx', ['物料编号'], [['00235']])
    merged = api.analyze({'action': 'merge', 'sources': [{**source(path), 'mapping': rule}]})
    assert merged['summary']['body_columns'] == ['物料编码']
    content = (tmp_path / 'SheetKit' / 'templates.json').read_text(encoding='utf8')
    assert '00235' not in content and str(path) not in content


def test_open_export_only_accepts_written_results(tmp_path, monkeypatch, xlsx):
    calls = []
    monkeypatch.setattr('os.startfile', calls.append)
    source_path = xlsx('src.xlsx', ['ID'], [['0001']])
    api = SheetKitApi()
    result = api.analyze({'action': 'clean', 'path': source_path})
    output = str(tmp_path / 'result.xlsx')
    assert not api.open_export({'path': source_path})['ok']
    assert api.export({'kind': 'clean', 'result_id': result['result_id'], 'destination': output})['ok']
    assert api.open_export({'path': output, 'folder': True})['ok']
    assert calls == [str(tmp_path)]



def test_unchanged_rows_and_schema_difference_sheets_are_opt_in(tmp_path, xlsx):
    old = xlsx('before.xlsx', ['ID', '名称', '旧列'], [['001', '甲', 2]])
    new = xlsx('after.xlsx', ['ID', '名称', '新列'], [['001', '甲', 3]])
    api = SheetKitApi()
    payload = {'action': 'compare', 'old_path': old, 'new_path': new, 'keys': ['ID']}
    assert 'unchanged' not in api.analyze(payload)['tables']
    result = api.analyze({**payload, 'options': {'include_unchanged': True}})
    assert result['preview']['unchanged']['rows'] == [['001', '甲', '3', '2', '2']]
    out = tmp_path / 'diff.xlsx'
    assert api.export({'kind': 'compare', 'result_id': result['result_id'], 'destination': str(out)})['ok']
    book = load_workbook(out, read_only=True)
    try:
        assert '字段差异' in book.sheetnames
        assert '按规则未变化' in book.sheetnames
    finally:
        book.close()

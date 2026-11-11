"""The desktop bridge: envelopes, paging, exports and cleanup."""

from __future__ import annotations

import os

import pytest
from openpyxl import load_workbook

from sheetkit.api import SheetKitApi


@pytest.fixture
def api():
    bridge = SheetKitApi()
    yield bridge
    bridge.shutdown()


def test_describe_reports_sheets_and_warnings(api, xlsx):
    path = xlsx('a.xlsx', ['编码'], [['00123']], extra_sheets={'二月': (['编码'], [['00456']])})
    response = api.describe({'path': path})
    assert response['ok'] is True
    assert response['file']['name'] == 'a.xlsx'
    assert response['file']['kind'] == 'xlsx'
    assert [item['name'] for item in response['file']['sheets']] == ['数据', '二月']


def test_describe_of_a_missing_file_returns_an_error_envelope(api, tmp_path):
    response = api.describe({'path': str(tmp_path / 'nope.xlsx')})
    assert response['ok'] is False
    assert response['error']['code'] == 'E_FILE_NOT_FOUND'
    assert 'nope.xlsx' in response['error']['message']


def test_describe_of_an_unsupported_file_returns_an_error_envelope(api, tmp_path):
    path = tmp_path / 'legacy.xls'
    path.write_bytes(b'x')
    response = api.describe({'path': str(path)})
    assert response['ok'] is False
    assert response['error']['code'] == 'E_UNSUPPORTED_FORMAT'


def test_preview_returns_one_page_and_the_total(api, xlsx):
    path = xlsx('big.xlsx', ['n'], [[i] for i in range(120)])
    response = api.preview({'path': path, 'offset': 0, 'limit': 50})
    assert response['ok'] is True
    table = response['table']
    assert table['columns'] == ['n']
    assert len(table['rows']) == 50
    assert table['total'] == 120
    assert table['offset'] == 0
    # Source row numbers stay attached to the previewed rows.
    assert table['row_numbers'][0] == 2
    assert table['row_numbers'][-1] == 51


def test_preview_pages_through_the_file(api, xlsx):
    path = xlsx('big.xlsx', ['n'], [[i] for i in range(120)])
    second = api.preview({'path': path, 'offset': 100, 'limit': 50})['table']
    assert len(second['rows']) == 20
    assert second['offset'] == 100
    assert second['total'] == 120


def test_preview_reuses_the_read_while_the_file_is_unchanged(api, xlsx):
    path = xlsx('a.xlsx', ['n'], [[i] for i in range(10)])
    first = api.preview({'path': path})['table']
    second = api.preview({'path': path})['table']
    assert first['rows'] == second['rows']


def test_analyze_compare_returns_a_summary_and_paged_tables(api, xlsx):
    old = xlsx('old.xlsx', ['物料编码', '数量'], [['A1', 1], ['B2', 2]])
    new = xlsx('new.xlsx', ['物料编码', '数量'], [['A1', 9], ['C3', 3]])
    response = api.analyze(
        {
            'action': 'compare',
            'old_path': old,
            'new_path': new,
            'keys': ['物料编码'],
        }
    )
    assert response['ok'] is True
    assert response['kind'] == 'compare'
    assert response['summary']['added'] == 1
    assert response['summary']['deleted'] == 1
    assert response['summary']['modified_rows'] == 1
    assert set(response['tables']) == {'added', 'deleted', 'changed', 'anomaly'}
    assert response['preview']['added']['rows'][0][0] == 'C3'
    assert response['preview']['changed']['rows'][0][:4] == ['A1', '数量', '1', '9']


def test_analyze_compare_refuses_a_missing_key(api, xlsx):
    old = xlsx('old.xlsx', ['物料编码'], [['A1']])
    new = xlsx('new.xlsx', ['物料编码'], [['A1']])
    response = api.analyze(
        {'action': 'compare', 'old_path': old, 'new_path': new, 'keys': []}
    )
    assert response['ok'] is False
    assert '匹配字段' in response['error']['message']


def test_analyze_rejects_an_unknown_action(api):
    response = api.analyze({'action': 'drop'})
    assert response['ok'] is False
    assert response['error']['code'] == 'E_VALIDATION'


def test_analyze_merge_returns_the_merged_rows(api, xlsx):
    first = xlsx('a.xlsx', ['物料编码'], [['A1']])
    second = xlsx('b.xlsx', ['物料编码'], [['B2']])
    response = api.analyze(
        {'action': 'merge', 'sources': [{'path': first}, {'path': second}]}
    )
    assert response['ok'] is True
    assert response['summary']['total_rows'] == 2
    assert response['preview']['merged']['rows'][0][0] == 'A1'


def test_plan_describes_the_merge_layout(api, xlsx):
    first = xlsx('a.xlsx', ['物料编码', '品名'], [['A1', '甲']])
    second = xlsx('b.xlsx', ['物料编码', '数量'], [['B2', 3]])
    response = api.plan({'sources': [{'path': first}, {'path': second}]})
    assert response['ok'] is True
    assert response['plan']['body_columns'] == ['物料编码', '品名', '数量']
    assert response['plan']['partial_columns'] == ['品名', '数量']


def test_analyze_clean_returns_the_cleaned_rows_and_flags(api, xlsx):
    path = xlsx(
        'orders.xlsx',
        ['订单编号', '物料编码', '数量'],
        [['A1', 'M1', 1], ['A1', 'M1', 2], ['B1', None, 3]],
    )
    response = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {
                'duplicate_key_columns': ['订单编号'],
                'required_columns': ['物料编码'],
            },
        }
    )
    assert response['ok'] is True
    assert response['summary']['result_rows'] == 3
    assert response['summary']['duplicate_rows'] == 2
    assert response['summary']['missing_required_rows'] == 1
    assert set(response['tables']) == {'cleaned', 'duplicates', 'anomalies'}


def test_a_destructive_duplicate_rule_asks_for_confirmation(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1'], ['A1']])
    response = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {
                'duplicate_action': 'keep_first',
                'duplicate_key_columns': ['订单编号'],
            },
        }
    )
    assert response['ok'] is False
    assert response['error']['code'] == 'E_CONFIRMATION_REQUIRED'
    impact = response['error']['context']['impact']
    assert impact['keep_first_removes'] == 1
    assert impact['result_rows']['keep_first'] == 1


def test_confirming_the_destructive_rule_produces_the_result(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1'], ['A1']])
    response = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {
                'duplicate_action': 'keep_first',
                'duplicate_key_columns': ['订单编号'],
                'confirmed': True,
            },
        }
    )
    assert response['ok'] is True
    assert response['summary']['result_rows'] == 1
    assert response['summary']['removed_duplicate_rows'] == 1


def test_impact_matches_what_the_confirmed_run_removes(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1'], ['A1'], ['A1'], ['B1']])
    options = {
        'duplicate_action': 'keep_first',
        'duplicate_key_columns': ['订单编号'],
    }
    impact = api.impact({'path': path, 'options': options})['impact']
    assert impact['keep_first_removes'] == 2

    confirmed = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {**options, 'confirmed': True},
        }
    )
    assert confirmed['summary']['result_rows'] == impact['result_rows']['keep_first']


def test_page_returns_more_rows_of_a_stored_result(api, xlsx):
    path = xlsx('big.xlsx', ['n'], [[i] for i in range(120)])
    response = api.analyze({'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}})
    result_id = response['result_id']
    assert len(response['preview']['cleaned']['rows']) == 50

    page = api.page({'result_id': result_id, 'table': 'cleaned', 'offset': 100, 'limit': 50})
    assert page['ok'] is True
    assert len(page['table']['rows']) == 20
    assert page['table']['total'] == 120


def test_page_of_an_unknown_result_is_reported(api):
    response = api.page({'result_id': 'result-999', 'table': 'cleaned'})
    assert response['ok'] is False
    assert response['error']['code'] == 'E_RESULT_EXPIRED'


def test_export_writes_the_report(api, xlsx, tmp_path):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1'], ['A1']])
    result = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {'duplicate_key_columns': ['订单编号']},
        }
    )
    destination = tmp_path / 'clean.xlsx'
    response = api.export(
        {
            'kind': 'clean',
            'result_id': result['result_id'],
            'destination': str(destination),
        }
    )
    assert response['ok'] is True
    assert response['path'] == str(destination)
    book = load_workbook(str(destination), read_only=True)
    try:
        assert book.sheetnames == ['清洗结果', '重复数据', '异常数据', '清洗摘要']
    finally:
        book.close()


def test_export_refuses_to_overwrite_the_source_file(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    result = api.analyze(
        {'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}}
    )
    response = api.export(
        {'kind': 'clean', 'result_id': result['result_id'], 'destination': path}
    )
    assert response['ok'] is False
    assert response['error']['code'] == 'E_OUTPUT_CONFLICT'


def test_release_drops_the_stored_result(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    result = api.analyze(
        {'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}}
    )
    assert api.release({'result_id': result['result_id']})['ok'] is True
    assert api.page({'result_id': result['result_id'], 'table': 'cleaned'})['ok'] is False


def test_shutdown_forgets_everything(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    result = api.analyze(
        {'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}}
    )
    api.shutdown()
    assert api.page({'result_id': result['result_id'], 'table': 'cleaned'})['ok'] is False


def test_choose_files_without_a_window_reports_an_error(api):
    response = api.choose_files({'kind': 'open'})
    assert response['ok'] is False
    assert response['error']['message'] == '窗口尚未就绪'


def test_progress_updates_are_delivered_to_the_window(api, xlsx):
    calls: list[str] = []

    class FakeWindow:
        def evaluate_js(self, script):
            calls.append(script)

    api._attach(FakeWindow())
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    api.analyze(
        {
            'action': 'clean',
            'path': path,
            'options': {'duplicate_action': 'none'},
        }
    )
    assert any('sheetkitProgress' in call for call in calls)
    assert any('读取文件' in call for call in calls)


def test_page_can_filter_the_result(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号', '品名'], [['A1', '甲'], ['B2', '乙'], ['C3', '甲乙']])
    result = api.analyze(
        {'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}}
    )
    response = api.page(
        {
            'result_id': result['result_id'],
            'table': 'cleaned',
            'offset': 0,
            'limit': 50,
            'filter': '甲',
        }
    )
    assert response['ok'] is True
    assert response['table']['total'] == 2
    assert response['table']['unfiltered_total'] == 3
    assert [row[0] for row in response['table']['rows']] == ['A1', 'C3']


def test_cancelling_an_unknown_job_is_remembered(api):
    response = api.cancel({'job_id': 'job-does-not-exist'})
    assert response['ok'] is True
    assert response['cancelled'] is True


def test_a_cancelled_job_stops_with_the_cancelled_code(api, xlsx):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    job_id = 'job-test-1'
    api._cancel_event(job_id).set()
    response = api.analyze(
        {
            'action': 'clean',
            'path': path,
            'job_id': job_id,
            'options': {'duplicate_action': 'none'},
        }
    )
    assert response['ok'] is False
    assert response['error']['code'] == 'E_CANCELLED'


def test_the_bridge_writes_nothing_next_to_the_input(api, xlsx, tmp_path):
    path = xlsx('orders.xlsx', ['订单编号'], [['A1']])
    before = sorted(os.listdir(tmp_path))
    api.analyze(
        {'action': 'clean', 'path': path, 'options': {'duplicate_action': 'none'}}
    )
    assert sorted(os.listdir(tmp_path)) == before

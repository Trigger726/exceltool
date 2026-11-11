"""Report layout: turns engine results into exported workbooks.

Sheet structure follows the product spec — one summary sheet plus the detail
sheets, colour-coded by change type so a reviewer can tell added, removed,
modified and anomalous rows apart without reading the numbers.
"""

from __future__ import annotations

from .clean import CleanResult
from .errors import ValidationError
from .compare import CompareResult, UnmatchedRow
from .exporter import SheetSpec, TINTS, WorkbookSpec, summary_sheet
from .merge import MergeResult
from .values import display_text


def _fixed(tint: str):
    def apply(_index: int, _row) -> str:
        return tint

    return apply


CHANGE_HEADERS = ['匹配字段', '修改列', '旧值', '新值', '旧版行号', '新版行号', '比较方式']


def change_rows(records: list[dict]) -> list[list]:
    return [
        [record['key'], record['column'], display_text(record['old_value']),
         display_text(record['new_value']), record['old_row'], record['new_row'], _compare_mode(record)]
        for record in records
    ]


def compare_report(result: CompareResult) -> WorkbookSpec:
    summary = result.summary()
    spec = WorkbookSpec(properties_title='SheetKit 表格对比报告')

    spec.add(
        summary_sheet(
            '对比摘要',
            [
                ('旧版文件', result.old_name),
                ('旧版工作表', result.old_sheet or '(默认)'),
                ('新版文件', result.new_name),
                ('新版工作表', result.new_sheet or '(默认)'),
                ('匹配字段', result.keys),
                ('旧版记录数', summary['old_rows']),
                ('新版记录数', summary['new_rows']),
                ('参与比对记录数', summary['compared_rows']),
                ('新增记录数', summary['added']),
                ('删除记录数', summary['deleted']),
                ('修改记录数', summary['modified_rows']),
                ('修改字段数', summary['modified_fields']),
                ('按所选规则未变化记录数', summary['unchanged']),
                ('严格比较有差异的匹配记录数', summary['strict_modified_rows']),
                ('含细微差异的记录数（可同时有实际修改）', summary['minor_rows']),
                ('细微差异字段数', summary['minor_fields']),
                ('异常记录数', summary['anomalies']),
                ('无法判定记录数', summary['unmatched']),
                ('仅旧版存在的字段', summary['only_in_old_columns']),
                ('仅新版存在的字段', summary['only_in_new_columns']),
                ('列顺序不同', summary['column_order_differs']),
                ('处理耗时(秒)', result.timings.get('total', 0)),
                ('提示', summary['warnings']),
            ],
        )
    )

    spec.add(
        SheetSpec(
            name='新增记录',
            headers=[*result.new_columns, '新版行号'],
            rows=[[*values, row_number] for _key, row_number, values in result.added],
            tint=_fixed(TINTS['added']),
        )
    )

    spec.add(
        SheetSpec(
            name='删除记录',
            headers=[*result.old_columns, '旧版行号'],
            rows=[[*values, row_number] for _key, row_number, values in result.deleted],
            tint=_fixed(TINTS['deleted']),
        )
    )

    spec.add(
        SheetSpec(
            name='修改明细',
            headers=CHANGE_HEADERS,
            rows=change_rows(result.modification_records),
            tint=_fixed(TINTS['modified']),
            widths=[28.0, 18.0, 30.0, 30.0, 11.0, 11.0, 22.0],
            wrap_columns=(2, 3),
        )
    )

    if result.minor:
        spec.add(SheetSpec(
            name='细微差异', headers=CHANGE_HEADERS, rows=change_rows(result.minor_records),
            widths=[28.0, 18.0, 30.0, 30.0, 11.0, 11.0, 26.0], wrap_columns=(2, 3),
        ))

    union_columns = list(result.old_columns) + [
        name for name in result.new_columns if name not in set(result.old_columns)
    ]
    anomaly_rows: list[list] = []
    for anomaly in result.anomalies:
        columns = result.new_columns if anomaly.side == 'new' else result.old_columns
        values = _align(anomaly.values, columns, union_columns)
        anomaly_rows.append(
            [
                '新版' if anomaly.side == 'new' else '旧版',
                '匹配字段为空' if anomaly.reason == 'blank' else '匹配字段重复',
                anomaly.key_display,
                anomaly.row_number,
                *values,
            ]
        )
    for item in result.unmatched:
        columns = result.new_columns if item.side == 'new' else result.old_columns
        values = _align(item.values, columns, union_columns)
        anomaly_rows.append(
            [
                '新版' if item.side == 'new' else '旧版',
                _unmatched_reason(item),
                item.key_display,
                item.row_number,
                *values,
            ]
        )

    spec.add(
        SheetSpec(
            name='异常记录',
            headers=['来源', '异常类型', '匹配字段', '原始行号', *union_columns],
            rows=anomaly_rows,
            tint=_fixed(TINTS['anomaly']),
            widths=[8.0, 22.0, 26.0, 11.0],
        )
    )
    if result.only_in_old or result.only_in_new:
        spec.add(SheetSpec(
            name='字段差异', headers=['字段名', '情况', '比较说明'], rows=[
                *([name, '仅旧版存在', '新版缺少此列，未比较'] for name in result.only_in_old),
                *([name, '仅新版存在', '旧版缺少此列，未比较'] for name in result.only_in_new),
            ],
        ))
    if result.unchanged_rows is not None:
        spec.add(SheetSpec(
            name='按规则未变化', headers=[*result.new_columns, '旧版行号', '新版行号'],
            rows=([*row, old, new] for row, old, new in result.unchanged_rows),
        ))
    return spec


def _compare_mode(record: dict) -> str:
    if record.get('accepted_difference'):
        return record['accepted_difference']
    if record.get('numeric_parse_failed'):
        return '数值比较失败，按文本比较'
    if record.get('numeric'):
        return '十进制数值比较'
    return '文本比较'


def _unmatched_reason(item: UnmatchedRow) -> str:
    return '旧版匹配字段重复，无法判定' if item.side == 'new' else '新版匹配字段重复，无法判定'


def _align(values: list, source_columns: list[str], target_columns: list[str]) -> list:
    """Move a row from its own column layout onto the shared layout."""
    index = {name: position for position, name in enumerate(source_columns)}
    out: list = []
    for name in target_columns:
        position = index.get(name)
        out.append(values[position] if position is not None and position < len(values) else None)
    return out


def merge_report(result: MergeResult) -> WorkbookSpec:
    spec = WorkbookSpec()
    spec.add(
        SheetSpec(
            name='合并结果',
            headers=list(result.columns),
            rows=result.rows,
        )
    )

    summary_rows: list[list] = []
    for source in result.plan.sources:
        summary_rows.append(
            [
                source.name,
                source.sheet or '(默认)',
                source.header_row,
                len(source.mapped_columns),
                source.row_count,
                '已跳过' if source.skipped else '已合并',
                '；'.join(source.warnings),
            ]
        )
    summary_rows.append(
        ['合计', '', '', len(result.plan.body_columns), result.row_count, '', '']
    )

    spec.add(
        SheetSpec(
            name='合并摘要',
            headers=['来源文件', '来源工作表', '表头行', '字段数', '记录数', '状态', '提示'],
            rows=summary_rows,
            widths=[34.0, 16.0, 9.0, 9.0, 10.0, 10.0, 60.0],
            wrap_columns=(6,),
        )
    )

    if result.plan.warnings:
        spec.add(summary_sheet('合并提示', [
            ('仅部分文件存在的字段', result.plan.partial_columns),
            ('提示', result.plan.warnings),
        ]))
    merged_files = sum(not source.skipped for source in result.plan.sources)
    spec.add(summary_sheet('汇总', [
        ('已合并文件数', merged_files),
        ('已跳过文件数', len(result.plan.sources) - merged_files),
        ('读取记录数', sum(source.row_count for source in result.plan.sources)),
        ('输出记录数', result.row_count),
    ]))
    return spec


def clean_report(result: CleanResult, output_columns: list[str] | None = None) -> WorkbookSpec:
    spec = WorkbookSpec(properties_title='SheetKit 数据清洗报告')
    columns = result.columns

    def tint(_index, row):
        return {'anomaly': TINTS['deleted'], 'duplicate': TINTS['modified']}.get(result.row_status(row))

    indices = None
    if output_columns is not None:
        if not isinstance(output_columns, list) or not output_columns or not all(isinstance(name, str) for name in output_columns):
            raise ValidationError('请至少选择一个要导出的字段')
        index = {name: i for i, name in enumerate(result.body_columns)}
        missing = [name for name in output_columns if name not in index]
        if missing:
            raise ValidationError('输出模板中的字段不存在：' + '、'.join(missing))
        if len(output_columns) != len(set(output_columns)):
            raise ValidationError('输出列中有重复字段，请调整后再导出')
        indices = [index[name] for name in output_columns] + list(range(len(index), len(columns)))

    def sheet(name, rows, row_tint):
        if indices is None:
            return SheetSpec(name=name, headers=list(columns), rows=rows, tint=row_tint)
        return SheetSpec(
            name=name, headers=[columns[i] for i in indices],
            rows=([row[i] for i in indices] for row in rows),
            tint=lambda position, _row: row_tint(position, rows[position]),
        )

    spec.add(sheet('清洗结果', result.rows, tint))
    spec.add(sheet('重复数据', result.duplicate_rows, _fixed(TINTS['modified'])))
    spec.add(sheet('异常数据', result.anomaly_rows, _fixed(TINTS['deleted'])))

    summary = result.summary()
    spec.add(
        summary_sheet(
            '清洗摘要',
            [
                ('源文件', summary['file']),
                ('工作表', summary['sheet'] or '(默认)'),
                ('原始记录数', summary['original_rows']),
                ('处理后记录数', summary['result_rows']),
                ('删除完全空白行', summary['remove_blank_rows']),
                ('删除的完全空白行数', summary['blank_rows'] if summary['remove_blank_rows'] else 0),
                ('清理空格的字段', summary['strip_columns']),
                ('必填检查字段', summary['required_columns']),
                ('日期检查字段', summary['date_columns']),
                ('数字检查字段', summary['number_columns']),
                ('清理空格的单元格数', summary['stripped_cells']),
                ('重复判断字段', summary['duplicate_key_columns']),
                ('重复处理方式', summary['duplicate_action_label']),
                ('重复组数', summary['duplicate_groups']),
                ('涉及重复的记录数', summary['duplicate_rows']),
                ('已删除的重复记录数', summary['removed_duplicate_rows']),
                ('必填缺失记录数', summary['missing_required_rows']),
                ('必填缺失单元格数', summary['missing_required_cells']),
                ('格式异常记录数', summary['format_anomaly_rows']),
                ('格式异常单元格数', summary['format_anomaly_cells']),
                ('日期异常数', summary['date_anomaly_cells']),
                ('数字异常数', summary['number_anomaly_cells']),
                ('处理耗时(秒)', result.timings.get('total', 0)),
                ('提示', summary['warnings']),
            ],
        )
    )
    return spec

"""Report layout: turns engine results into exported workbooks.

Sheet structure follows the product spec — one summary sheet plus the detail
sheets, colour-coded by change type so a reviewer can tell added, removed,
modified and anomalous rows apart without reading the numbers.
"""

from __future__ import annotations

from .clean import CleanResult
from .compare import CompareResult, UnmatchedRow
from .exporter import SheetSpec, TINTS, WorkbookSpec, summary_sheet
from .merge import MergeResult
from .values import display_text


def _fixed(tint: str):
    def apply(_index: int, _row) -> str:
        return tint

    return apply


def compare_report(result: CompareResult) -> WorkbookSpec:
    summary = result.summary()
    spec = WorkbookSpec()

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
                ('未变化记录数', summary['unchanged']),
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
            headers=['匹配字段', '修改列', '旧值', '新值', '旧版行号', '新版行号', '比较方式'],
            rows=[
                [
                    record['key'],
                    record['column'],
                    display_text(record['old_value']),
                    display_text(record['new_value']),
                    record['old_row'],
                    record['new_row'],
                    _compare_mode(record),
                ]
                for record in result.modification_records
            ],
            tint=_fixed(TINTS['modified']),
            widths=[28.0, 18.0, 30.0, 30.0, 11.0, 11.0, 22.0],
            wrap_columns=(2, 3),
        )
    )

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
    return spec


def _compare_mode(record: dict) -> str:
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
        spec.add(summary_sheet('合并提示', [('提示', result.plan.warnings)]))
    return spec


def clean_report(result: CleanResult) -> WorkbookSpec:
    spec = WorkbookSpec()
    columns = result.columns

    spec.add(
        SheetSpec(name='清洗结果', headers=list(columns), rows=result.rows)
    )
    spec.add(
        SheetSpec(
            name='重复数据',
            headers=list(columns),
            rows=result.duplicate_rows,
            tint=_fixed(TINTS['modified']),
        )
    )
    spec.add(
        SheetSpec(
            name='异常数据',
            headers=list(columns),
            rows=result.anomaly_rows,
            tint=_fixed(TINTS['deleted']),
        )
    )

    summary = result.summary()
    spec.add(
        summary_sheet(
            '清洗摘要',
            [
                ('源文件', summary['file']),
                ('工作表', summary['sheet'] or '(默认)'),
                ('原始记录数', summary['original_rows']),
                ('处理后记录数', summary['result_rows']),
                ('空白行数', summary['blank_rows']),
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
                ('处理耗时(秒)', result.timings.get('total', 0)),
                ('提示', summary['warnings']),
            ],
        )
    )
    return spec

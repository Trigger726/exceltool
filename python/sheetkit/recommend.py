"""Conservative, local suggestions. The user chooses which to apply."""

from __future__ import annotations

import re
from itertools import islice

from .clean import _check_date, _check_number
from .compare import KEY_SEPARATOR
from .reader import TableData
from .values import is_blank, key_text, normalize_header, to_decimal

_IDENTIFIERS = re.compile(
    r'^(?:id|sku|[a-z ]+[_ -](?:id|code|number|no)|'
    r'.*(?:编码|编号|订单号|单据号|工单号|批次号|流水号|序列号|条码|账号|证件号))$',
    re.I,
)
_LABEL = re.compile(r'日期|时间|金额|数量|名称|品名|规格|型号|地址|电话|备注|单价|状态|'
                    r'\b(?:name|date|time|quantity|qty|amount|price|status|description|phone|notes?)\b', re.I)
_VARIANT = re.compile(r'规格|型号|行号|明细号|颜色|尺寸|model|variant|size|line.?no', re.I)


def _identifier(name: str) -> bool:
    return bool(_IDENTIFIERS.fullmatch(name.replace('_', ' ')))


def header_suggestion(rows: list[tuple]) -> dict:
    """Use labels or a text-to-number transition in the first plausible row."""
    populated = [
        (number, [value for value in row if not is_blank(value)])
        for number, row in enumerate(rows, 1)
        if any(not is_blank(value) for value in row)
    ]
    for index, (number, values) in enumerate(populated[:-1]):
        following = populated[index + 1:index + 5]
        names = [normalize_header(value) for value in values]
        known = sum(_identifier(name) or bool(_LABEL.search(name)) for name in names)
        if len(values) == 1 and len(following[0][1]) > 1:
            continue  # A standalone title above the table.
        if len(set(names)) != len(names) or not any(isinstance(v, str) for v in values):
            break
        if len(following[0][1]) > len(values):
            break
        numeric_headers = sum(to_decimal(value) is not None for value in values)
        numeric_data = any(
            sum(to_decimal(value) is not None for value in data) > numeric_headers
            for _, data in following
        )
        if known or (len(values) >= 2 and numeric_headers == 0 and numeric_data):
            return {'row': number, 'reason': '依据字段名称及后续数据行推荐，请核对预览。'}
        break
    return {'row': None, 'reason': '未能可靠识别表头，请查看预览并确认表头行。'}


def match_suggestion(old: TableData, new: TableData, *, whitespace: bool, case: bool) -> dict:
    new_names = set(new.columns)
    shared = [name for name in old.columns if name in new_names]
    ids = [name for name in shared if _identifier(name)][:6]
    extras = [name for name in shared if name not in ids and _VARIANT.search(name)][:4]
    candidates = [(name,) for name in ids]
    candidates += [(name, extra) for i, name in enumerate(ids) for extra in [*extras, *ids[i+1:]]]
    scanned = old.row_count + new.row_count
    if scanned > 200_000 or not old.row_count or not new.row_count:
        return {'keys': [], 'reason': '当前数据量或记录数不适合自动验证，请手动选择匹配字段。'}

    def collect(table: TableData, names: tuple[str, ...], limit: int) -> set[str] | None:
        indexes = [table.column_index(name) for name in names]
        keys = set()
        for row in islice(table.rows, limit):
            parts = [key_text(row[i], ignore_whitespace=whitespace, ignore_case=case) for i in indexes]
            key = KEY_SEPARATOR.join(parts)
            if any(is_blank(part) for part in parts) or key in keys:
                return None
            keys.add(key)
        return keys

    remaining = 600_000
    for names in candidates:
        if any(collect(table, names, 200) is None for table in (old, new)):
            continue
        remaining -= scanned * len(names)
        if remaining < 0:
            break
        left, right = (collect(table, names, table.row_count) for table in (old, new))
        if left and right and left & right:
            reason = '两张表中均无空值和重复，且能匹配到记录。'
            if len(names) > 1:
                reason = '单字段未通过匹配检查，组合后两张表中均无空值和重复，且能匹配到记录。'
            return {'keys': list(names), 'reason': reason}
    return {'keys': [], 'reason': '未找到可可靠匹配的编号或组合，请手动选择两张表中用于识别同一条记录的字段。'}


def clean_suggestions(table: TableData) -> dict:
    sample = table.rows[:500]
    trim, dates, numbers = [], [], []
    duplicate = None
    for index, name in enumerate(table.columns):
        if any(isinstance(row[index], str) and row[index].strip() != row[index] for row in sample):
            trim.append(name)
        if re.search(r'日期|\bdate\b', name, re.I) and any(_check_date(row, index, name) for row in sample):
            dates.append(name)
        if re.search(r'数量|金额|单价|\b(?:qty|quantity|amount|price)\b', name, re.I):
            if any(_check_number(row, index, name) for row in sample):
                numbers.append(name)
        if duplicate is None and _identifier(name) and any(not is_blank(row[index]) for row in sample):
            duplicate = name
    return {
        'strip_columns': trim, 'date_columns': dates, 'number_columns': numbers,
        'duplicate_key_columns': [duplicate] if duplicate else [],
    }



# Only aliases reviewed as interchangeable within an office table.
_MERGE_ALIASES = (
    ('发货日期', '出货日期'),
    ('物料编码', '物料编号'),
    ('联系电话', '电话号码'),
)


def merge_suggestions(sources: list[dict]) -> list[dict]:
    suggestions = []
    for group in _MERGE_ALIASES:
        members = set(group)
        matches = [
            (index, members.intersection(source['columns']), source)
            for index, source in enumerate(sources) if not source['skipped']
        ]
        if any(len(names) > 1 for _, names, _ in matches):
            continue  # Both labels occur in a single file, so the meaning is ambiguous.
        populated = [(index, next(iter(names)), source) for index, names, source in matches if names]
        if not populated:
            continue
        first_source = populated[0][2]
        first_column = populated[0][1]
        target = first_source['mapped_columns'][first_source['columns'].index(first_column)]
        if target not in members:
            continue
        for index, name, source in populated[1:]:
            current = source['mapped_columns'][source['columns'].index(name)]
            if current == name and name != target and target not in source['mapped_columns']:
                suggestions.append({'source_index': index, 'column': name, 'target': target})
    return suggestions

"""Canonical value handling.

Excel stores "00123", 123 and 123.0 as three different things, and business
keys such as 物料编码 / 订单编号 are routinely stored as text with leading zeros
or as numbers with more than 15 digits. This module defines the single set of
rules used everywhere in the engine so that a key or a cell never gets an
implicit type conversion the user did not ask for.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

_NUMBER_CLEANUP = re.compile(r'[,\s，、￥¥$€£]')
_PAREN_NEGATIVE = re.compile(r'^\((.*)\)$')

# Excel's own epoch and the serial-number range that maps to sane dates.
_EXCEL_EPOCH = dt.datetime(1899, 12, 30)
_MAX_REASONABLE_YEAR = 2200
_MIN_REASONABLE_YEAR = 1900


def is_blank(value: Any) -> bool:
    """True for None, empty string, and strings that are only whitespace."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ''
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def row_is_blank(row: tuple[Any, ...] | list[Any]) -> bool:
    return all(is_blank(cell) for cell in row)


def format_number(value: float | int) -> str:
    """Render a number the way Excel would show it, without float noise."""
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        return ''
    if value.is_integer() and abs(value) < 1e16:
        return str(int(value))
    text = repr(value)
    if 'e' in text or 'E' in text:
        text = format(value, '.12f').rstrip('0').rstrip('.')
    return text


def format_datetime(value: dt.datetime) -> str:
    if value.microsecond:
        return value.strftime('%Y-%m-%d %H:%M:%S.%f').rstrip('0').rstrip('.')
    if (value.hour, value.minute, value.second) == (0, 0, 0):
        return value.strftime('%Y-%m-%d')
    return value.strftime('%Y-%m-%d %H:%M:%S')


def display_text(value: Any) -> str:
    """Human-readable text for previews and exported reports."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, dt.datetime):
        return format_datetime(value)
    if isinstance(value, dt.date):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, dt.time):
        return value.strftime('%H:%M:%S')
    if isinstance(value, Decimal):
        return str(int(value)) if value == value.to_integral_value() else str(value)
    return str(value)


def key_text(
    value: Any,
    *,
    ignore_whitespace: bool = True,
    ignore_case: bool = False,
) -> str:
    """Stable text form of a value used for key matching and value comparison.

    Only leading/trailing whitespace is removed and case folding is optional, so
    the behaviour matches the user-facing option "忽略文本首尾空格" exactly. The
    number 123 and the text "123" both produce "123", which is what users expect
    when a sheet mixes numeric and text cells in one column.
    """
    text = display_text(value)
    if ignore_whitespace:
        text = text.strip()
    if ignore_case:
        text = text.casefold()
    return text


def to_decimal(value: Any) -> Decimal | None:
    """Lenient numeric parse for user-designated numeric columns.

    Returns None when the value is not a number, so the caller can fall back to
    text comparison and report the cell instead of silently coercing it.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return Decimal(repr(value))
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return None

    text = str(value).strip()
    if not text:
        return None

    negative = False
    match = _PAREN_NEGATIVE.match(text)
    if match:
        text = match.group(1).strip()
        negative = True
    text = _NUMBER_CLEANUP.sub('', text)
    if not text:
        return None
    if text.startswith('+'):
        text = text[1:]
    if text.startswith('-'):
        negative = not negative
        text = text[1:]
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -result if negative else result


_DATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('ymd', re.compile(r'^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?$')),
    ('dmy', re.compile(r'^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$')),
    ('ym', re.compile(r'^(\d{4})[-/.年](\d{1,2})月?$')),
    ('compact', re.compile(r'^(\d{4})(\d{2})(\d{2})$')),
)


def parse_date(value: Any) -> dt.date | None:
    """Parse a value that is meant to be a date. None means "not a date"."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (bool, dt.time)):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        # Excel serial date: only accept the plausible window, otherwise the
        # number is far more likely to be an identifier than a date.
        if not -1000 < value < 80000:
            return None
        try:
            return (_EXCEL_EPOCH + dt.timedelta(days=float(value))).date()
        except (OverflowError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    for kind, pattern in _DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        groups = match.groups()
        try:
            if kind == 'ymd' or kind == 'compact':
                year, month, day = (int(g) for g in groups)
            elif kind == 'ym':
                year, month = int(groups[0]), int(groups[1])
                day = 1
            else:
                day, month, year = (int(g) for g in groups)
            return dt.date(year, month, day)
        except ValueError:
            return None
    for candidate in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M', '%d/%m/%Y', '%m/%d/%Y'):
        try:
            return dt.datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    return None


def date_is_implausible(value: dt.date) -> bool:
    return value.year < _MIN_REASONABLE_YEAR or value.year > _MAX_REASONABLE_YEAR


def normalize_header(value: Any) -> str:
    """Header text used for name-based matching.

    Whitespace and non-breaking spaces are stripped because exported reports
    very often carry them, which would otherwise break column alignment.
    """
    if value is None:
        return ''
    text = str(value).replace('\u00a0', ' ').replace('\u3000', ' ')
    return re.sub(r'\s+', ' ', text).strip()


def dedupe_names(names: list[str], placeholder: str = '未命名列') -> list[str]:
    """Make header names unique while keeping their original order."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for raw in names:
        name = raw if raw else placeholder
        if name in seen:
            seen[name] += 1
            candidate = f'{name}_{seen[name]}'
            while candidate in seen:
                seen[name] += 1
                candidate = f'{name}_{seen[name]}'
            seen[candidate] = 1
            result.append(candidate)
        else:
            seen[name] = 1
            result.append(name)
    return result

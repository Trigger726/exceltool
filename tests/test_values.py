"""Canonical value rules: the single place that decides how a cell becomes text."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from sheetkit.values import (
    date_is_implausible,
    dedupe_names,
    display_text,
    format_number,
    is_blank,
    key_text,
    normalize_header,
    parse_date,
    row_is_blank,
    to_decimal,
)


@pytest.mark.parametrize(
    'value',
    [None, '', '   ', '\t\n', float('nan')],
)
def test_is_blank_true(value):
    assert is_blank(value)


@pytest.mark.parametrize('value', [0, 0.0, False, '0', 'a', dt.datetime(2024, 1, 1)])
def test_is_blank_false(value):
    assert not is_blank(value)


def test_row_is_blank():
    assert row_is_blank([None, '', '  '])
    assert not row_is_blank([None, 0, None])


@pytest.mark.parametrize(
    'value,expected',
    [
        (5, '5'),
        (5.0, '5'),
        (-12.5, '-12.5'),
        (float('nan'), ''),
        (float('inf'), ''),
        (1e20, '100000000000000000000'),
    ],
)
def test_format_number(value, expected):
    assert format_number(value) == expected


@pytest.mark.parametrize(
    'value,expected',
    [
        (None, ''),
        (True, 'TRUE'),
        (False, 'FALSE'),
        ('00123', '00123'),
        (7, '7'),
        (2.5, '2.5'),
        (dt.datetime(2024, 3, 15), '2024-03-15'),
        (dt.datetime(2024, 3, 15, 9, 30), '2024-03-15 09:30:00'),
        (dt.datetime(2024, 3, 15, 9, 30, 0, 123000), '2024-03-15 09:30:00.123'),
        (dt.date(2024, 3, 15), '2024-03-15'),
        (dt.time(9, 30), '09:30:00'),
        (Decimal('12.50'), '12.50'),
        (Decimal('12'), '12'),
    ],
)
def test_display_text(value, expected):
    assert display_text(value) == expected


def test_display_text_never_invents_leading_zeros_or_precision():
    # 物料编码 / 订单编号 must survive as the exact stored text.
    assert display_text('00123') == '00123'
    assert display_text('9007199254740993') == '9007199254740993'


@pytest.mark.parametrize(
    'value,kwargs,expected',
    [
        ('  A1  ', {}, 'A1'),
        ('  A1  ', {'ignore_whitespace': False}, '  A1  '),
        ('Abc', {'ignore_case': True}, 'abc'),
        ('Abc', {}, 'Abc'),
        (123, {}, '123'),
        ('123', {}, '123'),
        (123.0, {}, '123'),
        (None, {}, ''),
    ],
)
def test_key_text(value, kwargs, expected):
    assert key_text(value, **kwargs) == expected


def test_key_text_does_not_collapse_internal_whitespace():
    # The user-facing option is "忽略文本首尾空格" only. Rewriting the inside of a
    # 规格型号 such as "M8 x 20" would silently change a business value.
    assert key_text('M8  x 20') == 'M8  x 20'


def test_key_text_matches_number_and_text_forms_of_the_same_value():
    # A mixed text/number column is common in real sheets; 123 and "123" are the
    # same key to a human reader.
    assert key_text(123) == key_text('123') == key_text(123.0)


@pytest.mark.parametrize(
    'value,expected',
    [
        (5, Decimal(5)),
        (5.5, Decimal('5.5')),
        ('1,234.5', Decimal('1234.5')),
        ('1,234.50', Decimal('1234.50')),
        ('￥1,000', Decimal('1000')),
        ('$2.50', Decimal('2.50')),
        (' 42 ', Decimal('42')),
        ('-5', Decimal('-5')),
        ('+5', Decimal('5')),
        ('(100)', Decimal('-100')),
        ('1 234', Decimal('1234')),
        ('1、234', Decimal('1234')),
    ],
)
def test_to_decimal_parses(value, expected):
    assert to_decimal(value) == expected


@pytest.mark.parametrize(
    'value',
    [None, '', '   ', 'abc', '12a', True, False, dt.datetime(2024, 1, 1), float('nan')],
)
def test_to_decimal_refuses(value):
    assert to_decimal(value) is None


def test_to_decimal_keeps_precision_that_float_would_lose():
    assert to_decimal('0.1') + to_decimal('0.2') == Decimal('0.3')
    assert to_decimal(0.1) + to_decimal(0.2) == Decimal('0.3')


@pytest.mark.parametrize(
    'value,expected',
    [
        (dt.datetime(2024, 3, 15), dt.date(2024, 3, 15)),
        (dt.date(2024, 3, 15), dt.date(2024, 3, 15)),
        ('2024-03-15', dt.date(2024, 3, 15)),
        ('2024/3/15', dt.date(2024, 3, 15)),
        ('2024.03.15', dt.date(2024, 3, 15)),
        ('2024年3月15日', dt.date(2024, 3, 15)),
        ('20240315', dt.date(2024, 3, 15)),
        ('15-03-2024', dt.date(2024, 3, 15)),
        ('2024-03', dt.date(2024, 3, 1)),
        ('2024年3月', dt.date(2024, 3, 1)),
        ('2024-03-15 09:30:00', dt.date(2024, 3, 15)),
        (45366, dt.date(2024, 3, 15)),
        (45366.0, dt.date(2024, 3, 15)),
    ],
)
def test_parse_date_accepts(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    'value',
    [
        None,
        '',
        '   ',
        'abc',
        '2024-13-45',
        True,
        dt.time(9, 30),
        float('nan'),
        # Outside the plausible Excel serial window this is an identifier, not a date.
        9007199254740993,
        -5000,
    ],
)
def test_parse_date_refuses(value):
    assert parse_date(value) is None


def test_parse_date_does_not_read_a_short_identifier_as_a_serial():
    # 物料编码 "1234" is a code, not 1903-05-18.
    assert parse_date('1234') is None
    assert parse_date(1234) == dt.date(1903, 5, 18)


@pytest.mark.parametrize(
    'value,expected',
    [
        (dt.date(2024, 3, 15), False),
        (dt.date(1899, 1, 1), True),
        (dt.date(2201, 1, 1), True),
        (dt.date(1900, 1, 1), False),
        (dt.date(2200, 12, 31), False),
    ],
)
def test_date_is_implausible(value, expected):
    assert date_is_implausible(value) is expected


@pytest.mark.parametrize(
    'value,expected',
    [
        ('  物料编码  ', '物料编码'),
        ('物料\u00a0编码', '物料 编码'),
        ('物料\u3000编码', '物料 编码'),
        ('a\t\tb', 'a b'),
        (None, ''),
        (7, '7'),
    ],
)
def test_normalize_header(value, expected):
    assert normalize_header(value) == expected


def test_dedupe_names_keeps_order_and_makes_names_unique():
    assert dedupe_names(['a', 'b', 'a', 'a']) == ['a', 'b', 'a_2', 'a_3']


def test_dedupe_names_fills_empty_headers():
    assert dedupe_names(['a', '', '']) == ['a', '未命名列', '未命名列_2']


def test_dedupe_names_avoids_colliding_with_an_existing_suffix():
    assert dedupe_names(['a', 'a_2', 'a']) == ['a', 'a_2', 'a_3']

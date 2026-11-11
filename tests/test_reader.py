"""Reader behaviour: formats, sheets, header rows, encoding, formulas, locks."""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import zipfile

import pytest

from sheetkit import validators
from sheetkit.errors import (
    CorruptFileError,
    FileAccessError,
    FileNotFoundError_,
    SheetNotFoundError,
    UnsupportedFormatError,
    ValidationError,
)
from sheetkit.reader import _guess_csv_encoding, profile_file, read_table


def inject_cached_value(path: str, cell_ref: str, cached: str) -> None:
    """Give a formula cell the cached result Excel would have stored."""
    folder = os.path.dirname(path) or '.'
    staging = os.path.join(folder, '_patch')
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(path) as archive:
        archive.extractall(staging)

    sheet_path = os.path.join(staging, 'xl', 'worksheets', 'sheet1.xml')
    with open(sheet_path, encoding='utf-8') as handle:
        xml = handle.read()

    pattern = re.compile(rf'(<c r="{cell_ref}"[^>]*>)(<f>.*?</f>)(.*?)(</c>)')
    match = pattern.search(xml)
    assert match, f'formula cell {cell_ref} not found in {xml[:400]}'
    replacement = f'{match.group(1)}{match.group(2)}<v>{cached}</v>{match.group(4)}'
    xml = xml[: match.start()] + replacement + xml[match.end() :]

    with open(sheet_path, 'w', encoding='utf-8') as handle:
        handle.write(xml)

    os.remove(path)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(staging):
            for name in files:
                full = os.path.join(root, name)
                archive.write(full, os.path.relpath(full, staging).replace(os.sep, '/'))
    shutil.rmtree(staging, ignore_errors=True)


def test_reads_columns_rows_and_source_row_numbers(xlsx):
    path = xlsx('a.xlsx', ['编码', '名称', '数量'], [['00123', '甲', 5], ['00456', '乙', 7]])
    table = read_table(path)
    assert table.columns == ['编码', '名称', '数量']
    assert table.rows == [['00123', '甲', 5], ['00456', '乙', 7]]
    # Row 1 is the header, so data starts at source row 2.
    assert table.row_numbers == [2, 3]
    assert table.sheet == '数据'


def test_leading_zeros_and_long_numbers_are_not_coerced(xlsx):
    path = xlsx(
        'codes.xlsx',
        ['物料编码', '订单编号', '电话'],
        [['00123', '9007199254740993', '13800001111']],
    )
    row = read_table(path).rows[0]
    assert row[0] == '00123'
    assert row[1] == '9007199254740993'
    assert row[2] == '13800001111'


def test_header_row_offset(xlsx):
    path = xlsx(
        'titled.xlsx',
        ['编码', '数量'],
        [['00123', 5]],
        preamble_rows=[['某公司出货表'], ['制表人：张三']],
    )
    table = read_table(path, header_row=3)
    assert table.columns == ['编码', '数量']
    assert table.rows == [['00123', 5]]
    assert table.row_numbers == [4]


def test_header_row_beyond_file_raises(xlsx):
    path = xlsx('small.xlsx', ['编码'], [['00123']])
    with pytest.raises(ValidationError, match='表头行'):
        read_table(path, header_row=99)


def test_sheet_selection_and_missing_sheet(xlsx):
    path = xlsx(
        'multi.xlsx',
        ['编码'],
        [['00123']],
        sheet='一月',
        extra_sheets={'二月': (['编码'], [['00456']])},
    )
    assert read_table(path, sheet='二月').rows == [['00456']]
    with pytest.raises(SheetNotFoundError, match='三月'):
        read_table(path, sheet='三月')
    profile = profile_file(path)
    assert [item.name for item in profile.sheets] == ['一月', '二月']


def test_blank_rows_dropped_by_default_and_kept_on_request(xlsx):
    path = xlsx('blanks.xlsx', ['编码', '数量'], [['00123', 5], [None, None], ['00456', 7]])
    assert read_table(path).row_count == 2
    kept = read_table(path, keep_blank_rows=True)
    assert kept.row_count == 3
    assert kept.blank_rows == 1


def test_duplicate_and_empty_header_names_are_made_unique(xlsx):
    path = xlsx('heads.xlsx', ['备注', '备注', None], [['a', 'b', 'c']])
    assert read_table(path).columns == ['备注', '备注_2', '未命名列']


def test_data_row_wider_than_header_labels_gets_placeholder_column(xlsx):
    # openpyxl pads the header row out to the sheet width, so the extra column
    # surfaces as an unnamed header rather than as a ragged row.
    path = xlsx('wide.xlsx', ['a', 'b'], [['1', '2', '3']])
    table = read_table(path)
    assert table.columns == ['a', 'b', '未命名列']
    assert table.rows == [['1', '2', '3']]


def test_csv_row_wider_than_header_is_reported(csv_file):
    path = csv_file('wide.csv', ['a', 'b'], [['1', '2', '3']])
    table = read_table(path)
    assert table.columns == ['a', 'b', '未命名列']
    assert table.rows == [['1', '2', '3']]
    assert any('超出表头列数' in item for item in table.warnings)


def test_formula_uses_cached_value(xlsx):
    path = xlsx('calc.xlsx', ['数量', '单价', '金额'], [[2, 3, '=B2*C2']])
    inject_cached_value(path, 'C2', '6')
    table = read_table(path)
    assert table.rows[0][2] == 6
    assert table.formula_cells == 1
    assert table.uncached_formula_cells == 0
    assert any('公式单元格' in item for item in table.warnings)


def test_formula_without_cached_value_is_reported_not_silently_empty(xlsx):
    path = xlsx('nocalc.xlsx', ['数量', '金额'], [[2, '=A2*10']])
    table = read_table(path)
    assert table.rows[0][1] is None
    assert table.uncached_formula_cells == 1
    assert any('没有缓存结果' in item for item in table.warnings)


def test_macro_workbook_is_read_as_data_only(xlsx):
    # An .xlsm is a normal zip workbook; renaming is enough to exercise the path.
    path = xlsx('macro.xlsx', ['编码'], [['00123']])
    macro_path = os.path.join(os.path.dirname(path), 'macro.xlsm')
    shutil.copyfile(path, macro_path)
    table = read_table(macro_path)
    assert table.rows == [['00123']]
    assert any('宏' in item for item in table.warnings)
    assert profile_file(macro_path).has_macros


@pytest.mark.parametrize(
    'written,detected',
    [
        ('utf-8-sig', 'utf-8-sig'),
        # BOM-less UTF-8 also decodes cleanly as utf-8-sig, which is tried first.
        ('utf-8', 'utf-8-sig'),
        ('gb18030', 'gb18030'),
        ('big5', 'big5'),
    ],
)
def test_csv_encoding_detection(csv_file, written, detected):
    # Traditional characters: Big5 cannot encode the simplified forms, and
    # GB18030/UTF-8 handle both.
    path = csv_file(
        f'data-{written}.csv',
        ['物料編碼', '品名'],
        [['00123', '中文品名']],
        encoding=written,
    )
    table = read_table(path)
    assert table.columns == ['物料編碼', '品名']
    assert table.rows == [['00123', '中文品名']]
    assert table.encoding == detected


def test_big5_is_not_swallowed_by_gb18030(csv_file):
    # Every valid Big5 sequence is also valid GB18030, so a fixed candidate
    # order can never reach Big5 and a traditional Chinese file turns to junk.
    path = csv_file('trad.csv', ['物料編碼'], [['中文品名']], encoding='big5')
    table = read_table(path)
    assert table.encoding == 'big5'
    assert table.rows == [['中文品名']]
    assert any('编码识别为 big5' in item for item in table.warnings)


def test_encoding_guess_survives_a_split_multibyte_tail():
    # The detection sample is cut at a byte cap, which can land in the middle
    # of a multi-byte character. That must not push UTF-8 onto GB18030.
    payload = ('物料编码,品名\r\n' * 20000 + '中').encode('utf-8')
    truncated = payload[:-1]
    with pytest.raises(UnicodeDecodeError):
        truncated.decode('utf-8')
    assert _guess_csv_encoding(truncated) == 'utf-8-sig'


def test_undetectable_csv_falls_back_with_a_warning(tmp_path):
    # 0x81 followed by a newline is invalid in UTF-8, GB18030, Big5 and CP1252.
    path = tmp_path / 'odd.csv'
    path.write_bytes(b'a,b\r\n1,\x81\r\n')
    table = read_table(str(path))
    assert table.encoding == 'latin-1'
    assert any('Latin-1' in item for item in table.warnings)


def test_csv_keeps_text_types_and_leading_zeros(csv_file):
    path = csv_file('codes.csv', ['编码', '长号'], [['00123', '9007199254740993']])
    table = read_table(path)
    assert table.rows == [['00123', '9007199254740993']]
    assert any('按文本读取' in item for item in table.warnings)


def test_csv_semicolon_delimiter_is_detected(csv_file):
    path = csv_file('semi.csv', ['编码', '数量'], [['00123', '5']], delimiter=';')
    table = read_table(path)
    assert table.columns == ['编码', '数量']
    assert table.delimiter == ';'


def test_csv_empty_cell_becomes_none(csv_file):
    path = csv_file('empty.csv', ['a', 'b'], [['1', '']])
    assert read_table(path).rows == [['1', None]]


def test_preview_limit_truncates(xlsx):
    path = xlsx('big.xlsx', ['n'], [[i] for i in range(500)])
    table = read_table(path, limit=50)
    assert table.row_count == 50
    assert table.truncated is True
    assert read_table(path).truncated is False


def test_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError_):
        read_table(str(tmp_path / 'nope.xlsx'))


def test_rejects_directory(tmp_path):
    with pytest.raises(ValidationError, match='文件夹'):
        read_table(str(tmp_path))


@pytest.mark.parametrize(
    'name,message',
    [
        ('legacy.xls', '旧版 .xls'),
        ('binary.xlsb', '.xlsb'),
        ('wps.et', 'WPS 专有'),
        ('notes.docx', '不支持的文件类型'),
    ],
)
def test_rejects_unsupported_extensions(tmp_path, name, message):
    path = tmp_path / name
    path.write_bytes(b'not a workbook')
    with pytest.raises(UnsupportedFormatError, match=re.escape(message)):
        read_table(str(path))


def test_rejects_corrupt_xlsx(tmp_path):
    path = tmp_path / 'broken.xlsx'
    path.write_bytes(b'this is not a zip archive')
    with pytest.raises(CorruptFileError):
        read_table(str(path))


def test_locked_file_reports_occupied(xlsx, exclusive_lock):
    path = xlsx('locked.xlsx', ['编码'], [['00123']])
    exclusive_lock(path)
    with pytest.raises(FileAccessError, match='占用'):
        read_table(path)


def test_lock_marker_produces_warning(xlsx, lock_marker):
    path = xlsx('open.xlsx', ['编码'], [['00123']])
    lock_marker(path)
    assert validators.is_likely_open_elsewhere(path)
    assert any('可能正被' in item for item in read_table(path).warnings)
    assert profile_file(path).maybe_open_elsewhere


def test_dates_are_read_as_dates(xlsx):
    path = xlsx('dates.xlsx', ['日期'], [[dt.datetime(2024, 3, 15)]])
    assert read_table(path).rows[0][0] == dt.datetime(2024, 3, 15)


def test_mixed_text_and_number_column_keeps_both_types(xlsx):
    path = xlsx('mixed.xlsx', ['值'], [['00123'], [123], [12.5]])
    rows = read_table(path).rows
    assert [type(row[0]).__name__ for row in rows] == ['str', 'int', 'float']

"""Input validation and path safety.

The desktop bridge is the only caller, but every argument still crosses a
process-language boundary, so nothing is trusted: operation names come from a
fixed whitelist, paths must resolve to real readable files, and an output path
may never be one of the inputs.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Sequence

from .errors import (
    FileAccessError,
    FileNotFoundError_,
    OutputConflictError,
    UnsupportedFormatError,
    ValidationError,
)

READABLE_EXTS: dict[str, str] = {
    '.xlsx': 'xlsx',
    '.xlsm': 'xlsm',
    '.csv': 'csv',
    '.txt': 'csv',
}

BLOCKED_EXTS: dict[str, str] = {
    '.xls': '旧版 .xls (BIFF) 格式不受支持，请在 Excel/WPS 中另存为 .xlsx 后重试',
    '.xlsb': '.xlsb 二进制格式不受支持，请另存为 .xlsx 后重试',
    '.xltx': '模板文件 .xltx 不受支持，请另存为 .xlsx 后重试',
    '.xltm': '模板文件 .xltm 不受支持，请另存为 .xlsx 后重试',
    '.et': 'WPS 专有 .et 格式不受支持，请在 WPS 中另存为 .xlsx 后重试',
}

EXPORT_EXT = '.xlsx'

MAX_TEXT_ARG = 4096
MAX_COLUMN_SELECTION = 400
MAX_FILE_BATCH = 500


def _clean_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f'{label} 必须是文本')
    text = value.strip()
    if len(text) > MAX_TEXT_ARG:
        raise ValidationError(f'{label} 过长')
    if '\x00' in text:
        raise ValidationError(f'{label} 含有非法字符')
    return text


def require_text(value: Any, label: str) -> str:
    text = _clean_text(value, label)
    if not text:
        raise ValidationError(f'{label} 不能为空')
    return text


def require_bool(value: Any, label: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValidationError(f'{label} 必须是布尔值')


def require_int(value: Any, label: str, *, minimum: int, maximum: int, default: int | None = None) -> int:
    if value is None or value == '':
        if default is None:
            raise ValidationError(f'{label} 不能为空')
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f'{label} 必须是整数') from None
    if not minimum <= number <= maximum:
        raise ValidationError(f'{label} 必须在 {minimum} 到 {maximum} 之间')
    return number


def require_str_list(value: Any, label: str, *, max_items: int = MAX_COLUMN_SELECTION) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f'{label} 必须是列表')
    if len(value) > max_items:
        raise ValidationError(f'{label} 数量超过上限 {max_items}')
    return [_clean_text(item, label) for item in value]


def detect_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in BLOCKED_EXTS:
        raise UnsupportedFormatError(BLOCKED_EXTS[ext], detail=path)
    kind = READABLE_EXTS.get(ext)
    if kind is None:
        raise UnsupportedFormatError(
            f'不支持的文件类型 {ext or "(无扩展名)"}，仅支持 .xlsx / .xlsm / .csv',
            detail=path,
        )
    return kind


def _has_lock_marker(path: str) -> bool:
    """Excel and WPS create a "~$name.xlsx" owner file while a workbook is open."""
    folder, name = os.path.split(path)
    try:
        return os.path.exists(os.path.join(folder, '~$' + name))
    except OSError:
        return False


def open_input(value: Any, *, label: str = '文件') -> tuple[str, str]:
    """Validate an input file and return (absolute path, kind).

    `kind` is one of 'xlsx' | 'xlsm' | 'csv'. Raises a specific SheetKitError so
    the UI can tell "missing", "locked", "unsupported format" and "invalid"
    apart instead of showing a generic failure.
    """
    raw = require_text(value, label + '路径')
    path = os.path.normpath(os.path.abspath(raw))

    if not os.path.exists(path):
        raise FileNotFoundError_(f'{label}不存在：{os.path.basename(path)}', detail=path)
    if os.path.isdir(path):
        raise ValidationError(f'{label}是一个文件夹，请选择文件', detail=path)

    kind = detect_kind(path)

    try:
        with open(path, 'rb'):
            pass
    except PermissionError as exc:
        raise FileAccessError(
            f'{label}无法读取，可能正被 Excel/WPS 占用或没有访问权限',
            detail=path,
        ) from exc
    except OSError as exc:
        raise FileAccessError(f'{label}读取失败：{exc.strerror or exc}', detail=path) from exc

    return path, kind


def is_likely_open_elsewhere(path: str) -> bool:
    """Excel/WPS leave a "~$name.xlsx" owner file while a workbook is open."""
    return _has_lock_marker(path)


def validate_output_path(
    value: Any,
    input_paths: Iterable[str],
    *,
    label: str = '输出文件',
) -> str:
    """Return a safe destination path, refusing to overwrite any input."""
    raw = require_text(value, label + '路径')
    out = os.path.normpath(os.path.abspath(raw))

    if os.path.isdir(out):
        raise OutputConflictError(f'{label}路径是一个文件夹', detail=out)
    ext = os.path.splitext(out)[1].lower()
    if ext != EXPORT_EXT:
        raise UnsupportedFormatError(
            f'{label}必须是 .xlsx 文件，当前为 {ext or "(无扩展名)"}', detail=out
        )

    inputs = {os.path.normcase(os.path.abspath(p)) for p in input_paths if p}
    if os.path.normcase(out) in inputs:
        raise OutputConflictError(
            '输出文件不能与输入文件相同，为避免破坏原始数据已阻止本次导出', detail=out
        )

    for candidate in inputs:
        try:
            if os.path.exists(out) and os.path.exists(candidate) and os.path.samefile(out, candidate):
                raise OutputConflictError(
                    '输出文件与某个输入文件指向同一份数据，已阻止本次导出', detail=out
                )
        except OSError:
            continue

    folder = os.path.dirname(out)
    if not folder or not os.path.isdir(folder):
        raise OutputConflictError(f'{label}所在文件夹不存在', detail=out)
    if not os.access(folder, os.W_OK):
        raise FileAccessError(f'{label}所在文件夹不可写', detail=folder)

    return out


def validate_sheet(value: Any, available: Sequence[str], *, label: str = '工作表') -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    name = _clean_text(value, label)
    if name not in available:
        raise ValidationError(
            f'{label} "{name}" 不存在，可选：{", ".join(available) or "(无)"}',
        )
    return name


def validate_columns(
    selected: Iterable[str],
    available: Sequence[str],
    *,
    label: str = '字段',
    allow_empty: bool = True,
) -> list[str]:
    chosen = list(dict.fromkeys(selected))
    if not chosen:
        if allow_empty:
            return []
        raise ValidationError(f'请至少选择一个{label}')
    missing = [name for name in chosen if name not in available]
    if missing:
        raise ValidationError(
            f'{label}不存在于当前表格：{", ".join(missing[:8])}'
            + ('…' if len(missing) > 8 else ''),
        )
    return chosen


def validate_key_columns(
    keys: Iterable[str], available: Sequence[str], *, label: str = '匹配字段'
) -> list[str]:
    """Key columns must exist, be unique and non-empty."""
    chosen = list(keys)
    if not chosen:
        raise ValidationError(f'请至少选择一个{label}')
    if len(chosen) > 12:
        raise ValidationError(f'{label}最多支持 12 个')
    duplicates = {name for name in chosen if chosen.count(name) > 1}
    if duplicates:
        raise ValidationError(f'{label}存在重复项：{", ".join(sorted(duplicates))}')
    return validate_columns(chosen, available, label=label, allow_empty=False)


def validate_common_columns(
    keys: Sequence[str],
    old_columns: Sequence[str],
    new_columns: Sequence[str],
    *,
    label: str = '匹配字段',
) -> list[str]:
    """Keys must exist on both sides, otherwise matching would be meaningless."""
    missing_old = [k for k in keys if k not in old_columns]
    missing_new = [k for k in keys if k not in new_columns]
    problems = []
    if missing_old:
        problems.append('旧版缺少 ' + ', '.join(missing_old))
    if missing_new:
        problems.append('新版缺少 ' + ', '.join(missing_new))
    if problems:
        raise ValidationError(
            f'{label}在两个文件中不一致：' + '；'.join(problems),
        )
    return list(keys)


def validate_action(action: Any, allowed: Sequence[str]) -> str:
    name = require_text(action, '操作名称')
    if name not in allowed:
        raise ValidationError(f'不支持的操作：{name}')
    return name


def validate_file_batch(paths: Any, *, label: str = '文件列表') -> list[str]:
    if not isinstance(paths, (list, tuple)):
        raise ValidationError(f'{label}必须是列表')
    if not paths:
        raise ValidationError(f'{label}不能为空')
    if len(paths) > MAX_FILE_BATCH:
        raise ValidationError(f'{label}最多支持 {MAX_FILE_BATCH} 个文件')
    unique: list[str] = []
    seen: set[str] = set()
    for item in paths:
        path, _kind = open_input(item, label=label)
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique

"""Persist user-named column rules in the current Windows profile."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .errors import ValidationError

KINDS = ('merge', 'clean')


def _config_file() -> Path:
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / '.config') / 'SheetKit' / 'templates.json'


def _field(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 1024


def _rule(kind: str, value: object) -> bool:
    if kind == 'merge' and isinstance(value, dict):
        return 0 < len(value) <= 2048 and all(_field(k) and _field(v) for k, v in value.items())
    if kind == 'clean' and isinstance(value, list):
        return 0 < len(value) <= 2048 and all(_field(v) for v in value) and len(value) == len(set(value))
    return False


def load_templates() -> dict:
    path = _config_file()
    try:
        with path.open(encoding='utf-8') as handle:
            loaded = json.load(handle)
    except FileNotFoundError:
        return {kind: {} for kind in KINDS}
    except (OSError, ValueError) as exc:
        raise ValidationError('无法读取本地模板配置，请检查 SheetKit 的配置文件') from exc
    if not isinstance(loaded, dict) or any(
        not isinstance(loaded.get(kind), dict)
        or any(not _field(name) or not _rule(kind, rule) for name, rule in loaded[kind].items())
        for kind in KINDS
    ):
        raise ValidationError('本地模板配置格式有误，请检查 SheetKit 的配置文件')
    return loaded


def save_template(kind: str, name: object, rule: object) -> None:
    if kind not in KINDS or not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise ValidationError('请输入 1 至 60 个字符的模板名称')
    if not _rule(kind, rule):
        raise ValidationError('请先设置字段对应关系或选择输出列')
    templates = load_templates()
    bucket = templates[kind]
    name = name.strip()
    if name not in bucket and len(bucket) >= 50:
        raise ValidationError('最多保存 50 个此类模板')
    bucket[name] = rule
    path = _config_file()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(templates, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    except OSError as exc:
        raise ValidationError('无法保存模板，请检查本地配置目录的写入权限') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

"""The desktop shell.

A pywebview window renders the built frontend. The frontend is a single
inlined HTML file that is loaded through WebView2's NavigateToString, so the
app never opens an HTTP port and never listens on the network.

The shell also owns the one thing the page cannot do for itself: turning a
native drag-and-drop into a real filesystem path.
"""

from __future__ import annotations

import json
import ctypes
import os
import sys

from . import APP_TITLE
from .api import SheetKitApi

WEBUI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webui')
INDEX_HTML = os.path.join(WEBUI_DIR, 'index.html')

WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 720
MIN_WIDTH = 700
MIN_HEIGHT = 480


class ShellError(RuntimeError):
    pass


def load_index() -> str:
    """Read the built frontend, or explain how to build it."""
    if not os.path.isfile(INDEX_HTML):
        raise ShellError(
            '找不到前端文件。请先在 frontend 目录执行 npm install 和 npm run build。'
        )
    with open(INDEX_HTML, encoding='utf-8') as handle:
        return handle.read()


def _register_drop_target(window) -> None:
    """Turn a native drop into a list of real file paths."""
    from webview.dom import DOMEventHandler

    def on_drop(event: dict) -> None:
        files = (event.get('dataTransfer') or {}).get('files') or []
        paths = [
            item.get('pywebviewFullPath')
            for item in files
            if isinstance(item, dict) and item.get('pywebviewFullPath')
        ]
        if not paths:
            return
        payload = json.dumps(paths, ensure_ascii=False)
        try:
            window.evaluate_js(f'window.sheetkitDrop && window.sheetkitDrop({payload})')
        except Exception:  # noqa: BLE001 - a failed hand-off must not kill the app
            pass

    window.dom.body.on('drop', DOMEventHandler(on_drop, prevent_default=True))


def run() -> int:
    import webview
    from webview.platforms import winforms

    if not winforms.is_chromium:
        raise ShellError('需要 Microsoft Edge WebView2 Runtime。请从微软官网下载并安装 Evergreen Runtime，然后重新打开 SheetKit。')

    html = load_index()
    api = SheetKitApi()

    window = webview.create_window(
        APP_TITLE,
        html=html,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        text_select=True,
        confirm_close=False,
    )
    api._attach(window)

    def on_loaded() -> None:
        try:
            _register_drop_target(window)
        except Exception:  # noqa: BLE001 - drag and drop is optional
            pass

    def on_closing() -> None:
        api.shutdown()

    window.events.loaded += on_loaded
    window.events.closing += on_closing

    # No http_server: the page is inlined, so nothing is served over the network.
    webview.start(gui='edgechromium', http_server=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run()
    except ShellError as exc:
        print(f'启动失败：{exc}', file=sys.stderr)
        if sys.platform == 'win32':
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'SheetKit 启动失败', 0x10)
        return 2

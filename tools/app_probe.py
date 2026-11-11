"""End-to-end probe for the desktop shell.

Launches the real window with the built frontend and checks that the page
renders, every route works, the theme switches, a real comparison runs through
the bridge and no network server was started.

    .venv\\Scripts\\python.exe tools\\app_probe.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python'))

from sheetkit.api import SheetKitApi  # noqa: E402
from sheetkit.shell import APP_TITLE, _register_drop_target, load_index  # noqa: E402

results: dict = {}
finished = threading.Event()

OLD_SAMPLE = os.path.join(ROOT, 'tools', '_probe_old.xlsx')
NEW_SAMPLE = os.path.join(ROOT, 'tools', '_probe_new.xlsx')


def write_samples() -> None:
    from openpyxl import Workbook

    def dump(path: str, rows: list[list]) -> None:
        book = Workbook()
        sheet = book.active
        sheet.title = '数据'
        sheet.append(['物料编码', '品名', '数量'])
        for row in rows:
            sheet.append(row)
        book.save(path)

    dump(OLD_SAMPLE, [['00123', '甲', 5], ['00124', '乙', 7]])
    dump(NEW_SAMPLE, [['00123', '甲', 5], ['00124', '乙二', 9], ['00125', '丙', 1]])


def main() -> int:
    import webview

    write_samples()
    html = load_index()
    api = SheetKitApi()

    window = webview.create_window(
        APP_TITLE,
        html=html,
        js_api=api,
        width=1100,
        height=720,
        min_size=(880, 560),
        resizable=True,
    )
    api._attach(window)

    def on_loaded() -> None:
        try:
            from webview.dom import _dnd_state

            # The shell must have wired the native drop handler; without it a
            # file dragged onto the window could not be turned into a path.
            _register_drop_target(window)
            results['drop_listener_registered'] = _dnd_state['num_listeners'] > 0

            results['document_title'] = window.evaluate_js('document.title')
            results['app_mounted'] = bool(
                window.evaluate_js(
                    "!!(document.querySelector('#app') && document.querySelector('#app').children.length)"
                )
            )
            results['home_cards'] = window.evaluate_js(
                "Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('开始处理')).length"
            )
            results['nav_items'] = window.evaluate_js(
                "Array.from(document.querySelectorAll('nav a')).map(a => a.textContent.trim())"
            )
            results['location'] = window.evaluate_js('location.href')
            results['protocol'] = window.evaluate_js('location.protocol')

            # Catch anything that throws while the routes are visited.
            window.evaluate_js(
                "window.__errors = [];"
                "window.addEventListener('error', function (e) { window.__errors.push(String(e.message)); });"
                "window.addEventListener('unhandledrejection', function (e) { window.__errors.push(String(e.reason)); });"
            )

            for route, heading in (
                ('#/compare', '表格对比'),
                ('#/merge', '批量合并'),
                ('#/clean', '数据清洗'),
                ('#/', 'SheetKit 表格效率助手'),
            ):
                window.evaluate_js(f"location.hash = '{route}'")
                time.sleep(0.6)
                results[f'heading_{route}'] = window.evaluate_js(
                    "var h = document.querySelector('main h1'); h ? h.textContent.trim() : null"
                )
                results[f'route_ok_{route}'] = results[f'heading_{route}'] == heading

            # The theme toggle must switch the palette.
            window.evaluate_js("document.querySelector('aside button').click()")
            time.sleep(0.3)
            results['theme_after_toggle'] = window.evaluate_js(
                "document.documentElement.className"
            )
            window.evaluate_js("document.querySelector('aside button').click()")
            time.sleep(0.2)

            # A real comparison has to run through the bridge and come back
            # with a usable preview.
            window.evaluate_js(
                "window.pywebview.api.analyze({action:'compare', old_path:'"
                + OLD_SAMPLE.replace('\\', '\\\\')
                + "', new_path:'"
                + NEW_SAMPLE.replace('\\', '\\\\')
                + "', keys:['物料编码']}).then(function (r) { window.__probe = r })"
            )
            for _ in range(80):
                if window.evaluate_js('window.__probe !== undefined'):
                    break
                time.sleep(0.1)

            probe = window.evaluate_js('JSON.stringify(window.__probe || null)')
            payload = json.loads(probe) if probe and probe != 'null' else None
            results['compare_ok'] = bool(payload and payload.get('ok'))
            if payload and payload.get('ok'):
                results['compare_summary'] = {
                    'added': payload['summary']['added'],
                    'deleted': payload['summary']['deleted'],
                    'modified_rows': payload['summary']['modified_rows'],
                }
                results['compare_preview_rows'] = len(
                    payload['preview']['changed']['rows']
                )
            else:
                results['compare_error'] = payload.get('error') if payload else 'no response'

            results['js_errors'] = window.evaluate_js('JSON.stringify(window.__errors || [])')
        except Exception as exc:  # noqa: BLE001 - the probe must report, never crash
            results['error'] = repr(exc)
        finally:
            window.destroy()

    window.events.loaded += on_loaded
    webview.start(http_server=False)
    finished.wait(45)
    print('PROBE_RESULTS ' + json.dumps(results, ensure_ascii=False, default=str), flush=True)

    ok = (
        results.get('app_mounted')
        and results.get('compare_ok')
        and not results.get('js_errors')
        and all(
            results.get(f'route_ok_{route}')
            for route in ('#/compare', '#/merge', '#/clean', '#/')
        )
    )
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

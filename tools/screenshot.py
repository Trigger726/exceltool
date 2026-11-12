"""Launches SheetKit on a given route and captures the window to a PNG.

    .venv\\Scripts\\python.exe tools\\screenshot.py #/compare tools\\_compare.png

Used to eyeball the real interface instead of guessing from the markup.

The capture sequence runs on a worker thread: the loaded callback fires on the
GUI thread, and sleeping there would stall the message pump, so the page would
never finish rendering.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python'))

from sheetkit.api import SheetKitApi  # noqa: E402
from sheetkit.shell import APP_TITLE, load_index  # noqa: E402


def capture_window(output: str) -> None:
    result = subprocess.run(
        [
            'powershell',
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-File',
            os.path.join(ROOT, 'tools', 'capture.ps1'),
            '-Output',
            output,
            '-ProcessName',
            'python',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors='replace',
    )
    print((result.stdout or '').strip(), flush=True)


def main() -> int:
    # Git Bash rewrites arguments that look like absolute paths, so "#/compare"
    # can arrive as "D:/DevTools/Git/compare". The route is accepted without
    # its leading slash and rebuilt here.
    raw = sys.argv[1] if len(sys.argv) > 1 else 'home'
    if raw.startswith('#'):
        route = raw
    elif raw in ('home', '/'):
        route = '#/'
    else:
        route = '#/' + raw.lstrip('/')
    output = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, 'tools', '_shot.png')

    import webview

    api = SheetKitApi()
    window = webview.create_window(
        APP_TITLE,
        html=load_index(),
        js_api=api,
        width=1100,
        height=720,
        min_size=(880, 560),
        resizable=True,
    )
    api._attach(window)

    def on_loaded() -> None:
        # The navigation and the check run on the GUI thread, because
        # evaluate_js pumps the message queue and lets the page render.
        for _ in range(60):
            settled = window.evaluate_js(
                "var h = document.querySelector('main h1'); h ? h.textContent.trim() : ''"
            )
            if settled:
                break
        # Let the router finish settling: each evaluate_js pumps the UI thread
        # and gives the page a chance to install its route handlers.
        for _ in range(8):
            window.evaluate_js('1')
            time.sleep(0.25)
        # The router may still be settling, so the route is requested until
        # the heading actually changes. Setting the hash only raises the
        # event; the page needs the message queue pumped before it re-renders,
        # and setting the same hash again would not raise a second event.
        heading = ''
        for _ in range(10):
            window.evaluate_js(f"location.hash = '{route}'")
            time.sleep(0.8)
            window.evaluate_js('1')
            time.sleep(0.6)
            heading = window.evaluate_js(
                "var h = document.querySelector('main h1'); h ? h.textContent.trim() : ''"
            )
            if heading and heading != '想怎么处理表格？':
                break
        print(f'HEADING {heading or "(none)"}', flush=True)

        def finish() -> None:
            capture_window(output)
            window.destroy()

        # The capture runs off the GUI thread so the window can paint.
        threading.Thread(target=finish, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(http_server=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())

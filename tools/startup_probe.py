"""Startup timing for SheetKit.

Measures how long the app takes to show its window, both from source and from
the packaged build.

The window is matched by its title rather than by the process id: a virtual
environment's python.exe re-executes the base interpreter, so the visible
window belongs to a child process. Killing is done through taskkill so the
whole tree goes away.

    .venv\\Scripts\\python.exe tools\\startup_probe.py
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
PACKAGED = os.path.join(ROOT, 'dist', 'SheetKit.exe')
TITLE = 'SheetKit'

user32 = ctypes.windll.user32
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_visible_titles() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            found.append((owner.value, buffer.value))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return found


def wait_for_window(timeout: float = 60.0) -> float | None:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        for _pid, title in find_visible_titles():
            if title.startswith(TITLE):
                return time.perf_counter() - started
        time.sleep(0.05)
    return None


def kill_tree(process: subprocess.Popen) -> None:
    subprocess.run(
        ['taskkill', '/T', '/F', '/PID', str(process.pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def run(label: str, command: list[str], cwd: str) -> float | None:
    process = subprocess.Popen(
        command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        return wait_for_window()
    finally:
        kill_tree(process)


def main() -> int:
    print('measuring startup...', flush=True)

    source = run('source', [PYTHON, os.path.join(ROOT, 'python', 'main.py')], ROOT)
    print(f'from source      : {source:.2f}s' if source else 'from source      : failed')

    if os.path.isfile(PACKAGED):
        packaged = run('packaged', [PACKAGED], os.path.dirname(PACKAGED))
        print(f'packaged build   : {packaged:.2f}s' if packaged else 'packaged build   : failed')
    else:
        print('packaged build   : not built (run build.bat first)')

    return 0 if source else 1


if __name__ == '__main__':
    sys.exit(main())

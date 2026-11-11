r"""Verify the single EXE in a disposable directory with real Windows dialogs.

The probe requires pywinauto in the developer environment. The EXE has no such
dependency. Run: .venv\Scripts\python.exe -X utf8 tools\packaged_probe.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from openpyxl import load_workbook
from pywinauto import Desktop, mouse

from app_probe import ROOT, workbook


def eventually(check, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.15)
    raise AssertionError('Timed out: ' + repr(check))


def select_path(pid, path, saving=False):
    desktop = Desktop(backend='win32')
    pattern = r'另存为|保存.*|Save.*' if saving else r'打开|Open'
    dialog = desktop.window(process=pid, class_name='#32770', title_re=pattern)
    dialog.wait('visible ready', timeout=15)
    filename = dialog.child_window(class_name='Edit', control_id=1001 if saving else 1148)
    filename.set_edit_text(str(path))
    filename.set_focus()
    filename.type_keys('{ENTER}')


def drag_file(app, path):
    """Use a Windows OLE file drag, with a disposable WinForms drag source."""
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object Windows.Forms.Form
$form.Text = 'SheetKit drag fixture'
$form.StartPosition = 'Manual'
$form.Location = New-Object Drawing.Point(5, 40)
$form.Size = New-Object Drawing.Size(180, 100)
$form.TopMost = $true
$button = New-Object Windows.Forms.Button
$button.Text = 'Drag file'
$button.Dock = 'Fill'
$button.Add_MouseDown({
    $files = New-Object Collections.Specialized.StringCollection
    [void]$files.Add($env:SHEETKIT_PROBE_DRAG_FILE)
    $data = New-Object Windows.Forms.DataObject
    $data.SetFileDropList($files)
    [void]$button.DoDragDrop($data, [Windows.Forms.DragDropEffects]::Copy)
})
$form.Controls.Add($button)
[void]$form.ShowDialog()
"""
    desktop = Desktop(backend='win32')
    process = subprocess.Popen(
        ['powershell', '-NoProfile', '-STA', '-Command', script],
        env=dict(os.environ, SHEETKIT_PROBE_DRAG_FILE=str(path)),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    fixture = desktop.window(process=process.pid, title='SheetKit drag fixture')
    try:
        fixture.wait('ready', timeout=15)
        start = fixture.child_window(title='Drag file').rectangle().mid_point()
        finish = app.rectangle().mid_point()
        mouse.move(coords=(start.x, start.y))
        mouse.press(coords=(start.x, start.y))
        try:
            time.sleep(0.3)
            mouse.move(coords=(finish.x, finish.y))
            time.sleep(0.4)
        finally:
            mouse.release(coords=(finish.x, finish.y))
        app.child_window(title=path.name, control_type='Text').wait('visible', timeout=15)
    finally:
        if fixture.exists(timeout=1):
            fixture.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()



def listening_ports(pid):
    script = 'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress'
    raw = subprocess.check_output(['powershell', '-NoProfile', '-Command', script], text=True)
    owners = {pid}
    processes = json.loads(raw)
    while True:
        discovered = {entry['ProcessId'] for entry in processes if entry['ParentProcessId'] in owners}
        if discovered <= owners:
            break
        owners.update(discovered)
    raw = subprocess.check_output(['netstat', '-ano', '-p', 'tcp'], text=True, errors='replace')
    return [line.split()[1] for line in raw.splitlines()
            if 'LISTENING' in line and int(line.split()[-1]) in owners]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix='sheetkit-exe-', ignore_cleanup_errors=True) as temp:
        folder = Path(temp)
        exe = folder / 'SheetKit.exe'
        shutil.copy2(ROOT / 'dist' / exe.name, exe)
        data = folder / '台账.xlsx'
        output = folder / '清洗结果.xlsx'
        workbook(data, [['订单号', '名称', '数量'], ['00012', '甲', 2], ['00013', '乙', 3]])

        env = {key: val for key, val in os.environ.items()
               if key not in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV')}
        env.update({
            'PATH': os.path.join(os.environ['SystemRoot'], 'System32'),
            'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': '--force-renderer-accessibility',
        })
        process = subprocess.Popen([str(exe)], cwd=folder, env=env)
        app = Desktop(backend='uia').window(title='SheetKit 表格效率助手')
        try:
            app.wait('visible', timeout=30)
            app.child_window(title='数据清洗', control_type='Hyperlink').wait('ready', timeout=20).invoke()
            app.child_window(title='选择文件', control_type='Button').wait('ready', timeout=20).invoke()
            pid = app.process_id()
            select_path(pid, data)
            app.child_window(title='开始清洗', control_type='Button').wait('ready', timeout=20).invoke()
            app.child_window(title='导出文件', control_type='Button').wait('ready', timeout=20).invoke()
            select_path(pid, output, saving=True)
            eventually(output.is_file)
            report = load_workbook(output, read_only=True)
            try:
                rows = list(report['清洗结果'].values)
                assert [row[0] for row in rows] == ['订单号', '00012', '00013']
            finally:
                report.close()
            app.child_window(title='批量合并', control_type='Hyperlink').wait('ready', timeout=15).invoke()
            app.child_window(title='添加文件', control_type='Button').wait('ready', timeout=15)
            drag_file(app, data)
            ports = listening_ports(process.pid)
            assert not ports, ports
            print('PACKAGED_PROBE ' + json.dumps({
                'isolated_exe': True,
                'native_open_and_save': True,
                'native_drop_merge': True,
                'clean_export_rows': len(rows) - 1,
                'leading_zero_preserved': True,
                'listening_tcp_ports': ports,
                'exe_bytes': exe.stat().st_size,
            }), flush=True)
        finally:
            if process.poll() is None:
                for dialog in Desktop(backend='win32').windows(class_name='#32770'):
                    if app.exists(timeout=1) and dialog.process_id() == app.process_id():
                        dialog.close()
                if app.exists(timeout=2):
                    app.close()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/T', '/F', '/PID', str(process.pid)], check=False)
                    process.wait(timeout=10)


if __name__ == '__main__':
    main()

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for SheetKit.

Produces a single self-contained SheetKit.exe: the Python engine, the WebView2
host (pythonnet) and the one inlined HTML file that carries the whole UI are
all inside the executable, so the user only has to double-click it.

WebView2 itself is a Windows system component and is not bundled.
"""

import os

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

ROOT = os.path.abspath(os.getcwd())
WEBUI = os.path.join(ROOT, 'python', 'sheetkit', 'webui', 'index.html')

datas = [(WEBUI, 'sheetkit/webui')]
datas += collect_data_files('webview')

hiddenimports = [
    'clr',
    'webview',
    'openpyxl',
    'openpyxl.cell._writer',
]

a = Analysis(
    ['python/main.py'],
    pathex=[ROOT, os.path.join(ROOT, 'python')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SheetKit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

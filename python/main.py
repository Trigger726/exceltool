"""SheetKit entry point.

    python main.py

The packaged build runs exactly the same code through PyInstaller.
"""

from __future__ import annotations

import os
import sys

# A frozen build must not start from the bundle directory, or the relative
# paths inside it would break.
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows consoles default to GBK, which cannot print the Chinese status
# messages the engine produces.
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')

from sheetkit.shell import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

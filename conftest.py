"""Make the engine importable as `sheetkit` without installing it."""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, 'python')
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

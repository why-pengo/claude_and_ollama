"""Shared pytest config — adds runner/ to sys.path so tests can import siblings.

The runner is invoked as `python runner/run_recipe.py` and relies on Python's
default behaviour of putting the script's directory on sys.path. Tests need to
mimic that so `from run_recipe import _cap` works as it does at runtime.
"""

import sys
from pathlib import Path

RUNNER_DIR = Path(__file__).resolve().parent.parent / "runner"
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

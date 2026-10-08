"""Shared test setup: headless matplotlib and import paths."""
import os
import sys

import matplotlib

matplotlib.use("Agg")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (ROOT, os.path.join(ROOT, "hardware")):
    if path not in sys.path:
        sys.path.insert(0, path)

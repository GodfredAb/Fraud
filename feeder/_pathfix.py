"""
Bootstraps sys.path so scripts in this subdirectory can do flat imports
(`import config`, `from profile_store import ...`, etc.) regardless of
which directory they're run from. Import this before anything else:

    import _pathfix  # noqa: F401
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "database"), os.path.join(_ROOT, "ml"),
           os.path.join(_ROOT, "feeder"), os.path.join(_ROOT, "monitor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

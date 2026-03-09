"""Pytest configuration.

Ensures the project root is on sys.path and the old __init__.py
doesn't interfere with test discovery.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

# Block the root __init__.py from being treated as a package
collect_ignore = ["__init__.py"]

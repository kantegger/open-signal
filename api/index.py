"""Vercel Python entrypoint for the Open Signal FastAPI application."""

import importlib
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE = REPOSITORY_ROOT / "python"
if str(CORE_SOURCE) not in sys.path:
    sys.path.insert(0, str(CORE_SOURCE))

app = importlib.import_module("apps.api.main").app

__all__ = ["app"]

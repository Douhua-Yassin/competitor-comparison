from __future__ import annotations

import subprocess
import sys


def test_reporting_routes_import_without_word_dependency() -> None:
    """The shared web routes must not force python-docx into the 8787 environment."""
    code = r'''
import builtins

original_import = builtins.__import__

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "docx" or name.startswith("docx."):
        raise ModuleNotFoundError("python-docx intentionally unavailable")
    return original_import(name, globals, locals, fromlist, level)

builtins.__import__ = guarded_import
import app.reporting.dashboard_routes
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

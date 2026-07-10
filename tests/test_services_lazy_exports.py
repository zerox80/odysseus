"""Regression tests for the lightweight ``services`` package boundary."""

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_services_package_does_not_eagerly_import_optional_stacks():
    code = """
import sys
import services
assert 'services.search' not in sys.modules
assert 'services.docs' not in sys.modules
assert 'services.research' not in sys.modules
assert 'services.memory' not in sys.modules
assert 'services.shell' not in sys.modules
assert 'SearchService' in services.__all__
class SearchModule:
    SearchService = object()
services.import_module = lambda name, package: SearchModule
from services import SearchService
assert SearchService is SearchModule.SearchService
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr

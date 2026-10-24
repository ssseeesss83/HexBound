"""Keep the pre-account regression suites explicitly in migration mode.
New account authorization suites run with secure defaults.
"""
import pytest
import os
import tempfile
from pathlib import Path

# backend.app exports a module-level ASGI application. Its import must never
# install rules or migrate a developer's real/default database during tests.
_import_database = tempfile.TemporaryDirectory(prefix="hexbound-test-import-")
os.environ["HEXBOUND_DB"] = str(Path(_import_database.name) / "import.sqlite3")


@pytest.fixture(autouse=True)
def legacy_regression_mode(request, monkeypatch):
    if request.module.__name__.split(".")[-1] in {"test_api", "test_studio", "test_product_flow"}:
        monkeypatch.setenv("HEXBOUND_ALLOW_GUESTS", "1")
        monkeypatch.setenv("HEXBOUND_LEGACY_ADMIN_TOKEN", "1")

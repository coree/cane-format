from __future__ import annotations

import os

import pytest

from tests.conftest import DATA


def test_required_data_is_present() -> None:
    """With CANE_REQUIRE_DATA=1 (full runs before a release), missing real test documents fail
    the run instead of silently skipping every real-data test."""
    if not os.environ.get("CANE_REQUIRE_DATA"):
        pytest.skip("set CANE_REQUIRE_DATA=1 to require the real test documents (tests/data)")
    for folder in ("brat", "conll", "bioc", "xml/genia", "invalid/bconv-skewed"):
        assert (DATA / folder).is_dir(), f"tests/data/{folder} is missing"

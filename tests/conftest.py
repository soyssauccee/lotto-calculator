from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def page():
    """Load a saved page from tests/fixtures by file name."""
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")

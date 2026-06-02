"""Shared test fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from itu_sync import catalog
from itu_sync.types import Meeting

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def catalog_dir(tmp_path: Path) -> Path:
    """A base folder pre-populated with the trimmed catalog fixtures."""
    for name in ("ITU-T_Meetings.xml", "ITU-R_Meetings.xml"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def sg12_june_2026(catalog_dir: Path) -> Meeting:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    for m in meetings:
        if m.td_date == "260609":
            return m
    raise AssertionError("SG12 June 2026 record not found in fixture")

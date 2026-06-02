"""Tests for catalog parsing and meeting resolution."""

from __future__ import annotations

from pathlib import Path

from itu_sync import catalog
from itu_sync.select import resolve_meeting


def test_loads_sg12_records(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    assert len(meetings) == 3
    assert all(m.meeting_code == "ITU-T SG 12" for m in meetings)


def test_sorted_newest_first(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    dates = [m.start_date for m in meetings]
    assert dates == sorted(dates, reverse=True)
    assert meetings[0].td_date == "260609"


def test_june_2026_fields(sg12_june_2026) -> None:
    m = sg12_june_2026
    assert m.ftp_paths == ["/t/2025/sg12/docs"]
    assert m.working_folder == "/ITU-T SG12/2025"
    assert m.local_path_sg == "/docs-dms"
    assert m.doc_prefix == "T25-SG12"
    assert m.td_date == "260609"


def test_itu_r_uses_included_folders(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-R")
    m = meetings[0]
    assert len(m.ftp_paths) > 1
    assert all(p.startswith("/r/") for p in m.ftp_paths)


def test_resolve_latest(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    chosen = resolve_meeting(meetings, sector="ITU-T", group="SG12", latest=True)
    assert chosen.td_date == "260609"


def test_resolve_by_meeting_date(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    chosen = resolve_meeting(meetings, sector="ITU-T", group="12", meeting="250909")
    assert chosen.td_date == "250909"


def test_group_matches_loosely(catalog_dir: Path) -> None:
    meetings = catalog.load_meetings(catalog_dir, "ITU-T")
    for group in ("SG12", "sg 12", "12"):
        chosen = resolve_meeting(meetings, sector="ITU-T", group=group, latest=True)
        assert chosen.meeting_code == "ITU-T SG 12"

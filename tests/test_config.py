"""Tests for old-app settings parsing and the loose meetings filter."""

from __future__ import annotations

from pathlib import Path

import pytest

from itu_sync.config import Config, read_old_ini
from itu_sync.select import match_filter
from itu_sync.types import Meeting

NEWLINE_INI = (
    "\nlicense=1\nusername=robitza\npass=3121,7117,9121,348\n"
    "drive=/Users/werner/Documents/ITU\nmeeting=ITU-T SG 12, Geneva\n"
)
CONCATENATED_INI = (
    "license=1username=robitzapass=3121,7117drive=/Users/werner/Documents/ITU"
    "meeting=ITU-T SG 12, Geneva"
)


def test_read_old_ini_newline_layout(tmp_path: Path) -> None:
    p = tmp_path / "ITU-Sync-new.ini"
    p.write_text(NEWLINE_INI)
    out = read_old_ini(p)
    assert out["username"] == "robitza"
    assert out["drive"] == "/Users/werner/Documents/ITU"


def test_read_old_ini_concatenated_layout(tmp_path: Path) -> None:
    p = tmp_path / "ITU-Sync-new.ini"
    p.write_text(CONCATENATED_INI)
    out = read_old_ini(p)
    assert out["username"] == "robitza"
    assert out["drive"] == "/Users/werner/Documents/ITU"


def test_read_old_ini_missing_file(tmp_path: Path) -> None:
    assert read_old_ini(tmp_path / "nope.ini") == {}


def test_fresh_config_is_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config()
    assert cfg.is_configured() is False
    # Sensible defaults without any old-app file present.
    assert cfg.get_sector() == "ITU-T"
    assert cfg.get_language() == "E"


def test_mark_configured_and_set_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config()
    cfg.set_language("fr")
    cfg.set_sector("ITU-R")
    cfg.mark_configured()

    # A new instance reads the persisted values.
    reloaded = Config()
    assert reloaded.is_configured() is True
    assert reloaded.get_language() == "F"  # normalized to a single upper code
    assert reloaded.get_sector() == "ITU-R"


def _m() -> Meeting:
    return Meeting(
        sector="ITU-T",
        meeting_code="ITU-T SG 12",
        place_date="ITU-T SG 12, Geneva, 9-17 June 2026",
        start_date="2026-06-09T00:00:00",
        td_date="260609",
        ftp_paths=["/t/2025/sg12/docs"],
        working_folder="/ITU-T SG12/2025",
        local_path_sg="/docs-dms",
        doc_prefix="T25-SG12",
    )


def test_match_filter_is_space_insensitive() -> None:
    m = _m()
    assert match_filter(m, "SG12")
    assert match_filter(m, "sg 12")
    assert match_filter(m, "Geneva")
    assert not match_filter(m, "SG5")

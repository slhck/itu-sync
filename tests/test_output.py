"""Tests for output helpers."""

from __future__ import annotations

from itu_sync.output import truncate_middle


def test_short_text_unchanged() -> None:
    assert truncate_middle("file-E.docx", 36) == "file-E.docx"


def test_long_text_elided_to_width() -> None:
    name = "T25-SG12-250114-TD-GEN-0001!!MSW-E.docx"
    out = truncate_middle(name, 20)
    assert len(out) == 20
    assert "…" in out
    assert out.startswith("T25-SG12")
    assert out.endswith(".docx")


def test_degenerate_widths() -> None:
    assert truncate_middle("anything", 1) == "…"
    assert truncate_middle("anything", 0) == "anything"

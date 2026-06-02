"""Tests for the English/language filter."""

from __future__ import annotations

import pytest

from itu_sync.language import keep_file


@pytest.mark.parametrize(
    "name",
    [
        "T25-SG12-C-0001-E.htm",
        "T25-SG12-C-0001!!MSW-E.docx",
        "T25-SG12-C-0005!R1!MSW-E.docx",
        "T25-SG12-C-0167!R1!ZIP-E.zip",
        "T25-SG12-R-0008!!MSW-E.docx",
    ],
)
def test_english_documents_kept(name: str) -> None:
    assert keep_file(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "T25-SG12-C-0001-F.docx",
        "T25-SG12-C-0001-S.pdf",
        "T25-SG12-C-0001-C.docx",
        "T25-SG12-C-0001-A.docx",
        "T25-SG12-C-0001-R.docx",
        # Per-document HTML carries a language token too and must be filtered.
        "T25-SG12-C-0001-F.htm",
        "T25-SG12-C-0001-S.htm",
    ],
)
def test_non_english_documents_dropped(name: str) -> None:
    assert keep_file(name) is False


def test_english_html_kept() -> None:
    assert keep_file("T25-SG12-C-0001-E.htm") is True


@pytest.mark.parametrize(
    "name",
    [
        "T25-SG12-C.xml",
        "T25-SG12-260609-TD.xml",
        "index.html",
        "page.htm",
        "CList.html",
        "style.css",
        "app.js",
        "logo.png",
    ],
)
def test_index_files_always_kept(name: str) -> None:
    # .xml index files end in a deceptive "C"/"TD" token; HTML index files
    # (no language token) are kept by the token rule, not the extension rule.
    assert keep_file(name) is True


def test_no_language_token_kept() -> None:
    assert keep_file("README.docx") is True


def test_other_language_selectable() -> None:
    assert keep_file("doc-F.docx", frozenset({"F"})) is True
    assert keep_file("doc-E.docx", frozenset({"F"})) is False

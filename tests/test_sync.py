"""Tests for the sync planning/download and listing, with a mocked FTPS client."""

from __future__ import annotations

from pathlib import Path

from itu_sync import sync
from itu_sync.types import Meeting

FIXTURES = Path(__file__).parent / "fixtures"


class FakeFTP:
    """A minimal stand-in for :class:`ImplicitFTPS` for tests.

    ``listing`` maps a directory path to ``[(name, facts), ...]`` like MLSD;
    ``files`` maps a full file path to its bytes.
    """

    def __init__(self, listing: dict, files: dict[str, bytes]) -> None:
        self.listing = {k.rstrip("/"): v for k, v in listing.items()}
        self.files = files
        self.retr_count = 0

    def mlsd(self, path: str = "", facts=None):  # noqa: ARG002
        return iter(self.listing.get(path.rstrip("/"), []))

    def dir(self, *args) -> None:  # noqa: ARG002
        pass

    def size(self, filename: str) -> int:
        return len(self.files[filename])

    def retrbinary(self, cmd: str, callback, blocksize: int = 8192) -> str:  # noqa: ARG002
        path = cmd.split(" ", 1)[1]
        self.retr_count += 1
        callback(self.files[path])
        return "226 Transfer complete"

    def quit(self) -> str:
        return "221 Goodbye"

    def close(self) -> None:
        pass


def _meeting() -> Meeting:
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


def _fake_ftp() -> FakeFTP:
    root = "/t/2025/sg12/docs/c/ties"
    contents = {
        "T25-SG12-C-0001-E.docx": b"english-doc",
        "T25-SG12-C-0001-F.docx": b"french-doc",
        "T25-SG12-C.xml": b"<index/>",
    }
    files = {f"{root}/{name}": data for name, data in contents.items()}
    listing = {
        root: [
            (name, {"type": "file", "size": str(len(data))})
            for name, data in contents.items()
        ]
    }
    return FakeFTP(listing, files)


def test_build_plan_filters_language(tmp_path: Path) -> None:
    ftp = _fake_ftp()
    plan = sync.build_plan(ftp, _meeting(), tmp_path, [("C", None)])
    names = {t.local_path.name for t in plan.to_download}
    # English doc and the index XML are kept; the French doc is dropped.
    assert "T25-SG12-C-0001-E.docx" in names
    assert "T25-SG12-C.xml" in names
    assert "T25-SG12-C-0001-F.docx" not in names


def test_local_paths_preserve_subfolders(tmp_path: Path) -> None:
    ftp = _fake_ftp()
    plan = sync.build_plan(ftp, _meeting(), tmp_path, [("C", None)])
    expected = tmp_path / "ITU-T SG12/2025/docs-dms/c/ties/T25-SG12-C-0001-E.docx"
    assert any(t.local_path == expected for t in plan.to_download)


def test_download_and_skip_by_size(tmp_path: Path) -> None:
    meeting = _meeting()

    plan = sync.build_plan(_fake_ftp(), meeting, tmp_path, [("C", None)])
    summary = sync.download_plan(plan, _fake_ftp, workers=2)
    assert summary.downloaded == 2
    assert summary.failed == 0

    doc = tmp_path / "ITU-T SG12/2025/docs-dms/c/ties/T25-SG12-C-0001-E.docx"
    assert doc.read_bytes() == b"english-doc"

    # Re-running skips everything already present with matching size.
    plan2 = sync.build_plan(_fake_ftp(), meeting, tmp_path, [("C", None)])
    assert plan2.to_download == []
    assert len(plan2.skipped) == 2


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    meeting = _meeting()
    plan = sync.build_plan(_fake_ftp(), meeting, tmp_path, [("C", None)])
    # Simulate dry-run: we never call download_plan.
    assert not (tmp_path / "ITU-T SG12").exists()
    assert len(plan.to_download) == 2


def test_parse_td_index() -> None:
    data = (FIXTURES / "T25-SG12-250909-TD.xml").read_bytes()
    rows = sync.parse_index_xml(data, "TD")
    assert len(rows) == 3
    first = rows[0]
    assert first["type"] == "TD"
    assert first["number"]
    assert first["title"]
    assert first["subgroup"]


def _offline(url: str) -> bytes:
    """A fetcher that simulates no web access (e.g. offline)."""
    raise OSError(f"offline: {url}")


def test_list_documents_uses_web_index() -> None:
    # The web index XML is fetched over HTTPS (mocked here) for a live view.
    fixture = (FIXTURES / "T25-SG12-250909-TD.xml").read_bytes()
    captured: list[str] = []

    def fetch(url: str) -> bytes:
        captured.append(url)
        return fixture

    rows, from_index = sync.list_documents(
        _fake_ftp(), _meeting(), [("TD", None)], fetch_url=fetch
    )
    assert from_index is True
    assert len(rows) == 3
    assert rows[0]["title"]
    assert captured == [
        "https://www.itu.int/dms_pages/itu-t/md/25/SG12/td/T25-SG12-260609-TD.xml"
    ]


def test_list_documents_falls_back_to_listing() -> None:
    # No web access and the fake server serves no index XML -> listing fallback.
    ftp = _fake_ftp()
    rows, from_index = sync.list_documents(
        ftp, _meeting(), [("C", None)], fetch_url=_offline
    )
    assert from_index is False
    # The English doc yields one row; its number is parsed from the filename.
    assert any(r["number"] == "0001" for r in rows)
    assert all(r["type"] == "C" for r in rows)

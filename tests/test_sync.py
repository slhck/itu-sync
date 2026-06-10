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
        # Parent directories, so a whole-tree walk from FTP_path works too.
        "/t/2025/sg12/docs": [("c", {"type": "dir"})],
        "/t/2025/sg12/docs/c": [("ties", {"type": "dir"})],
        root: [
            (name, {"type": "file", "size": str(len(data))})
            for name, data in contents.items()
        ],
    }
    return FakeFTP(listing, files)


def test_build_plan_empty_types_mirrors_everything(tmp_path: Path) -> None:
    # The CLI passes [] when --type is not given; that must mean "no filter"
    # (mirror the whole tree), not "nothing requested". Regression test for the
    # bug where sync reported 0 files without --type.
    ftp = _fake_ftp()
    for types in ([], None):
        plan = sync.build_plan(ftp, _meeting(), tmp_path, types)
        names = {t.local_path.name for t in plan.to_download}
        assert "T25-SG12-C-0001-E.docx" in names


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


def _fake_ftp_with_mtime(modify: str) -> FakeFTP:
    """One English doc whose MLSD facts carry a ``modify`` timestamp (UTC)."""
    root = "/t/2025/sg12/docs/c/ties"
    name = "T25-SG12-C-0001-E.docx"
    data = b"english-doc"
    files = {f"{root}/{name}": data}
    listing = {
        root: [(name, {"type": "file", "size": str(len(data)), "modify": modify})]
    }
    return FakeFTP(listing, files)


def test_redownloads_when_remote_is_newer(tmp_path: Path) -> None:
    meeting = _meeting()

    # First sync stamps the local file with the remote modification time.
    plan = sync.build_plan(
        _fake_ftp_with_mtime("20260601120000"), meeting, tmp_path, [("C", None)]
    )
    assert len(plan.to_download) == 1
    sync.download_plan(plan, lambda: _fake_ftp_with_mtime("20260601120000"), workers=1)

    # Unchanged remote -> skipped.
    plan2 = sync.build_plan(
        _fake_ftp_with_mtime("20260601120000"), meeting, tmp_path, [("C", None)]
    )
    assert plan2.to_download == []
    assert len(plan2.skipped) == 1

    # Replaced in place on the server (same size, newer mtime) -> re-download.
    plan3 = sync.build_plan(
        _fake_ftp_with_mtime("20260609090000"), meeting, tmp_path, [("C", None)]
    )
    assert len(plan3.to_download) == 1
    assert plan3.skipped == []


def test_keeps_local_file_newer_than_remote(tmp_path: Path) -> None:
    # A local copy downloaded before mtime stamping existed has its download
    # time as mtime; an older remote stamp must not trigger a re-download.
    meeting = _meeting()
    local = tmp_path / "ITU-T SG12/2025/docs-dms/c/ties/T25-SG12-C-0001-E.docx"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"english-doc")  # same size as the remote file

    plan = sync.build_plan(
        _fake_ftp_with_mtime("20200101000000"), meeting, tmp_path, [("C", None)]
    )
    assert plan.to_download == []
    assert len(plan.skipped) == 1


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


# A TD index with two liaison statements (one incoming, one outgoing) and one
# ordinary TD, used for the liaison (LS) tests below.
LIAISON_INDEX = (
    b"<?xml version='1.0' encoding='utf-8'?>\n"
    b"<page_content><folder_list>"
    b"<folder><subgroup>GEN</subgroup><doc_number>0010</doc_number>"
    b"<doc_type>TD</doc_type><main_source>SG11</main_source>"
    b"<reception_date>2026-01-01</reception_date>"
    b"<ltitle_e>LS/i on something incoming</ltitle_e></folder>"
    b"<folder><subgroup>GEN</subgroup><doc_number>0011</doc_number>"
    b"<doc_type>TD</doc_type><main_source>ITU-T Study Group 12</main_source>"
    b"<reception_date>2026-01-02</reception_date>"
    b"<ltitle_e>LS/o on something outgoing</ltitle_e></folder>"
    b"<folder><subgroup>GEN</subgroup><doc_number>0012</doc_number>"
    b"<doc_type>TD</doc_type><main_source>Editors</main_source>"
    b"<reception_date>2026-01-03</reception_date>"
    b"<ltitle_e>An ordinary temporary document</ltitle_e></folder>"
    b"</folder_list></page_content>"
)


def test_parse_index_marks_liaison_tds() -> None:
    rows = sync.parse_index_xml(LIAISON_INDEX, "TD")
    by_number = {r["number"]: r["type"] for r in rows}
    assert by_number == {"0010": "LS/i", "0011": "LS/o", "0012": "TD"}


def test_list_documents_liaison_only_incoming() -> None:
    rows, from_index = sync.list_documents(
        _fake_ftp(), _meeting(), [("LS", "i")], fetch_url=lambda _url: LIAISON_INDEX
    )
    assert from_index is True
    assert [r["number"] for r in rows] == ["0010"]
    assert rows[0]["type"] == "LS/i"


def _ls_fake_ftp() -> FakeFTP:
    """A fake server whose TD tree holds the liaison + ordinary TD files."""
    td = "/t/2025/sg12/docs/260609/td/ties"
    gen = f"{td}/gen"
    contents = {
        "T25-SG12-260609-TD-GEN-0010!!MSW-E.docx": b"incoming-ls",
        "T25-SG12-260609-TD-GEN-0011!!MSW-E.docx": b"outgoing-ls",
        "T25-SG12-260609-TD-GEN-0012!!MSW-E.docx": b"ordinary-td",
        "T25-SG12-260609-TD-GEN-0010!!MSW-F.docx": b"incoming-ls-fr",
    }
    files = {f"{gen}/{name}": data for name, data in contents.items()}
    listing = {
        td: [("gen", {"type": "dir"})],
        gen: [
            (name, {"type": "file", "size": str(len(data))})
            for name, data in contents.items()
        ],
    }
    return FakeFTP(listing, files)


def test_build_plan_liaison_only(tmp_path: Path) -> None:
    plan = sync.build_plan(
        _ls_fake_ftp(),
        _meeting(),
        tmp_path,
        [("LS", None)],
        fetch_url=lambda _url: LIAISON_INDEX,
    )
    names = {t.local_path.name for t in plan.to_download}
    # Only the two liaison TDs (English) are planned; the ordinary TD and the
    # French variant are excluded.
    assert names == {
        "T25-SG12-260609-TD-GEN-0010!!MSW-E.docx",
        "T25-SG12-260609-TD-GEN-0011!!MSW-E.docx",
    }
    # They land in the normal TD location.
    incoming = next(t for t in plan.to_download if "0010" in t.local_path.name)
    assert incoming.local_path == (
        tmp_path
        / "ITU-T SG12/2025/docs-dms/260609/td/ties/gen"
        / "T25-SG12-260609-TD-GEN-0010!!MSW-E.docx"
    )


def test_build_plan_liaison_incoming_only(tmp_path: Path) -> None:
    plan = sync.build_plan(
        _ls_fake_ftp(),
        _meeting(),
        tmp_path,
        [("LS", "i")],
        fetch_url=lambda _url: LIAISON_INDEX,
    )
    names = {t.local_path.name for t in plan.to_download}
    assert names == {"T25-SG12-260609-TD-GEN-0010!!MSW-E.docx"}


def test_build_plan_liaison_missing_index_warns(tmp_path: Path) -> None:
    warnings: list[str] = []
    plan = sync.build_plan(
        _ls_fake_ftp(),
        _meeting(),
        tmp_path,
        [("LS", None)],
        fetch_url=_offline,
        on_warning=warnings.append,
    )
    # Without the TD index, liaisons cannot be identified; nothing is planned
    # and the user is warned rather than silently getting an empty result.
    assert plan.to_download == []
    assert warnings

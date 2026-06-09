"""Tests for path resolution and the document-type registry."""

from __future__ import annotations

from pathlib import Path

from itu_sync import doctypes
from itu_sync.doctypes import index_filename, index_url, mirror_roots, parse_type_spec
from itu_sync.paths import local_base, remote_index_path


def test_local_base(sg12_june_2026) -> None:
    base = local_base("/Users/werner/Documents/ITU", sg12_june_2026)
    assert base == Path("/Users/werner/Documents/ITU/ITU-T SG12/2025/docs-dms")


def test_whole_mirror_when_no_types(sg12_june_2026) -> None:
    roots = mirror_roots(sg12_june_2026, [])
    assert len(roots) == 1
    assert roots[0].remote_root == "/t/2025/sg12/docs"
    assert roots[0].local_relprefix == ""


def test_type_subfolders(sg12_june_2026) -> None:
    roots = mirror_roots(sg12_june_2026, [("C", None), ("R", None)])
    by_label = {r.label: r for r in roots}
    assert by_label["C"].remote_root == "/t/2025/sg12/docs/c/ties"
    assert by_label["C"].local_relprefix == "c/ties"
    assert by_label["R"].remote_root == "/t/2025/sg12/docs/r/ties"


def test_td_subfolder_uses_meeting_date(sg12_june_2026) -> None:
    roots = mirror_roots(sg12_june_2026, [("TD", None)])
    assert roots[0].remote_root == "/t/2025/sg12/docs/260609/td/ties"


def test_td_subgroup(sg12_june_2026) -> None:
    roots = mirror_roots(sg12_june_2026, [("TD", "gen")])
    assert roots[0].remote_root == "/t/2025/sg12/docs/260609/td/ties/gen"


def test_index_filenames(sg12_june_2026) -> None:
    assert index_filename(sg12_june_2026, "C") == "T25-SG12-C.xml"
    assert index_filename(sg12_june_2026, "COL") == "T25-SG12-COL.xml"
    assert index_filename(sg12_june_2026, "TD") == "T25-SG12-260609-TD.xml"


def test_remote_index_path(sg12_june_2026) -> None:
    fn = index_filename(sg12_june_2026, "C")
    assert remote_index_path(sg12_june_2026, fn) == "/t/2025/sg12/docs/T25-SG12-C.xml"


def test_index_url(sg12_june_2026) -> None:
    base = "https://www.itu.int/dms_pages/itu-t/md/25/SG12"
    assert index_url(sg12_june_2026, "C") == f"{base}/c/T25-SG12-C.xml"
    assert index_url(sg12_june_2026, "R") == f"{base}/r/T25-SG12-R.xml"
    assert index_url(sg12_june_2026, "COL") == f"{base}/col/T25-SG12-COL.xml"
    assert index_url(sg12_june_2026, "TD") == f"{base}/td/T25-SG12-260609-TD.xml"


def test_parse_type_spec() -> None:
    assert parse_type_spec("C,R") == [("C", None), ("R", None)]
    assert parse_type_spec("td:gen") == [("TD", "gen")]
    assert parse_type_spec(None) == []


def test_parse_type_spec_rejects_unknown() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_type_spec("XYZ")


def test_parse_type_spec_liaison() -> None:
    assert parse_type_spec("LS") == [("LS", None)]
    assert parse_type_spec("LS/i") == [("LS", "i")]
    assert parse_type_spec("ls/o") == [("LS", "o")]
    assert parse_type_spec("C,LS/i") == [("C", None), ("LS", "i")]


def test_parse_type_spec_rejects_bad_liaison_direction() -> None:
    import pytest

    with pytest.raises(ValueError):
        parse_type_spec("LS/x")


def test_parse_type_spec_liaison_rejects_colon() -> None:
    import pytest

    # The liaison direction uses a slash (LS/i), not a colon.
    with pytest.raises(ValueError, match="slash"):
        parse_type_spec("LS:i")


def test_liaison_marking() -> None:
    assert doctypes.liaison_marking("LS/i on incoming foo") == "LS/i"
    assert doctypes.liaison_marking("LS/o on outgoing bar") == "LS/o"
    assert doctypes.liaison_marking("LS/o/r reply to baz") == "LS/o"
    assert doctypes.liaison_marking("Updated baseline text E.800") is None


def test_liaison_mirror_root_is_td_tree(sg12_june_2026) -> None:
    roots = mirror_roots(sg12_june_2026, [("LS", None)])
    assert len(roots) == 1
    # Liaison statements mirror the TD tree (filtered to the LS subset later).
    assert roots[0].remote_root == "/t/2025/sg12/docs/260609/td/ties"
    assert roots[0].local_relprefix == "260609/td/ties"
    assert roots[0].label == "LS"
    assert mirror_roots(sg12_june_2026, [("LS", "o")])[0].label == "LS/o"


def test_itu_r_ignores_types(catalog_dir) -> None:
    from itu_sync import catalog

    m = catalog.load_meetings(catalog_dir, "ITU-R")[0]
    roots = mirror_roots(m, [("C", None)])
    # ITU-R mirrors whole included folders regardless of the type filter.
    assert all(r.label == "all" for r in roots)
    assert len(roots) == len(m.ftp_paths)
    assert doctypes.DEFAULT_SERVER == "ties"

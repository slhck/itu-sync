"""Tests for the LIST-listing parser used as the MLSD fallback."""

from __future__ import annotations

import ftplib

import pytest

from itu_sync.ftps import _parse_list_line, walk


def test_parses_iis_dos_file_line() -> None:
    line = "01-08-25  04:16PM               163363 T25-SG12-C-0001!!MSW-A.docx"
    assert _parse_list_line(line) == ("T25-SG12-C-0001!!MSW-A.docx", False, 163363)


def test_parses_iis_dos_dir_line() -> None:
    line = "11-01-24  12:51PM       <DIR>          c"
    assert _parse_list_line(line) == ("c", True, 0)


def test_parses_unix_ls_line() -> None:
    line = "-rw-r--r--   1 owner group   12345 Jun  2 10:00 file-E.docx"
    assert _parse_list_line(line) == ("file-E.docx", False, 12345)


def test_unix_dir_line() -> None:
    line = "drwxr-xr-x   2 owner group    4096 Jun  2 10:00 ties"
    assert _parse_list_line(line) == ("ties", True, 4096)


def test_ignores_unrecognized_lines() -> None:
    assert _parse_list_line("") is None
    assert _parse_list_line("total 24") is None


class _WalkFTP:
    """Fake FTP whose MLSD/LIST raise ``error_perm`` for chosen paths.

    Models the live server's ``td/pub`` phantom directory: it lists fine but
    descending into ``td/pub/pub`` returns a 550.
    """

    def __init__(self, tree: dict[str, list], deny: set[str]) -> None:
        self.tree = {k.rstrip("/"): v for k, v in tree.items()}
        self.deny = {p.rstrip("/") for p in deny}

    def mlsd(self, path: str = "", facts=None):  # noqa: ARG002
        path = path.rstrip("/")
        if path in self.deny:
            raise ftplib.error_perm("550 The system cannot find the path specified.")
        return iter(self.tree.get(path, []))

    def dir(self, *args) -> None:
        # Used only when walk() falls back from MLSD to LIST.
        path = str(args[0]).rstrip("/")
        if path in self.deny:
            raise ftplib.error_perm("550 The system cannot find the path specified.")

    def size(self, filename: str) -> int | None:  # noqa: ARG002
        return None

    def retrbinary(self, cmd: str, callback, blocksize: int = 8192) -> str:  # noqa: ARG002
        return "226 Transfer complete"

    def quit(self) -> str:
        return "221 Goodbye"

    def close(self) -> None:
        pass


def _tree() -> dict[str, list]:
    f = {"type": "file", "size": "10"}
    d = {"type": "dir"}
    return {
        "/docs": [("ties", d), ("pub", d)],
        "/docs/ties": [("real-E.docx", f)],
        "/docs/pub": [("pub", d)],  # phantom: 550s when entered
    }


def test_walk_skips_inaccessible_subdir() -> None:
    ftp = _WalkFTP(_tree(), deny={"/docs/pub/pub"})
    files = sorted(p for p, _ in walk(ftp, "/docs"))
    assert files == ["/docs/ties/real-E.docx"]


def test_walk_propagates_root_failure() -> None:
    ftp = _WalkFTP(_tree(), deny={"/docs"})
    with pytest.raises(ftplib.error_perm):
        list(walk(ftp, "/docs"))

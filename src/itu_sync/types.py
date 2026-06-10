"""Typed records used across itu-sync."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

Sector = Literal["ITU", "ITU-D", "ITU-R", "ITU-T"]

SECTORS: tuple[str, ...] = ("ITU", "ITU-D", "ITU-R", "ITU-T")


@dataclass
class Meeting:
    """A single meeting parsed from a catalog record."""

    sector: str
    meeting_code: str
    """e.g. ``ITU-T SG 12``."""
    place_date: str
    """Human label shown in the picker, e.g. ``ITU-T SG 12, Geneva, 9-17 June 2026``."""
    start_date: str
    """ISO datetime used for newest-first sorting."""
    td_date: str
    """``yymmdd`` of the meeting, used for the TD subfolder/index."""
    ftp_paths: list[str]
    """Remote document roots. One for ITU/ITU-D/ITU-T, several for ITU-R."""
    working_folder: str
    """e.g. ``/ITU-T SG12/2025``."""
    local_path_sg: str
    """e.g. ``/docs-dms``."""
    doc_prefix: str | None
    """e.g. ``T25-SG12``, derived from the catalog's ``Frame_src_*`` fields."""
    sg_title: str = ""
    sg_no_period: str = ""
    sg_email: str = ""
    sg_homepage: str = ""
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocType:
    """A document type and where it lives under a meeting's ``FTP_path``."""

    code: str
    """Short code, e.g. ``C``, ``R``, ``COL``, ``TD``."""
    name: str
    """Human name, e.g. ``Contributions``."""


@dataclass(frozen=True)
class MirrorRoot:
    """A remote tree to mirror and where it lands locally."""

    remote_root: str
    """Absolute remote path to walk, e.g. ``/t/2025/sg12/docs/c/ties``."""
    local_relprefix: str
    """Local subpath under the meeting's local base, e.g. ``c/ties``."""
    label: str = ""
    """Display label, e.g. a type code."""


@dataclass
class FileTask:
    """A single remote file considered for download."""

    remote_path: str
    local_path: Path
    size: int
    mtime: float | None = None
    """Remote modification time (Unix timestamp), if the listing provided one."""


class DocRecord(TypedDict):
    """A row parsed from a per-type index XML, for the ``list`` use case."""

    type: str
    number: str
    title: str
    source: str
    date: str
    subgroup: str


@dataclass
class SyncSummary:
    """Outcome of a sync run."""

    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_downloaded: int = 0
    failures: list[str] = field(default_factory=list)

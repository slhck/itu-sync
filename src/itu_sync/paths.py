"""Resolve a meeting to its local destination base.

The local destination is ``drive + workingFolder + setLocalPathSG``, e.g.
``/Users/werner/Documents/ITU`` + ``/ITU-T SG12/2025`` + ``/docs-dms``.
"""

from __future__ import annotations

from pathlib import Path

from itu_sync.types import Meeting


def local_base(drive: str | Path, meeting: Meeting) -> Path:
    """Return the local base folder for ``meeting`` under ``drive``."""
    return (
        Path(drive)
        / meeting.working_folder.strip("/")
        / meeting.local_path_sg.strip("/")
    )


def remote_index_path(meeting: Meeting, index_filename: str) -> str:
    """Absolute remote path of an index XML at the docs root."""
    ftp_path = meeting.ftp_paths[0].rstrip("/") if meeting.ftp_paths else ""
    return f"{ftp_path}/{index_filename}"

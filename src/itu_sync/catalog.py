"""Download and parse the four ITU meeting catalogs.

The catalogs are plain public XML files (no authentication). Every command
refreshes them by default; they total about 300 KB. On a network error we fall
back to the cached copies in the base folder.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from itu_sync.types import Meeting

CATALOG_BASE = "https://www.itu.int/net/epub/ITU-Sync/"

# sector -> (filename, record element tag)
CATALOG_FILES: dict[str, tuple[str, str]] = {
    "ITU": ("ITU_Meetings.xml", "ITU_Meetings"),
    "ITU-D": ("ITU-D_NEW-Meetings.xml", "ITU-D_NEW-Meetings"),
    "ITU-R": ("ITU-R_Meetings.xml", "ITU-R_Meetings"),
    "ITU-T": ("ITU-T_Meetings.xml", "ITU-T_Meetings"),
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class CatalogError(RuntimeError):
    """Raised when a catalog can neither be downloaded nor read from cache."""


def download(url: str, timeout: float = 30.0) -> bytes:
    """Fetch ``url`` over HTTP(S) with a browser-like User-Agent.

    Used both for the public meeting catalogs and for the per-type index XMLs
    in ITU's ``dms_pages`` web system (see :func:`doctypes.index_url`).
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def refresh_catalogs(
    base_folder: Path,
    sectors: list[str] | None = None,
    *,
    on_warning: Callable[[str], object] | None = None,
) -> list[str]:
    """Download the catalogs for ``sectors`` (default all) into ``base_folder``.

    Returns the list of sectors that could not be refreshed (network errors);
    those fall back to any cached copy. Calls ``on_warning(msg)`` if provided.
    """
    base_folder.mkdir(parents=True, exist_ok=True)
    sectors = sectors or list(CATALOG_FILES)
    failed: list[str] = []
    for sector in sectors:
        filename, _ = CATALOG_FILES[sector]
        url = CATALOG_BASE + filename
        try:
            data = download(url)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            failed.append(sector)
            if on_warning is not None:
                on_warning(f"Could not refresh {filename}: {exc}")
            continue
        (base_folder / filename).write_bytes(data)
    return failed


def _xf_prefix(record: ET.Element) -> str | None:
    """Derive the document prefix (e.g. ``T25-SG12``) from ``Frame_src_*`` fields.

    Each field carries an ``XF=../docs-dms/<file>`` parameter naming an index XML
    such as ``T25-SG12-C.xml``; the prefix is that filename without its type
    suffix.
    """
    for child in record:
        if not child.tag.startswith("Frame_src_"):
            continue
        text = child.text or ""
        m = re.search(r"XF=\.\./[^/]+/([^&]+\.xml)", text)
        if not m:
            continue
        name = m.group(1).strip()
        # Strip "-<TYPE>.xml" or "-<yymmdd>-TD.xml" to get the bare prefix.
        m2 = re.match(r"(.+?)-(?:\d{6}-)?(?:C|R|COL|TD)\.xml$", name)
        if m2:
            return m2.group(1)
    return None


def _derive_working_folder(record: ET.Element) -> str:
    code = (record.findtext("Meeting_code") or "").strip()
    start = (record.findtext("Start_meeting_date") or "").strip()
    year = start[:4] if start else ""
    return f"/{code.replace(' ', '')}/{year}"


def _parse_record(record: ET.Element, sector: str) -> Meeting:
    raw = {child.tag: (child.text or "") for child in record}

    ftp_path: str = (record.findtext("FTP_path") or "").strip()
    included: list[str] = [
        (child.text or "").strip()
        for child in record
        if re.fullmatch(r"Included_folder_\d+", child.tag)
        and (child.text or "").strip()
    ]
    ftp_paths: list[str] = included if included else ([ftp_path] if ftp_path else [])

    working_folder = (record.findtext("workingFolder") or "").strip()
    if not working_folder:
        working_folder = _derive_working_folder(record)

    local_path_sg = (record.findtext("setLocalPathSG") or "").strip() or "/docs-dms"

    return Meeting(
        sector=sector,
        meeting_code=(record.findtext("Meeting_code") or "").strip(),
        place_date=(record.findtext("Meeting_place_date") or "").strip(),
        start_date=(record.findtext("Start_meeting_date") or "").strip(),
        td_date=(record.findtext("TD_date") or "").strip(),
        ftp_paths=ftp_paths,
        working_folder=working_folder,
        local_path_sg=local_path_sg,
        doc_prefix=_xf_prefix(record),
        sg_title=(record.findtext("SG_Title") or "").strip(),
        sg_no_period=(record.findtext("SG_No_Period") or "").strip(),
        sg_email=(record.findtext("SG_Email") or "").strip(),
        sg_homepage=(record.findtext("SG_Homepage") or "").strip(),
        raw=raw,
    )


def load_meetings(base_folder: Path, sector: str) -> list[Meeting]:
    """Parse the cached catalog for ``sector`` into newest-first ``Meeting``\\ s."""
    filename, tag = CATALOG_FILES[sector]
    path = base_folder / filename
    if not path.exists():
        raise CatalogError(
            f"No catalog for {sector} at {path}. Run a command without --no-refresh "
            f"while online to download it."
        )
    root = ET.fromstring(path.read_bytes())
    meetings = [_parse_record(rec, sector) for rec in root.findall(tag)]
    meetings.sort(key=lambda m: m.start_date, reverse=True)
    return meetings


def load_all_meetings(
    base_folder: Path, sectors: list[str] | None = None
) -> list[Meeting]:
    """Load meetings across ``sectors`` (default all), skipping missing catalogs."""
    sectors = sectors or list(CATALOG_FILES)
    out: list[Meeting] = []
    for sector in sectors:
        try:
            out.extend(load_meetings(base_folder, sector))
        except CatalogError:
            continue
    out.sort(key=lambda m: m.start_date, reverse=True)
    return out

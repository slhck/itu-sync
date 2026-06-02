"""Orchestration for the sync and list use cases.

Kept UI-agnostic: callers pass callbacks so the same functions drive the CLI
progress bar, the interactive pickers, and the tests.
"""

from __future__ import annotations

import os
import re
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from itu_sync import catalog, doctypes, ftps, paths
from itu_sync.ftps import FTPClient
from itu_sync.language import DEFAULT_LANGUAGES, keep_file
from itu_sync.types import DocRecord, FileTask, Meeting, SyncSummary

# (status, task) where status is one of: downloaded, skipped, failed
ProgressCb = Callable[[str, FileTask], None]
ConnectFactory = Callable[[], FTPClient]
# Fetch a URL's bytes; injectable so tests need not hit the network.
IndexFetcher = Callable[[str], bytes]


@dataclass
class SyncPlan:
    """The result of walking the remote tree and applying the language filter."""

    to_download: list[FileTask]
    skipped: list[FileTask]

    @property
    def all_tasks(self) -> list[FileTask]:
        return self.to_download + self.skipped

    @property
    def download_bytes(self) -> int:
        return sum(t.size for t in self.to_download)


def build_plan(
    ftp: FTPClient,
    meeting: Meeting,
    drive: str | Path,
    types: list[tuple[str, str | None]] | None,
    languages: frozenset[str] = DEFAULT_LANGUAGES,
    *,
    on_walk: Callable[[str], None] | None = None,
) -> SyncPlan:
    """Walk the selected remote roots, filter, and split into download/skip."""
    base = paths.local_base(drive, meeting)
    to_download: list[FileTask] = []
    skipped: list[FileTask] = []

    for root in doctypes.mirror_roots(meeting, types):
        if on_walk:
            on_walk(root.remote_root)
        for remote_path, size in ftps.walk(ftp, root.remote_root):
            name = remote_path.rsplit("/", 1)[-1]
            if not keep_file(name, languages):
                continue
            rel = remote_path[len(root.remote_root) :].lstrip("/")
            local = (
                base / root.local_relprefix / rel
                if root.local_relprefix
                else base / rel
            )
            task = FileTask(remote_path=remote_path, local_path=local, size=size)
            if local.exists() and local.stat().st_size == size:
                skipped.append(task)
            else:
                to_download.append(task)
    return SyncPlan(to_download=to_download, skipped=skipped)


def _download_one(ftp: FTPClient, task: FileTask) -> int:
    """Download a single file atomically. Returns bytes written."""
    task.local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = task.local_path.with_name(task.local_path.name + ".part")
    try:
        with open(tmp, "wb") as fh:
            ftp.retrbinary(f"RETR {task.remote_path}", fh.write)
        os.replace(tmp, task.local_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return task.size


def download_plan(
    plan: SyncPlan,
    connect_factory: ConnectFactory,
    *,
    workers: int = 4,
    progress: ProgressCb | None = None,
) -> SyncSummary:
    """Download ``plan.to_download`` in parallel, one FTPS connection per worker.

    ``ftplib`` is not safe to share across threads, so each worker thread opens
    and reuses its own connection via thread-local storage.
    """
    summary = SyncSummary(
        total=len(plan.all_tasks),
        skipped=len(plan.skipped),
    )
    for task in plan.skipped:
        if progress:
            progress("skipped", task)

    if not plan.to_download:
        return summary

    workers = max(1, min(workers, len(plan.to_download)))
    local = threading.local()
    created: list[FTPClient] = []
    created_lock = threading.Lock()

    def get_ftp() -> FTPClient:
        ftp = getattr(local, "ftp", None)
        if ftp is None:
            ftp = connect_factory()
            local.ftp = ftp
            with created_lock:
                created.append(ftp)
        return ftp

    lock = threading.Lock()

    def work(task: FileTask) -> None:
        try:
            written = _download_one(get_ftp(), task)
            with lock:
                summary.downloaded += 1
                summary.bytes_downloaded += written
            if progress:
                progress("downloaded", task)
        except Exception as exc:  # noqa: BLE001
            with lock:
                summary.failed += 1
                summary.failures.append(f"{task.remote_path}: {exc}")
            if progress:
                progress("failed", task)

    from concurrent.futures import ThreadPoolExecutor

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, plan.to_download))
    finally:
        for ftp in created:
            try:
                ftp.quit()
            except Exception:  # noqa: BLE001
                try:
                    ftp.close()
                except Exception:  # noqa: BLE001
                    pass
    return summary


# ----------------------------------------------------------------------------
# Listing
# ----------------------------------------------------------------------------


def parse_index_xml(data: bytes, type_code: str) -> list[DocRecord]:
    """Parse a per-type index XML into document rows.

    The TD index uses repeated ``<folder>`` elements with ``doc_number``,
    ``ltitle_e``, ``main_source``, ``reception_date``, ``subgroup``; the
    C/R/COL indexes share a similar ``<folder>`` schema.
    """
    root = ET.fromstring(data)
    rows: list[DocRecord] = []
    for folder in root.iter("folder"):
        rows.append(
            DocRecord(
                type=type_code,
                number=(folder.findtext("doc_number") or "").strip(),
                title=(folder.findtext("ltitle_e") or "").strip(),
                source=(folder.findtext("main_source") or "").strip(),
                date=(folder.findtext("reception_date") or "").strip(),
                subgroup=(folder.findtext("subgroup") or "").strip(),
            )
        )
    return rows


# Document number embedded in a filename, e.g. "...-C-0073!R1!MSW-E.docx" -> 0073.
_DOC_NUMBER = re.compile(r"-(\d{3,5})(?:[-!.]|$)")


def _load_index_bytes(
    ftp: FTPClient,
    meeting: Meeting,
    code: str,
    fetch_url: IndexFetcher,
) -> bytes | None:
    """Return the rich-metadata index XML for ``code``, or ``None``.

    Tries ITU's ``dms_pages`` web system over HTTPS (the live, authoritative
    source, so ``list`` always reflects newly submitted documents; see
    :func:`doctypes.index_url`), then an FTPS fetch. The index XMLs are
    generated by ITU's web frontend and are not normally on the FTPS server, so
    the web fetch is the one that usually succeeds."""
    try:
        data = fetch_url(doctypes.index_url(meeting, code))
        if data:
            return data
    except Exception:  # noqa: BLE001
        pass  # offline, or an unexpected layout; fall back to FTPS
    filename = doctypes.index_filename(meeting, code)
    try:
        data = ftps.fetch_bytes(ftp, paths.remote_index_path(meeting, filename))
    except Exception:  # noqa: BLE001
        return None
    return data or None


def _rows_from_listing(
    ftp: FTPClient, meeting: Meeting, code: str, subgroup: str | None
) -> list[DocRecord]:
    """Fallback listing: derive rows from the FTPS directory listing of a type.

    Used when no index XML is available. Metadata is limited to what the
    filename carries (document number); one row per document number.
    """
    rows: list[DocRecord] = []
    seen_numbers: set[str] = set()
    for root in doctypes.mirror_roots(meeting, [(code, subgroup)]):
        for remote_path, _size in ftps.walk(ftp, root.remote_root):
            name = remote_path.rsplit("/", 1)[-1]
            if not keep_file(name, DEFAULT_LANGUAGES):
                continue
            m = _DOC_NUMBER.search(name)
            number = m.group(1) if m else ""
            key = number or name
            if key in seen_numbers:
                continue
            seen_numbers.add(key)
            sub = root.remote_root.rsplit("/", 1)[-1] if code == "TD" else ""
            rows.append(
                DocRecord(
                    type=code,
                    number=number,
                    title=name,
                    source="",
                    date="",
                    subgroup=sub,
                )
            )
    rows.sort(key=lambda r: r["number"])
    return rows


def list_documents(
    ftp: FTPClient,
    meeting: Meeting,
    types: list[tuple[str, str | None]] | None,
    *,
    fetch_url: IndexFetcher = catalog.download,
) -> tuple[list[DocRecord], bool]:
    """List documents for the selected types (default all).

    Prefers each type's index XML (rich metadata), fetched from ITU's web
    system over HTTPS; falls back to a plain FTPS directory listing when no
    index is available. Returns ``(rows, from_index)`` where ``from_index`` is
    ``False`` if any type used the listing fallback. ``fetch_url`` is injectable
    for testing.
    """
    selected = types or [(code, None) for code in doctypes.ITU_T_TYPES]
    seen: set[str] = set()
    rows: list[DocRecord] = []
    from_index = True
    for code, subgroup in selected:
        if code in seen:
            continue
        seen.add(code)
        data = _load_index_bytes(ftp, meeting, code, fetch_url)
        if data is not None:
            for row in parse_index_xml(data, code):
                if subgroup and row["subgroup"].lower() != subgroup.lower():
                    continue
                rows.append(row)
        else:
            from_index = False
            rows.extend(_rows_from_listing(ftp, meeting, code, subgroup))
    return rows, from_index

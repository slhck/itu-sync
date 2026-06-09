"""Document-type registry: the one place that knows the per-sector layout.

For ITU-T (confirmed against a real synced tree) types map to subfolders under
``FTP_path`` and to an index XML at the docs root:

- ``C``   Contributions       -> ``c/ties/``           index ``<prefix>-C.xml``
- ``R``   Reports             -> ``r/ties/``           index ``<prefix>-R.xml``
- ``COL`` Collective Letters  -> ``col/ties/``         index ``<prefix>-COL.xml``
- ``TD``  Temporary Documents -> ``<yymmdd>/td/ties/`` index ``<prefix>-<date>-TD.xml``

``LS`` (liaison statements) is not a folder of its own: liaison statements are
Temporary Documents distinguished only by an ``LS/i`` (incoming) or ``LS/o``
(outgoing) prefix in their index-XML title (see :func:`liaison_marking`). They
live in the TD tree and have ordinary TD filenames, so selecting ``LS`` mirrors
the TD tree restricted to the liaison subset (the orchestration layer applies
that filter by document number; see :func:`liaison_mirror_root`).

Other sectors use different layouts; v1 mirrors their whole remote path as a
single "all" type (see :func:`mirror_roots`).
"""

from __future__ import annotations

import re

from itu_sync.types import DocType, Meeting, MirrorRoot

DEFAULT_SERVER = "ties"
"""The "ITU Headquarters" document server; the only one needed for v1."""

DMS_PAGES_BASE = "https://www.itu.int/dms_pages"
"""Base of ITU's web system that serves the per-type index XMLs over HTTPS."""

TD_SUBGROUPS: tuple[str, ...] = ("gen", "plen", "wp1", "wp2", "wp3", "wp4")

# ITU-T type registry, in display order.
ITU_T_TYPES: dict[str, DocType] = {
    "C": DocType("C", "Contributions"),
    "R": DocType("R", "Reports"),
    "COL": DocType("COL", "Collective Letters"),
    "TD": DocType("TD", "Temporary Documents"),
}

LIAISON_CODE = "LS"
"""The virtual type for liaison statements (a TD subset; see module docstring)."""

LIAISON_DIRECTIONS: dict[str, str] = {"i": "incoming", "o": "outgoing"}
"""Liaison direction qualifiers: ``i`` = incoming, ``o`` = outgoing."""

# A liaison statement is a TD whose English title starts with "LS/i" or "LS/o"
# (optionally followed by a "/r" reply suffix). The filename carries no marker.
_LIAISON_TITLE = re.compile(r"^\s*LS/([io])\b", re.IGNORECASE)


def liaison_marking(title: str) -> str | None:
    """Return ``"LS/i"`` or ``"LS/o"`` if ``title`` is a liaison statement.

    Liaison statements appear in the TD index XML as ordinary Temporary
    Documents whose English title begins with ``LS/i`` (incoming) or ``LS/o``
    (outgoing); reply variants (``LS/i/r``, ``LS/o/r``) keep their direction.
    Returns ``None`` for any other title.
    """
    m = _LIAISON_TITLE.match(title or "")
    return f"LS/{m.group(1).lower()}" if m else None


def parse_type_spec(spec: str | None) -> list[tuple[str, str | None]]:
    """Parse a ``--type`` value into ``(code, qualifier)`` pairs.

    Accepts case-insensitive, comma-separated codes with an optional qualifier:
    a subgroup after ``:`` for ``TD`` (``TD:gen``), or a direction after ``/``
    for ``LS`` — ``i`` (incoming) or ``o`` (outgoing), written ``LS/i`` /
    ``LS/o`` to match ITU's own notation. ``--type C,R`` ->
    ``[("C", None), ("R", None)]``; ``--type TD:gen`` -> ``[("TD", "gen")]``;
    ``--type LS/o`` -> ``[("LS", "o")]``. ``None``/empty means all types.
    """
    if not spec:
        return []
    pairs: list[tuple[str, str | None]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        # Liaison statements take a direction after a slash: LS, LS/i, LS/o.
        if part.upper() == LIAISON_CODE or part.upper().startswith(f"{LIAISON_CODE}/"):
            _, _, direction = part.partition("/")
            direction = direction.strip().lower() or None
            if direction is not None and direction not in LIAISON_DIRECTIONS:
                raise ValueError(
                    "Liaison direction must be 'i' or 'o' (e.g. LS/i), "
                    f"got {direction!r}."
                )
            pairs.append((LIAISON_CODE, direction))
            continue
        # Other types take an optional subgroup after a colon: TD, TD:gen.
        code, _, sub = part.partition(":")
        code = code.strip().upper()
        if code == LIAISON_CODE:
            raise ValueError(
                "Use a slash for the liaison direction: 'LS/i' or 'LS/o', not a colon."
            )
        if code not in ITU_T_TYPES:
            valid = ", ".join([*ITU_T_TYPES, LIAISON_CODE])
            raise ValueError(f"Unknown document type {code!r}. Valid types: {valid}")
        pairs.append((code, sub.strip().lower() or None))
    return pairs


def _td_subfolder(meeting: Meeting, subgroup: str | None, server: str) -> str:
    base = f"{meeting.td_date}/td/{server}"
    return f"{base}/{subgroup}" if subgroup else base


def _type_subfolder(
    code: str, subgroup: str | None, meeting: Meeting, server: str
) -> str:
    if code == "TD":
        return _td_subfolder(meeting, subgroup, server)
    return f"{code.lower()}/{server}"


def index_filename(meeting: Meeting, code: str) -> str:
    """Return the per-type index XML filename at the docs root."""
    prefix = meeting.doc_prefix
    if not prefix:
        raise ValueError(
            f"No document prefix known for {meeting.meeting_code}; "
            f"cannot build the {code} index filename."
        )
    if code == "TD":
        return f"{prefix}-{meeting.td_date}-TD.xml"
    return f"{prefix}-{code}.xml"


def index_url(meeting: Meeting, code: str) -> str:
    """Return the public HTTPS URL of a per-type index XML.

    The per-type index XMLs are generated by ITU's web frontend and are *not*
    on the FTPS document server; the old app fetched them from the ``dms_pages``
    web system, which serves them over plain HTTPS with no authentication, e.g.
    ``https://www.itu.int/dms_pages/itu-t/md/25/SG12/c/T25-SG12-C.xml``.

    The study-period year (``25``) and group (``SG12``) come from the document
    prefix (``T25-SG12``); the type maps to a lowercase subfolder (``c``, ``r``,
    ``col``, ``td``).
    """
    prefix = meeting.doc_prefix
    if not prefix:
        raise ValueError(
            f"No document prefix known for {meeting.meeting_code}; "
            f"cannot build the {code} index URL."
        )
    head, _, group = prefix.partition("-")  # "T25-SG12" -> "T25", "SG12"
    m = re.search(r"\d{2,}", head)
    year = m.group(0) if m else head
    sector_slug = meeting.sector.lower()  # "ITU-T" -> "itu-t"
    return (
        f"{DMS_PAGES_BASE}/{sector_slug}/md/{year}/{group}/"
        f"{code.lower()}/{index_filename(meeting, code)}"
    )


def liaison_mirror_root(
    meeting: Meeting, *, server: str = DEFAULT_SERVER, label: str = LIAISON_CODE
) -> MirrorRoot:
    """Remote/local root for liaison statements: the meeting's TD tree.

    Liaison statements are Temporary Documents (see :func:`liaison_marking`), so
    this returns the TD tree and liaison files land in the same place as TDs.
    The filename carries no ``LS`` marker, so this root is only meaningful
    together with a document-number filter applied by the caller; on its own it
    is just the full TD tree.
    """
    sub = _td_subfolder(meeting, None, server)
    ftp_path = meeting.ftp_paths[0].rstrip("/") if meeting.ftp_paths else ""
    return MirrorRoot(remote_root=f"{ftp_path}/{sub}", local_relprefix=sub, label=label)


def mirror_roots(
    meeting: Meeting,
    types: list[tuple[str, str | None]] | None = None,
    *,
    server: str = DEFAULT_SERVER,
) -> list[MirrorRoot]:
    """Resolve a meeting (and optional type set) to remote roots to mirror.

    With no types, mirror the whole remote path(s). For ITU-T with types, mirror
    each type's subfolder. Sectors other than ITU-T ignore type filtering and
    mirror their whole remote path(s) (preserving the remote layout locally).
    """
    roots: list[MirrorRoot] = []

    if meeting.sector == "ITU-R" or not meeting.doc_prefix:
        # Non-ITU-T layout (or unknown): mirror each remote path wholesale,
        # preserving the remote structure under the local base.
        for path in meeting.ftp_paths:
            rel = path.strip("/")
            roots.append(
                MirrorRoot(
                    remote_root=path.rstrip("/"), local_relprefix=rel, label="all"
                )
            )
        return roots

    ftp_path = meeting.ftp_paths[0].rstrip("/") if meeting.ftp_paths else ""

    if not types:
        # Whole-FTP_path mirror; remote layout preserved relative to FTP_path.
        return [MirrorRoot(remote_root=ftp_path, local_relprefix="", label="all")]

    for code, qualifier in types:
        if code == LIAISON_CODE:
            label = LIAISON_CODE if not qualifier else f"LS/{qualifier}"
            roots.append(liaison_mirror_root(meeting, server=server, label=label))
            continue
        sub = _type_subfolder(code, qualifier, meeting, server)
        roots.append(
            MirrorRoot(
                remote_root=f"{ftp_path}/{sub}",
                local_relprefix=sub,
                label=code if not qualifier else f"{code}:{qualifier}",
            )
        )
    return roots

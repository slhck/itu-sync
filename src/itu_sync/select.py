"""Resolve the shared meeting-selection flags to a single ``Meeting``.

Selection precedence: filter by sector and group, then ``--latest`` or
``--meeting``; if still ambiguous and interactive, show a picker; otherwise
raise so non-interactive callers fail with a clear message.
"""

from __future__ import annotations

import re
import sys

from itu_sync.types import Meeting


class SelectionError(RuntimeError):
    """Raised when the selection flags do not resolve to a single meeting."""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def match_group(meeting: Meeting, group: str) -> bool:
    """Loose match: ``SG12``, ``sg 12`` and ``12`` all select ``ITU-T SG 12``."""
    return _norm(group) in _norm(meeting.meeting_code)


def match_filter(meeting: Meeting, text: str) -> bool:
    """Substring filter for the ``meetings`` listing, space-insensitive so
    ``SG12`` matches ``ITU-T SG 12``. Matches the label or the meeting code."""
    needle = _norm(text)
    return needle in _norm(meeting.place_date) or needle in _norm(meeting.meeting_code)


def match_meeting(meeting: Meeting, needle: str) -> bool:
    """Match a substring of the place/date label or the ``yymmdd`` date."""
    n = needle.strip().lower()
    return n in meeting.place_date.lower() or n == meeting.td_date


def filter_meetings(
    meetings: list[Meeting],
    sector: str | None = None,
    group: str | None = None,
) -> list[Meeting]:
    out = meetings
    if sector:
        out = [m for m in out if m.sector == sector]
    if group:
        out = [m for m in out if match_group(m, group)]
    return out


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def resolve_meeting(
    meetings: list[Meeting],
    *,
    sector: str | None = None,
    group: str | None = None,
    latest: bool = False,
    meeting: str | None = None,
    interactive: bool | None = None,
) -> Meeting:
    """Resolve the flags to a single meeting, or raise :class:`SelectionError`."""
    if latest and meeting:
        raise SelectionError("--latest and --meeting are mutually exclusive.")

    candidates = filter_meetings(meetings, sector, group)
    if not candidates:
        raise SelectionError(f"No meetings match sector={sector!r} group={group!r}.")

    if meeting:
        candidates = [m for m in candidates if match_meeting(m, meeting)]
        if not candidates:
            raise SelectionError(f"No meeting matches {meeting!r}.")
        if len(candidates) == 1:
            return candidates[0]

    # Candidates are pre-sorted newest-first by the catalog loader.
    if latest:
        return candidates[0]
    if len(candidates) == 1:
        return candidates[0]

    if interactive is None:
        interactive = is_interactive()
    if interactive:
        return pick_meeting(candidates)

    raise SelectionError(
        "Selection is ambiguous; pass --latest or --meeting "
        f"(or run interactively). {len(candidates)} meetings match."
    )


def pick_meeting(meetings: list[Meeting]) -> Meeting:
    """Interactive picker with type-to-narrow substring filtering."""
    import click

    current = meetings
    while True:
        for i, m in enumerate(current[:40], 1):
            click.echo(
                f"  [{i:2}] {m.sector}  {(m.start_date or '')[:10]}  {m.place_date}"
            )
        if len(current) > 40:
            click.echo(f"  ... and {len(current) - 40} more; type to narrow")
        choice = click.prompt(
            "Select a number, or type text to filter (q to quit)",
            default="",
            show_default=False,
        ).strip()
        if choice.lower() == "q":
            raise SelectionError("Selection cancelled.")
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= min(len(current), 40):
                return current[idx - 1]
            click.echo("Out of range.")
            continue
        if choice:
            narrowed = [
                m
                for m in meetings
                if choice.lower() in m.place_date.lower()
                or choice.lower() in m.meeting_code.lower()
            ]
            current = narrowed or current
        elif len(current) == 1:
            return current[0]

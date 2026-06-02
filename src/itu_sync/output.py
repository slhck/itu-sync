"""Rich output helpers: meeting/document tables, progress, status lines."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

from itu_sync.types import DocRecord, Meeting

console = Console()
error_console = Console(stderr=True)


def truncate_middle(text: str, width: int) -> str:
    """Shorten ``text`` to ``width`` columns, eliding the middle with ``…``.

    Used to keep a progress line's filename column a constant width so the bar
    does not jump as filenames of different lengths scroll past. The middle is
    dropped rather than the end so the document prefix and extension stay
    visible.
    """
    if width <= 0 or len(text) <= width:
        return text
    if width == 1:
        return "…"
    keep = width - 1
    head = (keep + 1) // 2
    tail = keep - head
    return text[:head] + "…" + (text[-tail:] if tail else "")


def print_success(message: str) -> None:
    console.print(f"[green]✓[/green] {message}")


def print_error(message: str) -> None:
    error_console.print(f"[red]✗[/red] {message}")


def print_warning(message: str) -> None:
    console.print(f"[yellow]![/yellow] {message}")


def print_info(message: str) -> None:
    console.print(f"[blue]i[/blue] {message}")


def output_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))


def meetings_table(meetings: list[Meeting], title: str | None = None) -> None:
    if not meetings:
        console.print("[dim]No meetings found[/dim]")
        return
    table = Table(title=title)
    table.add_column("Sector", style="cyan", no_wrap=True)
    table.add_column("Start", style="green", no_wrap=True)
    table.add_column("Meeting")
    for m in meetings:
        table.add_row(
            m.sector, (m.start_date or "")[:10], m.place_date or m.meeting_code
        )
    console.print(table)


def meetings_json(meetings: list[Meeting]) -> None:
    output_json(
        [
            {
                "sector": m.sector,
                "meeting_code": m.meeting_code,
                "place_date": m.place_date,
                "start_date": m.start_date,
                "td_date": m.td_date,
                "ftp_paths": m.ftp_paths,
                "working_folder": m.working_folder,
                "local_path_sg": m.local_path_sg,
                "doc_prefix": m.doc_prefix,
            }
            for m in meetings
        ]
    )


def documents_table(rows: list[DocRecord], title: str | None = None) -> None:
    if not rows:
        console.print("[dim]No documents found[/dim]")
        return
    table = Table(title=title)
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("No.", style="green", no_wrap=True)
    table.add_column("Title")
    table.add_column("Source", style="magenta")
    table.add_column("Date", no_wrap=True)
    for r in rows:
        table.add_row(r["type"], r["number"], r["title"], r["source"], r["date"])
    console.print(table)

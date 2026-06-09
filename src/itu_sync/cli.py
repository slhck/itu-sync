"""click entry point and subcommands. Thin: delegates to the modules."""

from __future__ import annotations

import ftplib
import os
import sys
from pathlib import Path

import click
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Column

from itu_sync import __version__, catalog, doctypes, ftps, output, select, sync
from itu_sync.config import DEFAULT_DRIVE, ENV_PASSWORD, Config, read_old_ini
from itu_sync.language import LANGUAGE_CODES, LANGUAGE_NAMES
from itu_sync.select import SelectionError
from itu_sync.types import FileTask, Meeting


class Context:
    """Shared CLI state."""

    def __init__(self) -> None:
        self.config = Config()
        self.no_refresh = False
        self.verify_cert = False
        self.drive_override: str | None = None

    @property
    def drive(self) -> str:
        return self.drive_override or self.config.get_drive()

    def base_folder(self) -> Path:
        return Path(self.drive)

    def ensure_catalogs(self, sectors: list[str] | None = None) -> None:
        if self.no_refresh:
            return
        failed = catalog.refresh_catalogs(
            self.base_folder(), sectors, on_warning=output.print_warning
        )
        if failed:
            output.print_warning(f"Using cached catalogs for: {', '.join(failed)}")


pass_context = click.make_pass_decorator(Context, ensure=True)


@click.group()
@click.version_option(version=__version__, prog_name="itu-sync")
@click.option(
    "--no-refresh", is_flag=True, help="Use cached catalogs; skip the download."
)
@click.option(
    "--drive", type=str, default=None, help="Local base folder (overrides config)."
)
@click.option(
    "--verify-cert/--no-verify-cert",
    default=False,
    help="Verify the FTPS server certificate (default: do not verify).",
)
@pass_context
def main(ctx: Context, no_refresh: bool, drive: str | None, verify_cert: bool) -> None:
    """itu-sync — sync ITU meeting documents from the terminal."""
    ctx.no_refresh = no_refresh
    ctx.verify_cert = verify_cert
    ctx.drive_override = drive


# ---------------------------------------------------------------------------
# First-run setup
# ---------------------------------------------------------------------------


def _ask(question) -> str:
    """Run a questionary prompt, treating Ctrl-C/Esc as an abort."""
    answer = question.ask()
    if answer is None:
        raise click.Abort()
    return answer


def _check_login(ctx: Context, user: str, password: str) -> str | None:
    """Validate TIES credentials against the FTPS server.

    Returns ``None`` if the login succeeds, the sentinel ``"rejected"`` if the
    server refused the account or password, or an error description for a
    connection problem that prevented verification.
    """
    try:
        ftps.check_login(user, password, verify=ctx.verify_cert)
    except ftplib.error_perm:
        return "rejected"
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    return None


def run_setup(ctx: Context) -> None:
    """Guided first-run setup: prompt for every setting and store it.

    Walks through the folder, sector, language, TIES account, and (optionally)
    password. Fixed choices (sector, language) are arrow-key menus; free-text
    fields keep their defaults in brackets. If the old macOS app's settings file
    is present, its account and folder are offered as defaults, but nothing
    about the old app is required.
    """
    import questionary

    cfg = ctx.config
    output.print_info("Let's set up itu-sync. Use the arrow keys to choose options.")

    old = read_old_ini()  # optional convenience; absent on a fresh machine

    drive_default = cfg.get("drive") or old.get("drive") or DEFAULT_DRIVE
    drive = _ask(
        questionary.path("Folder to store documents in:", default=drive_default)
    )
    cfg.set_drive(os.path.expanduser(drive.strip()))

    sector = _ask(
        questionary.select(
            "Default sector:",
            choices=list(catalog.CATALOG_FILES),
            default=cfg.get_sector(),
        )
    )
    cfg.set_sector(sector)

    lang_choices = [
        questionary.Choice(
            title=f"{code} — {LANGUAGE_NAMES.get(code, code)}", value=code
        )
        for code in sorted(LANGUAGE_CODES)
    ]
    language = _ask(
        questionary.select(
            "Default language to download:",
            choices=lang_choices,
            default=cfg.get_language(),
        )
    )
    cfg.set_language(language)

    user_default = cfg.get_username() or old.get("username") or ""
    while True:
        user = _ask(
            questionary.text("TIES account (username):", default=user_default)
        ).strip()
        if user:
            cfg.set_username(user)

        if not _ask(questionary.confirm("Store your TIES password now?", default=True)):
            break
        password = _ask(questionary.password("TIES password:"))
        if not password:
            break
        if not user:
            cfg.set_password(password)
            break

        output.print_info("Checking your TIES credentials…")
        result = _check_login(ctx, user, password)
        if result is None:
            cfg.set_password(password)
            output.print_success("Credentials verified.")
            break
        if result == "rejected":
            output.print_error("Login was rejected — the account or password is wrong.")
            if _ask(
                questionary.confirm("Re-enter your account and password?", default=True)
            ):
                user_default = user
                continue
            break
        # A connection problem, not a wrong password: keep what was entered.
        output.print_warning(
            f"Could not verify right now ({result}). Storing it anyway."
        )
        cfg.set_password(password)
        break

    cfg.mark_configured()
    output.print_success(
        "Setup complete. Change any setting later with 'itu-sync config'."
    )


def ensure_configured(ctx: Context) -> None:
    """Run the guided setup on first use, when interactive and nothing is set."""
    if ctx.config.is_configured():
        return
    if select.is_interactive():
        run_setup(ctx)


# ---------------------------------------------------------------------------
# Shared meeting-selection options
# ---------------------------------------------------------------------------


def selection_options(func):
    func = click.option(
        "--sector", type=click.Choice(list(catalog.CATALOG_FILES)), default=None
    )(func)
    func = click.option(
        "--group",
        type=str,
        default=None,
        help="Study group, matched loosely (e.g. SG12).",
    )(func)
    func = click.option(
        "--latest", is_flag=True, help="Pick the most recent matching meeting."
    )(func)
    func = click.option(
        "--meeting",
        "meeting_sel",
        type=str,
        default=None,
        help="Substring of the label, or yymmdd.",
    )(func)
    return func


def _resolve(ctx: Context, sector, group, latest, meeting_sel) -> Meeting:
    ensure_configured(ctx)
    sector = sector or ctx.config.get_sector()
    ctx.ensure_catalogs([sector])
    meetings = catalog.load_meetings(ctx.base_folder(), sector)
    try:
        chosen = select.resolve_meeting(
            meetings,
            sector=sector,
            group=group,
            latest=latest,
            meeting=meeting_sel,
        )
    except SelectionError as exc:
        output.print_error(str(exc))
        sys.exit(2)
    ctx.config.set_sector(sector)
    return chosen


def _parse_types(type_spec: str | None) -> list[tuple[str, str | None]]:
    try:
        return doctypes.parse_type_spec(type_spec)
    except ValueError as exc:
        output.print_error(str(exc))
        sys.exit(2)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _credentials(ctx: Context, user_override: str | None) -> tuple[str, str]:
    user = user_override or ctx.config.get_username()
    if not user:
        if not select.is_interactive():
            output.print_error(
                "No TIES account configured. Run 'itu-sync config' or pass --user."
            )
            sys.exit(2)
        user = click.prompt("TIES account")
        if click.confirm("Save this account?", default=True):
            ctx.config.set_username(user)

    password = ctx.config.get_password()
    if not password:
        if not select.is_interactive():
            output.print_error(
                f"No TIES password found. Set {ENV_PASSWORD} or run 'itu-sync config'."
            )
            sys.exit(2)
        password = click.prompt("TIES password", hide_input=True)
        if click.confirm("Save the password to the keyring?", default=True):
            ctx.config.set_password(password)
    return user, password


# ---------------------------------------------------------------------------
# meetings
# ---------------------------------------------------------------------------


@main.command()
@selection_options
@click.option(
    "--filter",
    "filter_text",
    type=str,
    default=None,
    help="Substring filter on the label.",
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@pass_context
def meetings(
    ctx: Context, sector, group, latest, meeting_sel, filter_text, as_json
) -> None:
    """List meetings, newest first."""
    ensure_configured(ctx)
    sectors = [sector] if sector else None
    ctx.ensure_catalogs(sectors)
    items = catalog.load_all_meetings(ctx.base_folder(), sectors)
    items = select.filter_meetings(items, sector, group)
    if filter_text:
        items = [m for m in items if select.match_filter(m, filter_text)]
    if latest and items:
        items = [items[0]]
    if as_json:
        output.meetings_json(items)
    else:
        output.meetings_table(items, title="ITU Meetings")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@main.command()
@selection_options
@click.option(
    "--type",
    "type_spec",
    type=str,
    default=None,
    help="Comma-separated types (C,R,COL,TD,LS). LS = liaison statements; "
    "use LS/i / LS/o for incoming/outgoing. Default: all.",
)
@click.option(
    "--lang",
    default=None,
    help="Language to download (default: the configured language, usually en).",
)
@click.option("--user", "user_override", type=str, default=None, help="TIES account.")
@click.option("--workers", type=int, default=4, help="Parallel download connections.")
@click.option(
    "--dry-run", is_flag=True, help="List what would be downloaded; write nothing."
)
@pass_context
def sync_cmd(
    ctx,
    sector,
    group,
    latest,
    meeting_sel,
    type_spec,
    lang,
    user_override,
    workers,
    dry_run,
) -> None:
    """Sync (mirror) a meeting's documents over FTPS, English only."""
    chosen = _resolve(ctx, sector, group, latest, meeting_sel)
    types = _parse_types(type_spec)
    languages = frozenset({(lang or ctx.config.get_language())[:1].upper()})

    from itu_sync.paths import local_base

    base = local_base(ctx.drive, chosen)
    output.print_info(f"Meeting: {chosen.place_date}")
    for root in doctypes.mirror_roots(chosen, types):
        output.print_info(
            f"  remote {root.remote_root}  ->  local {base / root.local_relprefix}"
        )
    if any(code == doctypes.LIAISON_CODE for code, _ in types):
        output.print_info(
            "  (LS = liaison statements: the TD subset whose title is marked "
            "LS/i or LS/o)"
        )

    user, password = _credentials(ctx, user_override)

    def connect_factory():
        return ftps.connect(user, password, verify=ctx.verify_cert)

    output.print_info("Connecting and scanning the remote tree…")
    try:
        scan_ftp = connect_factory()
    except Exception as exc:  # noqa: BLE001
        output.print_error(f"Connection failed: {exc}")
        sys.exit(1)
    try:
        plan = sync.build_plan(
            scan_ftp,
            chosen,
            ctx.drive,
            types,
            languages,
            on_warning=output.print_warning,
        )
    finally:
        try:
            scan_ftp.quit()
        except Exception:  # noqa: BLE001
            scan_ftp.close()

    output.print_info(
        f"{len(plan.all_tasks)} files matched; "
        f"{len(plan.to_download)} to download "
        f"({plan.download_bytes / 1e6:.1f} MB), {len(plan.skipped)} already present."
    )

    if dry_run:
        for task in plan.to_download:
            output.console.print(f"[dim]would download[/dim] {task.local_path}")
        output.print_success("Dry run complete; nothing was written.")
        return

    if not plan.to_download:
        output.print_success("Everything is already up to date.")
        return

    name_width = 36
    total_files = len(plan.to_download)
    count_width = len(str(total_files))

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Downloading"),
        BarColumn(bar_width=30),
        TextColumn("[green]{task.fields[files]}"),
        DownloadColumn(),
        TimeRemainingColumn(),
        # Fixed-width, no-wrap filename last so the bar never shifts as
        # filenames of different lengths scroll past.
        TextColumn(
            "[dim]{task.fields[name]}",
            table_column=Column(width=name_width, no_wrap=True),
        ),
        console=output.console,
    ) as progress:
        done = 0
        bar = progress.add_task(
            "Downloading",
            total=plan.download_bytes,
            files=f"{0:>{count_width}}/{total_files}",
            name="",
        )

        def on_progress(status: str, task: FileTask) -> None:
            nonlocal done
            if status == "downloaded":
                done += 1
                progress.update(
                    bar,
                    advance=task.size,
                    files=f"{done:>{count_width}}/{total_files}",
                    name=output.truncate_middle(task.local_path.name, name_width),
                )
            elif status == "failed":
                progress.console.print(f"[red]failed[/red] {task.remote_path}")

        summary = sync.download_plan(
            plan, connect_factory, workers=workers, progress=on_progress
        )

    output.print_success(
        f"Done. downloaded={summary.downloaded} skipped={summary.skipped} "
        f"failed={summary.failed} ({summary.bytes_downloaded / 1e6:.1f} MB)"
    )
    for failure in summary.failures:
        output.print_error(failure)
    if summary.failed:
        sys.exit(1)


main.add_command(sync_cmd, name="sync")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@main.command(name="list")
@selection_options
@click.option(
    "--type",
    "type_spec",
    type=str,
    default=None,
    help="Comma-separated types (C,R,COL,TD,LS). LS = liaison statements; "
    "use LS/i / LS/o for incoming/outgoing. Default: all.",
)
@click.option("--user", "user_override", type=str, default=None, help="TIES account.")
@click.option("--json", "as_json", is_flag=True, help="Output JSON.")
@click.option("--count", is_flag=True, help="Print only the document count.")
@pass_context
def list_cmd(
    ctx, sector, group, latest, meeting_sel, type_spec, user_override, as_json, count
) -> None:
    """List a meeting's documents from the per-type index XML (no downloads)."""
    chosen = _resolve(ctx, sector, group, latest, meeting_sel)
    types = _parse_types(type_spec)
    user, password = _credentials(ctx, user_override)

    try:
        ftp = ftps.connect(user, password, verify=ctx.verify_cert)
    except Exception as exc:  # noqa: BLE001
        output.print_error(f"Connection failed: {exc}")
        sys.exit(1)
    try:
        rows, from_index = sync.list_documents(ftp, chosen, types)
    finally:
        try:
            ftp.quit()
        except Exception:  # noqa: BLE001
            ftp.close()

    if count:
        output.console.print(f"{len(rows)} documents")
        return
    if as_json:
        output.output_json(rows)
    else:
        if not from_index:
            output.print_warning(
                "No index XML available; showing a directory listing "
                "(document number and filename only, no title/source)."
            )
        output.documents_table(rows, title=f"Documents — {chosen.place_date}")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@main.command()
@click.option("--setup", is_flag=True, help="Run the guided setup again.")
@click.option("--user", type=str, default=None, help="Set the TIES account.")
@click.option(
    "--drive", "drive_opt", type=str, default=None, help="Set the local base folder."
)
@click.option(
    "--sector",
    "sector_opt",
    type=click.Choice(list(catalog.CATALOG_FILES)),
    default=None,
    help="Set the default sector.",
)
@click.option(
    "--language",
    "language_opt",
    type=click.Choice(sorted(LANGUAGE_CODES)),
    default=None,
    help="Set the default language to download.",
)
@click.option(
    "--password", is_flag=True, help="Prompt for and store the TIES password."
)
@click.option("--show", is_flag=True, help="Show current settings.")
@pass_context
def config(
    ctx: Context,
    setup,
    user,
    drive_opt,
    sector_opt,
    language_opt,
    password,
    show,
) -> None:
    """Set or show the TIES account, folder, sector, language, and password.

    With no options on a fresh install, this launches the guided setup.
    """
    cfg = ctx.config

    if setup:
        if not select.is_interactive():
            output.print_error("The guided setup needs an interactive terminal.")
            sys.exit(2)
        run_setup(ctx)
        return

    changed = False
    if user:
        cfg.set_username(user)
        output.print_success(f"TIES account set to {user}")
        changed = True
    if drive_opt:
        cfg.set_drive(os.path.expanduser(drive_opt))
        output.print_success(f"Folder set to {cfg.get_drive()}")
        changed = True
    if sector_opt:
        cfg.set_sector(sector_opt)
        output.print_success(f"Default sector set to {sector_opt}")
        changed = True
    if language_opt:
        cfg.set_language(language_opt)
        output.print_success(f"Default language set to {language_opt}")
        changed = True
    if password:
        pw = click.prompt("TIES password", hide_input=True)
        account = cfg.get_username()
        if account:
            output.print_info("Checking your TIES credentials…")
            result = _check_login(ctx, account, pw)
            if result == "rejected":
                output.print_error(
                    "Login was rejected — the account or password is wrong."
                )
                if not click.confirm("Store this password anyway?", default=False):
                    sys.exit(2)
            elif result is not None:
                output.print_warning(
                    f"Could not verify right now ({result}). Storing it anyway."
                )
            else:
                output.print_success("Credentials verified.")
        else:
            output.print_warning(
                "No account set yet, so the password can't be verified. "
                "Set one with 'itu-sync config --user <account>'."
            )
        cfg.set_password(pw)
        output.print_success("Password stored in the keyring.")
        changed = True

    # A fresh install with no flags: jump straight into the guided setup.
    if not changed and not show and not cfg.is_configured():
        if select.is_interactive():
            run_setup(ctx)
            return
        output.print_warning(
            "Not configured yet. Run 'itu-sync config --setup' interactively, "
            "or set --user/--drive/--sector/--language and the password."
        )
        return

    if changed:
        cfg.mark_configured()

    if show or not changed:
        lang = cfg.get_language()
        output.console.print(
            f"TIES account  : {cfg.get_username() or '[dim]not set[/dim]'}"
        )
        output.console.print(f"Folder        : {cfg.get_drive()}")
        output.console.print(f"Default sector: {cfg.get_sector()}")
        output.console.print(
            f"Default lang  : {lang} ({LANGUAGE_NAMES.get(lang, lang)})"
        )
        pw_status = (
            "[green]stored[/green]"
            if cfg.has_password()
            else "[yellow]not set[/yellow]"
        )
        output.console.print(f"Password      : {pw_status}")


if __name__ == "__main__":
    main()

"""Configuration and credential management.

Non-secret settings live in ``~/.config/itu-sync/config.json``; the TIES
password lives in the system keyring (service ``itu-sync``). The tool does not
depend on the old app: on first run the interactive setup prompts for every
setting. If the old app's settings file happens to be present, its account and
folder are offered as defaults, but nothing is required.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import keyring

SERVICE_NAME = "itu-sync"
PASSWORD_KEY = "ties_password"

ENV_USER = "ITU_TIES_USER"
ENV_PASSWORD = "ITU_TIES_PASSWORD"  # noqa: S105

DEFAULT_DRIVE = str(Path.home() / "Documents" / "ITU")
OLD_INI_PATH = Path(DEFAULT_DRIVE) / "ITU-Sync-new.ini"

# Keys that delimit values in the old app's non-standard one-line settings file.
_OLD_INI_KEYS = (
    "license",
    "username",
    "pass",
    "drive",
    "meeting",
    "sector",
    "Meeting_code",
    "ITU_Sector",
    "SG_No_Period",
    "SG_Email",
    "SG_Title",
    "SG_Homepage",
    "workingFolder",
    "Contribution_start_date",
    "FTP_root",
    "FTP_path",
    "EPUB_FTP_path",
    "bodyHtml",
    "web_room_assign",
    "TD_date",
    "syncEN",
    "syncAR",
    "syncCH",
    "syncES",
    "syncFR",
    "syncRU",
)


def read_old_ini(path: Path = OLD_INI_PATH) -> dict[str, str]:
    """Best-effort read of ``drive`` and ``username`` from the old settings file.

    The file is a run of ``key=value`` pairs where the known keys act as
    delimiters; observed files separate them either with newlines or by simple
    concatenation, so we stop a value at the next known key, a newline, or the
    end. We read only the non-secret fields; the obfuscated ``pass`` field is
    intentionally not decoded.
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return {}

    boundary = "|".join(re.escape(k) + "=" for k in _OLD_INI_KEYS)
    out: dict[str, str] = {}
    for key in ("drive", "username"):
        m = re.search(rf"{key}=(.*?)(?={boundary}|\n|$)", text, re.DOTALL)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


class Config:
    """Manages itu-sync settings and the TIES password."""

    def __init__(self) -> None:
        self.config_dir = Path.home() / ".config" / "itu-sync"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"

    # -- raw json ----------------------------------------------------------
    def _load(self) -> dict[str, str]:
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self, data: dict[str, str]) -> None:
        self.config_file.write_text(json.dumps(data, indent=2) + "\n")

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._load().get(key, default)

    def set(self, key: str, value: str) -> None:
        data = self._load()
        data[key] = value
        self._save(data)

    # -- first-run state ---------------------------------------------------
    def is_configured(self) -> bool:
        """True once the interactive setup has been completed at least once.

        The tool does not depend on the old app: a fresh install is simply
        "not configured" until the user runs setup (or sets things via the
        ``config`` command). A previously configured account (e.g. set in an
        earlier version) also counts, so existing users are not re-prompted.
        """
        return self.get("configured") == "true" or bool(self.get("username"))

    def mark_configured(self) -> None:
        self.set("configured", "true")

    # -- resolved settings -------------------------------------------------
    def get_drive(self) -> str:
        return self.get("drive") or DEFAULT_DRIVE

    def set_drive(self, drive: str) -> None:
        self.set("drive", drive)

    def get_username(self) -> str | None:
        return self.get("username") or os.environ.get(ENV_USER)

    def set_username(self, username: str) -> None:
        self.set("username", username)

    def get_sector(self) -> str:
        return self.get("sector") or "ITU-T"

    def set_sector(self, sector: str) -> None:
        self.set("sector", sector)

    def get_language(self) -> str:
        return self.get("language") or "E"

    def set_language(self, language: str) -> None:
        self.set("language", language[:1].upper())

    # -- password (keyring / env) -----------------------------------------
    def get_password(self) -> str | None:
        pw = keyring.get_password(SERVICE_NAME, PASSWORD_KEY)
        if pw:
            return pw
        return os.environ.get(ENV_PASSWORD)

    def set_password(self, password: str) -> None:
        keyring.set_password(SERVICE_NAME, PASSWORD_KEY, password)

    def delete_password(self) -> None:
        import keyring.errors

        try:
            keyring.delete_password(SERVICE_NAME, PASSWORD_KEY)
        except keyring.errors.PasswordDeleteError:
            pass

    def has_password(self) -> bool:
        return bool(self.get_password())

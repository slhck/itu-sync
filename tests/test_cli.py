"""Tests for CLI helpers that don't need a live server or a terminal."""

from __future__ import annotations

import ftplib
from pathlib import Path

import pytest

from itu_sync import cli


def _ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> cli.Context:
    monkeypatch.setenv("HOME", str(tmp_path))
    return cli.Context()


def test_check_login_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.ftps, "check_login", lambda *a, **k: None)
    assert cli._check_login(_ctx(tmp_path, monkeypatch), "user", "pw") is None


def test_check_login_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise ftplib.error_perm("530 Not logged in")

    monkeypatch.setattr(cli.ftps, "check_login", boom)
    assert cli._check_login(_ctx(tmp_path, monkeypatch), "user", "bad") == "rejected"


def test_check_login_connection_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(cli.ftps, "check_login", boom)
    result = cli._check_login(_ctx(tmp_path, monkeypatch), "user", "pw")
    assert result is not None
    assert result.startswith("error:")

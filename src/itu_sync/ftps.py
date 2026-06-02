"""Implicit FTPS client for ``confsynch.itu.int`` plus a recursive walk.

The ITU document server is Microsoft IIS FTP over implicit FTPS (TLS is
established on connect, port 990). Python's :class:`ftplib.FTP_TLS` only does
explicit FTPS, and IIS requires the data connection to reuse the control
connection's TLS session, so we subclass to handle both quirks.
"""

from __future__ import annotations

import ftplib
import io
import re
import ssl
from collections.abc import Callable, Iterator
from typing import Protocol

CONFSYNCH_HOST = "confsynch.itu.int"
CONFSYNCH_PORT = 990


class FTPClient(Protocol):
    """The subset of the FTP client interface that itu-sync relies on.

    Both :class:`ImplicitFTPS` and the test double satisfy this structurally,
    so the orchestration in ``sync.py`` need not depend on the concrete class.
    """

    def mlsd(
        self, path: str = ..., facts: list[str] = ...
    ) -> Iterator[tuple[str, dict[str, str]]]: ...

    def dir(self, *args: str | Callable[[str], object]) -> None: ...

    def size(self, filename: str) -> int | None: ...

    def retrbinary(
        self, cmd: str, callback: Callable[[bytes], object], blocksize: int = ...
    ) -> str: ...

    def quit(self) -> str: ...

    def close(self) -> None: ...


class ImplicitFTPS(ftplib.FTP_TLS):
    """FTP_TLS variant that does implicit FTPS and reuses the TLS session."""

    def __init__(self, *args, **kwargs) -> None:
        self._sock: ssl.SSLSocket | None = None
        super().__init__(*args, **kwargs)

    @property
    def sock(self) -> ssl.SSLSocket | None:
        return self._sock

    @sock.setter
    def sock(self, value: object) -> None:
        if value is not None and not isinstance(value, ssl.SSLSocket):
            # Implicit FTPS: wrap the control socket in TLS at connect time.
            value = self.context.wrap_socket(value, server_hostname=self.host)  # ty: ignore[invalid-argument-type]
        self._sock = value  # type: ignore[assignment]

    def ntransfercmd(self, cmd: str, rest: int | str | None = None):  # type: ignore[override]
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        # IIS requires the data connection to reuse the control TLS session.
        if self._prot_p and isinstance(self._sock, ssl.SSLSocket):  # ty: ignore[unresolved-attribute]
            conn = self.context.wrap_socket(
                conn,
                server_hostname=self.host,
                session=self._sock.session,
            )
        return conn, size


def make_context(verify: bool = False) -> ssl.SSLContext:
    """Build the TLS context. By default certificates are not verified, matching
    the old app's behavior."""
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def connect(
    user: str,
    password: str,
    *,
    host: str = CONFSYNCH_HOST,
    port: int = CONFSYNCH_PORT,
    verify: bool = False,
    timeout: float = 60.0,
) -> ImplicitFTPS:
    """Connect, log in, switch to protected passive mode, and return the client."""
    ftp = ImplicitFTPS(context=make_context(verify), timeout=timeout)
    ftp.connect(host, port)
    ftp.login(user, password)
    ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def check_login(
    user: str,
    password: str,
    *,
    host: str = CONFSYNCH_HOST,
    port: int = CONFSYNCH_PORT,
    verify: bool = False,
    timeout: float = 30.0,
) -> None:
    """Validate credentials by connecting and logging in, then disconnecting.

    Raises :class:`ftplib.error_perm` if the server rejects the account or
    password (a 530 reply), or another exception for a connection problem that
    prevented verification.
    """
    ftp = connect(user, password, host=host, port=port, verify=verify, timeout=timeout)
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        ftp.close()


def _mlsd_walk(ftp: FTPClient, root: str) -> Iterator[tuple[str, int]]:
    entries = list(ftp.mlsd(root))
    for name, facts in entries:
        if name in (".", ".."):
            continue
        entry_type = facts.get("type")
        if entry_type in ("cdir", "pdir"):
            continue
        path = f"{root.rstrip('/')}/{name}"
        if entry_type == "dir":
            try:
                yield from _mlsd_walk(ftp, path)
            except ftplib.error_perm:
                # Skip a subdirectory we cannot descend into (e.g. an IIS
                # phantom/virtual dir that LISTs but 550s when entered); a
                # failure on the root the caller asked for still propagates.
                continue
        elif entry_type == "file":
            yield path, int(facts.get("size", "0") or 0)


# IIS DOS-style LIST line, e.g.
#   "11-01-24  12:51PM       <DIR>          c"
#   "01-08-25  04:16PM               163363 T25-SG12-C-0001-E.docx"
_DOS_LINE = re.compile(
    r"^\d{2}-\d{2}-\d{2}\s+\d{1,2}:\d{2}[AP]M\s+(<DIR>|\d+)\s+(.+?)\s*$"
)


def _parse_list_line(line: str) -> tuple[str, bool, int] | None:
    """Parse one LIST line into ``(name, is_dir, size)``.

    Handles the IIS DOS-style format used by ``confsynch.itu.int`` and falls
    back to Unix ``ls -l`` style for portability. Returns ``None`` for lines
    that are neither (totals, blanks).
    """
    m = _DOS_LINE.match(line)
    if m:
        marker, name = m.group(1), m.group(2)
        if marker == "<DIR>":
            return name, True, 0
        return name, False, int(marker)

    parts = line.split(maxsplit=8)
    if len(parts) >= 9 and parts[0][0] in "-dl":
        name = parts[8]
        is_dir = parts[0].startswith("d")
        try:
            size = int(parts[4])
        except ValueError:
            size = 0
        return name, is_dir, size
    return None


def _list_walk(ftp: FTPClient, root: str) -> Iterator[tuple[str, int]]:
    lines: list[str] = []
    ftp.dir(root, lines.append)
    for line in lines:
        parsed = _parse_list_line(line.rstrip("\r\n"))
        if parsed is None:
            continue
        name, is_dir, size = parsed
        if name in (".", ".."):
            continue
        path = f"{root.rstrip('/')}/{name}"
        if is_dir:
            try:
                yield from _list_walk(ftp, path)
            except ftplib.error_perm:
                # Skip a subdirectory we cannot descend into (e.g. an IIS
                # phantom/virtual dir that LISTs but 550s when entered); a
                # failure on the root the caller asked for still propagates.
                continue
        else:
            yield path, size


def walk(ftp: FTPClient, root: str) -> Iterator[tuple[str, int]]:
    """Recursively yield ``(remote_path, size)`` for every file under ``root``.

    Prefers ``MLSD`` (IIS supports it); falls back to ``LIST`` parsing.
    """
    try:
        yield from _mlsd_walk(ftp, root)
    except ftplib.error_perm:
        yield from _list_walk(ftp, root)


def file_size(ftp: FTPClient, remote_path: str) -> int | None:
    """Return the remote file size via ``SIZE``, or ``None`` if unavailable."""
    try:
        return ftp.size(remote_path)
    except (ftplib.error_perm, ftplib.error_reply):
        return None


def fetch_bytes(ftp: FTPClient, remote_path: str) -> bytes:
    """Download a single small file (e.g. an index XML) into memory."""
    buf = io.BytesIO()
    ftp.retrbinary(f"RETR {remote_path}", buf.write)
    return buf.getvalue()

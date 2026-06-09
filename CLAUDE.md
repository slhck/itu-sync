# CLAUDE.md

Guidance for working in this repository.

## What this is

`itu-sync` replaces the broken `ITU-Sync` macOS LiveCode app. It downloads ITU
meeting catalogs over public HTTPS and mirrors a meeting's documents from
`confsynch.itu.int:990` over implicit FTPS, authenticated with a TIES account.
See `PRD.md` for the full specification and the reverse-engineering evidence.

## Layout

`src/` layout, package `itu_sync`, `uv_build` backend. Modules are split by
concern:

- `cli.py` — click entry point and subcommands; thin, delegates to the rest.
- `catalog.py` — download and parse the four meeting XML catalogs.
- `select.py` — resolve `--sector/--group/--latest/--meeting` to one meeting;
  the interactive picker.
- `doctypes.py` — the type registry (C/R/COL/TD) and per-sector layout. The one
  place that knows where each type lives under `FTP_path`. Also defines the
  virtual `LS` type: liaison statements are TDs marked `LS/i`/`LS/o` by title
  (`liaison_marking`), not a folder, so they mirror the TD tree filtered to that
  subset.
- `paths.py` — resolve a meeting to its local base and remote index path.
- `language.py` — the English/language filename filter.
- `ftps.py` — the `ImplicitFTPS` subclass, recursive `walk()`, single-file fetch.
- `sync.py` — UI-agnostic orchestration for sync (plan + parallel download) and
  list (fetch + parse index XML).
- `config.py` — `~/.config/itu-sync/` JSON + keyring; seeds defaults from the
  old app's INI.
- `output.py` — rich tables and status lines.
- `types.py` — `Meeting`, `DocType`, `MirrorRoot`, `FileTask`, `DocRecord`,
  `SyncSummary`.

## Conventions

- `from __future__ import annotations`, full type hints, `py.typed`.
- Keep `sync.py` UI-free: callers pass progress callbacks.
- The implicit-FTPS quirks (TLS at connect, reused TLS session on the data
  channel) live only in `ftps.ImplicitFTPS`; do not reinvent them elsewhere.
- The TIES password is keyring-only; never write it to disk. The old app's
  obfuscated `pass` field is intentionally not decoded.

## Checks

```bash
uv run ruff check && uv run ruff format --check . && uv run ty check && uv run pytest
```

Live FTPS is not part of CI; the mirror is tested with a mocked client (see
`tests/test_sync.py`).

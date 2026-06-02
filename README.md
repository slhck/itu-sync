# itu-sync

A small Python tool that replaces the broken `ITU-Sync` macOS app. It lets you pick an ITU meeting and work with its documents from the terminal:

- Sync meetings — refresh the list of meetings from ITU and browse it.
- Sync documents — download a meeting's documents (English) over FTPS, optionally restricted to one or more document types.
- List documents — show a meeting's documents without downloading them.

Every command works both interactively (guided pickers) and non-interactively (flags for scripting), including a `--latest` shortcut.

Very quick one-line usage:

```bash
# sync all contributions and TDs from latest SG12 meeting
uvx itu-sync sync --latest --group SG12 --type C,TD
```

Done! Read on to find out more.

## Disclaimer

> [!CAUTION]
>
> This software is provided as-is as a general-purpose tool for interacting with the ITU document services. The author provides this tool solely as software code and has no control over how it is used, no relationship with ITU, and no obligation to enforce any third-party terms of service or licenses. You, the user, are solely and independently responsible for ensuring that your use of this software complies with all applicable laws, regulations, and third-party terms of service, including those of ITU. By using this software, you agree to hold the author harmless from any claims, damages, or liabilities arising from your use of the software or your interactions with ITU's services.

## Installation

Install [with `uvx`](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uvx itu-sync --help
```

Or install with `pipx`:

```bash
pipx install itu-sync
```

Or, with pip:

```bash
pip3 install --user itu-sync
```

We assume you will be using `uvx`, otherwise just run `itu-sync` directly without `uvx` after installing from `pipx` or `pip`.

## Usage

The command provides four main subcommands:

```bash
itu-sync meetings  # list meetings
itu-sync sync      # sync documents of a meeting
itu-sync list      # list documents of a meeting
itu-sync config    # show current configuration or edit it
```

### First time setup

The first time you run any command in a terminal, a short guided setup asks for each setting and saves your answers. Example:

```text
$ itu-sync meetings
i Let's set up itu-sync. Use the arrow keys to choose options.
? Folder to store documents in: /Users/you/Documents/ITU
? Default sector: (Use arrow keys)
   ITU
   ITU-D
   ITU-R
 » ITU-T
? Default language to download:
 » E — English
   F — French
   S — Spanish
   A — Arabic
   C — Chinese
   R — Russian
? TIES account (username): yourname
? Store your TIES password now? (Y/n)
? TIES password: ********
i Checking your TIES credentials…
✓ Credentials verified.
✓ Setup complete. Change any setting later with 'itu-sync config'.
```

### Examples

Let's say we want to sync the latest Study Group 12 meeting's Contributions and Temporary Documents (TDs). With the interactive guided setup, we can just run:

```bash
itu-sync sync --latest --group SG12 --type C,TD
```

That's all!

Check `itu-sync sync --help` for more options.

Some more examples!

List meetings (newest first):

```bash
itu-sync meetings --sector ITU-T --filter SG12
```

Sync the latest SG 12 meeting's Contributions and Temporary Documents:

```bash
itu-sync sync --sector ITU-T --group SG12 --latest --type C,TD
```

Sync the Temporary Documents of a specific meeting:

```bash
itu-sync sync --meeting 260609 --type TD
```

List a meeting's TDs without downloading:

```bash
itu-sync list --group SG12 --latest --type TD
```

### Changing the config

Re-run the guided setup, or set any value individually:

```bash
itu-sync config --setup                  # run the guided setup again
itu-sync config --show                   # print the current settings
itu-sync config --user yourname          # set the TIES account
itu-sync config --drive ~/Documents/ITU  # set the storage folder
itu-sync config --sector ITU-T           # set the default sector
itu-sync config --language E             # set the default language
itu-sync config --password               # prompt for and store the password
```

Running `itu-sync config` with no options shows the current settings (or, on a fresh install, launches the guided setup).

Non-secret settings live in `~/.config/itu-sync/config.json`. The TIES password is stored in your operating system's keyring (Keychain on macOS), never in plaintext.

### Non-interactive use

In scripts or CI there is no terminal to prompt at, so the guided setup is skipped. Supply what you need through flags and environment variables; each value is resolved in this order:

- TIES account: the stored config, then `ITU_TIES_USER`, then `--user`.
- TIES password: the keyring, then the `ITU_TIES_PASSWORD` environment variable.
- Storage folder: the stored config, or `--drive` on any command.

When a required account or password is missing in non-interactive mode, the command exits with a clear error rather than hanging on a prompt.

## How it works

Meeting catalogs are four public XML files fetched over HTTPS from `https://www.itu.int/net/epub/ITU-Sync/` (no authentication). Documents are mirrored from `confsynch.itu.int:990` over implicit FTPS, authenticated with your TIES account. By default the FTPS server certificate is not verified (to match the old app); pass `--verify-cert` to enforce verification.

By default only English documents are downloaded; set a different default language during setup or with `itu-sync config --language`, or override per run with `itu-sync sync --lang fr`. The language code is the last hyphen-delimited token of the filename (e.g. `...-E.docx`). Index and metadata files (`.xml`, `.js`, `.css`, `.png`) are always kept.

## Development

```bash
uv run ruff check
uv run ruff format --check .
uv run ty check
uv run pytest
```

## License

MIT — see `LICENSE.md`.

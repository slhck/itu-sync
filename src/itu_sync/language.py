"""The English/language filter for document files.

Documents carry a language code as the last hyphen-delimited token of the
filename, just before the extension (``...-E.docx``). Index/metadata files have
no per-language variant and are always kept.
"""

from __future__ import annotations

import os

LANGUAGE_CODES: frozenset[str] = frozenset({"A", "C", "E", "F", "R", "S"})
"""A=Arabic, C=Chinese, E=English, F=French, R=Russian, S=Spanish."""

LANGUAGE_NAMES: dict[str, str] = {
    "E": "English",
    "F": "French",
    "S": "Spanish",
    "A": "Arabic",
    "C": "Chinese",
    "R": "Russian",
}
"""Human-readable names for the language codes, for prompts and help text."""

ALWAYS_KEEP_EXT: frozenset[str] = frozenset({".xml", ".js", ".css", ".png"})
"""Index/metadata extensions kept regardless of any trailing language token.

``.xml`` is here because the per-type index files end in a deceptive token
(``T25-SG12-C.xml``, ``...-TD.xml``) that must not be read as a language code.
``.htm``/``.html`` are intentionally *not* here: on the real server each
contribution has per-language HTML (``...-E.htm``, ``...-F.htm``, ``...-S.htm``),
and the old app's English sync kept only the ``-E`` ones. Index HTML such as
``CList.html`` or ``index.html`` carries no language token and is still kept by
the token rule below.
"""

DEFAULT_LANGUAGES: frozenset[str] = frozenset({"E"})


def keep_file(filename: str, languages: frozenset[str] = DEFAULT_LANGUAGES) -> bool:
    """Decide whether to keep ``filename`` for the requested ``languages``.

    The extension check comes first, so an index like ``T25-SG12-C.xml`` is not
    mistaken for Chinese. Files with no recognizable language token are kept.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in ALWAYS_KEEP_EXT:
        return True

    stem = filename[: len(filename) - len(ext)] if ext else filename
    token = stem.rsplit("-", 1)[-1] if "-" in stem else None
    if token in LANGUAGE_CODES:
        return token in languages
    return True

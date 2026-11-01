"""Locating the frontend in every place it can end up.

The same app must find ``ui/index.html`` in three very different layouts:

1. **Development** — plain files in the working tree (``web/index.html``).
2. **Nuitka standalone** — next to the binary, in ``my-app.dist/ui/``.
3. **Nuitka onefile** — inside a temporary directory that Nuitka unpacks at
   startup. ``__compiled__.containing_dir`` still points at the *binary* there,
   while ``__file__`` points inside the extraction directory, which is why the
   search walks up from this module instead of trusting either alone.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _search_dirs() -> list[Path]:
    """Directories to try, most specific first.

    Order:

    1. ``$ZAGRED_ASSETS`` — explicit override, useful for tests and for hosts
       that unpack assets somewhere unusual.
    2. This module's directory, then its parent and grandparent. In a onefile
       build this covers ``<tmp>/zagred/assets.py`` → ``<tmp>/ui``; in a
       standalone build it covers ``.../my-app.dist/zagred/assets.py`` →
       ``.../my-app.dist/ui``.
    3. The directory holding the executable (``sys.argv[0]``), for layouts where
       the binary sits beside its assets.
    4. The current working directory, which is what makes ``zagred dev`` work
       from a project root.

    Returns:
        Candidate directories with duplicates removed, keeping first
        occurrences so the most specific location still wins.
    """
    dirs: list[Path] = []
    override = os.environ.get("ZAGRED_ASSETS")
    if override:
        dirs.append(Path(override))

    here = Path(__file__).resolve().parent
    dirs.extend([here, here.parent, here.parent.parent])
    dirs.append(Path(sys.argv[0]).resolve().parent)
    dirs.append(Path.cwd())

    seen: set[Path] = set()
    unique = []
    for directory in dirs:
        if directory not in seen:
            seen.add(directory)
            unique.append(directory)
    return unique


def resolve_ui(ui: str | Path | None) -> str:
    """Turn a UI specification into something pywebview can load.

    Accepts a dev server URL, a directory (``index.html`` is appended), or a
    direct path to an HTML file. Relative paths are searched across every
    candidate from :func:`_search_dirs`, so the same call works in development
    and inside a compiled binary.

    Args:
        ui: ``http(s)://`` URL, directory, or HTML file. ``None`` is a
            programming error and raises.

    Returns:
        An absolute URL (passed through unchanged) or an absolute filesystem
        path to an existing HTML file.

    Raises:
        ValueError: If ``ui`` is ``None``.
        FileNotFoundError: If no candidate location contains the file. The
            message lists every directory that was searched, which is usually
            enough to spot a missing ``--include-data-dir`` in a build.
    """
    if ui is None:
        raise ValueError("no UI given: pass a path, or set [ui] in zagred.toml")

    text = str(ui)
    if text.startswith(("http://", "https://")):
        return text

    path = Path(text)
    candidates = [path] if path.is_absolute() else [d / text for d in _search_dirs()]
    for candidate in candidates:
        target = candidate / "index.html" if candidate.is_dir() else candidate
        if target.is_file():
            return str(target)

    raise FileNotFoundError(
        f"UI not found: {text!r}\n"
        f"searched: {', '.join(str(p) for p in candidates)}\n"
        "If this is a built binary, the frontend assets were not bundled."
    )

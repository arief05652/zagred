# CLI

```
zagred new [name] [--template T] [--lang L] [--pm P] [-y]
zagred dev [--debug]
zagred install [packages ...]
zagred build [--target T] [--jobs N] [--debug]
zagred doctor
```

Every command reads `zagred.toml` from the current directory, so run them at the
project root (or via `uv run` inside the project).

## `zagred new`

Scaffold a project. Without flags it asks for a name, a framework and a
language; `-y` accepts the defaults instead.

```bash
zagred new my-app --template react --lang ts --pm bun -y
```

`--pm` choices come from what is on `PATH` (`npm`, `pnpm`, `bun`). The question
is skipped for a plain-file frontend (nothing to install) and when only one
manager is installed. The choice is recorded in `zagred.toml`, never guessed
again.

Names are validated: letters and digits, must start with a letter, `-` and `_`
allowed.

## `zagred dev`

Start the dev server (when `[ui] command` is set), wait for `[ui] dev_url`, then
open the window against the UI source.

```bash
uv run zagred dev --debug
```

`--debug` opens the WebView inspector and keeps the right-click context menu.
The child process group is cleaned up on exit, so no orphan bundler survives
Ctrl+C.

## `zagred install`

```bash
uv run zagred install              # install what package.json declares
uv run zagred install vue-router   # add a package
```

Uses `[ui] package_manager` and nothing else — no lockfile sniffing, no mixing
two managers in one project. An unknown value, or a manager that is not on
`PATH`, fails with the fix spelled out.

## `zagred build`

```bash
uv run zagred build --target appimage --jobs 2
```

See [Building](build.md) for targets, exit codes and the five steps it runs.

## `zagred doctor`

Informational report of everything `dev` and `build` need. Always exits `0`.

```
zagred      0.1.4
python      3.12.8
platform    linux
pywebview   6.0
renderer    gtk
nuitka      MISSING (uv sync --group build)
patchelf    MISSING (required by Nuitka: pip install patchelf)
appimagetool (downloaded+cached by Nuitka if absent) -
```

`renderer` is the line that matters on Linux: `import webview` always succeeds,
because pywebview defers backend loading. Only importing the backend itself
proves the app can open a window.

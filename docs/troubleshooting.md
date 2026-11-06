# Troubleshooting

## `uv sync` says zagred is not found in the registry

It is not on PyPI yet. Projects created by `zagred new` get a
`[tool.uv.sources]` entry pointing at the local checkout. If you copied a
project from elsewhere:

```toml
# pyproject.toml
[tool.uv.sources]
zagred = { path = "/path/to/zagred", editable = true }
```

## `zagred dev` says GTK/QT cannot be loaded

The bindings exist on the system but this interpreter cannot see them — uv's
standalone Python does not look at `/usr/lib/python3/dist-packages`:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
rm -rf .venv
uv venv --python /usr/bin/python3 --system-site-packages
uv sync
```

Confirm with `uv run zagred doctor` → `renderer gtk`. If the window opens white
instead, the shim could not be injected; check that the page has no
`beforeunload` handler blocking navigation.

## `uv` warns that `VIRTUAL_ENV` does not match

You activated another project's venv. `deactivate`; `uv run` picks the right
one.

## `zagred doctor` says nuitka MISSING

```bash
uv sync --group build
```

## `patchelf` MISSING on Linux

Nuitka needs it to rewrite RPATHs:

```bash
pip install patchelf      # or your distro's package
```

`appimagetool` is downloaded and cached by Nuitka when missing — no manual step.

## A built app opens the inspector

It was built with `--debug`. Rebuild without the flag.

## Calls fail with `bad_arguments`

Arguments are **keyword** arguments. `zagred.call("greet", { name })` maps to
`greet(name=...)`; a positional-only signature or a typo in the key is the usual
cause. The message from Python's `TypeError` is passed through unchanged.

## A function is not reachable from JS

Two functions exposed under the same `__name__`: the last one wins, silently.
Rename one, or expose it under a different module.

## Nothing arrives on `zagred.on`

`app.emit` is a silent no-op before the page has loaded. Move the emit into
`@app.on_loaded`, or check that the event name string matches exactly on both
sides.

## A shortcut fires while typing

Modifier-less shortcuts are suppressed only for `input`, `textarea`, `select`
and contenteditable targets. A custom widget that swallows keys itself needs its
own `keydown` guard, or bind the shortcut in the page so it can inspect
`event.target`.

## Cross-compiling

Not supported. Build each OS on that OS, or in CI — Nuitka compiles against the
host toolchain and the host webview.

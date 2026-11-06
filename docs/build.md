# Building

One manifest, six targets, no hand-written compiler flags.

```bash
uv sync --group build                   # adds Nuitka (+ patchelf on Linux)
uv run zagred build                     # uses [build] target from zagred.toml
uv run zagred build --target appimage   # one-off override
```

`--target` on the command line beats `[build] target` in the manifest, which
beats `auto`. Set the manifest once and forget the flag.

## Targets

| `--target` | Nuitka flags | Output |
|---|---|---|
| `auto` | picks by OS | `.AppImage` / `.exe` / `.app` |
| `onefile` | `--mode=onefile` | single binary |
| `standalone` | `--mode=standalone` | folder with binary + libs |
| `exe` | `--mode=standalone --windows-create-installer` | NSIS `-setup.exe` |
| `appimage` | `--mode=app-dist --linux-create-installer` | `.AppImage` |
| `app` | `--mode=app` | macOS `.app` |
| `dmg` | `--mode=app --macos-create-installer` | `.dmg` |

`auto` picks `appimage` on Linux, `onefile` on Windows and `app` on macOS.
Cross-compiling is not supported: an unknown platform raises rather than
guessing.

Each target writes to its own directory, so building one never overwrites
another:

```
dist/
├── appimage/
│   ├── my-app.AppImage
│   └── my-app.dist/
├── onefile/
│   └── my-app
└── exe/
    └── my-app-setup.exe
```

!!! note "Antivirus on Windows"
    Some engines flag the `onefile` stub as suspicious. If that happens, ship
    `--target standalone` instead — same app, packaged as an installer, and it
    does not trigger the heuristic.

## What `zagred build` does

```
1. npm run build                    (in web/, if [ui] build is set)
2. write .zagred/build/<name>.py    static import of your App + boot()
3. nuitka --include-data-dir=web/dist=ui
4. wrap the .dist folder into the installer for the chosen target
5. write everything to dist/<target>/
```

Step 2 imports your App **statically** on purpose. Nuitka bundles only what it
can see through imports, so a dynamic `importlib.import_module("my_app.app")`
would leave your package out and crash at startup.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| frontend's code | the frontend builder failed |
| `1` | Nuitka is not installed |
| `2` | the UI dist directory is missing |
| Nuitka's code | Nuitka failed |

## Keeping the machine usable

A Nuitka build saturates every core by default. `--jobs` caps it:

```bash
uv run zagred build --jobs 2        # two compiler jobs
uv run zagred build --jobs -2       # all cores minus two
```

Or set it once:

```toml
[build]
jobs = 2
low_memory = true
```

`low_memory` additionally asks Nuitka for fewer jobs and lighter compiler
options, which is what keeps a small VM from swapping.

## `--debug` is for development only

```bash
uv run zagred build --debug
```

This bakes `debug=True` into the app, so the built binary opens the WebView
inspector. A warning is printed because this is easy to ship by accident.
Rebuild without the flag before releasing.

## Checking the toolchain

```bash
uv run zagred doctor
```

Prints the interpreter, pywebview, the **real** webview backend, Nuitka, and on
Linux `patchelf` and `appimagetool`. Missing optional pieces print the command
that fixes them; the report always exits `0`, so it is safe to call from a
script.

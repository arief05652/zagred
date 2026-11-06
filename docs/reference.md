# API reference

Everything importable from `zagred`:

```python
import zagred
zagred.App            # window, lifecycle, JS bridge
zagred.Manifest       # parsed zagred.toml
zagred.load_manifest  # read + validate a zagred.toml
zagred.__version__
```

The CLI lives in `zagred.cli` and is not imported by `zagred`, so `import zagred`
stays cheap and never drags in build tooling.

## `zagred.App`

### Constructor

All recognised keyword arguments and their defaults are listed in
[Backend → The App object](backend.md#the-app-object). Options are read once,
when the window is created.

### Registration

| Method | Returns | Notes |
|---|---|---|
| `expose(fn)` | `fn` | Usable as a decorator; registered under `fn.__name__` |
| `hotkey(combo, fn=None)` | `fn` or decorator | `ValueError` on an invalid combo, at registration |
| `on_start(fn)` | `fn` | Runs once the GUI loop is up |
| `on_loaded(fn)` | `fn` | Runs after the page has loaded |
| `on_closing(fn)` | `fn` | Return `False` to cancel the close |
| `on_closed(fn)` | `fn` | Runs on both close paths |
| `on_event(name, fn=None)` | `fn` or decorator | Any pywebview event; a typo fails at window creation |

Hooks may be stacked: each decorator adds one callable, all of them run.

### Events

| Method | Notes |
|---|---|
| `emit(name, payload=None)` | Pushes to `zagred.on(name, fn)`. No-op before the page can receive it. `TypeError` if `payload` is not JSON-serialisable |

### Window control

The window exists only between `run()` and the user closing it; calling these
before `run` or after close raises `RuntimeError`.

| Method | Effect |
|---|---|
| `minimize()` / `maximize()` / `restore()` | window state |
| `toggle_fullscreen()` | fullscreen on/off |
| `resize(width, height)` | size in logical pixels |
| `move(x, y)` | top-left corner |
| `set_title(title)` | update the running window's title |
| `show()` / `hide()` | visibility |
| `destroy()` | destroy the window |
| `load_url(url)` | navigate |
| `load_css(stylesheet)` | inject CSS |
| `evaluate_js(script)` | run JS and return its value; needs `unsafe-eval` under CSP |
| `run_js(script)` | run JS, return nothing; CSP-safe |
| `get_current_url()` | `str \| None` |

### Properties

| Property | Type | Notes |
|---|---|---|
| `width`, `height`, `x`, `y` | `int` | geometry of the running window |
| `state` | pywebview state | |
| `window` | pywebview window or `None` | the raw object, for anything unwrapped |

### `run(ui=None, debug=False)`

Creates the window, starts the GUI loop, blocks until it closes.

`ui` may be an `http(s)://` URL, a directory containing `index.html`, or an HTML
file. Anything else raises `FileNotFoundError`. No webview engine available
raises `SystemExit` after printing the platform-specific fix.

`debug=True` opens the inspector and stops suppressing the right-click menu.

## `zagred.Manifest`

Frozen dataclass — produced once per command by `load_manifest`, then read by
`dev` and `build`.

| Field | Default | TOML key |
|---|---|---|
| `name` | *required* | `[app] name` |
| `version` | `"0.1.0"` | `[app] version` |
| `id` | `com.example.<name>` | `[app] id` |
| `entry` | *required* | `[app] entry` (`module:attribute`) |
| `icon` | `None` | `[app] icon` |
| `ui_dir` | `"web"` | `[ui] dir` |
| `ui_dev_command` | `None` | `[ui] command` |
| `ui_dev_url` | `"http://localhost:5173"` | `[ui] dev_url` |
| `ui_build_command` | `None` | `[ui] build` |
| `ui_dist` | `"web/dist"` | `[ui] dist` |
| `ui_package_manager` | `"npm"` | `[ui] package_manager` |
| `target` | `"auto"` | `[build] target` |
| `output` | `"dist"` | `[build] output` |
| `jobs` | `None` | `[build] jobs` |
| `low_memory` | `False` | `[build] low_memory` |
| `extra` | `{}` | reserved, currently unused |

Derived: `manifest.module` (`entry.split(":")[0]`), `manifest.attribute`.

## `zagred.load_manifest(root=".")`

Reads and validates `zagred.toml` from `root`.

| Raises | When |
|---|---|
| `FileNotFoundError` | `zagred.toml` is not in `root` |
| `ValueError` | `[app] name` is missing, or `[app] entry` is not `module:attribute` |

## `window.zagred`

The shim, injected on `before_load`.

| Member | Notes |
|---|---|
| `call(name, args?)` | `Promise`; rejects with `Error` carrying `code` |
| `on(name, fn)` | subscribe; returns an unsubscribe function |
| `off(name, fn)` | unsubscribe by reference |
| `ready` | `Promise` resolved when the pywebview bridge exists |
| `hotkey(combo, fn)` | page-side binding; returns an unsubscribe function. Handler gets `{combo, event, target}` |
| `hotkeys` | array of combos bound from Python |

## Bridge envelope

`window.pywebview.api.call(name, args)` is the only exposed method. It never
raises; it always returns an envelope.

```json
{"ok": true, "data": <json>}
{"ok": false, "error": {"code": "unknown_command", "message": "..."}}
```

`data` is verified JSON-serialisable before the envelope is returned, so a bad
return value becomes an error in the UI instead of a blank window.

## `zagred.bridge`

| Function | Notes |
|---|---|
| `normalize(combo, mac=None)` | canonical form, e.g. `"ctrl+shift+p"`; `ValueError` on a bad combo |
| `key_table()` | modifier/alias/order tables plus `mod` for this platform, sent to the shim |

## `zagred.build`

| Function | Notes |
|---|---|
| `build(manifest, root, target=None, debug=False, jobs=None)` | frontend → entry script → Nuitka → artifacts; returns an exit code |
| `doctor()` | toolchain report; always `0` |
| `renderer()` | `(usable, name, fix)` — probes the real backend, not `import webview` |
| `pick_target(requested)` | resolves `auto` to a concrete target |
| `TARGETS` | target name → `(nuitka mode, extra flags)` |

## `zagred.assets`

| Function | Notes |
|---|---|
| `resolve_ui(ui)` | turns a path, directory or URL into something the window can load, searching the working tree, the standalone `.dist` folder and the onefile extraction dir |

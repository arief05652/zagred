# Backend

Windows and lifecycle live in Python, not in JSON. Everything below is
`zagred.App`.

## The App object

```python
import zagred

app = zagred.App(title="My App", size=(1024, 700))
```

All options are read **once**, when the window is created. Mutating the
attribute afterwards (`app.title = "x"`) does not update a running window — use
the matching control method instead, e.g. [`set_title()`](reference.md#window-control).

| Option | Default | Meaning |
|---|---|---|
| `title` | `"Zagred"` | Window title, also shown in the taskbar or dock |
| `size` | `(1024, 700)` | `(width, height)` in logical pixels |
| `min_size` | `(200, 100)` | Lower bound when the user resizes |
| `position` | `None` | `(x, y)` of the top-left corner; `None` lets the WM place it |
| `resizable` | `True` | `False` for fixed-size dialogs and splash windows |
| `fullscreen` | `False` | Start borderless and covering the screen |
| `maximized` | `False` | Start maximized, still decorated |
| `minimized` | `False` | Start minimized (or hidden, on some Linux WMs) |
| `frameless` | `False` | No title bar or borders; draw your own controls |
| `easy_drag` | `True` | In a frameless window, drag it by its background |
| `on_top` | `False` | Keep above other windows |
| `focus` | `True` | Take keyboard focus on open |
| `confirm_close` | `False` | Ask before closing |
| `transparent` | `False` | Transparent pixels behind the webview (CSS must agree) |
| `background_color` | `"#ffffff"` | Colour painted before the page renders |
| `icon` | `None` | PNG on Linux/Windows, ICNS or PNG on macOS |
| `menu` | `[]` | Platform menu, passed straight to pywebview |
| `draggable` | `False` | Let `.pywebview-drag-region` elements move a frameless window |
| `settings` | `{}` | `webview.settings` overrides, validated before the window opens |
| `start` | `{}` | Extra `webview.start()` arguments Zagred does not wrap |

`settings` and `start` are checked against what pywebview actually knows, so a
typo fails at startup with the list of real names instead of being ignored.

```python
app = zagred.App(
    title="Kiosk",
    frameless=True,
    draggable=True,
    settings={"ALLOW_DOWNLOADS": True, "OPEN_EXTERNAL_LINKS_IN_BROWSER": False},
    start={"private_mode": False, "storage_path": "~/.local/share/kiosk"},
)
```

## Exposed functions

Only `@app.expose` functions are reachable from JavaScript. Everything else on
`App` is Python-side control and is never exposed to the UI.

```python
@app.expose
def greet(name: str) -> str:
    return f"Hello, {name}!"


@app.expose
async def scan(folder: str) -> list[str]:
    ...
```

Rules worth knowing:

- A function is registered under its `__name__`; exposing two functions with the
  same name silently keeps the last one.
- Arguments are **keyword** arguments from JS. Wrong ones give `bad_arguments`.
- Every return value must be JSON-serialisable; that is checked before it leaves
  Python, so you get an error instead of a silent blank window.
- `async def` works — it is awaited on a worker thread.

Errors are classified so the UI can branch on `err.code`:

| `code` | When |
|---|---|
| `unknown_command` | nothing is exposed under that name |
| `bad_arguments` | the callable rejected the given keyword arguments |
| any `Exception` subclass name | your function raised — `ValueError`, `KeyError`, … |

See [error handling](frontend.md#errors).

## Lifecycle hooks

```python
@app.on_start
def ready() -> None:
    print("GUI loop is up")


@app.on_loaded
def page_ready() -> None:
    app.emit("hello", {"n": 1})


@app.on_closing
def before_close() -> bool | None:
    return save_state()   # return False to cancel the close


@app.on_closed
def gone() -> None:
    print("window destroyed")
```

`@app.on_closed` runs in both cases. Hooks may be stacked — each decorator adds
one callable, all of them run.

For the rest of pywebview's event surface use `on_event`, without a wrapper per
event:

```python
@app.on_event("resized")
def remember(width, height) -> None:
    print(width, height)
```

Available: `before_show`, `initialized`, `shown`, `minimized`, `maximized`,
`restored`, `resized`, `moved`, `request_sent`, `response_received` — plus the
four above. The signature differs per event, so accept `*args, **kwargs` when
you do not care. A typo in the name fails at startup, not silently at runtime.

## Events, Python → JS

```python
@app.expose
def start_job() -> None:
    for done, total in work():
        app.emit("job:progress", {"done": done, "total": total})
```

Received in the page with `zagred.on("job:progress", fn)` — see
[events](frontend.md#events).

`emit` is a silent no-op before the page can receive it (no window yet, or not
finished loading). It uses `run_js` with a JSON literal rather than
`evaluate_js`, so it keeps working under a Content-Security-Policy that forbids
`unsafe-eval`.

## Window control

The window exists only between `run()` and the user closing it. Calling a control
method before `run` — or from a hook that fires after close — raises
`RuntimeError`.

```python
app.minimize(); app.maximize(); app.restore()
app.toggle_fullscreen()
app.resize(1200, 800); app.move(100, 100)
app.set_title("Renamed")
app.show(); app.hide()
app.load_url("https://example.com")
app.load_css("body { background: #111 }")
```

Reading state:

```python
app.width, app.height, app.x, app.y   # ints
app.state                             # pywebview window state
app.window                            # the raw pywebview window, or None
app.get_current_url()                 # str | None
```

Talking to the page from Python:

```python
app.evaluate_js("document.title")     # returns a value; needs unsafe-eval under CSP
app.run_js("window.zagred._dispatch('x', 1)")  # fire and forget, CSP-safe
```

Prefer `app.emit()` over raw `run_js` for anything the page already subscribes
to — it handles the "not ready yet" and threading cases for you.

## Running

```python
if __name__ == "__main__":
    app.run()
```

`run` owns the calling thread and blocks until the window closes, so it is
normally the last statement of your entry module. `zagred dev` and
`zagred build` call it for you.

```python
app.run(ui="web", debug=True)
```

`ui` may be an `http(s)://` URL (the dev server) or a path — a directory
containing `index.html`, or an HTML file. `debug=True` opens the WebView
inspector and stops suppressing the right-click context menu. Development only.

# Zagred

**Desktop apps with a Python backend and a web frontend.**

Your app is a normal Python package. Your UI is a folder next to it. Zagred puts
the two together in a native window (via [pywebview](https://pywebview.flowrl.com))
and compiles the result into a `.AppImage`, `.exe`, `.app` or `.dmg`
(via [Nuitka](https://nuitka.net)).

- **Python 3.12+**, dependencies managed by [uv](https://docs.astral.sh/uv/)
- No Rust. No Node.js unless you want a bundler.
- Frontend: plain HTML/JS, or React / Vue / Solid with Vite
- Bridge with typed errors, async commands, and Python→JS events

---

## Quick start

```bash
# 1. install the CLI (not on PyPI yet — see "Local development")
uv tool install zagred

# 2. create a project — interactive: name, framework, JS or TS
zagred new

# 3. install everything
cd my-app
uv sync
uv run zagred install     # frontend deps, with the package manager you picked

# 4. run it
uv run zagred dev
```

Skip the questions in scripts:

```bash
zagred new my-app --template react --lang ts --pm bun -y
```

### Linux: one extra step

uv's Python cannot import the distro's `python3-gi`, so build the venv from the
system interpreter **before** `uv sync`:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
uv venv --python /usr/bin/python3 --system-site-packages
uv sync
```

Verify with `uv run zagred doctor` — it should report `renderer gtk`.

### What you get

```
my-app/
├── zagred.toml          # [app] identity, [ui] dirs, [build] options
├── pyproject.toml       # uv project, depends on zagred
├── .python-version      # pinned to 3.12
├── web/                 # your UI
│   ├── package.json     # only when a bundler is used
│   └── src/
└── my_app/
    └── app.py           # App, @expose, lifecycle
```

---

## The backend

Windows and lifecycle live in Python, not in JSON:

```python
# my_app/app.py
import zagred

app = zagred.App(title="My App", size=(1024, 700))


@app.expose
def greet(name: str) -> str:
    """Callable from the UI as zagred.call("greet", { name })."""
    return f"Hello, {name}!"


@app.expose
async def scan(folder: str) -> list[str]:
    ...
```

Rules worth knowing:

- A function is registered under its `__name__`; exposing two functions with the
  same name silently keeps the last one.
- Arguments are keyword arguments from JS. Wrong ones give `bad_arguments`.
- Every return value must be JSON-serialisable; that is checked before it leaves
  Python, so you get an error instead of a silent blank window.
- `async def` works — it is awaited on a worker thread.

## The frontend

```js
const msg = await zagred.call("greet", { name: "world" });
```

```js
zagred.call("greet").catch((err) => {
  console.error(err.code, err.message); // e.g. "bad_arguments"
});
```

Events, Python → JS:

```python
@app.expose
def start_job() -> None:
    for done, total in work():
        app.emit("job:progress", {"done": done, "total": total})
```

```js
const off = zagred.on("job:progress", (p) => console.log(p.done));
off(); // unsubscribe
```

`zagred.ready` is a promise that resolves once the bridge is live. Top-level
script code should `await zagred.ready` (or call from inside an event handler)
because the bridge is injected around page-load time.

### Hotkeys

There are two places to bind one, and the difference is where the work happens,
not how the key is matched.

**In Python**, when the shortcut should do something native — a dialog, a
window change, a background job:

```python
@app.hotkey("mod+k")
def palette() -> None:
    app.emit("open", "palette")
```

**In the page**, when the shortcut moves the UI itself — focus a field, step
through a list, jump to a section:

```js
const off = zagred.hotkey("j", () => setIndex((i) => i + 1));
zagred.hotkey("/", () => document.querySelector("input")?.focus());
zagred.hotkey("enter", ({ target }) => target?.closest("li")?.click());
off(); // unsubscribe
```

The handler receives `{ combo, event, target }`, so it can inspect the real
`KeyboardEvent` and whatever had focus. A page-side binding never touches the
bridge: no round-trip, no Python, and it works immediately — `zagred.hotkey()`
can be called at any time, unlike a Python binding, which is fixed when the shim
is injected.

The shim matches the keystroke before the page sees it, so both kinds cancel the
browser's own action — `Ctrl+P` opens your palette instead of a print dialog.
Every matched shortcut, from either side, also fires a `hotkey` event:

```js
zagred.on("hotkey", ({ combo }) => setStatus(`last key: ${combo}`));
```

| Written | Means |
|---|---|
| `ctrl` / `control` | Ctrl on every platform |
| `meta` / `cmd` / `super` / `win` | the platform key |
| `alt` / `option` | Alt |
| `shift` | Shift |
| `mod` | Ctrl on Linux and Windows, Cmd on macOS |
| `esc`, `return`, `up`, `del`, `space`, `plus` | the obvious keys |

Case, spacing and modifier order do not matter: `Ctrl+Shift+P`, `shift+ctrl+p`
and `CTRL + SHIFT + p` are the same shortcut. Everything else is the
`event.key` name, lowercased — `a`, `1`, `f5`, `tab`, `arrowdown`. Both sides use
the same grammar tables, so `mod+k` normalises identically in Python and in the
page.

A shortcut **without** a modifier is ignored while an input, textarea, select or
contenteditable element has focus, so typing `j` in a search box does not fire a
`j` shortcut. `Escape` is the exception — it never inserts anything, and
"cancel" is what a user expects. Modifier shortcuts are never affected, because
`Ctrl+K` is not something you type.

An invalid shortcut fails at registration: `ValueError` in Python, a thrown
`Error` in the page. Nothing is left silently unbound. A shortcut pressed
mid-composition (IME) is ignored.

---

## CLI

| Command | What it does |
|---|---|
| `zagred new [name]` | Interactive scaffold. `--template`, `--lang`, `--pm`, `-y` for scripts |
| `zagred dev [--debug]` | Start the frontend dev server, wait for it, open the window |
| `zagred install [pkg ...]` | Install frontend deps, or add packages, using the project's manager |
| `zagred build [--target T] [--jobs N] [--debug]` | Build the UI, compile with Nuitka |
| `zagred doctor` | Check python, pywebview, renderer, nuitka, patchelf, appimagetool |

`zagred dev` cleans up after itself: closing the window kills the whole frontend
process group, so no orphaned `vite` holding your terminal.

### Package manager

`zagred new` asks which manager to use — `npm`, `pnpm` or `bun` — and records it
in the manifest, so you never repeat the choice:

```toml
[ui]
package_manager = "bun"
command = "bun run dev -- --port 5173 --strictPort"
build   = "bun run build"
```

From then on:

```bash
uv run zagred install             # bun install
uv run zagred install vue-router  # bun add vue-router
```

It reads `[ui] package_manager` and nothing else — no guessing from lockfiles,
no mixing two managers in one project. Unknown values and a manager that is not
on `PATH` both fail with the fix spelled out.

The question is skipped for a plain-file frontend (nothing to install) and when
only one manager is installed. `--pm` answers it up front.

### Templates

| `--template` | `--lang js` | `--lang ts` | Bundler |
|---|---|---|---|
| `vanilla` *(default)* | plain files, **no npm** | Vite | optional |
| `react` | Vite | Vite | yes |
| `vue` | Vite | Vite | yes |
| `solid` | Vite | Vite | yes |

TypeScript projects ship `web/src/zagred.d.ts`:

```ts
const msg = await zagred.call<string>("greet", { name });
```

Bundler projects get `npm run dev -- --port 5173 --strictPort` in `zagred.toml`,
so `zagred dev` always finds the server on the port it polls.

### Window options

```python
app = zagred.App(
    title="My App",
    size=(1200, 800),
    min_size=(640, 480),
    position=(100, 100),      # omit to let the OS place it
    resizable=True,
    fullscreen=False,
    maximized=False,
    frameless=False,          # no title bar
    easy_drag=True,           # frameless windows stay draggable
    on_top=False,
    focus=True,
    confirm_close=False,      # ask before closing
    transparent=False,
    background_color="#ffffff",
    icon="my_app/resources/icon.png",
    menu=[],
    draggable=False,         # let .pywebview-drag-region move a frameless window
    settings={"ALLOW_DOWNLOADS": True},
    start={"user_agent": "MyApp/1.0", "private_mode": False},
)
```

`settings` and `start` are the escape hatches for everything pywebview exposes
and Zagred does not wrap: every `webview.settings` key and every
`webview.start()` argument. Both are validated at startup, so a typo fails with
the list of real names instead of doing nothing.

Control it at runtime:

```python
app.minimize() / app.maximize() / app.restore()
app.toggle_fullscreen()
app.resize(900, 600) / app.move(50, 50)
app.set_title("Renamed")
app.show() / app.hide() / app.destroy()
app.load_url("http://localhost:5173")
app.evaluate_js("document.title")            # blocking, returns the value
app.run_js("localStorage.clear()")           # fire and forget, CSP-safe
app.load_css("body { background: #111 }")    # queued, applies later
app.get_current_url()
```

Not here on purpose, each measured broken or useless on Linux:

| Missing | Why | Instead |
| --- | --- | --- |
| `load_html()` | the next navigation kills pywebview's bridge | `load_url()` |
| `create_file_dialog()` | `Gtk.Dialog.run()` runs off the main thread, so no dialog ever appears | `<input type="file">` in the page |
| `create_confirmation_dialog()` | same GTK problem | `confirm_close=True` |
| `get_cookies()` / `clear_cookies()` | a desktop app has no server session to keep | `app.window` |
| `shadow=`, `vibrancy=`, `text_select=`, `zoomable=` | the GTK backend never reads them | CSS |

Anything else pywebview offers is on `app.window`, the raw window object.

Read the live window, instead of the values you asked for at startup:

```python
app.width, app.height, app.x, app.y   # what the window manager settled on
app.state                             # pywebview State, may be empty
app.window                            # the raw pywebview Window, or None
```

Lifecycle hooks:

```python
@app.on_start
def boot(): ...        # GUI loop is up

@app.on_loaded
def ready(): ...       # page finished loading

@app.on_closing
def guard():
    return False       # cancel the close

@app.on_closed
def bye(): ...
```

And the rest of pywebview's events, when you need them:

```python
@app.on_event("resized")
def remember(width, height): ...

@app.on_event("request_sent")
def trace(*args, **kwargs): ...
```

`before_load`, `before_show`, `initialized`, `loaded`, `shown`, `minimized`,
`maximized`, `restored`, `resized`, `moved`, `request_sent`,
`response_received`, `closing`, `closed`. The handler receives that event's own
arguments; an unknown name fails when the window is created, listing the real
ones.

---

## Building

```bash
uv sync --group build       # adds Nuitka (+ patchelf on Linux)
uv run zagred build                     # uses [build] target from zagred.toml
uv run zagred build --target appimage   # one-off override
```

`--target` on the command line beats `[build] target` in the manifest, which
beats `auto`. Set the manifest once and forget the flag.

| `--target` | Nuitka flags | Output |
|---|---|---|
| `auto` | picks by OS | `.AppImage` / `.exe` / `.app` |
| `onefile` | `--mode=onefile` | single binary |
| `standalone` | `--mode=standalone` | folder with binary + libs |
| `exe` | `--mode=standalone --windows-create-installer` | NSIS `-setup.exe` |
| `appimage` | `--mode=app-dist --linux-create-installer` | `.AppImage` |
| `app` | `--mode=app` | macOS `.app` |
| `dmg` | `--mode=app --macos-create-installer` | `.dmg` |

Each target writes to its own directory, so building one never overwrites another:

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

On Windows, some antivirus engines flag the `onefile` stub as suspicious. If
that happens, ship `--target standalone` instead — same app, packaged as an
installer, and it does not trigger the heuristic.

### What `zagred build` does

```
1. npm run build                    (in web/, if [ui] build is set)
2. write .zagred/build/<name>.py    static import of your App + boot()
3. nuitka --include-data-dir=web/dist=ui
4. wrap the .dist folder into the installer for the chosen target
5. write everything to dist/<target>/
```

Step 2 imports your App statically on purpose. Nuitka bundles only what it can
see through imports, so a dynamic `importlib.import_module("my_app.app")` would
leave your package out and crash at startup.

### Keeping the machine usable

Compilation is CPU-hungry. Default is every core.

```toml
[build]
jobs       = 2       # at most 2 parallel C compiles
low_memory = true    # optional: fewer jobs + lighter compiler options
```

```bash
uv run zagred build --jobs 2     # one-off override
```

| `--jobs` | Effect |
|---|---|
| unset | every core (Nuitka default) |
| `2` | 2 parallel C compiles |
| `-1` | CPU count minus 1 |
| `1` | serial |

Measured on an 8-core laptop: default ≈ 6m47s wall / 39m30s CPU (~6 cores busy);
`--jobs=2` ≈ 11 min with load ~3.

### `--debug` is for development only

`zagred build --debug` bakes `debug=True` into the compiled app. pywebview then
enables developer extras, opens the WebView inspector, and stops suppressing the
right-click context menu. Fine for testing a packaged build, never for release.
The command warns when you do it.

---

## How it works

Every JS → Python call goes through one door:

```
zagred.call(name, args)
  → window.pywebview.api.call(name, args)     # the only exposed method
  → Bridge.call()  → your @expose function
  → {ok: true, data} | {ok: false, error: {code, message}}
  → resolved value, or a thrown Error(code, message)
```

Your code never touches `window.pywebview`. The `window.zagred` shim is injected
on `before_load` from a worker thread — calling `evaluate_js` directly on that
blocking event deadlocks the GTK main loop and leaves the window white.

## Requirements

| OS | Needs |
|---|---|
| Linux | `libwebkit2gtk-4.1`, `python3-gi`, venv created with `--system-site-packages`; `patchelf` comes with `--group build` |
| Windows | WebView2 runtime (preinstalled on Windows 11) |
| macOS | nothing extra |

Linux uses the GTK backend on purpose: Qt adds 80–150 MB to every build.
`appimagetool` is downloaded and cached by Nuitka when missing.
Cross-compiling is impossible — build each OS on that OS, or in CI.

## Troubleshooting

**`uv sync` says zagred is not found in the registry** — not on PyPI yet. Projects
created by `zagred new` get a `[tool.uv.sources]` entry pointing at the local
checkout. If you copied a project from elsewhere:

```toml
[tool.uv.sources]
zagred = { path = "/path/to/zagred", editable = true }
```

**`zagred dev` says GTK/QT cannot be loaded** — the bindings exist on the system
but this interpreter cannot see them:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
rm -rf .venv
uv venv --python /usr/bin/python3 --system-site-packages
uv sync
```

**`uv` warns that `VIRTUAL_ENV` does not match** — you activated another project's
venv. `deactivate`; `uv run` picks the right one.

**`zagred doctor` says nuitka MISSING** — `uv sync --group build`.

**A built app opens the inspector** — it was built with `--debug`. Rebuild without it.

---

## Milestones

### ✅ M0 — Spike
Bridge roundtrip, error envelope, async commands, events via `run_js`,
working `--mode=onefile` binary, assets resolved from the onefile temp dir.

### ✅ M1 — Runtime
`zagred.toml` parser, `@expose`, JS shim, event bus, scaffolds that run,
`zagred dev`, actionable errors instead of raw tracebacks, 38 unit tests.

### ✅ M2 — uv toolchain
Generated projects are uv projects; zagred resolved from the local checkout via
`[tool.uv.sources]` (editable); `.python-version` pinned to 3.12; `build`
dependency group carries nuitka + patchelf; `zagred new` prints next steps.

### ✅ M3 — Build
Six build targets, asset resolver for dev/standalone/onefile, per-target output
directories, `--jobs` / `low_memory`, `zagred doctor`, artifacts named after the app.

### 🟡 M4 — Ecosystem
- [x] `zagred new` wizard, `--template` / `--lang` / `-y`
- [x] Templates: vanilla, React, Vue, Solid × JS/TS
- [x] Vite HMR dev path, verified against a real React project
- [x] Typed bridge for TypeScript
- [x] Full window option set, lifecycle hooks, window control methods
- [ ] Multi-window (one `Bridge` per window)
- [ ] Plugin registry via `entry_points`
- [ ] `zagred add ui <kit>`

### ⬜ M5 — Security
- [ ] `capabilities.toml` + permission check before dispatch
- [ ] Default CSP
- [ ] Path traversal guard on the resource resolver

### ⬜ M6 — Release
- [ ] Publish to PyPI
- [ ] AppImage test on a clean VM (GTK typelibs)
- [ ] CI matrix (GitHub Actions, `Nuitka-Action`)
- [ ] Docs site, example apps, stable semver

---

## Fixed so far

23 bugs found and fixed while building this. The ones that would have shipped:

| # | Bug |
|---|---|
| B4 | Blank window from a built binary — onefile assets resolved from the wrong directory |
| B7 | `uv sync` failed in every generated project — zagred was declared from PyPI |
| B11 | GTK not visible from uv's Python — venv must use `--system-site-packages` |
| B12 | White window for seconds — `evaluate_js` deadlocked the blocking `before_load` event |
| B15 | Terminal broken after closing the window — orphaned `vite` held the TTY |
| B19 | Packaged app crashed: `No module named my_app` — dynamic import invisible to Nuitka |
| B21 | Building one target deleted another's artifacts — shared output dir |
| B22 | Release AppImage opened the WebView inspector — `--debug` baked into the build |
| B23 | `[build] target` in `zagred.toml` was silently ignored — `--target` defaulted to `auto` and always won, while `mode` was read by nobody |

Full list with causes and fixes: `git log` and the test suite in `tests/test_core.py`.

---

## Development

```bash
uv sync --extra build
uv run python -m unittest discover -s tests     # 38 tests
uv run zagred doctor
```

## Documentation

Built with [Zensical](https://zensical.org) from `docs/` and `zensical.toml`:

```bash
uvx zensical serve     # live preview on :8000
uvx zensical build     # static site into site/
```

Publishing: `.github/workflows/docs.yml` builds `docs/` on every push to `main`
that touches it, and deploys `site/` to GitHub Pages. One-time setup — set the
Pages source to GitHub Actions:

```bash
gh api -X POST repos/arief05652/zagred/pages -f build_type=workflow
```

(or Settings → Pages → Source: **GitHub Actions**). Site lands at
<https://arief05652.github.io/zagred/>.

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, ship it in commercial closed-source
apps; just keep the copyright notice.

Apps built with `zagred build` compile Zagred, pywebview, bottle, proxy_tools and
CPython into the binary, so your distribution should also include
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and the PSF licence (shipped with
Python). Nuitka is AGPL-3.0, but its Runtime Library Exception explicitly allows
closed-source output, and Zagred never bundles it.

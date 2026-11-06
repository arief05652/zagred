# Getting started

## One-time setup

Zagred is not on PyPI yet. Install it from a checkout or as a local tool:

```bash
git clone https://github.com/arief05652/zagred
cd zagred
uv sync
uv run zagred doctor
```

`zagred doctor` prints the interpreter, pywebview, the real webview backend,
Nuitka, and on Linux `patchelf` / `appimagetool`. It always exits `0`; a line
says what is missing and how to fix it.

### Linux: one extra step

uv's Python cannot import the distro's `python3-gi`, so build the venv from the
system interpreter **before** `uv sync`:

```bash
sudo apt install python3-gi gir1.2-webkit2-4.1
uv venv --python /usr/bin/python3 --system-site-packages
uv sync
```

Verify with `uv run zagred doctor` — it should report `renderer gtk`.

## Create a project

```bash
zagred new
```

It asks for a name, a framework and a language, then writes a project that
already builds. Skip the questions in scripts:

```bash
zagred new my-app --template react --lang ts --pm bun -y
```

| `--template` | `--lang js` | `--lang ts` | Bundler |
|---|---|---|---|
| `vanilla` *(default)* | plain files, **no npm** | Vite | optional |
| `react` | Vite | Vite | yes |
| `vue` | Vite | Vite | yes |
| `solid` | Vite | Vite | yes |

Then:

```bash
cd my-app
uv sync
uv run zagred install     # frontend deps, with the package manager you picked
uv run zagred dev
```

## What you get

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

Two sources of truth, on purpose:

- **Python** owns the window, the exposed functions and the hooks.
- **`zagred.toml`** owns build metadata only — no runtime settings duplicated.

## Editing the app

Open `my_app/app.py`, add a function, decorate it:

```python
@app.expose
def add(a: int, b: int) -> int:
    return a + b
```

Call it from `web/src/main.js`:

```js
const sum = await zagred.call("add", { a: 2, b: 3 });
```

Save; `zagred dev` reloads the page. The dev command starts the frontend dev
server when `[ui] dev_command` is set, waits for `[ui] dev_url`, then opens the
window.

## Next

- [Backend](backend.md) — window, `@expose`, lifecycle, events
- [Frontend](frontend.md) — `zagred.call`, events, TypeScript
- [Hotkeys](hotkeys.md) — bind in Python or in the page
- [Building](build.md) — `.AppImage`, `.exe`, `.app`, `.dmg`

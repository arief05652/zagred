# `zagred.toml`

Build metadata only. Runtime configuration — window size, hooks, exposed
functions — lives in Python, in your `App`. That keeps exactly one source of
truth for each decision.

```toml
[app]
name = "my-app"
version = "0.1.0"
id = "com.example.my-app"
entry = "my_app.app:app"
icon = "web/public/icon.png"

[ui]
dir = "web"
command = "npm run dev -- --port 5173 --strictPort"
dev_url = "http://127.0.0.1:5173"
build = "npm run build"
dist = "web/dist"
package_manager = "npm"

[build]
target = "auto"
output = "dist"
jobs = 2
low_memory = false
```

Only `[app] name` and a well-formed `[app] entry` are mandatory; everything else
falls back to the default below.

## `[app]`

| Key | Default | Meaning |
|---|---|---|
| `name` | *required* | App name, also the binary and artifact file name (`my-app.AppImage`) |
| `version` | `"0.1.0"` | Semver used for the binary's version metadata |
| `id` | `com.example.<name>` | Reverse-DNS id, e.g. `com.example.my-app`; used for the Linux desktop entry and AppStream |
| `entry` | *required* | `"module:attribute"` — must be importable **statically** |
| `icon` | `None` | PNG/ICO/ICNS for the window and the packaged binary |

`entry` is written into the generated entry script as
`from <module> import <attribute>`, so a dynamic
`importlib.import_module("my_app.app")` would leave your package out of the
bundle and crash at startup.

## `[ui]`

| Key | Default | Meaning |
|---|---|---|
| `dir` | `"web"` | Frontend source, relative to the project root; dev commands run here |
| `command` | `None` | Command that starts the dev server. `None` = no bundler, serve `dir` directly |
| `dev_url` | `"http://localhost:5173"` | `zagred dev` waits for this URL before opening the window |
| `build` | `None` | Command that produces the production frontend, run before Nuitka |
| `dist` | `"web/dist"` | Its output, bundled into the binary under `ui/` |
| `package_manager` | `"npm"` | `npm`, `pnpm` or `bun`; only used by `zagred install`, never guessed |

`zagred install` reads `package_manager` and nothing else — no lockfile
sniffing, no mixing two managers in one project.

## `[build]`

| Key | Default | Meaning |
|---|---|---|
| `target` | `"auto"` | `auto`, `onefile`, `standalone`, `exe`, `appimage`, `app`, `dmg` |
| `output` | `"dist"` | Directory that receives per-target build output |
| `jobs` | `None` | Parallel C compiler jobs; `None` = all cores, negative = cores minus N |
| `low_memory` | `False` | Fewer jobs and lighter compiler options |

A `--target` or `--jobs` on the command line overrides the manifest.

## Local development against a checkout

Projects created by `zagred new` get this already. If you copied a project from
elsewhere and zagred is not on PyPI:

```toml
# pyproject.toml
[tool.uv.sources]
zagred = { path = "/path/to/zagred", editable = true }
```

## Reference

- [`Manifest`](reference.md#zagredmanifest) — the parsed, immutable dataclass
- [`load_manifest()`](reference.md#zagredload_manifestroot) — read and validate a file

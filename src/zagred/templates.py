"""Frontend templates used by ``zagred new``.

Eight combinations are generated from four frameworks and two languages. Most
files are shared; only the entry module, the Vite config and ``tsconfig.json``
vary. ``vanilla`` + ``js`` is the one Node-free option: it writes plain files the
window can load as-is. Every other combination is a Vite project.

Templates are plain strings with ``__NAME__`` / ``__MODULE__`` tokens, substituted
by :func:`zagred.scaffold.render`. They are not ``str.format`` templates because
the CSS and JavaScript they contain use literal braces.
"""

from __future__ import annotations

import json

FRAMEWORKS = ["vanilla", "react", "vue", "solid"]
"""Framework identifiers accepted by ``--template``."""

LANGUAGES = ["js", "ts"]
"""Script languages accepted by ``--lang``."""

DEFAULT_FRAMEWORK = "vanilla"
"""Used when no framework is given and prompts are unavailable."""

DEFAULT_LANGUAGE = "js"
"""Used when no language is given and prompts are unavailable."""

VITE = "^8.3.5"
"""Pinned Vite major, verified to build all four frameworks."""

TYPESCRIPT = "^7.0.2"
"""Pinned TypeScript major, verified against the generated tsconfigs."""

# -- shared ----------------------------------------------------------------

STYLE = """\
:root { color-scheme: light dark; }
body {
  margin: 0;
  font: 15px/1.5 system-ui, sans-serif;
  display: grid;
  place-items: center;
  height: 100vh;
  background: Canvas;
  color: CanvasText;
}
main { text-align: center; padding: 1rem; }
input, button { font: inherit; padding: 6px 10px; margin: 4px; }
#out { font-family: ui-monospace, monospace; min-height: 1.5em; }
"""

ZAGRED_DTS = """\
/// <reference types="vite/client" />

export {};

declare global {
  interface Window {
    zagred: ZagredBridge;
  }
  /** Same object as window.zagred; exposed as a bare global for convenience. */
  const zagred: ZagredBridge;
}

export interface ZagredBridge {
  ready: Promise<void>;
  call<T = unknown>(name: string, args?: Record<string, unknown>): Promise<T>;
  on(name: string, fn: (payload: unknown) => void): () => void;
  off(name: string, fn: (payload: unknown) => void): void;
}
"""


def _json(data: dict) -> str:
    """Serialise a dict as pretty-printed JSON with a trailing newline.

    Args:
        data: Mapping to serialise, normally a ``package.json`` or ``tsconfig``.

    Returns:
        Indented JSON text, newline-terminated so generated files match editor
        conventions.
    """
    return json.dumps(data, indent=2) + "\n"


def _package(name: str, deps: dict, dev: dict, lang: str, typecheck: bool) -> str:
    """Build a ``package.json`` for one stack.

    Args:
        name: Package name, matching the project directory.
        deps: Runtime dependencies, e.g. ``{"react": "^19.3.1"}``.
        dev: Development dependencies, including Vite and any framework plugin.
        lang: ``"js"`` or ``"ts"``. Only TypeScript projects get a
            ``typecheck`` script, since it would have nothing to check otherwise.
        typecheck: Whether ``tsc --noEmit`` is meaningful for this framework.
            ``False`` for Vue, whose SFCs need ``vue-tsc``.

    Returns:
        The JSON text of the manifest, newline-terminated.
    """
    scripts = {"dev": "vite", "build": "vite build"}
    if typecheck and lang == "ts":
        scripts["typecheck"] = "tsc --noEmit"
    return _json(
        {
            "name": name,
            "private": True,
            "version": "0.1.0",
            "type": "module",
            "scripts": scripts,
            "dependencies": deps,
            "devDependencies": dev,
        }
    )


def _tsconfig(**overrides) -> str:
    """Build a ``tsconfig.json`` with sane defaults plus framework overrides.

    The defaults target a bundler build with no emit: ``moduleResolution:
    bundler``, ``noEmit`` and ``strict``. Frameworks that need JSX transformation
    pass their own settings.

    Args:
        **overrides: Two recognised keys. ``compilerOptions`` is merged into the
            default compiler options, e.g. ``{"jsx": "react-jsx"}``. Any other
            key replaces a top-level field, e.g. ``include``.

    Returns:
        JSON text of the config, newline-terminated.
    """
    config = {
        "compilerOptions": {
            "target": "ES2022",
            "lib": ["ES2022", "DOM", "DOM.Iterable"],
            "module": "ESNext",
            "moduleResolution": "bundler",
            "strict": True,
            "noEmit": True,
            "skipLibCheck": True,
            "isolatedModules": True,
            "verbatimModuleSyntax": True,
        },
        "include": ["src"],
    }
    config["compilerOptions"].update(overrides.pop("compilerOptions", {}))
    config.update(overrides)
    return _json(config)


def _index_html(script: str, root_id: str, body: str) -> str:
    """Build the Vite entry HTML for one template.

    Args:
        script: Entry module file name, resolved against ``/src/``, e.g.
            ``"main.tsx"``.
        root_id: Id of the mount container: ``"app"`` for Vue, ``"root"`` for
            the others.
        body: Markup to place inside the container. Only the static vanilla
            template passes anything here; React, Vue and Solid mount into an
            empty container, and shipping markup would flash before the
            component renders.

    Returns:
        The HTML document as text, with ``__NAME__`` left for the scaffold to
        substitute.
    """
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>__NAME__</title>
  </head>
  <body>
    <div id="{root_id}">{body}</div>
    <script type="module" src="/src/{script}"></script>
  </body>
</html>
"""


# -- vanilla (no bundler, js only) ----------------------------------------

STATIC_FILES = {
    "web/index.html": """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>__NAME__</title>
    <link rel="stylesheet" href="src/style.css" />
  </head>
  <body>
    <main>
      <h1>__NAME__</h1>
      <input id="who" value="world" />
      <button id="go">say hello</button>
      <button id="pick">pick a file</button>
      <p id="out">&mdash;</p>
    </main>
    <script type="module" src="src/main.js"></script>
  </body>
</html>
""",
    "web/src/main.js": """\
const out = document.getElementById("out");

async function show(promise) {
  try {
    out.textContent = (await promise) ?? "(nothing)";
  } catch (err) {
    out.textContent = `${err.code}: ${err.message}`;
  }
}

document.getElementById("go").addEventListener("click", () =>
  show(zagred.call("greet", { name: document.getElementById("who").value })),
);

document.getElementById("pick").addEventListener("click", () =>
  show(zagred.call("pick_file")),
);
""",
}

# -- vite shared -----------------------------------------------------------

VITE_PACKAGES = {
    "vanilla": lambda name, lang: _package(
        name, {}, {"typescript": TYPESCRIPT, "vite": VITE}, lang, True
    ),
    "react": lambda name, lang: _package(
        name,
        {"react": "^19.3.1", "react-dom": "^19.3.1"},
        {
            "@types/react": "^19.3.0",
            "@types/react-dom": "^19.3.0",
            "@vitejs/plugin-react": "^6.1.2",
            "typescript": TYPESCRIPT,
            "vite": VITE,
        },
        lang,
        True,
    ),
    "vue": lambda name, lang: _package(
        name,
        {"vue": "^3.5.44"},
        {"@vitejs/plugin-vue": "^6.0.10", "typescript": TYPESCRIPT, "vite": VITE},
        lang,
        True,
    ),
    "solid": lambda name, lang: _package(
        name,
        {"solid-js": "^1.9.18"},
        {"typescript": TYPESCRIPT, "vite": VITE, "vite-plugin-solid": "^2.11.15"},
        lang,
        True,
    ),
}

VITE_CONFIG = {
    "react": """\
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
});
""",
    "vue": """\
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
});
""",
    "solid": """\
import { defineConfig } from "vite";
import solid from "vite-plugin-solid";

export default defineConfig({
  plugins: [solid()],
});
""",
}


# -- react / solid (jsx, same shape) --------------------------------------

JSX_FILES = {
    "js": {
        "web/src/main.jsx": """\
import { createRoot } from "react-dom/client";
import App from "./App";
import "./style.css";

createRoot(document.getElementById("root")).render(<App />);
""",
        "web/src/App.jsx": """\
import { useState } from "react";

export default function App() {
  const [who, setWho] = useState("world");
  const [out, setOut] = useState("\\u2014");

  async function run(promise) {
    try {
      setOut((await promise) ?? "(nothing)");
    } catch (err) {
      setOut(err.code + ": " + err.message);
    }
  }

  return (
    <main>
      <h1>__NAME__</h1>
      <input value={who} onChange={(e) => setWho(e.target.value)} />
      <button onClick={() => run(zagred.call("greet", { name: who }))}>say hello</button>
      <button onClick={() => run(zagred.call("pick_file"))}>pick a file</button>
      <p id="out">{out}</p>
    </main>
  );
}
""",
    },
    "ts": {
        "web/src/main.tsx": """\
import { createRoot } from "react-dom/client";
import App from "./App";
import "./style.css";

createRoot(document.getElementById("root")!).render(<App />);
""",
        "web/src/App.tsx": """\
import { useState } from "react";

export default function App() {
  const [who, setWho] = useState("world");
  const [out, setOut] = useState("\\u2014");

  async function run(promise: Promise<unknown>) {
    try {
      setOut(String((await promise) ?? "(nothing)"));
    } catch (err) {
      const e = err as { code?: string; message: string };
      setOut(`${e.code}: ${e.message}`);
    }
  }

  return (
    <main>
      <h1>__NAME__</h1>
      <input value={who} onChange={(e) => setWho(e.target.value)} />
      <button onClick={() => run(zagred.call("greet", { name: who }))}>say hello</button>
      <button onClick={() => run(zagred.call("pick_file"))}>pick a file</button>
      <p id="out">{out}</p>
    </main>
  );
}
""",
    },
}

SOLID_FILES = {
    "js": {
        "web/src/main.jsx": """\
import { render } from "solid-js/web";
import App from "./App";
import "./style.css";

render(() => <App />, document.getElementById("root"));
""",
        "web/src/App.jsx": """\
import { createSignal } from "solid-js";

export default function App() {
  const [who, setWho] = createSignal("world");
  const [out, setOut] = createSignal("\\u2014");

  async function run(promise) {
    try {
      setOut((await promise) ?? "(nothing)");
    } catch (err) {
      setOut(err.code + ": " + err.message);
    }
  }

  return (
    <main>
      <h1>__NAME__</h1>
      <input value={who()} onInput={(e) => setWho(e.currentTarget.value)} />
      <button onClick={() => run(zagred.call("greet", { name: who() }))}>say hello</button>
      <button onClick={() => run(zagred.call("pick_file"))}>pick a file</button>
      <p id="out">{out()}</p>
    </main>
  );
}
""",
    },
    "ts": {
        "web/src/main.tsx": """\
import { render } from "solid-js/web";
import App from "./App";
import "./style.css";

render(() => <App />, document.getElementById("root")!);
""",
        "web/src/App.tsx": """\
import { createSignal } from "solid-js";

export default function App() {
  const [who, setWho] = createSignal("world");
  const [out, setOut] = createSignal("\\u2014");

  async function run(promise: Promise<unknown>) {
    try {
      setOut(String((await promise) ?? "(nothing)"));
    } catch (err) {
      const e = err as { code?: string; message: string };
      setOut(`${e.code}: ${e.message}`);
    }
  }

  return (
    <main>
      <h1>__NAME__</h1>
      <input value={who()} onInput={(e) => setWho(e.currentTarget.value)} />
      <button onClick={() => run(zagred.call("greet", { name: who() }))}>say hello</button>
      <button onClick={() => run(zagred.call("pick_file"))}>pick a file</button>
      <p id="out">{out()}</p>
    </main>
  );
}
""",
    },
}

VUE_FILES = {
    "js": {
        "web/src/main.js": """\
import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
""",
        "web/src/App.vue": """\
<script setup>
import { ref } from "vue";

const who = ref("world");
const out = ref("\\u2014");

async function run(promise) {
  try {
    out.value = (await promise) ?? "(nothing)";
  } catch (err) {
    out.value = err.code + ": " + err.message;
  }
}
</script>

<template>
  <main>
    <h1>__NAME__</h1>
    <input v-model="who" />
    <button @click="run(zagred.call('greet', { name: who }))">say hello</button>
    <button @click="run(zagred.call('pick_file'))">pick a file</button>
    <p id="out">{{ out }}</p>
  </main>
</template>
""",
    },
    "ts": {
        "web/src/main.ts": """\
import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";

createApp(App).mount("#app");
""",
        "web/src/App.vue": """\
<script setup lang="ts">
import { ref } from "vue";

const who = ref("world");
const out = ref("\\u2014");

async function run(promise: Promise<unknown>) {
  try {
    out.value = String((await promise) ?? "(nothing)");
  } catch (err) {
    const e = err as { code?: string; message: string };
    out.value = `${e.code}: ${e.message}`;
  }
}
</script>

<template>
  <main>
    <h1>__NAME__</h1>
    <input v-model="who" />
    <button @click="run(zagred.call('greet', { name: who }))">say hello</button>
    <button @click="run(zagred.call('pick_file'))">pick a file</button>
    <p id="out">{{ out }}</p>
  </main>
</template>
""",
    },
}

VANILLA_VITE = {
    "js": {
        "web/src/main.js": """\
import "./style.css";

const out = document.getElementById("out");
const who = document.getElementById("who");

async function run(promise) {
  try {
    out.textContent = (await promise) ?? "(nothing)";
  } catch (err) {
    out.textContent = err.code + ": " + err.message;
  }
}

document.getElementById("go").addEventListener("click", () =>
  run(zagred.call("greet", { name: who.value })),
);
document.getElementById("pick").addEventListener("click", () => run(zagred.call("pick_file")));
""",
    },
    "ts": {
        "web/src/main.ts": """\
import "./style.css";

const out = document.getElementById("out")!;
const who = document.getElementById("who") as HTMLInputElement;

async function run(promise: Promise<unknown>) {
  try {
    out.textContent = String((await promise) ?? "(nothing)");
  } catch (err) {
    const e = err as { code?: string; message: string };
    out.textContent = `${e.code}: ${e.message}`;
  }
}

document.getElementById("go")!.addEventListener("click", () =>
  run(zagred.call("greet", { name: who.value })),
);
document.getElementById("pick")!.addEventListener("click", () => run(zagred.call("pick_file")));
""",
    },
}

BODY_MARKUP = """\
      <main>
        <h1>__NAME__</h1>
        <input id="who" value="world" />
        <button id="go">say hello</button>
        <button id="pick">pick a file</button>
        <p id="out">&mdash;</p>
      </main>
"""


def build_files(framework: str, lang: str) -> dict[str, str]:
    """Return every frontend file for one framework/language combination.

    Paths are relative to the project root and already include the ``web/``
    prefix. The set varies: TypeScript adds ``zagred.d.ts`` and ``tsconfig.json``
    (plus a ``*.vue`` shim for Vue), and frameworks with a plugin add a Vite
    config.

    Args:
        framework: One of :data:`FRAMEWORKS`.
        lang: One of :data:`LANGUAGES`.

    Returns:
        Mapping of relative path to unrendered template text.

    Raises:
        ValueError: If ``framework`` or ``lang`` is not recognised.
    """
    """Return {path: template} for the chosen combination."""
    if framework not in FRAMEWORKS:
        raise ValueError(f"unknown framework {framework!r}; pick one of {FRAMEWORKS}")
    if lang not in LANGUAGES:
        raise ValueError(f"unknown language {lang!r}; pick one of {LANGUAGES}")

    if framework == "vanilla" and lang == "js":
        return {"web/src/style.css": STYLE, **STATIC_FILES}

    files: dict[str, str] = {"web/src/style.css": STYLE}
    files["web/package.json"] = VITE_PACKAGES[framework]("__NAME__", lang)
    if lang == "ts":
        files["web/src/zagred.d.ts"] = ZAGRED_DTS
        if framework == "react":
            files["web/tsconfig.json"] = _tsconfig(compilerOptions={"jsx": "react-jsx"})
        elif framework == "solid":
            files["web/tsconfig.json"] = _tsconfig(
                compilerOptions={"jsx": "preserve", "jsxImportSource": "solid-js"}
            )
        else:
            files["web/tsconfig.json"] = _tsconfig()
            if framework == "vue":
                files["web/src/vue-shim.d.ts"] = 'declare module "*.vue";\n'

    if framework in VITE_CONFIG:
        ext = "ts" if lang == "ts" else "js"
        files[f"web/vite.config.{ext}"] = VITE_CONFIG[framework]

    entry = {
        ("react", "js"): JSX_FILES["js"],
        ("react", "ts"): JSX_FILES["ts"],
        ("solid", "js"): SOLID_FILES["js"],
        ("solid", "ts"): SOLID_FILES["ts"],
        ("vue", "js"): VUE_FILES["js"],
        ("vue", "ts"): VUE_FILES["ts"],
        ("vanilla", "js"): VANILLA_VITE["js"],
        ("vanilla", "ts"): VANILLA_VITE["ts"],
    }[(framework, lang)]
    files.update(entry)

    root_id = "app" if framework == "vue" else "root"
    script = next(path for path in files if path.startswith("web/src/main"))
    # Only the no-bundler vanilla page carries static markup; everything else
    # mounts into an empty container, so shipping the same markup flashes it first.
    body = BODY_MARKUP if (framework == "vanilla" and lang == "js") else ""
    files["web/index.html"] = _index_html(script.split("/")[-1], root_id, body)
    return files

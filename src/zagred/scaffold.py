"""`zagred new` — scaffold a project for a chosen frontend stack.

Templates use __NAME__ / __MODULE__ tokens, not str.format: the CSS and JS in
them contain braces of their own.
"""

from __future__ import annotations

import importlib.metadata
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from .templates import (
    BRIDGE_JS,
    BRIDGE_TS,
    DEFAULT_FRAMEWORK,
    DEFAULT_LANGUAGE,
    build_files,
)

PYPROJECT = """\
[project]
name = "__NAME__"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["zagred"]

[dependency-groups]
build = [
    "nuitka>=4.2",
    "patchelf>=0.18; sys_platform == 'linux'",
]
__SOURCES__"""

APP_PY = '''\
import zagred

app = zagred.App(
    title="__NAME__",
    size=(1024, 700),
    min_size=(640, 480),
)


@app.expose
def greet(name: str) -> str:
    """Reachable from the UI as zagred.call("greet", { name })."""
    return f"Hello, {name}!"


@app.expose
def add(a: int, b: int) -> int:
    return a + b


@app.expose
def pick_file() -> str | None:
    """Native dialog, driven from the UI."""
    files = app.create_file_dialog(allow_multiple=False)
    return files[0] if files else None
'''

GITIGNORE = """\
__pycache__/
*.py[oc]
.venv/
dist/
.zagred/
web/dist/
web/node_modules/
"""

_BUILD_SECTION = """\
[build]
# What to produce. Each target writes its own dist/<target>/ folder, so
# building one never overwrites another.
#   auto        whatever this OS ships best: AppImage, onefile, or .app
#   onefile     one self-contained executable, slower to start
#   standalone  folder holding the executable plus its libraries
#   exe         Windows installer (NSIS)
#   appimage    Linux AppImage
#   app         macOS .app bundle
#   dmg         macOS disk image
target      = "auto"
# output      = "dist"   # parent folder for the dist/<target>/ directories
# jobs        = -1       # parallel C compiles; -2 keeps 2 cores free for other work
# low_memory  = false    # lighter compiler options, for a small-RAM machine
"""

PACKAGE_MANAGERS = {
    "npm": {"install": "npm install", "add": "npm install", "run": "npm run"},
    "pnpm": {"install": "pnpm install", "add": "pnpm add", "run": "pnpm run"},
    "bun": {"install": "bun install", "add": "bun add", "run": "bun run"},
}

DEFAULT_PACKAGE_MANAGER = "npm"


def detect_package_managers() -> list[str]:
    """Find the JavaScript package managers available on ``PATH``.

    Returns:
        Names usable as a package manager, in :data:`PACKAGE_MANAGERS` order so
        ``npm`` wins ties. Empty when none of them is installed.
    """
    return [name for name in PACKAGE_MANAGERS if shutil.which(name)]


MANIFEST_STATIC = (
    """\
# zagred.toml — the only config file a Zagred app needs.
# Anything commented out is optional; delete the leading '#' to use it.

[app]
# Window title, and the name of the built file.
name    = "__NAME__"
# App version, also written into the installer metadata.
version = "0.1.0"
# Reverse-DNS id, used by macOS bundles.
id      = "com.example.__MODULE__"
# <module>:<the object holding your App>.
entry   = "__MODULE__.app:app"
# Icon file: .png on Linux, .ico on Windows, .icns on macOS.
# icon  = "__MODULE__/resources/icon.png"

[ui]
# Folder the window loads from.
dir     = "web"
# Production build, bundled as ui/ into the binary.
dist    = "web/dist"
# Which package manager zagred install uses, if you add a bundler later.
package_manager = "__PM__"
# Plain files need no build step. Once you add a bundler, switch on these three:
# command = "__PM_RUN__ dev -- --port 5173 --strictPort"
# dev_url = "http://127.0.0.1:5173"
# build   = "__PM_RUN__ build"

"""
    + _BUILD_SECTION
)

MANIFEST_VITE = (
    """\
# zagred.toml — the only config file a Zagred app needs.
# Anything commented out is optional; delete the leading '#' to use it.

[app]
# Window title, and the name of the built file.
name    = "__NAME__"
# App version, also written into the installer metadata.
version = "0.1.0"
# Reverse-DNS id, used by macOS bundles.
id      = "com.example.__MODULE__"
# <module>:<the object holding your App>.
entry   = "__MODULE__.app:app"
# Icon file: .png on Linux, .ico on Windows, .icns on macOS.
# icon  = "__MODULE__/resources/icon.png"

[ui]
# Frontend root, where the commands below run.
dir     = "web"
# Which package manager zagred install uses: npm, pnpm or bun.
package_manager = "__PM__"
# What zagred dev starts, and the port it waits for.
# Comment both out to load dist/ directly, with no dev server.
command = "__PM_RUN__ dev -- --port 5173 --strictPort"
dev_url = "http://127.0.0.1:5173"
# Run by zagred build before Nuitka.
build   = "__PM_RUN__ build"
# Output of build, bundled as ui/ into the binary.
dist    = "web/dist"

"""
    + _BUILD_SECTION
)


@dataclass(frozen=True)
class Stack:
    """A frontend combination chosen at scaffold time.

    Attributes:
        framework: One of ``"vanilla"``, ``"react"``, ``"vue"``, ``"solid"``.
        language: ``"js"`` or ``"ts"``.
    """

    framework: str = DEFAULT_FRAMEWORK
    language: str = DEFAULT_LANGUAGE

    @property
    def bundler(self) -> bool:
        """Whether a bundler (and therefore Node.js) is required.

        Only ``vanilla`` + ``js`` skips it: that combination writes plain files
        that the window can load directly, so the project stays Node-free.
        """
        return not (self.framework == "vanilla" and self.language == "js")


def render(
    template: str,
    name: str,
    module: str,
    sources: str,
    package_manager: str = DEFAULT_PACKAGE_MANAGER,
) -> str:
    """Substitute the scaffold placeholders in one template string.

    ``str.format`` cannot be used here: the CSS and JavaScript that get written
    into a new project contain literal braces.

    Args:
        template: Text containing ``__NAME__``, ``__MODULE__``, ``__SOURCES__``,
            one of the ``__BRIDGE_*__`` tokens or one of the ``__PM*__`` tokens.
        name: Project name as typed by the user, e.g. ``"my-app"``.
        module: Python-safe module name, e.g. ``"my_app"``.
        sources: Pre-rendered ``[tool.uv.sources]`` block, or empty when zagred
            is installed from an index.
        package_manager: One of :data:`PACKAGE_MANAGERS`. Its commands fill the
            ``__PM__`` (name), ``__PM_INSTALL__``, ``__PM_ADD__`` and
            ``__PM_RUN__`` tokens.

    Returns:
        The template with every known token replaced.

    Raises:
        ValueError: If ``package_manager`` is not a known manager.
    """
    commands = PACKAGE_MANAGERS.get(package_manager)
    if commands is None:
        raise ValueError(
            f"unknown package manager {package_manager!r}; pick one of {sorted(PACKAGE_MANAGERS)}"
        )
    return (
        template.replace("__NAME__", name)
        .replace("__MODULE__", module)
        .replace("__SOURCES__", sources)
        .replace("__BRIDGE_JS__", BRIDGE_JS)
        .replace("__BRIDGE_TS__", BRIDGE_TS)
        .replace("__PM__", package_manager)
        .replace("__PM_INSTALL__", commands["install"])
        .replace("__PM_ADD__", commands["add"])
        .replace("__PM_RUN__", commands["run"])
    )


def local_source() -> Path | None:
    """Find the checkout zagred was installed from, when there is one.

    pip and uv record source installs in PEP 610 ``direct_url.json``. A release
    published to PyPI has no such file, which is exactly the signal we want:
    generated projects then depend on ``zagred`` from the index instead of
    pointing at a local path that only works on this machine.

    Returns:
        The project directory of the local checkout, or ``None`` when zagred
        came from an index or the recorded path is not a Python project.
    """
    try:
        dist = importlib.metadata.distribution("zagred")
    except importlib.metadata.PackageNotFoundError:
        return None

    raw = dist.read_text("direct_url.json")
    if not raw:
        return None

    url = json.loads(raw).get("url", "")
    if not url.startswith("file://"):
        return None

    path = Path(unquote(urlparse(url).path))
    return path if (path / "pyproject.toml").is_file() else None


def _sources_block(source: Path | None) -> str:
    """Render the ``[tool.uv.sources]`` block for a generated pyproject.

    ``editable = true`` matters: without it uv installs a copy, and edits to
    zagred never show up until the project is re-synced.

    Args:
        source: Local checkout path, or ``None`` for an index install.

    Returns:
        A TOML fragment including its leading newline, or ``""``.
    """
    if source is None:
        return ""
    return f'\n[tool.uv.sources]\nzagred = {{ path = "{source}", editable = true }}\n'


_AUTO = object()


def create(
    name: str,
    root: Path,
    stack: Stack = Stack(),
    source=_AUTO,
    package_manager: str = DEFAULT_PACKAGE_MANAGER,
) -> list[Path]:
    """Write a complete, runnable project into ``root``.

    Produces the manifest, the uv project, the Python package and the frontend
    files for the chosen stack. Nothing is installed; the caller prints the
    follow-up commands.

    Args:
        name: Project name as typed by the user. Dashes are converted to
            underscores for the importable module name.
        root: Destination directory. Created if missing; parents are created too.
        stack: Frontend framework and language.
        source: Local zagred checkout to pin in ``[tool.uv.sources]``. Defaults to
            auto-detection via :func:`local_source`; pass ``None`` explicitly to
            force an index dependency.
        package_manager: One of :data:`PACKAGE_MANAGERS`, recorded in the
            manifest and used for the commands written into it.

    Returns:
        Paths of every file written, in creation order, for progress output.

    Raises:
        ValueError: If ``stack`` names an unknown framework or language, or
            ``package_manager`` is not a known manager.
    """
    module = name.replace("-", "_")
    if source is _AUTO:
        source = local_source()
    sources = _sources_block(source)

    files: dict[str, str] = {
        "zagred.toml": MANIFEST_VITE if stack.bundler else MANIFEST_STATIC,
        "pyproject.toml": PYPROJECT,
        ".python-version": "3.12\n",
        ".gitignore": GITIGNORE,
        "__MODULE__/__init__.py": "",
        "__MODULE__/app.py": APP_PY,
        **build_files(stack.framework, stack.language),
    }

    written: list[Path] = []
    for relative, template in files.items():
        path = root / render(relative, name, module, sources, package_manager)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render(template, name, module, sources, package_manager), encoding="utf-8"
        )
        written.append(path)
    return written

"""Parsing for ``zagred.toml`` — build metadata only.

Runtime configuration (window size, hooks, exposed functions) lives in Python,
in your :class:`zagred.app.App`. Keeping this file to build concerns means there
is exactly one source of truth for each decision.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "zagred.toml"


@dataclass(frozen=True)
class Manifest:
    """Everything ``zagred.toml`` can say, already defaulted and validated.

    Instances are immutable: they are produced once per command by
    :func:`load_manifest` and then read by ``zagred dev`` and ``zagred build``.

    Attributes:
        name: Application name. Also the binary and artifact file name
            (``my-app.AppImage``, ``my-app.exe``).
        version: Semver string used for the binary's version metadata.
        id: Reverse-DNS application id, e.g. ``com.example.my-app``. Used for
            the Linux desktop entry and AppStream metadata.
        entry: Import path to the App instance, ``"module:attribute"``.
            Must be importable **statically** — ``zagred build`` writes
            ``from <module> import <attribute>`` into the compiled entry script.
        icon: Optional path to a PNG/ICO/ICNS used for the window and the
            packaged binary.
        ui_dir: Directory holding the frontend source, relative to the project
            root. Dev server commands run with this as their working directory.
        ui_dev_command: Shell command that starts the frontend dev server, e.g.
            ``npm run dev -- --port 5173 --strictPort``. ``None`` means the
            frontend needs no bundler and ``zagred dev`` serves ``ui_dir``
            directly.
        ui_dev_url: URL of that dev server. ``zagred dev`` waits for this port
            before opening the window.
        ui_build_command: Shell command that produces the production frontend,
            run by ``zagred build`` before Nuitka.
        ui_dist: Directory produced by ``ui_build_command``; bundled into the
            binary under ``ui/``.
        target: Default build target (``auto``, ``onefile``, ``standalone``,
            ``exe``, ``appimage``, ``app``, ``dmg``). A ``--target`` passed on
            the command line overrides it.
        output: Directory that receives per-target build output.
        jobs: Default parallelism for the C compiler. ``None`` means "all
            cores"; negative values mean "CPU count minus N".
        low_memory: Ask Nuitka for fewer jobs and lighter compiler options.
        extra: Reserved for future keys; currently unused.
    """

    name: str
    version: str = "0.1.0"
    id: str = ""
    entry: str = ""
    icon: str | None = None
    # [ui]
    ui_dir: str = "web"
    ui_dev_command: str | None = None
    ui_dev_url: str = "http://localhost:5173"
    ui_build_command: str | None = None
    ui_dist: str = "web/dist"
    # [build]
    target: str = "auto"
    output: str = "dist"
    jobs: int | None = None
    low_memory: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def module(self) -> str:
        """Module half of :attr:`entry`, e.g. ``"my_app.app"``."""
        return self.entry.split(":", 1)[0]

    @property
    def attribute(self) -> str:
        """Attribute half of :attr:`entry`, usually ``"app"``."""
        return self.entry.split(":", 1)[1]


def load_manifest(root: str | Path = ".") -> Manifest:
    """Read and validate ``zagred.toml`` from ``root``.

    Missing optional keys fall back to the defaults on :class:`Manifest`. Only
    ``[app] name`` and a well-formed ``[app] entry`` are mandatory.

    Args:
        root: Directory containing ``zagred.toml``. Relative paths are allowed.

    Returns:
        A validated, immutable :class:`Manifest`.

    Raises:
        FileNotFoundError: When ``zagred.toml`` is not in ``root``.
        ValueError: When ``[app] name`` is missing or ``[app] entry`` is not in
            ``"module:attribute"`` form.
    """
    path = Path(root) / CONFIG_NAME
    if not path.is_file():
        raise FileNotFoundError(f"{CONFIG_NAME} not found in {Path(root).resolve()}")

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    app = raw.get("app", {})
    ui = raw.get("ui", {})
    build = raw.get("build", {})

    name = app.get("name")
    if not name:
        raise ValueError(f"{CONFIG_NAME}: [app] name is required")
    entry = app.get("entry")
    if not entry or ":" not in entry:
        raise ValueError(f"{CONFIG_NAME}: [app] entry must look like 'module:attribute'")

    return Manifest(
        name=name,
        version=str(app.get("version", "0.1.0")),
        id=app.get("id", f"com.example.{name}"),
        entry=entry,
        icon=app.get("icon"),
        ui_dir=ui.get("dir", "web"),
        ui_dev_command=ui.get("command"),
        ui_dev_url=ui.get("dev_url", "http://localhost:5173"),
        ui_build_command=ui.get("build"),
        ui_dist=ui.get("dist", "web/dist"),
        target=build.get("target", "auto"),
        output=build.get("output", "dist"),
        jobs=build.get("jobs"),
        low_memory=bool(build.get("low_memory", False)),
    )

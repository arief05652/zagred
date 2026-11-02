"""The ``zagred`` command line.

Five commands share this module: ``new`` (interactive scaffold), ``dev`` (run
against the UI source), ``install`` (drive the project's package manager),
``build`` (compile with Nuitka) and ``doctor`` (report what the toolchain is
missing). ``dev``, ``install`` and ``build`` are thin wrappers; the real work
lives in :mod:`zagred.scaffold` and :mod:`zagred.build`.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .manifest import load_manifest
from .scaffold import (
    DEFAULT_PACKAGE_MANAGER,
    PACKAGE_MANAGERS,
    Stack,
    detect_package_managers,
)
from .templates import DEFAULT_FRAMEWORK, DEFAULT_LANGUAGE, FRAMEWORKS, LANGUAGES

NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to a command.

    Args:
        argv: Argument list to parse. Defaults to ``sys.argv[1:]``, which is what
            the ``zagred`` console script relies on; tests pass a list.

    Returns:
        Process exit code, ``0`` on success.
    """
    parser = argparse.ArgumentParser(prog="zagred", description="Zagred desktop apps")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="scaffold a project")
    new.add_argument("name", nargs="?")
    new.add_argument("--template", choices=FRAMEWORKS, help="frontend framework")
    new.add_argument("--lang", choices=LANGUAGES, help="javascript or typescript")
    new.add_argument(
        "--pm",
        choices=sorted(PACKAGE_MANAGERS),
        help="package manager for the frontend (default: ask, or the first one found)",
    )
    new.add_argument("-y", "--yes", action="store_true", help="accept defaults instead of asking")

    dev = sub.add_parser("dev", help="run the app against the UI source")
    dev.add_argument("--debug", action="store_true")

    install = sub.add_parser(
        "install", help="install frontend dependencies, or add packages"
    )
    install.add_argument(
        "packages",
        nargs="*",
        help="packages to add; omit to install what package.json already declares",
    )

    build = sub.add_parser("build", help="compile with Nuitka")
    build.add_argument(
        "--target",
        default=None,
        help="onefile|standalone|exe|appimage|app|dmg|auto "
        "(default: [build] target from zagred.toml)",
    )
    build.add_argument(
        "--jobs",
        type=int,
        help="parallel C compiler jobs; negative = CPU count minus N (keeps the machine usable)",
    )
    build.add_argument(
        "--debug",
        action="store_true",
        help="open the WebView inspector in the built app (development only, do not ship)",
    )

    sub.add_parser("doctor", help="check the toolchain")

    args = parser.parse_args(argv)
    if args.command == "new":
        return _new(args)
    if args.command == "dev":
        return _dev(args.debug)
    if args.command == "install":
        return _install(args.packages)
    if args.command == "build":
        from .build import build

        manifest = load_manifest()
        return build(manifest, Path.cwd(), target=args.target, debug=args.debug, jobs=args.jobs)
    if args.command == "doctor":
        from .build import doctor

        return doctor()
    return 1


# -- prompting --------------------------------------------------------------


def _interactive() -> bool:
    """Whether prompts can be shown, i.e. stdin is a terminal."""
    return sys.stdin.isatty()


def _ask(question: str, default: str) -> str:
    """Ask a free-text question, falling back to ``default``.

    Non-interactive runs (CI, piped input) never block: they return ``default``
    immediately, so ``zagred new`` stays scriptable.

    Args:
        question: Prompt text, printed without the trailing colon.
        default: Value used when stdin is not a terminal, on empty input, or on
            end-of-file.

    Returns:
        The user's answer, stripped, or ``default``.
    """
    if not _interactive():
        return default
    try:
        answer = input(f"? {question} [{default}]: ").strip()
    except EOFError:
        return default
    return answer or default


def _choose(question: str, options: list[str], default: str) -> str:
    """Ask the user to pick one of ``options`` from a numbered list.

    Accepts either a number or the literal option text. Unrecognised input falls
    back to ``default`` rather than looping, so a typo never traps the user in a
    prompt.

    Args:
        question: Prompt text shown above the list.
        options: Choices to print, in order. The default is marked with ``*``.
        default: Pre-selected option; must be a member of ``options``.

    Returns:
        The chosen option string, or ``default`` when stdin is not a terminal or
        the answer could not be matched.
    """
    if not _interactive():
        return default
    print(f"? {question}")
    for number, option in enumerate(options, 1):
        marker = "*" if option == default else " "
        print(f"  {marker} {number}) {option}")
    answer = _ask("choice", str(options.index(default) + 1))
    if answer.isdigit() and 1 <= int(answer) <= len(options):
        return options[int(answer) - 1]
    return answer if answer in options else default


# -- commands ---------------------------------------------------------------


def _new(args) -> int:
    """Handle ``zagred new``: prompt for anything missing, then scaffold.

    Args:
        args: Parsed argparse namespace with ``name``, ``template``, ``lang`` and
            ``yes``. Anything already provided skips its prompt.

    Returns:
        ``0`` on success, ``1`` when the name is invalid or the target directory
        already exists.
    """
    from .scaffold import create

    name = args.name or _ask("Project name", "my-app")
    if not NAME_RE.match(name):
        print(
            f"[zagred] invalid name {name!r}: start with a letter, then letters, digits, - or _",
            file=sys.stderr,
        )
        return 1

    quiet = args.yes or not _interactive()
    framework = args.template or (
        DEFAULT_FRAMEWORK if quiet else _choose("Frontend framework", FRAMEWORKS, DEFAULT_FRAMEWORK)
    )
    language = args.lang or (
        DEFAULT_LANGUAGE if quiet else _choose("Script language", LANGUAGES, DEFAULT_LANGUAGE)
    )
    stack = Stack(framework=framework, language=language)
    package_manager = args.pm or _pick_package_manager(stack, quiet)

    root = Path.cwd() / name
    if root.exists():
        print(f"[zagred] {root} already exists", file=sys.stderr)
        return 1

    for path in create(name, root, stack=stack, package_manager=package_manager):
        print(f"  created {path.relative_to(Path.cwd())}")

    steps = [f"cd {name}"]
    if stack.bundler:
        steps.append(f"cd web && {PACKAGE_MANAGERS[package_manager]['install']} && cd ..")
    if sys.platform.startswith("linux"):
        # GTK lives in the distro's python3-gi, invisible to uv's own Python.
        steps.append("uv venv --python /usr/bin/python3 --system-site-packages")
    steps += ["uv sync", "uv run zagred dev"]

    print(f"\n{framework} + {language} + {package_manager}. Next steps:")
    for step in steps:
        print(f"  {step}")
    print(
        "\nTo compile a binary (adds Nuitka):\n"
        "  uv sync --group build\n"
        "  uv run zagred build\n"
    )
    return 0


def _pick_package_manager(stack: Stack, quiet: bool) -> str:
    """Decide which package manager the generated manifest records.

    A plain-file frontend never installs anything, so it keeps the default
    rather than asking a question that has no effect.

    Args:
        stack: Chosen frontend stack; only ``bundler`` is read.
        quiet: Skip the prompt and take the first available manager.

    Returns:
        A key of :data:`PACKAGE_MANAGERS`.
    """
    if not stack.bundler:
        return DEFAULT_PACKAGE_MANAGER
    available = detect_package_managers() or [DEFAULT_PACKAGE_MANAGER]
    if quiet or len(available) == 1:
        return available[0]
    return _choose("Package manager", available, available[0])


def _ui_cwd(root: Path, manifest) -> Path:
    """Working directory for frontend commands.

    Args:
        root: Project root.
        manifest: Parsed manifest; only ``ui_dir`` is read.

    Returns:
        ``root/ui_dir`` when that directory exists, otherwise ``root`` — which
        keeps single-directory projects working.
    """
    candidate = root / manifest.ui_dir
    return candidate if candidate.is_dir() else root


def _install(packages: list[str]) -> int:
    """Handle ``zagred install``: drive the project's package manager.

    The manager comes from ``[ui] package_manager``, never from guessing, so a
    project scaffolded with bun keeps using bun. With no arguments this installs
    what ``package.json`` already declares; with arguments it adds packages.

    Args:
        packages: Package names to add. Empty means "install everything".

    Returns:
        ``0`` on success, ``1`` when the configured manager is unknown or not
        installed, otherwise the manager's own exit code.
    """
    root = Path.cwd()
    manifest = load_manifest(root)
    manager = manifest.ui_package_manager
    commands = PACKAGE_MANAGERS.get(manager)
    if commands is None:
        print(
            f"[zagred] unknown [ui] package_manager {manager!r}; "
            f"pick one of {sorted(PACKAGE_MANAGERS)}",
            file=sys.stderr,
        )
        return 1

    cwd = _ui_cwd(root, manifest)
    argv = (commands["add"] if packages else commands["install"]).split() + packages
    print(f"[zagred] {' '.join(argv)}  (in {cwd.name}/)")
    try:
        return subprocess.run(argv, cwd=cwd).returncode
    except FileNotFoundError:
        print(f"[zagred] {manager} is not installed or not on PATH", file=sys.stderr)
        return 1


def _dev(debug: bool) -> int:
    """Handle ``zagred dev``: start the UI, then open a window on it.

    Two modes, chosen by the manifest. With ``[ui] command`` set, the dev server
    is started and ``zagred`` waits for its port. Without it, ``[ui] dir`` is
    served straight from disk by pywebview's own HTTP server.

    The frontend process is always stopped on the way out, including when the
    window is closed, when the server fails to start, and on Ctrl+C.

    Args:
        debug: Open the WebView inspector.

    Returns:
        ``0`` on a normal exit, ``1`` if the dev server never became ready.
    """
    root = Path.cwd()
    manifest = load_manifest(root)
    sys.path.insert(0, str(root))

    process = None
    if manifest.ui_dev_command:
        cwd = _ui_cwd(root, manifest)
        print(f"[zagred] frontend: {manifest.ui_dev_command}  (in {cwd.name}/)")
        process = _spawn(manifest.ui_dev_command, cwd)
        try:
            _wait_for(manifest.ui_dev_url, process)
        except RuntimeError as exc:
            _stop(process)
            print(f"[zagred] {exc}", file=sys.stderr)
            return 1
        ui = manifest.ui_dev_url
    else:
        ui = str(root / manifest.ui_dir)

    app = getattr(importlib.import_module(manifest.module), manifest.attribute)
    try:
        app.run(ui=ui, debug=debug)
    finally:
        if process is not None:
            _stop(process)
    return 0


def _spawn(command: str, cwd: Path) -> subprocess.Popen:
    """Start the frontend dev server in its own session.

    Without a new session, ``shell=True`` gives us a process that dies while
    ``npm`` → ``sh`` → ``node`` keep running and holding the TTY. Closing the
    window then leaves Vite reading a dead terminal, which surfaces as
    ``Error: read EIO`` on every keypress.

    Args:
        command: Shell command from ``[ui] command``.
        cwd: Directory to run it in, normally ``[ui] dir``.

    Returns:
        The running process. Its pid doubles as the process-group id on POSIX,
        which is what :func:`_stop` uses.
    """
    if os.name == "nt":
        return subprocess.Popen(command, shell=True, cwd=cwd)
    return subprocess.Popen(command, shell=True, cwd=cwd, start_new_session=True)


def _stop(process: subprocess.Popen) -> None:
    """Stop a frontend process tree started by :func:`_spawn`.

    Sends ``SIGTERM`` to the whole group first so the server can clean up, waits
    up to five seconds, then ``SIGKILL``s whatever is left. The final sweep is
    what catches the npm shim's grandchildren (``sh`` and ``node``), which are
    not children of the process we spawned.

    Safe to call twice and safe on an already-dead process. On Windows it falls
    back to ``taskkill /T``.

    Args:
        process: The process returned by :func:`_spawn`.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True
        )
        return

    if process.poll() is None:
        _signal_group(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    # npm shims and vite are grandchildren: sweep whatever is left in the group.
    _signal_group(process.pid, signal.SIGKILL)


def _signal_group(pgid: int, sig: int) -> None:
    """Send a signal to a whole process group, ignoring races.

    ``ProcessLookupError`` means everything already exited, and
    ``PermissionError`` means it is not ours; both are normal during shutdown and
    must not interrupt cleanup.

    Args:
        pgid: Process-group id, which equals the spawned leader's pid.
        sig: Signal number, e.g. ``signal.SIGTERM``.
    """
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _wait_for(url: str, process: subprocess.Popen, timeout: float = 60.0) -> None:
    """Poll until the dev server accepts connections on its port.

    Fails fast when the server exits instead of waiting out the whole timeout,
    which is the difference between a one-second error and a one-minute hang.

    Args:
        url: Dev server URL from ``[ui] dev_url``. Only host and port are used.
        process: The dev server process, watched for premature exit.
        timeout: Seconds to keep trying before giving up.

    Raises:
        RuntimeError: If the server exited, or the port never opened.
    """
    parsed = urlparse(url)
    host, port = parsed.hostname or "localhost", parsed.port or 80
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("frontend dev server exited before it was ready")
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"frontend dev server never opened {host}:{port}")

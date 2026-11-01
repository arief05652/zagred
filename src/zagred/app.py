"""Application object: window creation, lifecycle hooks, and the JS bridge.

``zagred.toml`` only carries build metadata. Everything the window does at
runtime — size, chrome, visibility, lifecycle — is declared here in Python so
there is a single source of truth.
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Callable

from .assets import resolve_ui
from .bridge import SHIM, Bridge

# Printed when no webview engine can be imported. Keyed by ``sys.platform``;
# the Linux text also explains the uv/`python3-gi` split, which is the single
# most common setup failure.
WEBVIEW_HINT = {
    "linux": (
        "Zagred needs GTK bindings that this interpreter can import.\n"
        "  sudo apt install python3-gi gir1.2-webkit2-4.1\n"
        "uv's Python cannot see the distro's python3-gi, so recreate the venv:\n"
        "  rm -rf .venv && uv venv --python /usr/bin/python3 --system-site-packages && uv sync"
    ),
    "win32": (
        "Zagred needs the WebView2 runtime:\n"
        "  https://developer.microsoft.com/microsoft-edge/webview2/"
    ),
}


class App:
    """A Zagred application: one window, one bridge, one lifecycle.

    Typical use::

        import zagred

        app = zagred.App(title="Notes", size=(1024, 700))

        @app.expose
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        @app.on_start
        def boot() -> None:
            print("ready")

    Only ``@app.expose`` functions are reachable from JavaScript. Everything
    else on this class is Python-side control (window manipulation, events,
    hooks) and is never exposed to the UI.

    The window itself only exists between :meth:`run` and the user closing it.
    Calling a control method such as :meth:`minimize` before ``run`` — or from
    a hook that fires after close — raises ``RuntimeError``.
    """

    def __init__(
        self,
        title: str = "Zagred",
        size: tuple[int, int] = (1024, 700),
        min_size: tuple[int, int] | None = None,
        position: tuple[int, int] | None = None,
        resizable: bool = True,
        fullscreen: bool = False,
        maximized: bool = False,
        minimized: bool = False,
        frameless: bool = False,
        easy_drag: bool = True,
        on_top: bool = False,
        focus: bool = True,
        shadow: bool = False,
        confirm_close: bool = False,
        transparent: bool = False,
        text_select: bool = False,
        zoomable: bool = False,
        vibrancy: bool = False,
        background_color: str = "#ffffff",
        icon: str | None = None,
        menu: list | None = None,
    ) -> None:
        """Configure the window that :meth:`run` will open.

        All options are read once, when the window is created. Mutating the
        attribute afterwards (``app.title = "x"``) does *not* update a running
        window — use the matching control method instead, e.g.
        :meth:`set_title`.

        Args:
            title: Window title, also shown in the taskbar or dock.
            size: ``(width, height)`` in logical pixels. Initial window size.
            min_size: ``(width, height)`` lower bound when the user resizes.
                Defaults to ``(200, 100)`` when omitted.
            position: ``(x, y)`` screen coordinates for the top-left corner.
                ``None`` lets the window manager place the window.
            resizable: Whether the user may resize the window. Set ``False``
                for fixed-size dialogs and splash windows.
            fullscreen: Start borderless and covering the screen.
            maximized: Start maximized but still decorated. Mutually exclusive
                with ``fullscreen`` in practice — pick one.
            minimized: Start minimized (or hidden in the taskbar on some Linux
                window managers).
            frameless: Draw the window without a title bar or borders. Pair with
                ``easy_drag`` and draw your own controls in the UI.
            easy_drag: When ``frameless`` is set, let the user drag the window by
                its background. No effect on decorated windows.
            on_top: Keep the window above other windows. Useful for tools and
                floating palettes; avoid for normal apps.
            focus: Take keyboard focus on open. Set ``False`` for background or
                notification-style windows.
            shadow: Draw a drop shadow around a ``frameless`` window.
            confirm_close: Ask the user to confirm before closing. Combine with
                :meth:`on_closing` when you need to save state first.
            transparent: Allow transparent pixels behind the webview. Requires a
                transparent background in your CSS as well.
            text_select: Allow selecting text. Defaults to ``False``, which
                matches native app behaviour; enable it for document-style UIs.
            zoomable: Enable pinch/ctrl-wheel zooming of the page.
            vibrancy: macOS only — blurred, translucent background material.
                Ignored on Linux and Windows.
            background_color: Color painted before the page renders, as a CSS
                color string. Set it to match your UI to avoid a flash of white.
            icon: Path to the window icon (PNG on Linux/Windows, ICNS or PNG on
                macOS). Also used by ``zagred build`` when ``[app] icon`` is set.
            menu: Platform menu definition passed straight to pywebview. Empty
                means "no custom menu".

        Raises:
            Nothing. Invalid paths and unsupported options surface when
            :meth:`run` creates the window.
        """
        self.title = title
        self.size = size
        self.min_size = min_size
        self.position = position
        self.resizable = resizable
        self.fullscreen = fullscreen
        self.maximized = maximized
        self.minimized = minimized
        self.frameless = frameless
        self.easy_drag = easy_drag
        self.on_top = on_top
        self.focus = focus
        self.shadow = shadow
        self.confirm_close = confirm_close
        self.transparent = transparent
        self.text_select = text_select
        self.zoomable = zoomable
        self.vibrancy = vibrancy
        self.background_color = background_color
        self.icon = icon
        self.menu = menu or []

        self._exposed: dict[str, Callable] = {}
        self._start_hooks: list[Callable] = []
        self._loaded_hooks: list[Callable] = []
        self._closing_hooks: list[Callable] = []
        self._closed_hooks: list[Callable] = []
        self._window = None

    # -- decorators -----------------------------------------------------

    def expose(self, fn: Callable) -> Callable:
        """Make ``fn`` callable from JavaScript.

        The function is registered under its ``__name__``, which is the string
        the UI passes to ``zagred.call(...)``. Exposing two functions with the
        same name keeps the last one silently.

        Arguments arrive as keyword arguments, and the return value must be
        JSON-serialisable — that is checked before the value leaves Python, so a
        mistake becomes an error in the UI instead of a blank window.

        Args:
            fn: The function to expose. May be a coroutine function; coroutines
                are awaited on the bridge's worker thread.

        Returns:
            ``fn`` unchanged, so this works as a decorator.

        Example:
            >>> @app.expose
            ... def greet(name: str) -> str:
            ...     return f"Hello, {name}!"
        """
        self._exposed[fn.__name__] = fn
        return fn

    def on_start(self, fn: Callable) -> Callable:
        """Register a hook that runs once the GUI loop is up.

        Fires before the page finishes loading, so it is the right place to
        start background work whose results you will ``emit`` later. Runs on a
        worker thread, not the UI thread.

        Args:
            fn: Zero-argument callable.

        Returns:
            ``fn`` unchanged, so this works as a decorator.
        """
        self._start_hooks.append(fn)
        return fn

    def on_loaded(self, fn: Callable) -> Callable:
        """Register a hook that runs when the page has finished loading.

        Runs on a worker thread. Use it to push initial state to the UI; the
        bridge is live by this point.

        Args:
            fn: Zero-argument callable.

        Returns:
            ``fn`` unchanged, so this works as a decorator.
        """
        self._loaded_hooks.append(fn)
        return fn

    def on_closing(self, fn: Callable) -> Callable:
        """Register a hook that runs when the user tries to close the window.

        Return ``False`` from the hook to cancel the close. Returning ``None``
        or any other value lets the close proceed. If several hooks are
        registered, the first one returning ``False`` cancels it.

        Args:
            fn: Zero-argument callable returning ``bool | None``.

        Returns:
            ``fn`` unchanged, so this works as a decorator.

        Example:
            >>> @app.on_closing
            ... def guard():
            ...     return save_unsaved_changes() or False
        """
        self._closing_hooks.append(fn)
        return fn

    def on_closed(self, fn: Callable) -> Callable:
        """Register a hook that runs after the window is gone.

        The window object is already invalid here, so window control methods
        will raise. Use it for cleanup only.

        Args:
            fn: Zero-argument callable.

        Returns:
            ``fn`` unchanged, so this works as a decorator.
        """
        self._closed_hooks.append(fn)
        return fn

    # -- events ---------------------------------------------------------

    def emit(self, name: str, payload=None) -> None:
        """Push an event to the UI, to be received by ``zagred.on(name, fn)``.

        Uses ``run_js`` with a JSON literal rather than ``evaluate_js``, so it
        keeps working under a strict Content-Security-Policy that forbids
        ``unsafe-eval``.

        Silent no-op before the window exists, which makes ``emit`` safe to call
        from hooks and background threads without null checks.

        Args:
            name: Event name. Must match the string the UI subscribed to.
            payload: Any JSON-serialisable value. Sent as-is to every listener.

        Raises:
            TypeError: If ``payload`` is not JSON-serialisable (raised by
                ``json.dumps``; nothing is sent in that case).
        """
        if self._window is None:
            return
        script = "window.zagred&&window.zagred._dispatch(%s,%s)" % (
            json.dumps(name),
            json.dumps(payload),
        )
        self._window.run_js(script)

    # -- window control -------------------------------------------------

    def _win(self):
        """Return the live pywebview window, or fail with a useful message."""
        if self._window is None:
            raise RuntimeError("the window is not running yet")
        return self._window

    def minimize(self) -> None:
        """Minimize the window to the taskbar or dock."""
        self._win().minimize()

    def maximize(self) -> None:
        """Maximize the window to fill the screen, keeping decorations."""
        self._win().maximize()

    def restore(self) -> None:
        """Undo a minimize or maximize."""
        self._win().restore()

    def toggle_fullscreen(self) -> None:
        """Switch between fullscreen and the previous decorated state."""
        self._win().toggle_fullscreen()

    def resize(self, width: int, height: int) -> None:
        """Resize the window and remember the new size.

        Args:
            width: New width in logical pixels.
            height: New height in logical pixels.
        """
        self.size = (width, height)
        self._win().resize(width, height)

    def move(self, x: int, y: int) -> None:
        """Move the window's top-left corner and remember the new position.

        Args:
            x: Screen x coordinate in logical pixels.
            y: Screen y coordinate in logical pixels.
        """
        self.position = (x, y)
        self._win().move(x, y)

    def set_title(self, title: str) -> None:
        """Change the window title and remember it.

        Args:
            title: New title text.
        """
        self.title = title
        self._win().set_title(title)

    def show(self) -> None:
        """Show a window that was hidden with :meth:`hide`."""
        self._win().show()

    def hide(self) -> None:
        """Hide the window without closing it."""
        self._win().hide()

    def destroy(self) -> None:
        """Close the window programmatically, running the usual close hooks."""
        self._win().destroy()

    def load_url(self, url: str) -> None:
        """Navigate the current window to another URL.

        Args:
            url: Absolute URL, or a path resolvable by the asset resolver.
        """
        self._win().load_url(url)

    def evaluate_js(self, script: str):
        """Run JavaScript in the page and return its last expression.

        Blocks until the page answers, so call it from a worker thread rather
        than from a blocking window event. Requires the page to allow ``eval``
        unless you use ``window.run_js`` semantics.

        Args:
            script: JavaScript source. A raw string is recommended for scripts
                containing backslashes.

        Returns:
            The last evaluated expression converted to Python types: JS objects
            become ``dict``, arrays become ``list``, ``undefined`` becomes
            ``None``.
        """
        return self._win().evaluate_js(script)

    def create_file_dialog(
        self,
        allow_multiple: bool = False,
        directory: str = "",
        save_filename: str = "",
        file_types: tuple = (),
    ) -> tuple | None:
        """Open the operating system's file picker.

        Blocks until the user answers, so call it from inside an ``@app.expose``
        function (which already runs on a worker thread) rather than from a hook
        that must stay responsive.

        Args:
            allow_multiple: Let the user select more than one file.
            directory: Directory the dialog opens in. Empty means the OS default.
            save_filename: Pre-filled file name, for save-style dialogs.
            file_types: Tuple of ``"Description (*.ext;*.ext)"`` strings used to
                filter the list. Empty allows all files.

        Returns:
            A tuple of absolute paths, or ``None`` if the user cancelled.
        """
        import webview

        return self._win().create_file_dialog(
            webview.FileDialog.OPEN,
            directory=directory,
            allow_multiple=allow_multiple,
            save_filename=save_filename,
            file_types=file_types,
        )

    # -- run ------------------------------------------------------------

    @property
    def window(self):
        """The underlying pywebview window, or ``None`` when not running."""
        return self._window

    def _window_kwargs(self) -> dict:
        """Translate the constructor options into pywebview's keyword names.

        Returns:
            Keyword arguments for ``webview.create_window``. ``x`` and ``y`` are
            only included when a position was given, so the window manager keeps
            control otherwise.
        """
        kwargs = {
            "width": self.size[0],
            "height": self.size[1],
            "min_size": self.min_size or (200, 100),
            "resizable": self.resizable,
            "fullscreen": self.fullscreen,
            "maximized": self.maximized,
            "minimized": self.minimized,
            "frameless": self.frameless,
            "easy_drag": self.easy_drag,
            "on_top": self.on_top,
            "focus": self.focus,
            "shadow": self.shadow,
            "confirm_close": self.confirm_close,
            "transparent": self.transparent,
            "text_select": self.text_select,
            "zoomable": self.zoomable,
            "vibrancy": self.vibrancy,
            "background_color": self.background_color,
            "menu": self.menu,
        }
        if self.position:
            kwargs["x"], kwargs["y"] = self.position
        return kwargs

    def run(self, ui: str | Path | None = None, debug: bool = False) -> None:
        """Create the window, start the GUI loop, and block until it closes.

        The GUI loop owns the calling thread, so ``run`` is normally the last
        statement of your entry module. ``zagred dev`` and ``zagred build`` both
        call this for you.

        Args:
            ui: What to load. An ``http(s)://`` URL is used as-is (the dev
                server). Anything else is resolved as a path — either a
                directory containing ``index.html`` or an HTML file — searching
                the working tree, the standalone ``.dist`` folder, and the
                onefile extraction directory.
            debug: Open the WebView inspector and stop suppressing the right-click
                context menu. Development only; ``zagred build --debug`` bakes
                this into a packaged app.

        Raises:
            FileNotFoundError: If ``ui`` cannot be resolved to an existing file.
            SystemExit: If no webview engine is available. The platform-specific
                fix is printed to stderr first.
        """
        import webview

        # pywebview ships OPEN_DEVTOOLS_IN_DEBUG=True, so any debug run pops the
        # inspector window. Tie it to the explicit flag instead of global state.
        webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = debug

        target = resolve_ui(ui)
        window = webview.create_window(
            self.title,
            url=target,
            js_api=Bridge(self._exposed),
            **self._window_kwargs(),
        )
        self._window = window

        def inject(*_args):
            """Inject the JS shim off-thread, because this event blocks."""

            # before_load is a *blocking* event on the main thread. Calling
            # evaluate_js() there deadlocks: the renderer waits for this handler
            # to return, so the page stays blank for seconds. Run it off-thread.
            def work():
                """Evaluate the shim on a worker thread and ignore late failures."""

                try:
                    window.evaluate_js(SHIM)
                except Exception:  # noqa: BLE001 - the page may already be gone
                    pass

            threading.Thread(target=work, daemon=True).start()

        def closing(*_args) -> bool:
            """Let any ``on_closing`` hook veto the close by returning False."""
            for hook in self._closing_hooks:
                if hook() is False:
                    return False
            return True

        window.events.before_load += inject
        window.events.loaded += lambda *_: _run_all(self._loaded_hooks)
        window.events.closing += closing
        window.events.closed += lambda *_: _run_all(self._closed_hooks)

        try:
            webview.start(debug=debug, func=_run_all, args=(self._start_hooks,), icon=self.icon)
        except webview.errors.WebViewException as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            hint = WEBVIEW_HINT.get(sys.platform) or "Install GTK or Qt bindings for your system."
            print(hint, file=sys.stderr)
            raise SystemExit(1) from exc
        self._window = None


def _run_all(hooks: list[Callable]) -> None:
    """Call every hook in order, letting exceptions propagate to the caller."""
    for hook in hooks:
        hook()

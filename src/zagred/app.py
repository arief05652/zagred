"""Application object: window creation, lifecycle hooks, and the JS bridge.

``zagred.toml`` only carries build metadata. Everything the window does at
runtime — size, chrome, visibility, lifecycle — is declared here in Python so
there is a single source of truth.
"""

from __future__ import annotations

import inspect
import json
import sys
import threading
from pathlib import Path
from typing import Callable

from .assets import resolve_ui
from .bridge import SHIM, Bridge, key_table, normalize

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
        confirm_close: bool = False,
        transparent: bool = False,
        background_color: str = "#ffffff",
        icon: str | None = None,
        menu: list | None = None,
        draggable: bool = False,
        settings: dict | None = None,
        start: dict | None = None,
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
            confirm_close: Ask the user to confirm before closing. Combine with
                :meth:`on_closing` when you need to save state first.
            transparent: Allow transparent pixels behind the webview. Requires a
                transparent background in your CSS as well.
            background_color: Color painted before the page renders, as a CSS
                color string. Set it to match your UI to avoid a flash of white.
            icon: Path to the window icon (PNG on Linux/Windows, ICNS or PNG on
                macOS). Also used by ``zagred build`` when ``[app] icon`` is set.
            menu: Platform menu definition passed straight to pywebview. Empty
                means "no custom menu".
            draggable: Let elements matching ``.pywebview-drag-region`` inside a
                frameless window move it. Unlike ``easy_drag`` this is per
                element, so buttons in the same bar keep working.
            settings: ``webview.settings`` overrides, applied before the window
                opens. Keys are validated against what pywebview knows, so a
                typo fails the build of the window instead of being ignored.
                Useful: ``{"ALLOW_DOWNLOADS": True}``,
                ``{"OPEN_EXTERNAL_LINKS_IN_BROWSER": False}``,
                ``{"IGNORE_SSL_ERRORS": True}`` for a kiosk app.
            start: Extra ``webview.start()`` arguments Zagred does not wrap:
                ``user_agent``, ``private_mode``, ``storage_path``,
                ``http_server``, ``http_port``, ``gui``, ``ssl``,
                ``localization``, ``server``, ``server_args``, ``menu``.
                Validated the same way as ``settings``.

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
        self.confirm_close = confirm_close
        self.transparent = transparent
        self.background_color = background_color
        self.icon = icon
        self.menu = menu or []
        self.draggable = draggable
        self.settings = dict(settings or {})
        self.start = dict(start or {})

        self._exposed: dict[str, Callable] = {}
        self._hotkeys: dict[str, Callable] = {}
        self._event_hooks: dict[str, list[Callable]] = {}
        # Set once the page has loaded. pywebview gates run_js on before_load and
        # waits up to 20s for it, so emitting from an earlier event (initialized,
        # before_show) would stall the GUI thread instead of failing fast.
        self._ready = False
        self._start_hooks: list[Callable] = []
        self._loaded_hooks: list[Callable] = []
        self._closing_hooks: list[Callable] = []
        self._closed_hooks: list[Callable] = []
        self._window = None
        self._bridge: Bridge | None = None

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

    def hotkey(self, combo: str, fn: Callable | None = None):
        """Bind a keyboard shortcut to a Python function.

        The key is grabbed by the shim before the page sees it, so the browser's
        own action is cancelled — pressing ``Ctrl+P`` runs your function instead
        of opening a print dialog. A shortcut matched in the UI is also
        dispatched as a ``hotkey`` event, so page code can react without a trip
        through Python:

        .. code-block:: js

            zagred.on("hotkey", ({ combo }) => console.log(combo));

        A shortcut with no modifier is ignored while an input, textarea, select
        or contenteditable element has focus, so typing ``k`` into a search box
        never fires ``Ctrl+K``'s sibling ``k``.

        Args:
            combo: The shortcut, e.g. ``"Ctrl+K"``. Modifiers are
                ``ctrl``/``meta``/``alt``/``shift``, plus ``mod`` for Ctrl on
                Linux and Windows and Cmd on macOS. Key names follow
                ``event.key``: ``a``, ``1``, ``escape``, ``enter``, ``up``, ``f5``.
            fn: Zero-argument callable. Omit it to use this as a decorator.

        Returns:
            ``fn`` unchanged, or a decorator when ``fn`` is omitted.

        Raises:
            ValueError: If ``combo`` is empty, has no key, or names two keys.
                Raised at registration time, before the window opens.

        Example:
            >>> @app.hotkey("mod+k")
            ... def palette() -> None:
            ...     app.emit("open", "palette")
        """
        if fn is None:
            return lambda inner: self.hotkey(combo, inner)

        self._hotkeys[normalize(combo)] = fn
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

    def on_event(self, name: str, fn: Callable | None = None):
        """Run ``fn`` when pywebview reports one of its own events.

        The four decorators above cover the lifecycle Zagred needs. This reaches
        the rest of pywebview's event surface without inventing a wrapper per
        event:

        ``before_show``, ``initialized``, ``shown``, ``minimized``,
        ``maximized``, ``restored``, ``resized``, ``moved``, ``request_sent``,
        ``response_received`` — plus ``before_load``, ``loaded``, ``closing``,
        ``closed``, which also still work through the decorators.

        ``fn`` receives whatever pywebview passes for that event, so the
        signature differs per event — ``resized`` gets ``width``/``height``,
        ``request_sent`` gets the request. Accept ``*args, **kwargs`` when you
        do not care. Returning ``False`` cancels the close for ``closing``.

        The name is checked when the window is created, not here, so a typo
        fails at startup with the list of real names instead of being silently
        never called.

        Args:
            name: pywebview event name.
            fn: Callable invoked with that event's arguments.

        Returns:
            ``fn`` unchanged, or a decorator when ``fn`` is omitted, so this
            works both as ``@app.on_event("resized")`` and as a plain call.

        Example:
            >>> @app.on_event("resized")
            ... def remember(width, height) -> None:
            ...     print(width, height)
        """
        if fn is None:
            return lambda inner: self.on_event(name, inner)

        self._event_hooks.setdefault(name, []).append(fn)
        return fn

    # -- events ---------------------------------------------------------

    def emit(self, name: str, payload=None) -> None:
        """Push an event to the UI, to be received by ``zagred.on(name, fn)``.

        Uses ``run_js`` with a JSON literal rather than ``evaluate_js``, so it
        keeps working under a strict Content-Security-Policy that forbids
        ``unsafe-eval``.

        Silent no-op before the page can receive it — no window yet, or a window
        that exists but has not finished loading. From the GUI thread the actual
        push is handed to a worker thread, because pywebview runs several events
        (``before_load``, ``before_show``, ``closing``) synchronously on that
        thread and ``run_js`` needs it to answer.

        Args:
            name: Event name. Must match the string the UI subscribed to.
            payload: Any JSON-serialisable value. Sent as-is to every listener.

        Raises:
            TypeError: If ``payload`` is not JSON-serialisable (raised by
                ``json.dumps``; nothing is sent in that case).
        """
        if self._window is None or not self._ready:
            return
        script = "window.zagred&&window.zagred._dispatch(%s,%s)" % (
            json.dumps(name),
            json.dumps(payload),
        )

        def send() -> None:
            """Push the event, ignoring the window vanishing underneath us."""
            window = self._window
            if window is None:
                return
            try:
                window.run_js(script)
            except Exception:  # noqa: BLE001 - pywebview raises while teardown runs
                pass

        if threading.current_thread() is threading.main_thread():
            # pywebview runs some events (before_load, before_show, closing)
            # synchronously on the GUI thread, and run_js needs that same loop to
            # answer: calling it here blocks for the full 20s timeout, which
            # freezes the window instead of delivering anything.
            threading.Thread(target=send, daemon=True).start()
        else:
            send()

    # -- window control -------------------------------------------------

    def _win(self):
        """Return the live pywebview window, or fail with a useful message."""
        if self._window is None:
            raise RuntimeError("the window is not running yet")
        return self._window

    # -- live window state ----------------------------------------------

    @property
    def width(self) -> int:
        """Current width in logical pixels, as the window manager sees it."""
        return self._win().width

    @property
    def height(self) -> int:
        """Current height in logical pixels, as the window manager sees it."""
        return self._win().height

    @property
    def x(self) -> int:
        """Current left edge on the screen, in logical pixels."""
        return self._win().x

    @property
    def y(self) -> int:
        """Current top edge on the screen, in logical pixels."""
        return self._win().y

    @property
    def state(self):
        """Live window state as pywebview's ``State`` object.

        It is mapping-like and may be empty until the backend reports a change,
        so do not assume a ``NORMAL`` value before the user has touched the
        window. Compare against ``webview.window.State`` members when it is
        populated.
        """
        return self._win().state

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

        Called from inside an ``@app.expose`` function, the navigation is
        deferred by a fraction of a second. pywebview hands the function's
        result back to JavaScript *after* it returns, and starting the
        navigation first destroys the document that result was meant for: the
        delivery then blocks for its full 20s timeout, and every later call in
        the page hangs behind it. Deferring lets the answer land first.
        Measured on WebKitGTK 4.1 with pywebview 6.2.

        Args:
            url: Absolute URL, or a path resolvable by the asset resolver.
        """
        if self._bridge is not None and self._bridge.busy:
            # shortcut: a 0.3s timer, not proof the answer landed; pywebview
            # offers no "after the response" hook to wait on.
            threading.Timer(0.3, self._win().load_url, args=(url,)).start()
            return
        self._win().load_url(url)

    def evaluate_js(self, script: str):
        """Run JavaScript in the page and return its last expression.

        Blocks until the page answers, so call it from a worker thread rather
        than from a blocking window event. For a result you do not need, use
        :meth:`run_js` — it never waits.

        Args:
            script: JavaScript source. A raw string is recommended for scripts
                containing backslashes.

        Returns:
            The last evaluated expression converted to Python types: JS objects
            become ``dict``, arrays become ``list``, ``undefined`` becomes
            ``None``.
        """
        return self._win().evaluate_js(script)

    def run_js(self, script: str):
        """Run JavaScript without waiting for an answer.

        Fire-and-forget: the script is queued and executed later, so read its
        effect with :meth:`evaluate_js` (or on a later call), never on the next
        line. Safe from any thread and works under a strict CSP that forbids
        ``eval``.

        Args:
            script: JavaScript source.

        Returns:
            Whatever the backend reports for the call; nothing you should rely
            on.
        """
        return self._win().run_js(script)

    def load_css(self, stylesheet: str) -> None:
        """Inject a stylesheet into the loaded page.

        Queued like :meth:`run_js`, so the rules are not in effect on the next
        line. Nothing is written to disk and nothing survives a navigation.

        Args:
            stylesheet: Raw CSS, not a path. Read the file yourself first.
        """
        self._win().load_css(stylesheet)

    def get_current_url(self) -> str | None:
        """The URL the window is showing, or ``None`` before it commits one."""
        return self._win().get_current_url()

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
            "confirm_close": self.confirm_close,
            "transparent": self.transparent,
            "background_color": self.background_color,
            "menu": self.menu,
            "draggable": self.draggable,
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

        # Both dicts are validated here, where pywebview is importable, so a typo
        # fails at startup with the list of real names instead of being ignored.
        _check_options(self.settings, webview.settings, "webview.settings")
        for key, value in self.settings.items():
            webview.settings[key] = value
        # func/args/debug/icon are Zagred's to pass; letting them through here
        # would collide with the keywords used below.
        start_params = set(inspect.signature(webview.start).parameters)
        _check_options(
            self.start, start_params - {"func", "args", "debug", "icon"}, "webview.start"
        )

        target = resolve_ui(ui)
        bridge = Bridge(self._exposed, self._hotkeys)
        self._bridge = bridge
        window = webview.create_window(
            self.title,
            url=target,
            js_api=bridge,
            **self._window_kwargs(),
        )
        self._window = window

        available = {name for name in dir(window.events) if not name.startswith("_")}
        unknown = sorted(set(self._event_hooks) - available)
        if unknown:
            raise ValueError(
                f"unknown pywebview event(s): {', '.join(unknown)}\n"
                f"  available: {', '.join(sorted(available))}"
            )
        for name, hooks in self._event_hooks.items():
            event = getattr(window.events, name)
            event += _hook_runner(hooks)

        def inject(*_args):
            """Inject the JS shim off-thread, because this event blocks."""

            # before_load is a *blocking* event on the main thread. Calling
            # evaluate_js() there deadlocks: the renderer waits for this handler
            # to return, so the page stays blank for seconds. Run it off-thread.
            def work():
                """Evaluate the shim on a worker thread and ignore late failures."""

                # The shim also parses combos the UI binds itself, so it needs
                # the same tables Python normalises with. Always sent.
                script = SHIM
                script += "\nwindow.zagred._keys = %s;" % json.dumps(key_table())
                if self._hotkeys:
                    # Combos bound in Python, so the shim knows what to claim.
                    # shortcut: injected once, so hotkey() after run() is ignored;
                    # push the array again if live rebinding is ever needed.
                    script += "\nwindow.zagred.hotkeys = %s;" % json.dumps(
                        sorted(self._hotkeys)
                    )

                try:
                    window.evaluate_js(script)
                except Exception:  # noqa: BLE001 - the page may already be gone
                    pass

            threading.Thread(target=work, daemon=True).start()

        def closing(*_args) -> bool:
            """Let any ``on_closing`` hook veto the close by returning False."""
            for hook in self._closing_hooks:
                if hook() is False:
                    return False
            return True

        def mark_loading(*_args) -> None:
            """Close the emit gate again: the document is being replaced."""
            self._ready = False

        def mark_ready(*_args) -> None:
            """Unlock emit() now that the page can receive events."""
            self._ready = True

        window.events.before_load += mark_loading
        window.events.before_load += inject
        window.events.loaded += mark_ready
        window.events.loaded += lambda *_: _run_all(self._loaded_hooks)
        window.events.closing += closing
        window.events.closed += lambda *_: _run_all(self._closed_hooks)

        try:
            webview.start(
                debug=debug,
                func=_run_all,
                args=(self._start_hooks,),
                icon=self.icon,
                **self.start,
            )
        except webview.errors.WebViewException as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            hint = WEBVIEW_HINT.get(sys.platform) or "Install GTK or Qt bindings for your system."
            print(hint, file=sys.stderr)
            raise SystemExit(1) from exc
        self._window = None
        self._ready = False
        self._bridge = None


def _run_all(hooks: list[Callable]) -> None:
    """Call every hook in order, letting exceptions propagate to the caller."""
    for hook in hooks:
        hook()


def _hook_runner(hooks: list[Callable]) -> Callable:
    """Wrap several hooks into the single callable pywebview expects.

    Returns:
        A callable that forwards the event's arguments to every hook and
        propagates ``False``, which is how pywebview cancels a close.
    """

    def run(*args, **kwargs):
        result = None
        for hook in hooks:
            value = hook(*args, **kwargs)
            if value is False:
                return False
            result = value
        return result

    return run


def _check_options(given: dict, known, where: str) -> None:
    """Reject option names pywebview does not recognise.

    Args:
        given: User-supplied mapping.
        known: Mapping or parameter view of accepted names.
        where: Name used in the error, e.g. ``"webview.start"``.

    Raises:
        ValueError: If ``given`` holds a key that is not in ``known``. The list
            of valid names is included, so the fix is visible in the traceback.
    """
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise ValueError(
            f"unknown {where} option(s): {', '.join(unknown)}\n"
            f"  known: {', '.join(sorted(known))}"
        )

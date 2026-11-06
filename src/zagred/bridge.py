"""The single JavaScript ↔ Python door.

pywebview exposes exactly one object per window as ``window.pywebview.api``.
Zagred puts a single method on it (``call``) so the user's API surface stays in
our own dispatcher instead of leaking dozens of generated attribute names. The
shim below wraps that method as the friendlier ``window.zagred``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys

#: Bridge command the shim uses for keyboard shortcuts. Reserved: it is routed
#: before the exposed-function table, so exposing a function under this name has
#: no effect.
HOTKEY = "__hotkey__"

_MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "meta": "meta",
    "cmd": "meta",
    "command": "meta",
    "super": "meta",
    "win": "meta",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "shift": "shift",
}
_ALIASES = {
    "up": "arrowup",
    "down": "arrowdown",
    "left": "arrowleft",
    "right": "arrowright",
    "esc": "escape",
    "return": "enter",
    "del": "delete",
    "spacebar": "space",
    "plus": "+",
}
_ORDER = ("ctrl", "meta", "alt", "shift")


def key_table() -> dict:
    """Return the shortcut vocabulary the shim needs to parse a combo alone.

    The UI can bind its own shortcuts with ``zagred.hotkey(...)``, and that has
    to normalise ``Ctrl+Shift+P`` without a round-trip to Python. Sending the
    tables keeps one source of truth: change a modifier here and both sides
    agree, instead of two lists drifting apart.

    Returns:
        The modifier, alias and ordering tables, plus what ``mod`` means on this
        platform.
    """
    return {
        "mods": _MODIFIERS,
        "aliases": _ALIASES,
        "order": list(_ORDER),
        "mod": "meta" if sys.platform == "darwin" else "ctrl",
    }


def normalize(combo: str, mac: bool | None = None) -> str:
    """Rewrite a shortcut into the one spelling the shim produces.

    Matching is a string comparison, so both sides have to agree exactly. The
    shim builds ``event.key`` in lowercase with the modifiers in a fixed order;
    this function accepts the looser spelling a human writes — ``Ctrl+Shift+P``,
    ``shift+ctrl+p``, the cross-platform ``mod`` — and returns that same form.

    Args:
        combo: The shortcut as written, e.g. ``"Ctrl+K"`` or ``"alt+Up"``.
        mac: Treat ``mod`` as ``meta``. Defaults to guessing from the platform.

    Returns:
        The canonical form, e.g. ``"ctrl+shift+p"``.

    Raises:
        ValueError: If the shortcut is empty, has no key, or names two keys.

    Example:
        >>> normalize("Shift+Ctrl+P")
        'ctrl+shift+p'
    """
    if mac is None:
        mac = sys.platform == "darwin"

    tokens = [part.strip().lower() for part in str(combo).split("+") if part.strip()]
    modifiers: set[str] = set()
    key = None

    for token in tokens:
        if token in _MODIFIERS:
            modifiers.add(_MODIFIERS[token])
        elif token == "mod":
            modifiers.add("meta" if mac else "ctrl")
        elif key is None:
            key = _ALIASES.get(token, token)
        else:
            raise ValueError(f"{combo!r} names more than one key")

    if key is None:
        raise ValueError(f"{combo!r} has modifiers but no key")

    return "+".join([name for name in _ORDER if name in modifiers] + [key])


# Injected on ``before_load`` from a worker thread — see App.run for why it must
# not run on the blocking event itself.
#
# ``ready`` resolves once pywebview has installed its own bridge object; page
# scripts may run before that, so every call awaits it. Events use ``run_js``
# with JSON literals instead of ``evaluate_js``, which keeps them working under a
# Content-Security-Policy that forbids 'unsafe-eval'.
SHIM = r"""
(function () {
  if (window.zagred) return;
  var handlers = new Map();
  var ready = new Promise(function (resolve) {
    var timer = setInterval(function () {
      if (window.pywebview && window.pywebview.api && window.pywebview.api.call) {
        clearInterval(timer);
        resolve();
      }
    }, 20);
  });

  function editable(node) {
    if (!node) return false;
    var tag = (node.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || node.isContentEditable === true;
  }

  window.zagred = {
    ready: ready,
    async call(name, args) {
      await ready;
      var res = await window.pywebview.api.call(name, args || {});
      if (res && res.ok) return res.data;
      var err = new Error((res && res.error && res.error.message) || "call failed");
      err.code = (res && res.error && res.error.code) || "error";
      throw err;
    },
    on(name, fn) {
      var list = handlers.get(name);
      if (!list) handlers.set(name, (list = []));
      list.push(fn);
      return function () { window.zagred.off(name, fn); };
    },
    off(name, fn) {
      var list = handlers.get(name);
      if (list && list.indexOf(fn) !== -1) list.splice(list.indexOf(fn), 1);
    },
    // Filled in from Python after injection; combos bound with app.hotkey().
    hotkeys: [],
    // Grammar tables from Python, so a UI-side combo normalises identically.
    _keys: { mods: {}, aliases: {}, order: [], mod: "ctrl" },
    _bound: new Map(),
    _normalize(combo) {
      var table = this._keys;
      var tokens = String(combo)
        .toLowerCase()
        .split("+")
        .map(function (part) { return part.trim(); })
        .filter(function (part) { return part.length > 0; });

      var mods = [];
      var key = null;
      tokens.forEach(function (token) {
        var mod = token === "mod" ? table.mod : table.mods[token];
        if (typeof mod === "string") {
          if (mods.indexOf(mod) === -1) mods.push(mod);
          return;
        }
        if (key !== null) throw new Error(combo + " names more than one key");
        key = table.aliases[token] || token;
      });

      if (key === null) throw new Error(combo + " has modifiers but no key");
      return table.order.filter(function (name) { return mods.indexOf(name) !== -1; }).concat([key]).join("+");
    },
    hotkey(combo, fn) {
      var name = this._normalize(combo);
      var list = this._bound.get(name);
      if (!list) this._bound.set(name, (list = []));
      list.push(fn);
      return function () {
        var at = list.indexOf(fn);
        if (at !== -1) list.splice(at, 1);
      };
    },
    _match(e) {
      var remote = this.hotkeys.length > 0;
      if (!remote && this._bound.size === 0) return;

      var parts = [];
      if (e.ctrlKey) parts.push("ctrl");
      if (e.metaKey) parts.push("meta");
      if (e.altKey) parts.push("alt");
      if (e.shiftKey) parts.push("shift");

      var key = (e.key || "").toLowerCase();
      // A modifier pressed on its own is not a shortcut.
      if (!key || key === "control" || key === "meta" || key === "alt" || key === "shift") return;
      // While typing, an unmodified key belongs to the field. Escape is the one
      // exception: it never inserts anything, and "cancel" is what users expect.
      if (!parts.length && key !== "escape" && editable(e.target)) return;
      if (key === " " || key === "spacebar") key = "space";

      var combo = parts.concat([key]).join("+");
      var local = this._bound.get(combo);
      var owns = remote && this.hotkeys.indexOf(combo) !== -1;
      if (!local && !owns) return;

      // Claim the keystroke before the browser acts on it (Ctrl+P, F5, ...).
      e.preventDefault();
      if (local) {
        local.slice().forEach(function (fn) {
          try { fn({ combo: combo, event: e, target: e.target }); } catch (err) { console.error(err); }
        });
      }
      this._dispatch("hotkey", { combo: combo });
      if (owns) this.call("__hotkey__", { combo: combo }).catch(function (err) { console.error(err); });
    },
    _dispatch(name, payload) {
      var list = handlers.get(name);
      if (list) list.forEach(function (fn) { try { fn(payload); } catch (e) { console.error(e); } });
    }
  };

  window.addEventListener("keydown", function (e) {
    if (!e.isComposing) window.zagred._match(e);
  }, true);
})();
"""


class Bridge:
    """The object handed to pywebview as ``js_api``.

    Holds no state beyond the exposed-function table, so a future multi-window
    release can create one per window.

    Attributes:
        _registry: Mapping of command name to the function registered with
            ``@app.expose``.
        _hotkeys: Mapping of normalized shortcut to the function registered with
            :meth:`zagred.app.App.hotkey`.
        _calls: How many dispatches are running right now. Navigation uses it to
            defer until the answer has been delivered to JavaScript.
    """

    def __init__(self, registry: dict, hotkeys: dict | None = None):
        """Store the command and shortcut tables.

        Args:
            registry: Mapping of name to callable. Names must match what the UI
                passes to ``zagred.call(...)``.
            hotkeys: Mapping of normalized shortcut to a zero-argument callable,
                as built by :meth:`zagred.app.App.hotkey`. Kept separate from
                ``registry`` so a shortcut can never be reached by name.
        """
        self._registry = registry
        self._hotkeys = hotkeys if hotkeys is not None else {}
        self._calls = 0

    @property
    def busy(self) -> bool:
        """True while a dispatch is in flight, i.e. a bridge call is running."""
        return self._calls > 0

    def call(self, name: str, args: dict | None = None) -> dict:
        """Dispatch one command and return a result envelope.

        Always returns a dictionary rather than raising, because an uncaught
        exception here would surface in JavaScript as an opaque failure. Errors
        are classified so the UI can branch on ``err.code``:

        - ``unknown_command`` — nothing is exposed under this name.
        - ``bad_arguments`` — the callable rejected the given keyword arguments
          (``TypeError``), usually a typo or a missing field.
        - any ``Exception`` subclass name — the user's function raised.

        Coroutine functions are run to completion with ``asyncio.run`` on the
        thread pywebview already dedicated to this call.

        Args:
            name: Registered command name.
            args: Keyword arguments from JavaScript. ``None`` is treated as an
                empty mapping.

        Returns:
            ``{"ok": True, "data": ...}`` on success, or
            ``{"ok": False, "error": {"code": str, "message": str}}`` on failure.
            ``data`` is guaranteed to be JSON-serialisable; that is verified
            before the envelope is returned.
        """
        if name == HOTKEY:
            return self._pressed((args or {}).get("combo"))

        self._calls += 1
        try:
            return self._dispatch(name, args)
        finally:
            self._calls -= 1

    def _dispatch(self, name: str, args: dict | None) -> dict:
        """Look the command up and run it, returning the result envelope.

        Split out of :meth:`call` so the in-flight counter is decremented even
        when the function raises.

        Args:
            name: Registered command name.
            args: Keyword arguments from JavaScript.

        Returns:
            The ``ok``/``error`` envelope described in :meth:`call`.
        """
        fn = self._registry.get(name)
        if fn is None:
            return _error("unknown_command", f"no exposed function named {name!r}")

        try:
            data = fn(**(args or {}))
            if inspect.isawaitable(data):
                data = asyncio.run(data)
            json.dumps(data)  # fail here, not as a blank window
            return {"ok": True, "data": data}
        except TypeError as exc:
            return _error("bad_arguments", str(exc))
        except Exception as exc:  # noqa: BLE001 - every failure must reach JS
            return _error(type(exc).__name__, str(exc))

    def _pressed(self, combo: str | None) -> dict:
        """Run the Python side of a keyboard shortcut.

        Called by the shim, never by page code directly. An unbound combo is a
        success with ``False`` rather than an error, because the shim may be
        holding a stale list: a shortcut bound later in the session, or a UI
        that knows about combos Python does not.

        Args:
            combo: The canonical shortcut the shim matched.

        Returns:
            The usual envelope, with ``True`` when a callable ran.
        """
        fn = self._hotkeys.get(combo)
        if fn is None:
            return {"ok": True, "data": False}

        try:
            fn()
            return {"ok": True, "data": True}
        except Exception as exc:  # noqa: BLE001 - a shortcut must not kill the UI
            return _error(type(exc).__name__, str(exc))


def _error(code: str, message: str) -> dict:
    """Build the failure half of the envelope.

    Args:
        code: Machine-readable tag the UI can branch on.
        message: Human-readable explanation, propagated to ``Error.message``.

    Returns:
        ``{"ok": False, "error": {"code": code, "message": message}}``.
    """
    return {"ok": False, "error": {"code": code, "message": message}}

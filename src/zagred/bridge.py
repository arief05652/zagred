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
    _dispatch(name, payload) {
      var list = handlers.get(name);
      if (list) list.forEach(function (fn) { try { fn(payload); } catch (e) { console.error(e); } });
    }
  };
})();
"""


class Bridge:
    """The object handed to pywebview as ``js_api``.

    Holds no state beyond the exposed-function table, so a future multi-window
    release can create one per window.

    Attributes:
        _registry: Mapping of command name to the function registered with
            ``@app.expose``.
    """

    def __init__(self, registry: dict):
        """Store the command table.

        Args:
            registry: Mapping of name to callable. Names must match what the UI
                passes to ``zagred.call(...)``.
        """
        self._registry = registry

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


def _error(code: str, message: str) -> dict:
    """Build the failure half of the envelope.

    Args:
        code: Machine-readable tag the UI can branch on.
        message: Human-readable explanation, propagated to ``Error.message``.

    Returns:
        ``{"ok": False, "error": {"code": code, "message": message}}``.
    """
    return {"ok": False, "error": {"code": code, "message": message}}

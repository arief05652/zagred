"""Entry point that ``zagred build`` compiles into the binary.

The generated entry script imports your App *statically*::

    from my_app.app import app
    from zagred.runtime import boot

    boot(app, ui="ui", debug=False)

Nuitka bundles only what it can see through imports, so resolving the App with
``importlib.import_module("my_app.app")`` would compile fine and then fail at
runtime with ``ModuleNotFoundError``.
"""

from __future__ import annotations


def boot(app, ui: str, debug: bool = False) -> None:
    """Start a compiled app from its entry script.

    This is the only thing the generated entry module does, which keeps the
    compiled surface tiny and gives static analysers a single import to follow.

    Args:
        app: Your :class:`zagred.app.App` instance, imported statically.
        ui: Where the bundled frontend lives. Always ``"ui"`` in generated
            builds — ``zagred build`` copies ``[ui] dist`` into an ``ui/``
            directory inside the package, and the asset resolver finds it
            relative to the running code (including the onefile temp directory).
        debug: Open the WebView inspector. Baked in from ``zagred build --debug``;
            always ``False`` for release builds.
    """
    app.run(ui=ui, debug=debug)

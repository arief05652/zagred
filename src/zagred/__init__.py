"""Zagred — Python backends, web frontends, native desktop apps.

Public surface:

- :class:`zagred.App` — window, lifecycle and the JS bridge.
- :class:`zagred.Manifest` — parsed ``zagred.toml``.
- :func:`zagred.load_manifest` — read ``zagred.toml`` from a project root.

The CLI lives in :mod:`zagred.cli` and is not imported here, so ``import zagred``
stays cheap and never drags in build tooling.
"""

from .app import App
from .manifest import Manifest, load_manifest

__version__ = "0.1.3"
__all__ = ["App", "Manifest", "load_manifest", "__version__"]

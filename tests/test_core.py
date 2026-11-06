"""Self-checks for the parts that break silently: parsing, dispatch, asset paths."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import tomllib
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from zagred import assets
from zagred.app import App
from zagred.assets import resolve_ui
from zagred.bridge import HOTKEY, SHIM, Bridge, key_table, normalize
from zagred.build import pick_target
from zagred.manifest import load_manifest
from zagred.scaffold import Stack, create
from zagred.templates import FRAMEWORKS, LANGUAGES


class ManifestTest(unittest.TestCase):
    def _write(self, root: Path, body: str) -> Path:
        (root / "zagred.toml").write_text(body, encoding="utf-8")
        return root

    def test_build_parallelism(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = load_manifest(
                self._write(
                    Path(tmp),
                    '[app]\nname = "demo"\nentry = "demo.app:app"\n'
                    "[build]\njobs = -1\nlow_memory = true\n",
                )
            )
            self.assertEqual(manifest.jobs, -1)
            self.assertTrue(manifest.low_memory)

    def test_build_defaults_leave_the_machine_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = load_manifest(
                self._write(Path(tmp), '[app]\nname = "demo"\nentry = "demo.app:app"\n')
            )
            self.assertIsNone(manifest.jobs)
            self.assertFalse(manifest.low_memory)

    def test_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = load_manifest(self._write(Path(tmp), '[app]\nname = "demo"\nentry = "demo.app:app"\n'))
            self.assertEqual(manifest.id, "com.example.demo")
            self.assertEqual(manifest.ui_dir, "web")
            self.assertEqual(manifest.ui_package_manager, "npm")
            self.assertEqual(manifest.module, "demo.app")
            self.assertEqual(manifest.attribute, "app")

    def test_legacy_mode_key_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = load_manifest(
                self._write(
                    Path(tmp),
                    '[app]\nname = "demo"\nentry = "demo.app:app"\n'
                    '[build]\nmode = "onefile"\ntarget = "exe"\n',
                )
            )
            self.assertEqual(manifest.target, "exe")
            self.assertFalse(hasattr(manifest, "mode"), "mode was folded into target")

    def test_entry_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                load_manifest(self._write(Path(tmp), '[app]\nname = "demo"\nentry = "no-colon"\n'))


class BridgeTest(unittest.TestCase):
    def test_ok(self):
        bridge = Bridge({"greet": lambda name: f"hi {name}"})
        self.assertEqual(bridge.call("greet", {"name": "ari"}), {"ok": True, "data": "hi ari"})

    def test_unknown_command(self):
        result = Bridge({}).call("nope")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "unknown_command")

    def test_bad_arguments(self):
        result = Bridge({"greet": lambda name: name}).call("greet", {"who": "x"})
        self.assertEqual(result["error"]["code"], "bad_arguments")

    def test_async(self):
        async def slow() -> int:
            return 42

        self.assertEqual(Bridge({"slow": slow}).call("slow")["data"], 42)

    def test_unserializable_payload_is_an_error_not_a_crash(self):
        result = Bridge({"bad": lambda: object()}).call("bad")
        self.assertFalse(result["ok"])


class AssetsTest(unittest.TestCase):
    def test_url_passthrough(self):
        self.assertEqual(resolve_ui("http://localhost:5173"), "http://localhost:5173")

    def test_directory_resolves_to_index_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<html></html>", encoding="utf-8")
            self.assertTrue(resolve_ui(tmp).endswith("index.html"))

    def test_relative_spec_found_via_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ui").mkdir()
            (Path(tmp) / "ui" / "index.html").write_text("<html></html>", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ZAGRED_ASSETS": tmp}):
                self.assertEqual(resolve_ui("ui"), str(Path(tmp) / "ui" / "index.html"))

    def test_missing_ui_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                resolve_ui(Path(tmp) / "nope")

    def test_walks_up_from_module_file_like_onefile_extraction(self):
        """B4: assets sit next to the extracted package dir, not next to the binary."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "zagred").mkdir()
            (root / "ui").mkdir()
            (root / "ui" / "index.html").write_text("<html></html>", encoding="utf-8")
            fake_module = root / "zagred" / "assets.py"
            fake_module.write_text("", encoding="utf-8")
            with mock.patch.object(assets, "__file__", str(fake_module)):
                self.assertEqual(resolve_ui("ui"), str(root / "ui" / "index.html"))


class ScaffoldTest(unittest.TestCase):
    def test_no_unrendered_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            for path in create("my-app", Path(tmp), source=None):
                text = path.read_text(encoding="utf-8")
                for token in ("__NAME__", "__MODULE__", "__SOURCES__"):
                    self.assertNotIn(token, text)

    def test_generated_manifest_points_at_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            create("my-app", Path(tmp), source=None)
            manifest = load_manifest(tmp)
            self.assertEqual(manifest.entry, "my_app.app:app")
            self.assertTrue((Path(tmp) / "my_app" / "app.py").is_file())

    def test_pyproject_is_uv_resolvable_when_zagred_is_a_local_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "zagred-checkout"
            source.mkdir()
            (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            project = Path(tmp) / "app"
            create("app", project, source=source)

            data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
            self.assertEqual(data["project"]["dependencies"], ["zagred"])
            self.assertEqual(data["tool"]["uv"]["sources"]["zagred"]["path"], str(source))
            self.assertTrue(data["tool"]["uv"]["sources"]["zagred"]["editable"])
            self.assertEqual(data["dependency-groups"]["build"][0], "nuitka>=4.2")

    def test_pins_a_tested_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            create("app", Path(tmp), source=None)
            self.assertEqual((Path(tmp) / ".python-version").read_text().strip(), "3.12")

    def test_no_sources_block_for_a_published_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "app"
            create("app", project, source=None)
            data = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
            self.assertNotIn("tool", data)


class _Slot:
    """Stands in for one pywebview event: records handlers, fires on +=."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, fn):
        self.handlers.append(fn)
        return self


class _FakeWindow:
    """Stands in for one pywebview window, recording what reaches it."""

    def __init__(self):
        self.kw = {}
        self.events = SimpleNamespace(
            **{
                name: _Slot()
                for name in (
                    "_pywebviewready",
                    "before_load",
                    "before_show",
                    "closed",
                    "closing",
                    "initialized",
                    "loaded",
                    "maximized",
                    "minimized",
                    "moved",
                    "request_sent",
                    "resized",
                    "response_received",
                    "restored",
                    "shown",
                )
            }
        )
        self.exports = []
        self.scripts = []
        self.calls = []
        self.width, self.height, self.x, self.y = 1024, 700, 10, 20
        self.state = "NORMAL"

    def evaluate_js(self, script):
        self.exports.append(threading.current_thread().name)
        self.scripts.append(script)
        return "answered"

    def run_js(self, script):
        self.calls.append(("run_js", script))

    def load_css(self, stylesheet):
        self.calls.append(("load_css", stylesheet))

    def get_current_url(self):
        return "http://127.0.0.1:5173/"


# Mirrors the keys pywebview 6 ships, so option validation is exercised for real.
_FAKE_SETTINGS = {
    "ALLOW_DOWNLOADS": False,
    "ALLOW_FILE_URLS": True,
    "DRAG_REGION_DIRECT_TARGET_ONLY": False,
    "DRAG_REGION_SELECTOR": ".pywebview-drag-region",
    "DEFAULT_HTTP_PORT": 42001,
    "IGNORE_SSL_ERRORS": False,
    "OPEN_DEVTOOLS_IN_DEBUG": True,
    "OPEN_EXTERNAL_LINKS_IN_BROWSER": True,
    "REMOTE_DEBUGGING_PORT": None,
    "SHOW_DEFAULT_MENUS": True,
    "WEBVIEW2_RUNTIME_PATH": None,
}


def _fake_webview_run(ui_path: Path, app=None):
    """Run ``app`` against a fake pywebview module and return the window."""
    created = []

    def create_window(*args, **kwargs):
        window = _FakeWindow()
        window.kw = kwargs
        created.append(window)
        return window

    def start(
        func=None,
        args=None,
        localization=None,
        gui=None,
        debug=False,
        http_server=False,
        http_port=None,
        user_agent=None,
        private_mode=True,
        storage_path=None,
        menu=None,
        server=None,
        server_args=None,
        ssl=False,
        icon=None,
    ):
        # Same signature as pywebview.start, so option validation is real.
        created[0].start_kwargs = {key: value for key, value in locals().items() if key != "self"}

    fake = types.ModuleType("webview")
    fake.create_window = create_window
    fake.start = start
    fake.errors = SimpleNamespace(WebViewException=RuntimeError)
    fake.settings = dict(_FAKE_SETTINGS)

    with mock.patch.dict(sys.modules, {"webview": fake}):
        (app or App()).run(ui=str(ui_path))
    created[0].settings = fake.settings
    return created[0]


class RunLoopTest(unittest.TestCase):
    """B12: injecting the shim on the before_load thread deadlocked the page."""

    _Slot = _Slot
    _Window = _FakeWindow

    def _run(self, ui_path: Path, app=None):
        return _fake_webview_run(ui_path, app)

    def _fire(self, window, event: str) -> None:
        """Run every handler of an event, in registration order."""
        for handler in getattr(window.events, event).handlers:
            handler()

    def test_shim_is_not_injected_on_the_blocking_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            window = self._run(index)

            self.assertEqual(window.exports, [])
            self._fire(window, "before_load")

            deadline = time.time() + 2
            while not window.exports and time.time() < deadline:
                time.sleep(0.01)
            self.assertEqual(len(window.exports), 1)
            # the shim must run off the blocking before_load thread
            self.assertNotEqual(window.exports[0], threading.current_thread().name)

    def test_window_is_not_created_hidden(self):
        # pywebview's GTK backend never maps a window created with hidden=True,
        # even after show(). Keep it visible and rely on a fast load instead.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            window = self._run(index)
            self.assertNotIn("hidden", window.kw)
            self.assertIn("background_color", window.kw)

    def test_devtools_are_tied_to_the_debug_flag(self):
        # pywebview defaults OPEN_DEVTOOLS_IN_DEBUG to True, which is how a
        # release build ended up opening the inspector.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")

            seen = {}

            def create_window(*args, **kwargs):
                window = self._Window()
                window.kw = kwargs
                created.append(window)
                return window

            created = []
            for debug in (False, True):
                fake = types.ModuleType("webview")
                fake.create_window = create_window
                fake.start = lambda **kwargs: None
                fake.errors = SimpleNamespace(WebViewException=RuntimeError)
                fake.settings = {"OPEN_DEVTOOLS_IN_DEBUG": None}
                with mock.patch.dict(sys.modules, {"webview": fake}):
                    App().run(ui=str(index), debug=debug)
                seen[debug] = fake.settings["OPEN_DEVTOOLS_IN_DEBUG"]

            self.assertFalse(seen[False])
            self.assertTrue(seen[True])

    def test_window_options_reach_pywebview(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")

            created = []

            def create_window(*args, **kwargs):
                window = self._Window()
                window.kw = kwargs
                created.append(window)
                return window

            fake = types.ModuleType("webview")
            fake.create_window = create_window
            fake.start = lambda **kwargs: None
            fake.errors = SimpleNamespace(WebViewException=RuntimeError)
            fake.settings = {}

            app = App(
                title="demo",
                size=(900, 600),
                min_size=(400, 300),
                position=(10, 20),
                resizable=False,
                fullscreen=True,
                frameless=True,
                on_top=True,
                confirm_close=True,
                transparent=True,
                draggable=True,
                background_color="#101010",
            )
            with mock.patch.dict(sys.modules, {"webview": fake}):
                app.run(ui=str(index))

            kw = created[0].kw
            self.assertEqual((kw["width"], kw["height"]), (900, 600))
            self.assertEqual(kw["min_size"], (400, 300))
            self.assertEqual((kw["x"], kw["y"]), (10, 20))
            self.assertFalse(kw["resizable"])
            self.assertTrue(kw["fullscreen"])
            self.assertTrue(kw["frameless"])
            self.assertTrue(kw["on_top"])
            self.assertTrue(kw["confirm_close"])
            self.assertTrue(kw["transparent"])
            self.assertTrue(kw["draggable"])
            self.assertTrue(kw["transparent"])
            self.assertEqual(kw["background_color"], "#101010")

    def test_registered_hotkeys_reach_the_shim(self):
        # The shim has to match shortcuts itself to cancel the keystroke
        # synchronously, so the list is injected beside it.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            app = App()
            app.hotkey("Ctrl+K", lambda: None)
            window = self._run(index, app=app)

            self._fire(window, "before_load")
            deadline = time.time() + 2
            while not window.scripts and time.time() < deadline:
                time.sleep(0.01)

            script = window.scripts[0]
            self.assertIn('window.zagred.hotkeys = ["ctrl+k"]', script)
            self.assertIn("window.zagred._keys = {", script)

    def test_the_grammar_tables_are_sent_even_without_hotkeys(self):
        # The UI may bind a shortcut at any time, so its normalize() needs the
        # tables before Python has bound anything.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            window = self._run(index)

            self._fire(window, "before_load")
            deadline = time.time() + 2
            while not window.scripts and time.time() < deadline:
                time.sleep(0.01)

            script = window.scripts[0]
            self.assertEqual(
                json.loads(script.split("window.zagred._keys = ", 1)[1].split(";", 1)[0]),
                key_table(),
            )

    def test_no_hotkey_block_when_nothing_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            window = self._run(index)

            self._fire(window, "before_load")
            deadline = time.time() + 2
            while not window.scripts and time.time() < deadline:
                time.sleep(0.01)

            self.assertNotIn("hotkeys =", window.scripts[0])


class TemplateTest(unittest.TestCase):
    def test_every_combination_scaffolds_and_parses(self):
        for framework in FRAMEWORKS:
            for lang in LANGUAGES:
                with self.subTest(framework=framework, lang=lang), tempfile.TemporaryDirectory() as tmp:
                    stack = Stack(framework=framework, language=lang)
                    paths = create("demo", Path(tmp), stack=stack, source=None)

                    for path in paths:
                        text = path.read_text(encoding="utf-8")
                        for token in ("__NAME__", "__MODULE__", "__SOURCES__", "__BRIDGE_JS__", "__BRIDGE_TS__"):
                            self.assertNotIn(token, text, f"{path.name} kept {token}")

                    package = Path(tmp) / "web" / "package.json"
                    if stack.bundler:
                        data = json.loads(package.read_text(encoding="utf-8"))
                        self.assertEqual(data["scripts"]["dev"], "vite")
                        self.assertIn("build", data["scripts"])
                    else:
                        self.assertFalse(package.exists(), "static template must not need npm")

                    manifest = load_manifest(tmp)
                    if stack.bundler:
                        self.assertIn("strictPort", manifest.ui_dev_command)
                        self.assertEqual(manifest.ui_dev_url, "http://127.0.0.1:5173")
                    else:
                        self.assertIsNone(manifest.ui_dev_command)

    def test_bridge_binding_is_declared_wherever_it_is_called(self):
        """A bare `zagred` only resolves if the same module declares it.

        Vue is the case that hurt: its template compiler looks identifiers up on
        the component instance, never on ``window``, so the template rendered
        ``_ctx.zagred.call(...)`` and every button silently threw.
        """
        for framework in FRAMEWORKS:
            for lang in LANGUAGES:
                with self.subTest(framework=framework, lang=lang), tempfile.TemporaryDirectory() as tmp:
                    create("demo", Path(tmp), stack=Stack(framework, lang), source=None)
                    checked = 0
                    for path in (Path(tmp) / "web").rglob("*"):
                        if path.suffix not in {".js", ".jsx", ".ts", ".tsx", ".vue"}:
                            continue
                        text = path.read_text(encoding="utf-8")
                        if "zagred.call(" not in text:
                            continue
                        checked += 1
                        self.assertIn(
                            "const zagred",
                            text,
                            f"{framework}/{lang}: {path.name} calls zagred without declaring it",
                        )
                    self.assertGreater(checked, 0, f"{framework}/{lang}: no bridge call to check")

    def test_ts_templates_ship_bridge_types(self):
        for framework in FRAMEWORKS:
            if framework == "vanilla":
                continue
            with self.subTest(framework=framework), tempfile.TemporaryDirectory() as tmp:
                create("demo", Path(tmp), stack=Stack(framework=framework, language="ts"), source=None)
                self.assertTrue((Path(tmp) / "web" / "src" / "zagred.d.ts").is_file())
                self.assertTrue((Path(tmp) / "web" / "tsconfig.json").is_file())

    def test_the_hotkey_types_are_ambient(self):
        # BRIDGE_TS names HotkeyEvent without importing it, so the interface has
        # to live in `declare global` or every generated TS app fails to compile.
        from zagred.templates import BRIDGE_TS, ZAGRED_DTS

        ambient = ZAGRED_DTS.split("declare global {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("interface HotkeyEvent", ambient)
        self.assertIn("interface HotkeyPayload", ambient)
        self.assertIn("hotkey:", BRIDGE_TS)

    def test_unknown_stack_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                create("demo", Path(tmp), stack=Stack(framework="angular", language="js"), source=None)


class PackageManagerTest(unittest.TestCase):
    """The chosen package manager is recorded once and then always honoured."""

    def test_manifest_records_the_manager(self):
        for manager in ("npm", "pnpm", "bun"):
            with self.subTest(manager=manager), tempfile.TemporaryDirectory() as tmp:
                create("demo", Path(tmp), Stack("react", "js"), source=None, package_manager=manager)
                text = (Path(tmp) / "zagred.toml").read_text(encoding="utf-8")
                self.assertIn(f'package_manager = "{manager}"', text)
                self.assertIn(f'command = "{manager} run dev -- --port 5173', text)
                self.assertIn(f'build   = "{manager} run build"', text)

    def test_static_frontend_records_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            create("demo", Path(tmp), Stack("vanilla", "js"), source=None, package_manager="bun")
            manifest = load_manifest(tmp)

            self.assertEqual(manifest.ui_package_manager, "bun")
            self.assertIsNone(manifest.ui_dev_command, "plain files must stay server-free")

    def test_unknown_manager_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                create("demo", Path(tmp), Stack("react", "js"), source=None, package_manager="yarn")

    def _project(self, root: Path, manager: str) -> None:
        (root / "web").mkdir(parents=True)
        (root / "zagred.toml").write_text(
            '[app]\nname = "demo"\nentry = "demo.app:app"\n'
            f'[ui]\npackage_manager = "{manager}"\n',
            encoding="utf-8",
        )

    def test_install_uses_the_configured_manager(self):
        from zagred import cli

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp), "pnpm")
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(cli.subprocess, "run", fake_run), contextlib.redirect_stdout(
                    io.StringIO()
                ):
                    self.assertEqual(cli.main(["install", "vue-router"]), 0)
                    self.assertEqual(captured["argv"], ["pnpm", "add", "vue-router"])

                    self.assertEqual(cli.main(["install"]), 0)
                    self.assertEqual(captured["argv"], ["pnpm", "install"])
            finally:
                os.chdir(previous)

    def test_install_reports_an_unknown_manager(self):
        from zagred import cli

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp), "yarn")
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                    code = cli.main(["install"])
            finally:
                os.chdir(previous)

        self.assertEqual(code, 1)
        self.assertIn("unknown [ui] package_manager", err.getvalue())


class RuntimeTest(unittest.TestCase):
    """B17: dynamic import left the app package out of the Nuitka build."""

    def test_boot_runs_the_app_with_the_bundled_ui(self):
        from zagred.runtime import boot

        class FakeApp:
            def __init__(self):
                self.calls = []

            def run(self, ui, debug=False):
                self.calls.append((ui, debug))

        app = FakeApp()
        boot(app, ui="ui", debug=True)
        self.assertEqual(app.calls, [("ui", True)])


class DevServerTest(unittest.TestCase):
    """B15: closing the window left npm/sh/vite alive, holding the TTY."""

    @unittest.skipIf(os.name == "nt", "process groups are POSIX only")
    def test_stop_kills_the_whole_process_group(self):
        from zagred.cli import _spawn, _stop

        process = _spawn("sleep 30 & sleep 30", Path.cwd())
        time.sleep(0.3)
        _stop(process)

        # The group is gone as soon as its last member is signalled, but the
        # kernel can still report it for a moment, so poll instead of asserting
        # once — otherwise this flakes on a loaded machine.
        deadline = time.time() + 2
        while time.time() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        self.fail("process group survived _stop()")


class BuildArgvTest(unittest.TestCase):
    """`--jobs` must reach Nuitka, so a build does not eat every core."""

    def _run(self, jobs=None, low_memory=False, manifest_jobs=None, target="onefile", manifest_target="auto"):
        from zagred import build as build_mod
        from zagred.manifest import Manifest

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web" / "dist").mkdir(parents=True)
            (root / "web" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            manifest = Manifest(
                name="demo",
                version="0.1.0",
                entry="demo.app:app",
                ui_dist="web/dist",
                jobs=manifest_jobs,
                low_memory=low_memory,
                target=manifest_target,
            )
            with mock.patch.object(build_mod.subprocess, "run", fake_run), mock.patch.object(
                build_mod.importlib.util, "find_spec", lambda name: object()
            ), mock.patch.object(
                build_mod, "renderer", lambda: (True, "gtk", "")
            ), contextlib.redirect_stdout(io.StringIO()):
                code = build_mod.build(manifest, root, target=target, jobs=jobs)

        self.assertEqual(code, 0)
        return captured["argv"]

    def test_each_target_gets_its_own_output_dir(self):
        onefile = self._run(target="onefile")
        appimage = self._run(target="appimage")
        output_dirs = {arg.split("=", 1)[1] for arg in onefile + appimage if arg.startswith("--output-dir")}

        self.assertEqual(len(output_dirs), 2, "targets must not share an output directory")
        self.assertTrue(any(path.endswith("dist/onefile") for path in output_dirs))
        self.assertTrue(any(path.endswith("dist/appimage") for path in output_dirs))

    def test_jobs_flag_from_cli(self):
        self.assertIn("--jobs=2", self._run(jobs=2))

    def test_manifest_target_used_when_cli_is_silent(self):
        argv = self._run(target=None, manifest_target="appimage")

        self.assertTrue(any(path.endswith("dist/appimage") for path in argv))

    def test_cli_target_wins_over_manifest(self):
        argv = self._run(target="standalone", manifest_target="appimage")

        self.assertFalse(any(path.endswith("dist/appimage") for path in argv))
        self.assertTrue(any(path.endswith("dist/standalone") for path in argv))

    def test_jobs_flag_from_manifest(self):
        self.assertIn("--jobs=-1", self._run(manifest_jobs=-1))

    def test_cli_jobs_wins_over_manifest(self):
        argv = self._run(jobs=3, manifest_jobs=8)
        self.assertIn("--jobs=3", argv)
        self.assertNotIn("--jobs=8", argv)

    def test_no_flag_when_unset(self):
        self.assertFalse([a for a in self._run() if a.startswith("--jobs")])

    def test_low_memory_flag(self):
        self.assertIn("--low-memory", self._run(low_memory=True))

    def test_build_refuses_a_backend_that_cannot_open_a_window(self):
        from zagred import build as build_mod
        from zagred.manifest import Manifest

        err = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web" / "dist").mkdir(parents=True)
            manifest = Manifest(name="demo", entry="demo.app:app", ui_dist="web/dist")
            with mock.patch.object(
                build_mod.importlib.util, "find_spec", lambda name: object()
            ), mock.patch.object(
                build_mod, "renderer", lambda: (False, "gtk", "sudo apt install python3-gi")
            ), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = build_mod.build(manifest, root, target="onefile")
            made_artifact = (root / "dist").exists()

        self.assertEqual(code, 1)
        self.assertIn("could not open a window", err.getvalue())
        self.assertIn("python3-gi", err.getvalue())
        self.assertFalse(made_artifact, "a broken backend must not produce a binary")

    def _entry(self, debug):
        from zagred import build as build_mod
        from zagred.manifest import Manifest

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web" / "dist").mkdir(parents=True)
            (root / "web" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            manifest = Manifest(name="demo", entry="demo.app:app", ui_dist="web/dist", version="0.1.0")
            err = io.StringIO()
            with mock.patch.object(build_mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0)), \
                 mock.patch.object(build_mod.importlib.util, "find_spec", lambda name: object()), \
                 mock.patch.object(build_mod, "renderer", lambda: (True, "gtk", "")), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                build_mod.build(manifest, root, target="onefile", debug=debug)
            entry = (root / ".zagred" / "build" / "demo.py").read_text(encoding="utf-8")
        return entry, err.getvalue()

    def test_release_build_bakes_debug_false(self):
        entry, warning = self._entry(debug=False)
        self.assertIn("debug=False", entry)
        self.assertEqual(warning, "")

    def test_debug_build_bakes_debug_true_and_warns(self):
        entry, warning = self._entry(debug=True)
        self.assertIn("debug=True", entry)
        self.assertIn("inspector", warning.lower())


class TargetTest(unittest.TestCase):
    def test_explicit(self):
        self.assertEqual(pick_target("appimage"), "appimage")

    def test_unknown(self):
        with self.assertRaises(ValueError):
            pick_target("zip")


class TemplateVersionTest(unittest.TestCase):
    """Tooling versions live in two constants, so every template must use them."""

    def test_every_vite_template_uses_the_shared_versions(self):
        from zagred.templates import TYPESCRIPT, VITE, VITE_PACKAGES

        for framework, build in VITE_PACKAGES.items():
            for lang in ("js", "ts"):
                packages = json.loads(build("demo", lang))
                self.assertEqual(packages["devDependencies"]["typescript"], TYPESCRIPT, framework)
                self.assertEqual(packages["devDependencies"]["vite"], VITE, framework)


class HotkeyTest(unittest.TestCase):
    """Matching is a string comparison, so both sides must spell it the same."""

    def test_case_spacing_and_modifier_order_do_not_matter(self):
        for combo in ("Ctrl+Shift+P", "shift+ctrl+p", " ctrl + SHIFT + p ", "Ctrl+Shift+Ctrl+p"):
            with self.subTest(combo=combo):
                self.assertEqual(normalize(combo), "ctrl+shift+p")

    def test_mod_follows_the_platform(self):
        self.assertEqual(normalize("mod+k", mac=False), "ctrl+k")
        self.assertEqual(normalize("mod+k", mac=True), "meta+k")
        self.assertEqual(normalize("cmd+k", mac=False), "meta+k")

    def test_key_aliases_land_on_the_event_key_spelling(self):
        self.assertEqual(normalize("Esc"), "escape")
        self.assertEqual(normalize("Alt+Up"), "alt+arrowup")
        self.assertEqual(normalize("Return"), "enter")
        self.assertEqual(normalize("ctrl+plus"), "ctrl++")
        self.assertEqual(normalize("Space"), "space")

    def test_a_shortcut_needs_exactly_one_key(self):
        for bad in ("", "ctrl", "ctrl+ctrl", "ctrl+a+b"):
            with self.subTest(combo=bad), self.assertRaises(ValueError):
                normalize(bad)

    def test_registration_normalizes_and_supports_the_decorator_form(self):
        app = App()
        calls = []

        @app.hotkey("Ctrl+K")
        def open_palette():
            calls.append("ran")

        self.assertIn("ctrl+k", app._hotkeys)
        app._hotkeys["ctrl+k"]()
        self.assertEqual(calls, ["ran"])

    def test_a_bad_combo_fails_at_startup_not_at_keypress(self):
        with self.assertRaises(ValueError):
            App().hotkey("ctrl", lambda: None)

    def test_bridge_runs_the_bound_function(self):
        calls = []
        bridge = Bridge({}, {"ctrl+k": lambda: calls.append("ran")})

        self.assertEqual(bridge.call(HOTKEY, {"combo": "ctrl+k"}), {"ok": True, "data": True})
        self.assertEqual(calls, ["ran"])
        # A combo the shim knows about but Python does not is not an error.
        self.assertEqual(bridge.call(HOTKEY, {"combo": "ctrl+j"}), {"ok": True, "data": False})

    def test_a_failing_shortcut_reports_instead_of_crashing(self):
        def boom():
            raise RuntimeError("nope")

        result = Bridge({}, {"ctrl+k": boom}).call(HOTKEY, {"combo": "ctrl+k"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], {"code": "RuntimeError", "message": "nope"})

    def test_an_exposed_function_cannot_hijack_the_hotkey_command(self):
        bridge = Bridge({HOTKEY: lambda: "hijacked"}, {})

        self.assertEqual(bridge.call(HOTKEY, {"combo": "x"}), {"ok": True, "data": False})

    def test_the_shim_carries_the_matching_logic(self):
        for piece in ("keydown", HOTKEY, '"hotkey"', "preventDefault", "isComposing"):
            self.assertIn(piece, SHIM)

    def test_the_ui_can_bind_its_own_shortcuts(self):
        self.assertIn("hotkey(combo, fn)", SHIM)

    def test_the_grammar_tables_are_complete(self):
        # One source of truth: the UI normalises with the same data.
        table = key_table()

        self.assertEqual(table["aliases"]["esc"], "escape")
        self.assertEqual(table["aliases"]["up"], "arrowup")
        self.assertEqual(table["order"], ["ctrl", "meta", "alt", "shift"])
        self.assertIn(table["mod"], ("ctrl", "meta"))
        self.assertEqual(json.loads(json.dumps(table)), table, "must survive the trip to JS")


class WebviewSurfaceTest(unittest.TestCase):
    """The parts of pywebview's window API Zagred had not reached yet."""

    def _app(self):
        """An App with a fake window already attached, so nothing blocks."""
        app = App()
        app._window = _FakeWindow()
        return app, app._window

    def test_control_methods_delegate_to_the_window(self):
        app, window = self._app()

        app.load_css("body { color: red }")
        app.run_js("1+1")

        self.assertEqual(window.calls, [("load_css", "body { color: red }"), ("run_js", "1+1")])
        self.assertEqual(app.get_current_url(), "http://127.0.0.1:5173/")

    def test_evaluate_js_returns_the_value(self):
        app, window = self._app()

        self.assertEqual(app.evaluate_js("document.title"), "answered")
        self.assertEqual(window.exports, [threading.current_thread().name])

    def test_only_apis_that_work_on_linux_are_offered(self):
        """Every removed call was measured broken or pointless on GTK."""
        removed = (
            "load_html",  # kills pywebview's bridge on the next navigation
            "create_file_dialog",  # Gtk.Dialog.run() off the main thread
            "create_confirmation_dialog",  # same
            "get_cookies",  # no server session to keep
            "clear_cookies",
        )
        app, _ = self._app()

        for name in removed:
            self.assertFalse(hasattr(App, name), name)

    def test_live_properties_read_from_the_window(self):
        app, _ = self._app()

        self.assertEqual((app.width, app.height, app.x, app.y, app.state), (1024, 700, 10, 20, "NORMAL"))

    def test_properties_refuse_to_guess_before_the_window_exists(self):
        app = App()

        for name in ("width", "height", "x", "y", "state"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                getattr(app, name)

    def test_on_event_reaches_every_hook_with_the_event_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            seen = []
            app = App()
            @app.on_event("resized")
            def first(width, height):
                seen.append((width, height))

            app.on_event("resized", lambda width, height: seen.append("second"))

            window = _fake_webview_run(index, app=app)
            window.events.resized.handlers[0](800, 600)

            self.assertEqual(seen, [(800, 600), "second"])

    def test_on_event_can_veto_a_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            app = App()
            app.on_event("closing", lambda: False)
            app.on_event("closing", lambda: print("never reached"))

            window = _fake_webview_run(index, app=app)

            self.assertIs(window.events.closing.handlers[0](), False)

    def test_an_unknown_event_fails_before_the_window_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            app = App()
            app.on_event("resizedd", lambda: None)

            with self.assertRaises(ValueError) as caught:
                _fake_webview_run(index, app=app)

            self.assertIn("resizedd", str(caught.exception))
            self.assertIn("available:", str(caught.exception))

    def test_emit_is_dropped_until_the_page_has_loaded(self):
        # run_js waits up to 20s for the before_load event, so emitting from an
        # earlier hook (initialized, before_show) used to freeze the GUI thread
        # instead of returning.
        app, window = self._app()

        app.emit("loaded", {"x": 1})
        self.assertEqual(window.calls, [])

        app._ready = True
        app.emit("loaded", {"x": 1})
        deadline = time.time() + 2
        while not window.calls and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(window.calls[0][0], "run_js")

    def test_emit_is_dropped_again_after_a_navigation_starts(self):
        # A reload fires before_load once more; the gate has to close, or emit
        # from that hook waits 20s inside pywebview's before_load gate and
        # freezes the GUI thread.
        app = App()
        app._ready = True
        app._window = _FakeWindow()

        app._ready = False  # yang dilakukan handler before_load
        app.emit("loaded", {"x": 1})
        self.assertEqual(app._window.calls, [])

    def test_emit_survives_a_window_that_cannot_run_js_yet(self):
        # before_load/before_show get a live window object that cannot execute JS
        # yet; pywebview raises there, and that exception used to abort the load
        # event which called the hook.
        app, window = self._app()
        app._ready = True

        def explode(script):
            raise RuntimeError("Main window failed to start")

        window.run_js = explode
        app.emit("loaded", {"x": 1})

    def test_emit_still_rejects_a_payload_that_is_not_json(self):
        app, _ = self._app()
        app._ready = True

        with self.assertRaises(TypeError):
            app.emit("bad", object())

    def test_bridge_reports_when_a_dispatch_is_in_flight(self):
        seen = {}
        bridge = Bridge({})
        bridge._registry["probe_busy"] = lambda: seen.setdefault("busy", bridge.busy)

        self.assertFalse(bridge.busy)
        bridge.call("probe_busy", {})
        self.assertTrue(seen["busy"])
        self.assertFalse(bridge.busy)

    def test_load_url_is_deferred_while_a_bridge_call_is_running(self):
        # pywebview delivers the result to JS after the function returns; if the
        # document is already navigating, that delivery blocks for 20s and takes
        # every later call down with it.
        app, window = self._app()
        window.load_url = lambda url: window.calls.append(("load_url", url))
        app._bridge = SimpleNamespace(busy=True)

        app.load_url("http://example.test/")
        self.assertEqual(window.calls, [])

        time.sleep(0.5)
        self.assertEqual(window.calls[-1], ("load_url", "http://example.test/"))

    def test_load_url_navigates_immediately_outside_a_bridge_call(self):
        app, window = self._app()
        window.load_url = lambda url: window.calls.append(("load_url", url))
        app._bridge = SimpleNamespace(busy=False)

        app.load_url("http://example.test/")

        self.assertEqual(window.calls, [("load_url", "http://example.test/")])

    def test_settings_and_start_options_reach_pywebview(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            app = App(
                settings={"ALLOW_DOWNLOADS": True},
                start={"user_agent": "zagred/test", "private_mode": False},
                draggable=True,
            )

            window = _fake_webview_run(index, app=app)

            self.assertEqual(window.settings["ALLOW_DOWNLOADS"], True)
            self.assertEqual(window.start_kwargs["user_agent"], "zagred/test")
            self.assertEqual(window.start_kwargs["private_mode"], False)
            self.assertIs(window.kw["draggable"], True)

    def test_a_mistyped_option_is_rejected_with_the_valid_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")

            for kwargs, needle in (
                ({"settings": {"ALLOW_DOWNLOAD": True}}, "webview.settings"),
                ({"start": {"useragent": "x"}}, "webview.start"),
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError) as caught:
                    RunLoopTest._run(self, index, app=App(**kwargs))
                self.assertIn(needle, str(caught.exception))

    def test_start_cannot_override_what_zagred_owns(self):
        # func/args/debug/icon are passed by run() itself; a duplicate keyword
        # would be a TypeError deep inside pywebview instead of a clear message.
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")

            for key in ("func", "args", "debug", "icon"):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    RunLoopTest._run(self, index, app=App(start={key: None}))


if __name__ == "__main__":
    unittest.main()

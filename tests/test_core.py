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
from zagred.bridge import Bridge
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


class RunLoopTest(unittest.TestCase):
    """B12: injecting the shim on the before_load thread deadlocked the page."""

    class _Slot:
        def __init__(self):
            self.handlers = []

        def __iadd__(self, fn):
            self.handlers.append(fn)
            return self

    class _Window:
        def __init__(self):
            self.kw = {}
            self.events = SimpleNamespace(
                before_load=RunLoopTest._Slot(),
                loaded=RunLoopTest._Slot(),
                closing=RunLoopTest._Slot(),
                closed=RunLoopTest._Slot(),
            )
            self.exports = []

        def evaluate_js(self, script):
            self.exports.append(threading.current_thread().name)

        def run_js(self, script):
            pass

    def _run(self, ui_path: Path):
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

        with mock.patch.dict(sys.modules, {"webview": fake}):
            App().run(ui=str(ui_path))
        return created[0]

    def test_shim_is_not_injected_on_the_blocking_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<html></html>", encoding="utf-8")
            window = self._run(index)

            self.assertEqual(window.exports, [])
            window.events.before_load.handlers[0]()

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
                zoomable=True,
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
            self.assertTrue(kw["zoomable"])
            self.assertEqual(kw["background_color"], "#101010")


class TemplateTest(unittest.TestCase):
    def test_every_combination_scaffolds_and_parses(self):
        for framework in FRAMEWORKS:
            for lang in LANGUAGES:
                with self.subTest(framework=framework, lang=lang), tempfile.TemporaryDirectory() as tmp:
                    stack = Stack(framework=framework, language=lang)
                    paths = create("demo", Path(tmp), stack=stack, source=None)

                    for path in paths:
                        text = path.read_text(encoding="utf-8")
                        for token in ("__NAME__", "__MODULE__", "__SOURCES__"):
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

    def test_ts_templates_ship_bridge_types(self):
        for framework in FRAMEWORKS:
            if framework == "vanilla":
                continue
            with self.subTest(framework=framework), tempfile.TemporaryDirectory() as tmp:
                create("demo", Path(tmp), stack=Stack(framework=framework, language="ts"), source=None)
                self.assertTrue((Path(tmp) / "web" / "src" / "zagred.d.ts").is_file())
                self.assertTrue((Path(tmp) / "web" / "tsconfig.json").is_file())

    def test_unknown_stack_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                create("demo", Path(tmp), stack=Stack(framework="angular", language="js"), source=None)


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

        with self.assertRaises(ProcessLookupError):
            os.killpg(process.pid, 0)


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


if __name__ == "__main__":
    unittest.main()

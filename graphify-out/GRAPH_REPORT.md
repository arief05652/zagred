# Graph Report - zagred  (2026-11-06)

## Corpus Check
- 13 files · ~20,537 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 371 nodes · 580 edges · 33 communities (6 shown, 27 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 27 edges (avg confidence: 0.87)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Stdlib Import Surface
- Test Harness and Root
- Project Scaffolding
- Lifecycle Hooks and Events
- Hotkey Binding
- Manifest and Package Manager
- Build Argument Tests
- Shim Injection and Run Loop
- Test Fakes
- Run Loop Tests
- Template Rendering
- Webview Surface Tests
- Fake Webview Harness
- Bridge Dispatcher
- Asset Resolution Tests
- Bridge Dispatch Tests
- Template Tests
- Runtime Tests
- Compiled Entry Runtime
- Package Root

## God Nodes (most connected - your core abstractions)
1. `App` - 58 edges
2. `BuildArgvTest` - 15 edges
3. `HotkeyTest` - 15 edges
4. `WebviewSurfaceTest` - 15 edges
5. `_FakeWindow` - 13 edges
6. `build()` - 12 edges
7. `create()` - 11 edges
8. `_fake_webview_run()` - 11 edges
9. `RunLoopTest` - 11 edges
10. `load_manifest()` - 10 edges

## Surprising Connections (you probably didn't know these)
- `_fake_webview_run()` --uses--> `App`  [INFERRED]
  tests/test_core.py → src/zagred/app.py
- `HotkeyTest` --uses--> `App`  [INFERRED]
  tests/test_core.py → src/zagred/app.py
- `RunLoopTest` --uses--> `App`  [INFERRED]
  tests/test_core.py → src/zagred/app.py
- `WebviewSurfaceTest` --uses--> `App`  [INFERRED]
  tests/test_core.py → src/zagred/app.py
- `_pick_package_manager()` --uses--> `Stack`  [INFERRED]
  src/zagred/cli.py → src/zagred/scaffold.py

## Import Cycles
- None detected.

## Communities (33 total, 27 thin omitted)

### Community 0 - "Stdlib Import Surface"
Cohesion: 0.06
Nodes (15): build(), doctor(), _module_version(), pick_target(), renderer(), _dev(), _install(), main() (+7 more)

### Community 1 - "Test Harness and Root"
Cohesion: 0.06
Nodes (8): resolve_ui(), _search_dirs(), key_table(), normalize(), DevServerTest, ScaffoldTest, TargetTest, TemplateVersionTest

### Community 2 - "Project Scaffolding"
Cohesion: 0.11
Nodes (11): _ask(), _choose(), _interactive(), _new(), _pick_package_manager(), create(), detect_package_managers(), local_source() (+3 more)

### Community 6 - "Manifest and Package Manager"
Cohesion: 0.17
Nodes (3): ManifestTest, PackageManagerTest, fake_run()

### Community 8 - "Shim Injection and Run Loop"
Cohesion: 0.13
Nodes (4): inject(), _check_options(), _hook_runner(), _run_all()

### Community 11 - "Template Rendering"
Cohesion: 0.23
Nodes (5): build_files(), _index_html(), _json(), _package(), _tsconfig()

## Knowledge Gaps
- **1 isolated node(s):** `zagred`
  These have ≤1 connection - possible missing edges. (Counts symbols only; 182 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `App` connect `Lifecycle Hooks and Events` to `Stdlib Import Surface`, `Test Harness and Root`, `Window Control API`, `Hotkey Binding`, `Shim Injection and Run Loop`, `Run Loop Tests`, `Webview Surface Tests`, `Fake Webview Harness`, `Cookie Clearing`, `Cookie Reading`, `Current URL`, `Live Height`, `Navigation`, `Minimize Window`, `Move Window`, `Resize Window`, `Restore Window`, `Run JavaScript`, `Show Window`, `Live Position`?**
  _High betweenness centrality (0.387) - this node is a cross-community bridge._
- **Are the 4 inferred relationships involving `App` (e.g. with `_fake_webview_run()` and `HotkeyTest`) actually correct?**
  _`App` has 4 INFERRED edges - model-reasoned connections that need verification._
- **What connects `zagred` to the rest of the system?**
  _1 weakly-connected nodes found - possible missing edges._
- **Should `Stdlib Import Surface` be split into smaller, more focused modules?**
  _Cohesion score 0.06203007518796992 - nodes in this community are weakly interconnected._
- **Why does `HotkeyTest` connect `Hotkey Binding` to `Test Harness and Root`, `Lifecycle Hooks and Events`?**
  _High betweenness centrality (0.097) - this node is a cross-community bridge._
- **Should `Test Harness and Root` be split into smaller, more focused modules?**
  _Cohesion score 0.057004830917874394 - nodes in this community are weakly interconnected._
- **Why does `BuildArgvTest` connect `Build Argument Tests` to `Test Harness and Root`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
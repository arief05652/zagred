# PLAN — Zagred

Desktop app dengan backend Python dan frontend web. Renderer `pywebview`,
packaging `uv`, kompilasi `Nuitka`.

Status: **0.1.0** — jalan end-to-end di Linux.

## Identity

Tauri menaruh semuanya di JSON dan meminta kamu belajar Rust. Zagred ambil posisi
berlawanan:

> **Manifest minimal, runtime di Python. App-mu adalah package Python biasa; UI cuma folder di sebelahnya.**

1. **Kode adalah konfigurasi.** `zagred.toml` hanya untuk build & metadata.
   Jendela, lifecycle, dan fungsi yang dipanggil UI ditulis di Python.
2. **Tidak ada lapisan "backend".** Tidak ada analog `src-tauri/`. Package
   Python-mu *adalah* backend.
3. **UI adalah tetangga, bukan bawahan.** `web/` sibling, supaya `node_modules`
   tidak masuk ke distribusi.
4. **uv adalah package manager-nya.** Project hasil scaffold adalah uv project
   biasa: `uv sync` → `uv run zagred dev`. zagred hidup di venv milik project,
   bukan di tool global, supaya dependensi aplikasi ikut terlihat.

| Tauri | Zagred |
|---|---|
| `tauri.conf.json` | `zagred.toml` |
| `#[tauri::command]` | `@app.expose` |
| `invoke("x", {})` | `zagred.call("x", {})` |
| `src-tauri/` + `Cargo.toml` | *(tidak ada — package Python-mu langsung)* |
| `cargo` / `npm` | **`uv`** |
| `tauri build` (Rust bundler) | `zagred build` (**Nuitka**) |
| `.tauri/` | `.zagred/` |

## Struktur

```
myapp/
├── zagred.toml          # build metadata
├── pyproject.toml       # uv project
├── .python-version      # 3.12
├── web/                 # UI: file statis, atau project Vite
│   ├── package.json     # hanya kalau pakai bundler
│   └── src/
└── myapp/
    ├── app.py           # App + @expose + lifecycle
    └── resources/
```

`pyproject.toml` hasil scaffold:

```toml
[project]
name = "myapp"
requires-python = ">=3.12"
dependencies = ["zagred"]

[dependency-groups]
build = ["nuitka>=4.2", "patchelf>=0.18; sys_platform == 'linux'"]

[tool.uv.sources]              # otomatis selama zagred belum di PyPI
zagred = { path = "/path/to/zagred", editable = true }
```

## Sudah dicapai

### Runtime & bridge
- `@app.expose` + `zagred.call()` dengan envelope error (`code` + `message`)
- Command async (`asyncio.run` di thread bridge)
- `app.emit()` → `zagred.on()` lewat `run_js` + literal JSON (aman CSP tanpa `unsafe-eval`)
- Shim disuntik dari worker thread — `evaluate_js` di `before_load` deadlock
- Validasi serialisasi JSON sebelum hasil meninggalkan Python
- 38 unit test (`uv run python -m unittest discover -s tests`)

### App & jendela
- 20+ opsi jendela: `size`, `min_size`, `position`, `resizable`, `fullscreen`,
  `frameless`, `easy_drag`, `on_top`, `confirm_close`, `transparent`,
  `text_select`, `zoomable`, `vibrancy`, `background_color`, `icon`, `menu`
- Kontrol runtime: `minimize/maximize/restore/toggle_fullscreen/resize/move/`
  `set_title/show/hide/destroy/load_url/evaluate_js/create_file_dialog`
- Lifecycle: `on_start`, `on_loaded`, `on_closing` (return `False` = batal), `on_closed`

### CLI & template
- `zagred new` wizard: framework (vanilla/react/vue/solid) + bahasa (js/ts)
- 8 kombinasi template, semuanya lolos `npm install` + `npm run build` + `tsc --noEmit`
- `zagred dev` menjalankan dev server (cwd `web/`), menunggu port, membuka jendela,
  dan membunuh seluruh process group saat jendela ditutup
- `zagred doctor` melaporkan renderer nyata (`gtk`), bukan sekadar `import webview`
- Typed bridge untuk TypeScript (`web/src/zagred.d.ts`)

### Build
- 6 target Nuitka: `onefile`, `standalone`, `exe`, `appimage`, `app`, `dmg` + `auto`
- Tiap target menulis ke `dist/<target>/` — tidak saling menimpa
- Entry script `<name>.py` diimpor **statis** supaya Nuitka ikut membundel package app
- `--jobs` / `low_memory` untuk membatasi pemakaian CPU
- Artefak dinamai sesuai `[app] name`
- `--debug` hanya untuk development: memberi warning karena membuka inspector

### Diverifikasi di mesin ini (Linux, 8 core)
- `zagred build --target onefile` → binary 12 MB
- `zagred build --target appimage` → `test-zagred.AppImage` 22 MB, **berhasil dibuka**
- Aset UI + bundle GSAP ikut di dalam paket
- `uv sync` di project baru → venv Python 3.12, zagred editable, bridge menjawab
- `zagred dev` + Vite: dev server 5173, status `loaded` ~0.86 s
- `--jobs=2`: load ~3, build tetap selesai

## Belum

- Multi-window (satu `Bridge` per window)
- Plugin registry via `entry_points`, `zagred add ui <kit>`
- Capability / ACL, CSP default, guard path traversal
- Tray, auto-update
- Build AppImage diuji di VM bersih (typelib GTK)
- Terbit ke PyPI, CI matrix 3 OS

## Build pipeline

| `--target` | Flag Nuitka | Output |
|---|---|---|
| `onefile` | `--mode=onefile` | satu binary |
| `standalone` | `--mode=standalone` | folder `.dist/` |
| `exe` | `--mode=standalone --windows-create-installer` | `-setup.exe` |
| `appimage` | `--mode=app-dist --linux-create-installer` | `.AppImage` |
| `app` | `--mode=app` | `.app` |
| `dmg` | `--mode=app --macos-create-installer` | `.dmg` |

Butuh **Nuitka >= 4.2**, dipasang lewat dependency group `build`, bukan lewat
paket zagred. Cross-compile tidak mungkin — pakai CI.

## Prasyarat per OS

| OS | Butuh | Dari mana |
|---|---|---|
| Linux | `libwebkit2gtk-4.1`, `python3-gi` | sistem (apt/dnf) |
| Linux | venv `--system-site-packages` | `uv venv` |
| Linux | `patchelf` | `uv sync --group build` |
| Linux | `appimagetool` | diunduh otomatis oleh Nuitka |
| Windows | WebView2 runtime | sistem |
| macOS | — | WKWebView bawaan |

## Keputusan yang sudah dikunci

- **Backend Linux: GTK.** Qt/QtWebEngine menambah 80–150 MB per build.
- **uv sebagai package manager.** Satu tool untuk env, lock, dan instalasi lokal.
- **Python dipin ke 3.12** lewat `.python-version` supaya build reproducible.
- **Satu pintu bridge.** `js_api` hanya punya satu method (`call`).
- **Satu direktori per target build**, supaya artefak lama tidak tertimpa.
- **Config TOML**, bukan JSON.
- **Lisensi MIT.** Kode Zagred ikut terkompilasi ke binary user, jadi copyleft (GPL/AGPL) akan menular ke app mereka. MIT menjaga app user tetap bisa closed-source.
- **`--debug` bukan untuk rilis**, dan build memberi warning.

## Risiko

| Risiko | Level | Status |
|---|---|---|
| Layer putih / deadlock saat load | 🔴 | **Selesai** — B12 |
| Package app tidak ikut terkompilasi | 🔴 | **Selesai** — B19 |
| Artefak target saling menimpa | 🔴 | **Selesai** — B21 |
| Build debug ikut terkirim | 🔴 | **Selesai** — B22 |
| Typelib GTK tidak ikut AppImage | 🔴 | Belum diuji di VM bersih |
| zagred belum di PyPI | 🟠 | Mitigasi `[tool.uv.sources]` |
| Cross-compile mustahil | 🟠 | CI matrix |
| Onefile: startup lambat + false positive AV | 🟠 | `--target standalone` jadi alternatif |
| `js_api` single object per window | 🟡 | Ditangani desain satu-pintu |
| Belum ada lisensi | 🟠 | **Selesai** — MIT (`LICENSE`) + `THIRD-PARTY-NOTICES.md` |

## Berikutnya

1. Uji AppImage di VM Linux bersih.
2. Multi-window: satu `Bridge` per window.
3. `capabilities.toml` + guard sebelum dispatch (M5).
4. Plugin registry via `entry_points`.
5. Terbitkan ke PyPI + CI matrix GitHub Actions.
6. Sertakan `THIRD-PARTY-NOTICES.md` + teks lisensi ke dalam paket build secara otomatis.

# Hotkeys

There are two places to bind a shortcut. The difference is where the work
happens, not how the key is matched.

## In Python

When the shortcut should do something native — a dialog, a window change, a
background job:

```python
@app.hotkey("mod+k")
def palette() -> None:
    app.emit("open", "palette")
```

A Python binding is fixed when the shim is injected, at startup.

## In the page

When the shortcut moves the UI itself — focus a field, step through a list, jump
to a section:

```js
const off = zagred.hotkey("j", () => setIndex((i) => i + 1));
zagred.hotkey("/", () => document.querySelector("input")?.focus());
zagred.hotkey("enter", ({ target }) => target?.closest("li")?.click());
off(); // unsubscribe
```

The handler receives `{ combo, event, target }`, so it can inspect the real
`KeyboardEvent` and whatever had focus. A page-side binding never touches the
bridge: no round-trip, no Python, and it works immediately.

## Grammar

| Written | Means |
|---|---|
| `ctrl` / `control` | Ctrl on every platform |
| `meta` / `cmd` / `super` / `win` | the platform key |
| `alt` / `option` | Alt |
| `shift` | Shift |
| `mod` | Ctrl on Linux and Windows, Cmd on macOS |
| `esc`, `return`, `up`, `del`, `space`, `plus` | the obvious keys |

Case, spacing and modifier order do not matter: `Ctrl+Shift+P`, `shift+ctrl+p`
and `CTRL + SHIFT + p` are the same shortcut. Everything else is the `event.key`
name, lowercased — `a`, `1`, `f5`, `tab`, `arrowdown`.

Both sides use the same grammar tables (`key_table()` is sent to the page), so
`mod+k` normalises identically in Python and in the page.

## Matching rules

The shim matches the keystroke **before** the page sees it, so both kinds cancel
the browser's own action — ++ctrl+p++ opens your palette instead of a print
dialog.

- A shortcut **without** a modifier is ignored while an input, textarea, select
  or contenteditable element has focus, so typing `j` in a search box does not
  fire a `j` shortcut.
- `Escape` is the exception — it never inserts anything, and "cancel" is what a
  user expects.
- Modifier shortcuts are never affected, because ++ctrl+k++ is not something you
  type.
- A keypress during IME composition is ignored.
- A modifier pressed on its own is not a shortcut.

## The `hotkey` event

Every matched shortcut, from either side, also fires a `hotkey` event:

```js
zagred.on("hotkey", ({ combo }) => setStatus(`last key: ${combo}`));
```

Useful for a shortcut reference overlay or telemetry of your own.

## Invalid shortcuts

An invalid shortcut fails at registration: `ValueError` in Python, a thrown
`Error` in the page. Nothing is left silently unbound.

```python
@app.hotkey("ctrl+")   # ValueError: 'ctrl+' has modifiers but no key
@app.hotkey("a+b")     # ValueError: names more than one key
```

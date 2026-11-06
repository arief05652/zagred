# Frontend

Any folder with an `index.html` works: plain HTML/JS, or React, Vue, Solid with
Vite. Zagred injects a small shim (`window.zagred`) on `before_load`, so it is
available to every script in the page.

```js
const msg = await zagred.call("greet", { name: "world" });
```

Arguments are a plain object — they arrive in Python as **keyword** arguments.
The return value is whatever your function returned, already JSON-serialised.

## `zagred.call(name, args?)`

```js
const rows = await zagred.call("scan", { folder: "/tmp" });
```

| Field | Meaning |
|---|---|
| `name` | the Python function's `__name__` |
| `args` | keyword arguments, default `{}` |
| returns | resolved value of the call, or a thrown `Error` |

`async def` functions work transparently; the promise resolves when the
coroutine finishes.

## Errors

```js
zagred.call("greet").catch((err) => {
  console.error(err.code, err.message); // e.g. "bad_arguments"
});
```

| `err.code` | When |
|---|---|
| `unknown_command` | nothing is exposed under that name |
| `bad_arguments` | wrong or missing keyword arguments (`TypeError`) |
| anything else | the exception class name your function raised |

Nothing is swallowed: an uncaught exception in Python becomes a rejected
promise, not a blank window.

## Events

Python pushes, JS subscribes:

```python
@app.expose
def start_job() -> None:
    for done, total in work():
        app.emit("job:progress", {"done": done, "total": total})
```

```js
const off = zagred.on("job:progress", ({ done, total }) => {
  bar.style.width = `${(done / total) * 100}%`;
});

off(); // unsubscribe
```

`zagred.on` returns an unsubscribe function. `zagred.off(name, fn)` does the same
by reference.

## Ready

The page may run before pywebview installs its own bridge object. Every
`zagred.call` already awaits that internally; if you need the timing yourself:

```js
await zagred.ready;
```

## TypeScript

TypeScript projects ship `web/src/zagred.d.ts`:

```ts
const msg = await zagred.call<string>("greet", { name });
```

Add a generic to `call` and both sides stay in sync with your Python signature.

## Shortcuts in the page

Page-side bindings never touch the bridge — no round-trip, no Python, and they
can be registered at any time:

```js
const off = zagred.hotkey("j", () => setIndex((i) => i + 1));
zagred.hotkey("/", () => document.querySelector("input")?.focus());
```

Full grammar and precedence rules: [Hotkeys](hotkeys.md).

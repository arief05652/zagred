# Third-party notices

Zagred is MIT licensed (see `LICENSE`). It depends on the components below.
When you build an app with `zagred build`, your compiled binary contains Zagred
and its Python dependencies, so your app distribution should ship this file —
plus the full licence texts — alongside your own licence.

## Bundled into every built app

| Component | Licence | Copyright |
|---|---|---|
| zagred | MIT | © 2026 arief minardi |
| [pywebview](https://pywebview.flowrl.com) | BSD-3-Clause | © 2014-2017 Roman Sirokov |
| [bottle](https://bottlepy.org) | MIT | © 2009-2024 Marcel Hellkamp |
| [proxy_tools](https://github.com/jtushman/proxy_tools) | MIT | Jonathan Tushman |
| [typing_extensions](https://pypi.org/project/typing-extensions/) | PSF-2.0 | © Python Software Foundation |
| CPython runtime | PSF-2.0 | © Python Software Foundation |

### pywebview — BSD-3-Clause

```
Copyright (c) 2014-2017, Roman Sirokov
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its contributors
  may be used to endorse or promote products derived from this software without
  specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### PSF-2.0 (Python, typing_extensions)

The Python licence text ships with every CPython installation as `LICENSE` in
its base directory, and is available at
<https://docs.python.org/3/license.html>. Include it in your app distribution.

## Build-time only — not redistributed

These run on your machine during `zagred build` and are never copied into the
output. They impose no obligations on your app.

| Component | Licence | Notes |
|---|---|---|
| Nuitka | AGPL-3.0 | Compiler. Its Runtime Library Exception explicitly permits distributing closed-source output. Zagred invokes it as a separate process and never bundles it. |
| patchelf | GPL-3.0-or-later | Installed by `uv sync --group build`, used by Nuitka. |
| uv | MIT OR Apache-2.0 | Dependency and environment manager. |
| npm / Vite / TypeScript / framework plugins | MIT, Apache-2.0, MPL-2.0 | Only used to build the frontend, never bundled. |

## Host dependencies — installed by the user, never bundled

| Component | Licence |
|---|---|
| GTK 3 | LGPL-2.1+ |
| WebKitGTK | BSD-2-Clause, LGPL-2+ |
| PyGObject (`gi`) | LGPL-2.1+ |
| WebView2 (Windows) | Microsoft proprietary |

Zagred does not bundle these. They are provided by the operating system, so the
LGPL relinking obligations stay with the platform, not with your app.

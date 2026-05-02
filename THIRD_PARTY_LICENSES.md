# Third-Party Licenses

## texconv.exe

**Source:** [DirectXTex](https://github.com/microsoft/DirectXTex)  
**License:** MIT License

```
MIT License

Copyright (c) Microsoft Corporation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Version:** Run `texconv.exe /?` to confirm the exact version string and match
against a released tag from [DirectXTex releases](https://github.com/microsoft/DirectXTex/releases).
Update this file with the build date/version once confirmed.

---

## requests (Python)

**License:** Apache License 2.0  
**Bundled at:** `_vendor/requests/` (loaded via `dependency_manager.ensure_dependencies_installed()`)  
Not installed via pip at runtime — the plugin ships its own vendored copy.

---

## Pillow (Python)

**License:** HPND (Historical Permission Notice and Disclaimer)  
May be bundled under `_vendor/` — check `dependency_manager.py` for the full
list of vendored packages and verify this file covers all of them.

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

---

## Vendored Python packages (`_vendor/`)

Loaded by `dependency_manager.ensure_dependencies_installed()`; nothing is
installed with pip at runtime. Each package's full license text ships in its
`*.dist-info/` folder.

| Package | Version | License |
|---------|---------|---------|
| requests | 2.32.5 | Apache-2.0 |
| urllib3 | 2.5.0 | MIT |
| idna | 3.10 | BSD-3-Clause |
| charset-normalizer | 3.4.3 | MIT |
| certifi | 2025.8.3 | MPL-2.0 |
| Pillow | 11.3.0 | MIT-CMU (HPND) |

Pillow includes compiled modules for both CPython 3.11 (`*.cp311-win_amd64.pyd`,
Painter 10/11) and CPython 3.13 (`*.cp313-win_amd64.pyd`, Painter 12). Both
come from the official Pillow 11.3.0 wheels; the Python sources are identical.

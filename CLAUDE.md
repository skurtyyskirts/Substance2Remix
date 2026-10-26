# Substance2Remix — LLM Assistant Bootstrap

Substance Painter plugin bridging Adobe Substance 3D Painter with NVIDIA RTX Remix.
Installed as `Documents/Adobe/Adobe Substance 3D Painter/python/plugins/substance2remix`
(Painter lists plugins by folder name). Other plugins live in `plugins/archive/`, which
Painter ignores because it has no `__init__.py`.

## Module Map

| File | Purpose |
|------|-------|
| `__init__.py` | Painter entry points (`start_plugin`/`close_plugin`); menu, dock panel, submodule reload on "Reload plugin" |
| `core.py` | `RemixConnectorPlugin`: operations (pull, import, push, force push, link, show), worker plumbing, diagnostics |
| `remix_api.py` | `RemixAPIClient` REST client for the RTX Remix Toolkit + path helpers |
| `painter_controller.py` | Painter API wrapper: channels, resolution, fill layers (main thread only) |
| `texture_processor.py` | texconv DDS→PNG, Remix normal decode (Pillow), resize, Blender unwrap launcher |
| `ui_panel.py` | Dock panel + plugin icon |
| `async_utils.py` | `QRunnable` worker + signals |
| `settings_schema.py` / `settings_dialog.py` | Settings defaults, sanitizing/migration, dialog |
| `diagnostics_dialog.py` | Diagnostics text dialog |
| `dependency_manager.py` | Puts `_vendor/` (requests, Pillow) on `sys.path` |
| `blender_auto_unwrap.py` | Runs inside Blender (`--background`); Smart UV Project |
| `plugin_info.py` | Name/version constants |

## Threading rules

- Every `substance_painter.*` call runs on the GUI thread. Painter's API is not thread-safe.
- Network and file work runs in `Worker`s via `RemixConnectorPlugin._start_worker`; its
  `on_result`/`on_error` callbacks are delivered on the GUI thread through `_MainThreadInvoker`.
- Push = worker preflight → **GUI-thread export** → worker ingest/update/save.
- One user operation at a time (`_begin_operation` / `_finish_operation` / `_fail_operation`).
  Expected failures raise `RemixError` (shown without a traceback).

## RTX Remix REST facts (verified against Toolkit 1.6.1 source)

Routes live in `<Remix>/exts/lightspeed.trex.service.core/.../routes/`.
- `GET /stagecraft/assets/?selection=true` returns the *extended* selection: a selected
  instance brings its mesh, bound material and shader. There is **no**
  `/stagecraft/assets/{prim}/material` endpoint (never was); don't add probing for it.
- Prim paths go in URLs with their leading slash: `/stagecraft/assets//RootNode/...`.
- Instance → mesh: `inst_<HASH>_<N>` maps to `meshes/mesh_<HASH>` (index dropped).
- `PUT /stagecraft/textures/` must use `force: false`. `force: true` now requires exact
  `expected_current_textures` and otherwise returns a 422.
- Ingest (`POST /ingestcraft/mass-validator/queue/material`) merges dicts but **replaces
  lists**. Only override `context_plugin.data`; overriding `check_plugins` drops
  `ConvertToOctahedral`, and AperturePBR defaults to octahedral normals.
- Valid ingest types: DIFFUSE, ROUGHNESS, METALLIC, EMISSIVE, NORMAL_OGL/DX/OTH, HEIGHT, …
  There is no OPACITY or AO type. AperturePBR reads opacity from the albedo alpha.
- `GET /stagecraft/project/` returns 404 when the Toolkit runs without a project.

## Network / TLS Policy

All HTTP calls go through `RemixAPIClient.make_request()`. TLS verification is disabled
only for loopback hosts (parsed hostname `localhost`, `127.0.0.1`, `::1`), enabled
otherwise. Connection failures fail fast with a "Remix not running" message; timeouts
and 5xx retry. Do NOT add direct `requests` calls outside `make_request()`.

## Tools

- `texconv.exe` (bundled, DirectXTex MIT). Two-channel BC5 normals need `-f R8G8B8A8_UNORM`
  to be written as PNG. Timeout 180 s.
- Blender unwrap timeout 900 s. The script filters operator kwargs by RNA properties
  (Blender 5.x rejects unknown keywords). Output goes to `_temp/unwrapped/`, never into
  the Remix project.
- `_vendor/PIL` ships both cp311 (Painter 10/11) and cp313 (Painter 12) binaries.

## Running Tests

Use Painter's Python (PySide6 + matching Pillow ABI). `pytest` must be importable,
for example from a venv's `site-packages` on `PYTHONPATH`:

```bash
PY="/c/Program Files/Adobe/Adobe Substance 3D Painter/resources/pythonsdk/python.exe"
export QT_QPA_PLATFORM=offscreen
export QT_PLUGIN_PATH="C:\\Program Files\\Adobe\\Adobe Substance 3D Painter\\PlugIns"
"$PY" -m pytest tests/ -q
```

Outside Painter, `PySide6` needs `os.add_dll_directory(<Painter install dir>)` for its Qt DLLs.
Tests that need Qt skip when PySide6 is missing.

# Substance2Remix — LLM Assistant Bootstrap

Substance Painter plugin bridging Adobe Substance 3D Painter with NVIDIA RTX Remix.
Installed as `Documents/Adobe/Adobe Substance 3D Painter/python/plugins/substance2remix`
(Painter lists plugins by folder name). Other plugins live in `plugins/archive/`, which
Painter ignores because it has no `__init__.py`.

## Module Map

| File | Purpose |
|------|-------|
| `__init__.py` | Painter entry points (`start_plugin`/`close_plugin`); menu, dock panel, submodule reload on "Reload plugin" |
| `core.py` | `RemixConnectorPlugin`: operations (pull, import, push, force push, link, show, add channels), settings/preset API, worker plumbing, diagnostics |
| `pbr_maps.py` | **The one table of texture maps**: Remix input, ingest type, suffix, Painter channel names/format, export name, DDS encoding. Everything else derives from it |
| `remix_api.py` | `RemixAPIClient` REST client for the RTX Remix Toolkit + path helpers |
| `painter_controller.py` | Painter API wrapper: channels (incl. labelled User channels), resolution, fill layers (main thread only) |
| `texture_processor.py` | texconv DDS→PNG, Remix normal decode (Pillow), anisotropy remap, resize, Blender unwrap launcher |
| `ui_panel.py` | Dock panel (connection, link, normals, preset switcher, actions) + plugin icon |
| `async_utils.py` | `QRunnable` worker + signals |
| `settings_schema.py` | Settings defaults, sanitizing/migration, `PRESET_KEYS`, `user_config_dir()` |
| `settings_store.py` | `SettingsStore`: autosaved `settings.json` + `presets.json` in `%APPDATA%\Substance2Remix\`, legacy migration |
| `settings_dialog.py` | Autosaving settings dialog with preset bar and Texture Maps tab |
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
- Push and import read their settings once on the GUI thread (`_push_options`, `_import_options`)
  and pass them to the workers. Never call `read_link()`/`project_normal_format()` from a worker.
- Settings are replaced, never mutated in place (`SettingsStore.update` returns a new dict),
  so a worker holding `self.settings` keeps a consistent snapshot.

## Normal map convention

- Pull stores the convention the project is created with as link metadata `remix_normal_format`.
- `project_normal_format(link)` = that value, else the `normal_map_format` setting.
- Push exports `Normal_OpenGL`/`Normal_DirectX` in that convention **and** ingests it as
  `NORMAL_OGL`/`NORMAL_DX` (same value, passed explicitly to `ingest_texture`). The ingest sets
  the ingest material's `inputs:encoding` (1 = OGL, 2 = DX) and ConvertToOctahedral decodes with it.
  Verified live: the same normal authored GL and DX decodes identically; a mislabelled one flips Y.
- Import converts Remix octahedral normals to the project's convention.

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
  lists**. For the standard maps only override `context_plugin.data`; overriding
  `check_plugins` drops `ConvertToOctahedral`, and AperturePBR defaults to octahedral normals.
- Ingest types (`TextureTypes`): DIFFUSE, ROUGHNESS, METALLIC, EMISSIVE, NORMAL_OGL/DX/OTH,
  HEIGHT, ANISOTROPY, TRANSMITTANCE, MEASUREMENT_DISTANCE, SINGLE_SCATTERING (+ OTHER, SKYBOX).
  There is no OPACITY or AO type. AperturePBR reads opacity from the albedo alpha.
- **Anisotropy and subsurface maps** are dropped by the default schema: `MaterialShaders`
  rebuilds the ingest material from a fixed attribute list without them, and ConvertToDDS's
  defaults don't list their inputs. For these the payload sends `check_plugins = [ConvertToDDS
  with conversion_settings for that one input]` (encodings from `TEXTURE_INFO` in
  `lightspeed.trex.asset_pipeline.core`) **and** `data.mass_ui.shared_int_fields = []`
  (the schema's shared field targets ConvertToOctahedral; a missing target is a 422).
  Outputs: `<stem>.an|tr|md|ss.rtex.dds` with a `.meta` sidecar (`validation_passed`), so
  `PUT /stagecraft/textures/` with `force:false` accepts them. Verified live on 1.6.1.
- AperturePBR_Opacity has `anisotropy_texture` and the three `subsurface_*_texture` inputs;
  other shaders may not, so push assigns those in a second batch that may fail on its own.
- There is no REST route to set `inputs:encoding` on a project material. Captured materials
  default to octahedral; if a user changed it, pushed normals shade wrong.
- `GET /stagecraft/project/` returns 404 when the Toolkit runs without a project.
- `executor: 1` runs each ingest in a separate Kit process. The GUI/StageCraft apps point it
  at `lightspeed.app.trex.validation_cli.kit`; the 1.6.1 *headless* app doesn't, so its
  ingests fail ("Plugin MaterialShaders was not registered") unless launched with
  `--/exts/omni.flux.validator.mass.core/override_process_experience=${app}/lightspeed.app.trex.validation_cli.kit`.

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

## Painter channels

- Painter 12 names channels after OpenPBR and keeps legacy aliases; `pbr_maps.PbrMap.channels`
  lists names to try (e.g. `SpecularRoughnessAnisotropy`, then `Anisotropylevel`).
- Subsurface thickness has no channel type: it lives in a User channel labelled
  "Remix Thickness" (found by label, created in the first free `User0..31` slot).
- Export `documentMap` names: the six standard maps use fixed names (`baseColor`, `roughness`, …);
  the others use `channel.type().name.lower()` (as Painter's own export tests do), e.g. `user0`.

## Running Tests

Use Painter's Python (PySide6 + matching Pillow ABI). `pytest` must be importable without
mixing in another Python's site-packages, e.g. `python.exe -m pip install --target <dir> pytest`.
Python 3.8+ ignores `PATH` for DLLs, so PySide6 needs `os.add_dll_directory(<Painter install
dir>)`; a `sitecustomize.py` in that same `<dir>` doing it works:

```bash
PY="/c/Program Files/Adobe/Adobe Substance 3D Painter/resources/pythonsdk/python.exe"
export PYTHONPATH="<dir with pytest + sitecustomize.py>" PYTHONNOUSERSITE=1
export QT_QPA_PLATFORM=offscreen
export QT_PLUGIN_PATH="C:\\Program Files\\Adobe\\Adobe Substance 3D Painter\\PlugIns"
"$PY" -m pytest tests/ -q -p no:cacheprovider
```

Tests import plugin modules through the real package (`tests/_isolated.import_plugin_module`),
so relative imports work. Tests that need Qt skip when PySide6 is missing.

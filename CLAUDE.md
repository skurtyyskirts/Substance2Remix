# Substance2Remix — LLM Assistant Bootstrap

Substance Painter plugin bridging Adobe Substance 3D Painter with NVIDIA RTX Remix.
Installed as `Documents/Adobe/Adobe Substance 3D Painter/python/plugins/substance2remix`
(Painter lists plugins by folder name). Other plugins live in `plugins/archive/`, which
Painter ignores because it has no `__init__.py`.

## Module Map

| File | Purpose |
|------|-------|
| `__init__.py` | Painter entry points (`start_plugin`/`close_plugin`); menu, dock panel, submodule reload on "Reload plugin" |
| `core.py` | `RemixConnectorPlugin`: operations (pull, import, push, link, show, add channels), shelf registration, settings API, worker plumbing, diagnostics |
| `pbr_maps.py` | **The one table of texture maps**: Remix input, ingest type, suffix, Painter channel names/format, export name, DDS encoding. Everything else derives from it |
| `remix_api.py` | `RemixAPIClient` REST client for the RTX Remix Toolkit + path helpers |
| `painter_controller.py` | Painter API wrapper: channels (incl. labelled User channels), resolution, fill layers, shelf + preview shader (main thread only) |
| `texture_processor.py` | texconv DDS→PNG, Remix normal decode (Pillow), anisotropy remap, resize, Blender unwrap launcher |
| `ui_panel.py` | Dock panel (connection, link, normals, actions) + plugin icon |
| `async_utils.py` | `QRunnable` worker + signals |
| `settings_schema.py` | Settings defaults, sanitizing/migration (`_RETIRED_KEYS`), `user_config_dir()` |
| `settings_store.py` | `SettingsStore`: autosaved `settings.json` in `%APPDATA%\Substance2Remix\`, legacy migration, `.bak` for unreadable files |
| `settings_dialog.py` | Autosaving settings dialog: General, Push, Blender, Advanced (no OK/Cancel, no presets) |
| `shelf/shaders/rtx-remix-preview.glsl` | Painter viewport shader previewing every Remix map, on the plugin's shelf (see "Preview shader") |
| `diagnostics_dialog.py` | Diagnostics text dialog |
| `dependency_manager.py` | Puts `_vendor/` (requests, Pillow) on `sys.path` |
| `blender_auto_unwrap.py` | Runs inside Blender (`--background`); Smart UV Project |
| `plugin_info.py` | Name/version constants |

## Design rules

Don't rebuild a control Painter or Remix already has. Artists expect these choices in those apps:
- **What's pushed** = the channels in the texture set (Painter's Texture Set Settings). No per-map
  switches. Import brings every map the material has. Opacity always rides in the albedo alpha.
- **Whether Remix uses a map** (Enable Emission, alpha state, Inwards Displacement) is set on the
  Remix material. Push assigns textures; it never changes material parameters.
- **The viewport shader** is picked in Shader Settings. The plugin only applies its shader when Pull
  creates a project from the default template; elsewhere it adds a hint to the message, never switches.
- **Add Remix Channels** only covers the maps without an obvious Painter channel (`CHANNEL_GROUPS`:
  anisotropy, subsurface). Standard channels are added in Texture Set Settings.
- **Settings** are what Pull needs in place of Painter's New Project dialog, push placement, the
  Blender unwrap and connection basics. No presets, no export format/folder (push exports PNGs to
  `core.EXPORT_DIR`; Remix converts to DDS), no tool-path fields (texconv is bundled; custom
  `texconv_path`/`blender_unwrap_script_path` in `settings.json` are still honoured).
- Retiring a setting: add its key to `settings_schema._RETIRED_KEYS` and bump `SETTINGS_VERSION`.

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

## Preview shader

- Painter's default "PBR - Metal Rough with alpha blending" shader reads only basecolor, metallic,
  roughness, specularlevel, opacity (+ normal/height/emissive/AO via libs). It ignores every Remix
  extra map. `rtx-remix-preview.glsl` is that shader plus anisotropy (`channel_anisotropylevel`,
  angle 0 = tangent, like Remix) and a subsurface approximation from `channel_absorptioncolor`
  (TransmissionColor), `channel_scatteringcolor` (SubsurfaceColor) and `channel_user0..3`
  (thickness; `remixThicknessChannel` picks the slot). Without those channels it is pixel-identical.
- The shader lives on the plugin's shelf (`shelf/`, name `substance2remix`). `_register_shelf`
  adds it at startup with `resource.Shelves.add` (session-only, so every start re-adds it; one
  retry after 3 s). Painter crawls it in milliseconds but `resource.search` only finds it about
  10 s later; `_remix_shader_url` falls back to `import_project_resource(..., Usage.SHADER)` until then.
- Painter's Python API has no shader functions; `PainterController.use_remix_shader` calls the JS API
  through `substance_painter.js.evaluate`: `alg.shaders.instances()`,
  `alg.shaders.updateShaderInstance(id, url)`, `alg.shaders.setParameters(id, {...})`.
  `js.evaluate` returns parsed JSON. `sync_thickness_slot` updates `remixThicknessChannel` on
  instances already using the shader (after Add Remix Channels or an import adds thickness).
- Verified in Painter 12.2 (startup-script harness: a module in
  `Documents/.../python/startup/` runs at launch; delete it afterwards):
  - "Creation of the shader rtx-remix-preview successful", with live parameters.
  - Search finds `resource://substance2remix/rtx-remix-preview?...`, and the switch uses that URL.
  - A saved `.spp` reopens with the shader after the shelf is removed: Painter embeds it
    (`resource://restored_from_cache1/...`).
  - All ten Remix maps export with the runtime documentMap names (`specularroughnessanisotropy`,
    `transmissioncolor`, `user0`, `subsurfacecolor`).

## Painter channels

- Painter 12 names channels after OpenPBR and keeps legacy aliases; `pbr_maps.PbrMap.channels`
  lists names to try (e.g. `SpecularRoughnessAnisotropy`, then `Anisotropylevel`).
- Subsurface thickness has no channel type: it lives in a User channel labelled
  "Remix Thickness" (found by label, created in the first free `User0..31` slot).
- Export `documentMap` names: the six standard maps use fixed names (`baseColor`, `roughness`, …);
  the others use `channel.type().name.lower()` (as Painter's own export tests do), e.g. `user0`.
  Verified exporting in Painter 12.2.

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

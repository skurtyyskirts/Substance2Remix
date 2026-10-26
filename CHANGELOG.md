# Changelog

All notable changes to Substance2Remix. Versions follow [Semantic Versioning](https://semver.org/); the
running version is `PLUGIN_VERSION` in `plugin_info.py`.

## [1.1.0] - 2026-10-26

### Added

- **RTX Remix preview shader** (`assets/shaders/rtx-remix-preview.glsl`). Painter's standard
  "PBR - Metal Rough with alpha blending" shader ignores Remix's anisotropy and subsurface maps, so
  painting them showed nothing. The new shader renders the standard maps exactly like that shader and
  also shows anisotropy (along the mesh tangent, as in Remix) and an approximation of Remix's subsurface
  look from the transmittance, thickness and single-scattering maps. It has its own controls in Shader
  Settings: subsurface preview strength, default thickness, and the thickness User channel.
- Pull, Import (when the material has anisotropy or subsurface maps) and **Add Remix Channels** switch
  the project to the preview shader. **Use RTX Remix Preview Shader** in the menu switches any project.
  A checkbox in **Settings > Texture Maps** turns the automatic switch off. The shader is imported into
  the project, so the `.spp` doesn't depend on the plugin.

### Removed

- **Presets.** Settings simply save as you change them and load again on the next start. The preset bar
  in Settings and the preset switcher in the dock panel are gone, and `presets.json` is no longer used.

### Fixed

- Pull no longer lists informational notes, such as "uses the tiling plane", under "Skipped". The note
  also points to the right tab: **Settings > Project**.
- The Settings dialog's "Saved" message no longer outlives the dialog.

### Verified

- In Painter 12.2: the preview shader compiles and is applied, and Painter exports all ten Remix maps,
  including anisotropy, transmittance, thickness and single scattering, under the channel names the
  plugin resolves at runtime.

## [1.0.0] - 2026-10-26

Tested with Substance 3D Painter 12.2 and the RTX Remix Toolkit 1.6.1. This release also includes the
unreleased 0.5.1 work (expanded test suite, lifecycle cleanup, parallel texture pipelines).

### Added

- **Every texture map RTX Remix ingests.** Besides albedo, normal, roughness, metallic, height and
  emissive (with opacity in the albedo alpha), Push and Import now handle **anisotropy** and the three
  **subsurface** maps: transmittance, thickness (measurement distance) and single scattering.
  Remix's default ingest pipeline drops these maps, so the plugin sends them through Remix's own
  DDS conversion (`.an`, `.tr`, `.md` and `.ss.rtex.dds`, with Remix's ingest metadata).
- **Settings > Texture Maps** tab: turn each map on or off for Push and Import. It shows which Painter
  channel feeds each map.
- **Add Remix Channels**: one click (panel, menu or the Texture Maps tab) adds the Painter channels
  for every map that's switched on. Subsurface thickness gets a User channel labelled "Remix Thickness".
- **Presets**: save your workflow settings under a name, switch presets from the dock panel or the
  Settings dialog, and see when the current settings differ from the active preset. Presets leave
  machine-specific values (Remix address, tool and export paths) alone, so they can be shared.
- **Autosave**: every settings change is saved as you make it. The dialog has no OK/Cancel step.
- The dock panel shows the open project's normal map convention, and the push summary names it,
  e.g. "Pushed albedo, normal (DirectX), roughness".
- Dock panel with the live Remix connection, linked material, current operation and actions.
- Grouped menu with **Link to Selected Remix Material** and **Show Linked Material in Remix**.
- Pull asks which material to link when the selection spans several, and can import the material's
  textures right away.
- The texture set resolution follows the source texture's aspect ratio (e.g. 512×2048).
- The Diagnostics dialog covers the Remix project, ingest folder, edit layer, selection, normal format,
  settings and presets files, tool paths and Pillow status.

### Changed

- **Settings now live in `%APPDATA%\Substance2Remix\`** (`settings.json`, `presets.json`) instead of the
  plugin folder, so reinstalling or updating keeps them. An existing `settings.json` in the plugin folder
  is migrated on first start.
- **Normal maps carry their convention end to end.** Pull records the project's normal map format in the
  `.spp`. Push exports the normal map in that convention and declares the same one to Remix
  (`NORMAL_OGL` or `NORMAL_DX`); Remix uses it to convert the map to octahedral. Import converts Remix's
  normals back to the project's convention. Push reads all its settings once at the start, so changing
  settings during a push can't mislabel the normal map.
- Export uses Painter's `Normal_OpenGL`/`Normal_DirectX` output, so height and baked normal detail are
  included in the normal map.
- Anisotropy is remapped between Painter's Anisotropy Level (0 = isotropic) and Remix's signed range
  (0.5 = isotropic) on push and import.
- The anisotropy and subsurface maps are assigned in their own update. A material without those inputs
  (e.g. a translucent one) reports them as skipped instead of failing the whole push. If Painter can't
  export one of them, the push retries without them, so they never block the standard maps.
- Force Push reports a map it couldn't copy under the new file names, instead of pushing it under the
  old name or leaving it out without a word.
- Imports round a non-power-of-two source up (e.g. 3000 px → 4096), so the texture set is never smaller
  than the source.
- Presets and settings that can't be read are kept as a `.bak` copy. If `presets.json` was locked at
  startup, its presets are merged back in before the file is written again.
- The panel's normals line says "(from Settings)" for projects that weren't created by Pull, and the
  panel asks before a preset replaces settings that aren't saved in any preset.

### Fixed

- **Push on Remix 1.6:** texture updates send `force: false`. Remix 1.6 rejects `force: true` unless the
  current values are sent too.
- **Normal maps on push:** the ingest no longer overrides Remix's check plugins. Before, overriding them
  dropped the octahedral conversion, so normal maps shaded incorrectly in AperturePBR.
- **Import Textures** builds a real fill layer. Before, it imported the files but never applied them.
  A channel whose texture can't be applied no longer stays active and hides the layers below with its
  default value.
- Remix's BC5 normal maps convert in Painter, and octahedral normals are decoded back to tangent space.
- Messages reach you: Painter 12 has no `display_message`, so results now go to the panel, Painter's
  Log window and, when needed, a dialog.
- Painter API calls stay on the main thread. Only one operation runs at a time, Pull asks before
  closing an unsaved project, and background errors can't release another operation's lock.
- Fails fast with a clear message when Remix isn't running.
- Pillow works on Painter 12 (Python 3.13). The bundled copy had only Python 3.11 binaries.
- Blender re-unwrap works on Blender 4.x/5.x, writes to `_temp/unwrapped/` instead of the Remix project's
  captures, and auto-detects Blender. `.gltf` meshes are written as glTF; before, they were written as
  GLB under a `.gltf` name and the unwrap reported a failure.
- Aspect-ratio restore works for TGA exports, and resizing keeps the export's file format.
- The project template is passed to Painter, instance prims map to their mesh, absolute mesh references
  resolve, and relinking clears the previous material's size and project data.

### Removed

- Material auto-discovery, which probed a Remix endpoint that doesn't exist. The Remix selection already
  carries the material.
- The separate opacity map (Remix has no opacity texture type) and JPEG export.
- The unused `agent/` folder, `SYNC_SETUP.md`, the unused `Remix.spexp` preset and the stale
  `HEALTH_CHECK.md`. `settings.json` is no longer tracked in git.

### Other

- Restored the MIT `LICENSE` file, which an earlier release had dropped.

## [0.5.0] - 2025-12-23

### Added

- Background workers for pulls, imports and exports, with a progress dialog.
- Force Push (relink) to push a project onto a different Remix material.
- Diagnostics dialog, persistent settings and a dedicated menu.

### Changed

- Modular core; bundled Python dependencies; better `texconv.exe` detection.

### Fixed

- Relative texture paths, UI freezes during import/export, and errors when the Remix API is unavailable.

## [0.4] - 2025-08-02

- Bundled dependency manager, the first Force Push to Remix, and a Substance2Remix submenu.

## [0.3.1] - 2025-07-30

- The bundled `texconv.exe` is found automatically.

## [0.3] - 2025-07-29

- Changing settings no longer creates a folder in the plugins folder; file cleanup and renames.

[1.1.0]: https://github.com/skurtyyskirts/Substance2Remix/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/skurtyyskirts/Substance2Remix/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/skurtyyskirts/Substance2Remix/releases/tag/v0.5.0
[0.4]: https://github.com/skurtyyskirts/Substance2Remix/releases/tag/0.4a
[0.3.1]: https://github.com/skurtyyskirts/Substance2Remix/releases/tag/0.3.1a
[0.3]: https://github.com/skurtyyskirts/Substance2Remix/releases/tag/0.3a

# Substance2Remix

A Substance 3D Painter plugin that connects Painter to the NVIDIA RTX Remix Toolkit. Pull a captured mesh and its material into Painter, paint, and push the textures straight back onto the Remix material.

**v1.0.0** · tested with Substance 3D Painter 12.2 and RTX Remix Toolkit 1.6.1 · [Changelog](CHANGELOG.md)

## What's new in 1.0

- **Every RTX Remix texture map.** Albedo (with opacity in the alpha), normal, roughness, metallic, height and emissive, plus anisotropy and subsurface transmittance, thickness and single scattering. Turn each one on or off in **Settings > Texture Maps**.
- **OpenGL or DirectX normals, end to end.** Each project keeps the normal convention it was created with. Push exports in that convention and tells Remix which one it is, so Remix's octahedral conversion is always right.
- **Presets and autosave.** Every settings change saves immediately. Save named presets and switch between them from the dock panel.
- **Works with Remix 1.6.** Pushes use Remix's validated update path and its default ingest pipeline. Import builds a real fill layer.
- **Settings survive updates.** They now live in `%APPDATA%\Substance2Remix\`, outside the plugin folder.

## Features

- **Pull from Remix**: creates a Painter project from the mesh (or several meshes) selected in the Remix viewport, linked to their material. The material's existing Remix textures are imported as a fill layer. The texture set takes the source texture's aspect ratio (for example 512×2048 for a 1:4 texture).
- **Import Textures from Remix**: adds the linked material's current textures to the open project as one undoable fill layer. Octahedral normals are converted back to the project's convention, and albedo alpha goes to the Opacity channel.
- **Push to Remix**: exports the active texture set and ingests it through Remix's own pipeline (octahedral normal conversion, DDS compression, ingest metadata). It then assigns the textures to the material and saves the Remix layer.
- **Force Push to Selected Material**: relinks the project to whatever material is selected in Remix and pushes under new file names, so earlier ingests are never overwritten.
- **Link to Selected Remix Material** and **Show Linked Material in Remix**: relink without pushing, or select the linked material in Remix.
- **Add Remix Channels**: adds the Painter channels for every map you've switched on, so the extra maps are ready to paint.
- **Dock panel**: shows the live Remix connection, the linked material, the project's normal convention, the active preset and the running operation, with the main actions one click away.
- **Optional Blender re-unwrap** for captures with unusable UVs. The newest installed Blender is found automatically.
- **Diagnostics**: one dialog with the Painter, Remix, tool, settings and project-link state, plus the plugin log.

## Requirements

- Adobe Substance 3D Painter 10 or later, tested on 12.2. The bundled Pillow is built for the Python of Painter 10–11 (3.11) and Painter 12 (3.13).
- NVIDIA RTX Remix Toolkit with a project open, tested on 1.6.1. Its REST API listens on `http://localhost:8011` by default.
- Windows (the bundled `texconv.exe` is a Windows tool).
- Blender, optional, only for the re-unwrap option.

`texconv.exe` (DirectXTex), `requests` and Pillow are bundled. Nothing else needs installing.

## Installation

1. Download `Substance2Remix-v1.0.0.zip` from the [latest release](https://github.com/skurtyyskirts/Substance2Remix/releases/latest).
2. Close Substance 3D Painter.
3. Extract the zip into Painter's plugin folder:
   `Documents\Adobe\Adobe Substance 3D Painter\python\plugins`
   You should end up with `...\python\plugins\substance2remix\__init__.py`. The folder name matters, because Painter lists plugins by folder name. If you downloaded the source code instead, rename `Substance2Remix-main` to `substance2remix`.
4. Start Painter and tick **Python > substance2remix**. Painter remembers this for later sessions.
5. The **Substance2Remix** menu appears in the menu bar and the panel docks on the side. If you close the panel, its icon in the dock bar brings it back.

In RTX Remix, start the Toolkit and open your mod project before you pull or push. The panel's status dot turns green when Painter can reach it.

### Updating

Close Painter, delete the old `substance2remix` folder and extract the new one in its place. Your settings and presets live in `%APPDATA%\Substance2Remix\` and are kept.

**Upgrading from 0.x:** older versions kept `settings.json` inside the plugin folder. Extract the new version over the old folder, or copy the old `settings.json` into the new `substance2remix` folder, before starting Painter. It is migrated to `%APPDATA%\Substance2Remix\` on first start. If your old folder had a different name, delete it so Painter doesn't load two copies.

## Workflow

1. In the RTX Remix viewport, select the mesh you want to texture. Its material is picked up automatically. Shift-click several meshes that share a material to bundle them into one project.
2. In Painter, choose **Pull from Remix**. If the current project has unsaved changes, you're asked first. If the selection spans several materials, you choose which one to link.
3. Paint. For anisotropy or subsurface maps, click **Add Remix Channels** first.
4. Choose **Push to Remix**. Only maps that are switched on and whose channel exists in the texture set are pushed.

The link to the Remix material is stored inside the `.spp` file, so pushing still works after you save, close and reopen the project.

## Texture maps

| Remix map (AperturePBR input) | Painter channel | Notes |
| --- | --- | --- |
| Albedo (`diffuse_texture`) | Base Color | |
| Opacity | Opacity | Stored in the albedo alpha. AperturePBR has no separate opacity texture. |
| Normal (`normalmap_texture`) | Normal, plus Height detail | Remix converts it to octahedral; see below. |
| Roughness (`reflectionroughness_texture`) | Roughness | |
| Metallic (`metallic_texture`) | Metallic | |
| Height (`height_texture`) | Height | Displacement / parallax. |
| Emissive (`emissive_mask_texture`) | Emissive | |
| Anisotropy (`anisotropy_texture`) | Anisotropy Level | Painter's 0 to 1 maps onto Remix's 0 to +1 (isotropic is 0.5 in the file). |
| Subsurface Transmittance (`subsurface_transmittance_texture`) | Transmission Color | |
| Subsurface Thickness (`subsurface_thickness_texture`) | User channel "Remix Thickness" | Painter has no thickness channel; values pass through unchanged. |
| Subsurface Single Scattering (`subsurface_single_scattering_texture`) | Subsurface Color | Remix reads it as linear data. |

Painter 12 names channels after OpenPBR. On older Painter versions the plugin falls back to the legacy names (Anisotropy Level, Absorption Color, Scattering Color).

## Normal maps: OpenGL or DirectX

- **New projects** use **Settings > Project > Normal Map Format**. Pull stores that choice in the project.
- **Push** exports the normal map in the project's convention, using Painter's normal output that includes height and baked normal detail. It ingests the map as `NORMAL_OGL` or `NORMAL_DX`. Remix uses that to convert the map to octahedral, the format AperturePBR expects. The push summary names the convention, for example "normal (DirectX)".
- **Import** converts Remix's octahedral normals back to the project's convention.
- The panel shows the open project's convention ("Normals: OpenGL"). Painter can't report a project's normal format to plugins, so projects that weren't created by Pull (or were created before 1.0) use the setting, and the panel shows "(from Settings)". Pushes are correct either way, because the exported file and the declared convention always match. Imports convert to that convention, so set it to your project's normal format (**Edit > Project Configuration** in Painter).

The pushed map is octahedral, so the Remix material's **Normal Map Encoding** must be *Octahedral*. That's the default for captured materials. If you changed it in Remix, set it back.

## Settings and presets

Open **Substance2Remix > Settings...** or use the panel's **Settings...** button. Changes are saved as you make them.

| Tab | What it controls |
| --- | --- |
| Connection | Remix API address, request timeout, connection test |
| Project | Auto-import after Pull, texture resolution, normal map format, project template, tiling-plane pulls, Blender re-unwrap |
| Texture Maps | Which Remix maps Push and Import include, and the Painter channel behind each one |
| Export | Export format, aspect-ratio restore, Remix output subfolder, export folder |
| Paths | texconv, Blender, custom unwrap script, plugin log |
| Advanced | Log level, Blender Smart UV parameters |

**Presets** sit at the top of the Settings dialog. Use **Save As...** to name the current setup and **Save** to update the active preset. Switch presets from the dialog or the dock panel. "Unsaved changes" means your settings differ from the active preset. A preset stores workflow settings only: the Remix address, tool paths and export folder stay as they are. **Restore Defaults** resets the settings and keeps your presets.

Settings are stored in `%APPDATA%\Substance2Remix\settings.json` and presets in `presets.json` next to it.

## Troubleshooting

- **"Can't reach RTX Remix"**: start the Toolkit and open a project. If you changed its port, update **Settings > Connection** and click **Test Connection**.
- **A map isn't pushed**: check that it's switched on in **Settings > Texture Maps** and that its channel exists in the active texture set. **Add Remix Channels** adds it.
- **"Remix rejected the anisotropy/subsurface maps"**: the material's shader has no such inputs (for example a translucent material). The standard maps are still pushed.
- **Normals look inverted in Remix**: check the panel's "Normals:" line against how you painted, and make sure the Remix material's Normal Map Encoding is Octahedral.
- **Diagnostics...** shows the full state. The plugin log is `logs/remix_connector.log` in the plugin folder (**Open Log Folder**).

## Notes

- **Re-unwrapping changes UVs.** With the Blender option on, the project's UVs no longer match the mesh in Remix, so pushed textures only line up after you replace that mesh in Remix.
- Only the active texture set is pushed.
- Pulled textures are staged in `Pulled Textures/<Remix project>/<material hash>/` inside the plugin folder.

## Development

Run the tests with Painter's bundled Python, which has PySide6 and matches the vendored Pillow build. `CLAUDE.md` has the exact command plus the architecture, threading rules and the RTX Remix REST facts the plugin relies on.

## License

[MIT](LICENSE). Third-party components are listed in `THIRD_PARTY_LICENSES.md`.

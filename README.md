# Substance2Remix

A Substance 3D Painter plugin that connects Painter to the NVIDIA RTX Remix Toolkit. Pull a captured mesh and its material into Painter, paint, and push the textures straight back onto the Remix material.

**v1.1.0** · tested with Substance 3D Painter 12.2 and RTX Remix Toolkit 1.6.1 · [Changelog](CHANGELOG.md)

## What's new in 1.1

- **See every Remix map in Painter's viewport.** The new **RTX Remix preview shader** renders like Painter's standard alpha-blended PBR shader. It also shows anisotropy and Remix's subsurface maps (transmittance, thickness and single scattering). It sits on its own shelf, so you pick it in **Shader Settings** like any other shader. Pull uses it for new projects.
- **Fewer controls, each in the place you'd expect.** The plugin no longer duplicates what Painter or Remix already control:
  - Presets are gone. Every change saves as you make it and loads again the next time Painter starts.
  - Push sends whatever channels the texture set has, so there are no per-map switches.
  - The viewport shader is chosen in Shader Settings.
  - Pushing onto a different material is now Link, then Push.

## What's in 1.0

- **Every RTX Remix texture map.** Albedo (with opacity in the alpha), normal, roughness, metallic, height and emissive, plus anisotropy and subsurface transmittance, thickness and single scattering.
- **OpenGL or DirectX normals, end to end.** Each project keeps the normal format it was created with. Push exports in that format and tells Remix which one it is, so Remix's octahedral conversion is always right.
- **Works with Remix 1.6.** Pushes use Remix's validated update path and its default ingest pipeline. Import builds a real fill layer.
- **Settings survive updates.** They live in `%APPDATA%\Substance2Remix\`, outside the plugin folder.

## Features

- **Pull from Remix**: creates a Painter project from the mesh (or several meshes) selected in the Remix viewport, linked to their material. The material's existing Remix textures are imported as a fill layer. The texture set takes the source texture's aspect ratio (for example 512×2048 for a 1:4 texture).
- **Import Textures from Remix**: adds the linked material's current textures to the open project as one undoable fill layer. Octahedral normals are converted back to the project's normal format, and albedo alpha goes to the Opacity channel.
- **Push to Remix**: exports the active texture set and ingests it through Remix's own pipeline (octahedral normal conversion, DDS compression, ingest metadata). It then assigns the textures to the material and saves the Remix layer.
- **Link to Selected Remix Material** and **Show Linked Material in Remix**: point the project at whatever material is selected in Remix (the next push goes there), or select the linked material in Remix.
- **Add Remix Channels > Anisotropy / Subsurface**: adds the Painter channels for the Remix maps that have no obvious Painter channel. Standard channels like Emissive are added in **Texture Set Settings** as usual.
- **RTX Remix preview shader**: a viewport shader that shows every map Remix uses (see [Viewport preview](#viewport-preview)).
- **Dock panel**: shows the live Remix connection, the linked material, the project's normal format and the running operation, with the main actions one click away.
- **Optional Blender re-unwrap** for captures with unusable UVs. The newest installed Blender is found automatically.
- **Diagnostics**: one dialog with the Painter, Remix, tool, settings and project-link state, plus the plugin log.

## Requirements

- Adobe Substance 3D Painter 10 or later, tested on 12.2. The bundled Pillow is built for the Python of Painter 10–11 (3.11) and Painter 12 (3.13).
- NVIDIA RTX Remix Toolkit with a project open, tested on 1.6.1. Its REST API listens on `http://localhost:8011` by default.
- Windows (the bundled `texconv.exe` is a Windows tool).
- Blender, optional, only for the re-unwrap option.

`texconv.exe` (DirectXTex), `requests` and Pillow are bundled. Nothing else needs installing.

## Installation

1. Download `Substance2Remix-v1.1.0.zip` from the [latest release](https://github.com/skurtyyskirts/Substance2Remix/releases/latest).
2. Close Substance 3D Painter.
3. Extract the zip into Painter's plugin folder:
   `Documents\Adobe\Adobe Substance 3D Painter\python\plugins`
   You should end up with `...\python\plugins\substance2remix\__init__.py`. The folder name matters, because Painter lists plugins by folder name. If you downloaded the source code instead, rename `Substance2Remix-main` to `substance2remix`.
4. Start Painter and tick **Python > substance2remix**. Painter remembers this for later sessions.
5. The **Substance2Remix** menu appears in the menu bar and the panel docks on the side. If you close the panel, its icon in the dock bar brings it back. The plugin also adds a **substance2remix** shelf holding the preview shader.

In RTX Remix, start the Toolkit and open your mod project before you pull or push. The panel's status dot turns green when Painter can reach it.

### Updating

Close Painter, delete the old `substance2remix` folder and extract the new one in its place. Your settings live in `%APPDATA%\Substance2Remix\` and are kept.

**Upgrading from 0.x:** older versions kept `settings.json` inside the plugin folder. Before starting Painter, either extract the new version over the old folder or copy the old `settings.json` into the new `substance2remix` folder. It moves to `%APPDATA%\Substance2Remix\` on first start. If your old folder had a different name, delete it so Painter doesn't load two copies.

## Workflow

1. In the RTX Remix viewport, select the mesh you want to texture. Its material is picked up automatically. Shift-click several meshes that share a material to bundle them into one project.
2. In Painter, choose **Pull from Remix**. If the current project has unsaved changes, you're asked first. If the selection spans several materials, you choose which one to link.
3. Paint. For anisotropy or subsurface maps, use **Add Remix Channels** first.
4. Choose **Push to Remix**. Every Remix map whose channel exists in the active texture set is pushed.

The link to the Remix material is stored inside the `.spp` file, so pushing still works after you save, close and reopen the project. To send a project's textures to a different material, select that material in Remix, choose **Link to Selected Remix Material**, then push.

## Texture maps

| Remix map (AperturePBR input) | Painter channel | Notes |
| --- | --- | --- |
| Albedo (`diffuse_texture`) | Base Color | |
| Opacity | Opacity | Stored in the albedo alpha. AperturePBR has no separate opacity texture. |
| Normal (`normalmap_texture`) | Normal, plus Height detail | Remix converts it to octahedral; see below. |
| Roughness (`reflectionroughness_texture`) | Roughness | |
| Metallic (`metallic_texture`) | Metallic | |
| Height (`height_texture`) | Height | Remix uses it for parallax. |
| Emissive (`emissive_mask_texture`) | Emissive | |
| Anisotropy (`anisotropy_texture`) | Specular Anisotropy | Painter's 0 to 1 maps onto Remix's 0 to +1 (isotropic is 0.5 in the file). |
| Subsurface Transmittance (`subsurface_transmittance_texture`) | Transmission Color | |
| Subsurface Thickness (`subsurface_thickness_texture`) | User channel "Remix Thickness" | Painter has no thickness channel; values pass through unchanged. |
| Subsurface Single Scattering (`subsurface_single_scattering_texture`) | Subsurface Color | Remix reads it as linear data. |

Painter 12 names channels after OpenPBR. On older Painter versions the plugin falls back to the legacy names (Anisotropy Level, Absorption Color, Scattering Color).

A pushed map is assigned to the material, but some settings for using it stay on the Remix material, where you'd set them for any texture:

- **Emissive** shows when **Enable Emission** is on.
- **Opacity** follows the alpha settings (**Use Legacy Alpha State**, **Blend Enabled**, alpha test).
- **Height**: its parallax depth is **Inwards Displacement**.

## Viewport preview

Painter's standard shaders don't read most of Remix's extra maps. The usual "PBR - Metal Rough with alpha blending" shader ignores anisotropy, transmittance, thickness and single scattering. You could paint them, but you couldn't see them.

The plugin ships the **RTX Remix preview shader** (`rtx-remix-preview`) on its **substance2remix** shelf. It is that same standard shader, so the usual maps look exactly as before. It adds two things:

- **Anisotropy**: highlights stretch along the mesh tangent, as in Remix (Remix has no anisotropy angle).
- **Subsurface**: where any of the transmittance, thickness or single-scattering maps is painted, light coming through the surface is filtered by the transmittance color over the painted thickness and tinted by the single-scattering color. Thicker areas let less light through.

**Pull** uses it for projects created from Painter's default template. A project template of your own keeps its shader. For any other project, choose **rtx-remix-preview** in **Shader Settings**, like any shader. Painter stores the shader inside the project, so the `.spp` opens with it even without the plugin.

Its **RTX Remix Preview** controls are in Shader Settings:

- subsurface preview strength
- the thickness assumed where none is painted
- which User channel holds the thickness map (the plugin sets this when it adds or imports that channel)

The subsurface part is a viewport approximation. RTX Remix renders the final look, and the shader only changes what you see in Painter, never what is pushed.

## Normal maps: OpenGL or DirectX

- **New projects** use **Settings > General > Normal Map Format**. Pull stores that choice in the project.
- **Push** exports the normal map in the project's format, using Painter's normal output that includes height and baked normal detail. It ingests the map as `NORMAL_OGL` or `NORMAL_DX`. Remix uses that to convert the map to octahedral, the format AperturePBR expects. The push summary names the format, for example "normal (DirectX)".
- **Import** converts Remix's octahedral normals back to the project's format.
- **The panel** shows the open project's format ("Normals: OpenGL"). Painter can't report a project's normal format to plugins. Projects that weren't created by Pull (or were created before 1.0) use the setting, and the panel shows "(from Settings)".
  - Pushes are correct either way, because the exported file and the declared format always match.
  - Imports convert to the setting's format, so set it to match your project (**Edit > Project Configuration** in Painter).

The pushed map is octahedral, so the Remix material's **Normal Map Encoding** must be *Octahedral*. That's the default for captured materials. If you changed it in Remix, set it back.

## Settings

Open **Substance2Remix > Settings...** or use the panel's **Settings...** button. Every change is saved as you make it and loaded again the next time Painter starts. There's no OK button to remember.

| Tab | What it controls |
| --- | --- |
| General | Remix address, and what Pull uses in place of Painter's New Project dialog: project template, normal map format, starting resolution, auto-import, tiling plane |
| Push | Restoring the source texture's aspect ratio, the Remix output subfolder |
| Blender | The optional re-unwrap, the Blender path and the Smart UV Project parameters |
| Advanced | Request timeout, log level |

**Restore Defaults** resets every setting (it asks first). Settings are stored in `%APPDATA%\Substance2Remix\settings.json`.

## Troubleshooting

- **"Can't reach RTX Remix"**: start the Toolkit and open a project. If you changed its port, update **Settings > General > RTX Remix Address**. The panel's status dot shows the result, and **↻** checks again.
- **A map isn't pushed**: its channel must exist in the active texture set. Add standard channels in Texture Set Settings, and anisotropy or subsurface with **Add Remix Channels**.
- **A pushed map has no effect in Remix**: check the Remix material settings listed under [Texture maps](#texture-maps), for example Enable Emission.
- **"Remix rejected the anisotropy/subsurface maps"**: the material's shader has no such inputs (for example a translucent material). The standard maps are still pushed.
- **Normals look inverted in Remix**: check the panel's "Normals:" line against how you painted, and make sure the Remix material's Normal Map Encoding is Octahedral.
- **Anisotropy or subsurface paint doesn't show in Painter**: the project uses another shader. Choose **rtx-remix-preview** in Shader Settings. For subsurface, raise **Subsurface preview strength** there if the effect is too subtle.
- **Diagnostics...** shows the full state. The plugin log is `logs/remix_connector.log` in the plugin folder (**Open Log Folder**).

## Notes

- **Re-unwrapping changes UVs.** With the Blender option on, the project's UVs no longer match the mesh in Remix, so pushed textures only line up after you replace that mesh in Remix.
- Only the active texture set is pushed.
- Pulled textures are staged in `Pulled Textures/<Remix project>/<material hash>/` inside the plugin folder. Push exports PNGs to a temporary folder, and Remix converts them to DDS on ingest.

## Development

Run the tests with Painter's bundled Python, which has PySide6 and matches the vendored Pillow build. `CLAUDE.md` has the exact command plus the architecture, threading rules and the RTX Remix REST facts the plugin relies on.

## License

[MIT](LICENSE). Third-party components are listed in `THIRD_PARTY_LICENSES.md`.

# Substance2Remix

A Substance 3D Painter plugin that connects Painter to the NVIDIA RTX Remix Toolkit. Pull a captured mesh and its material into Painter, paint, and push the textures straight back onto the Remix material.

## Features

- **Pull from Remix**: creates a Painter project from the mesh (or several meshes) selected in the Remix viewport, linked to their material. The material's existing Remix textures are imported as a fill layer, and the texture set takes the source texture's aspect ratio (for example 512×2048 for a 1:4 texture).
- **Import Textures from Remix**: adds the linked material's current textures to the open project as one undoable fill layer. Octahedral normal maps are converted back to tangent space, and albedo alpha goes to the Opacity channel.
- **Push to Remix**: exports the active texture set, ingests the textures through Remix's own pipeline (octahedral normal conversion, DDS compression, ingest metadata), assigns them to the material and saves the Remix layer.
- **Force Push to Selected Material**: relinks the project to whatever material is selected in Remix and pushes under new file names, so earlier ingests are never overwritten.
- **Link to Selected Remix Material** and **Show Linked Material in Remix**: relink without pushing, or select the linked material in Remix.
- **Dock panel**: shows the live Remix connection, the linked material and the running operation, with the main actions one click away.
- **Optional Blender re-unwrap** for captures with unusable UVs (finds the newest installed Blender automatically).
- **Diagnostics**: one dialog with the Painter, Remix, tool and project-link state, plus the plugin log.

## Requirements

- Adobe Substance 3D Painter, tested on 12.2. Older versions need the `substance_painter.layerstack` Python API.
- NVIDIA RTX Remix Toolkit with a project open (tested on 1.6.1). Its REST API listens on `http://localhost:8011` by default.
- Blender (optional, only for the re-unwrap option)

`texconv.exe` (DirectXTex), `requests` and Pillow are bundled.

## Installation

1. Copy the plugin folder into Painter's plugin directory, usually `Documents\Adobe\Adobe Substance 3D Painter\python\plugins`. Name the folder `substance2remix`, since the folder name is what Painter lists.
2. Start Painter and enable it under **Python > substance2remix**.
3. The **Substance2Remix** menu appears in the menu bar and the panel docks on the side. If you close the panel, its icon in the dock bar reopens it.

## Workflow

1. In the RTX Remix viewport, select the mesh you want to texture. Its material is picked up automatically. Shift-click several meshes that share a material to bundle them into one project.
2. In Painter, choose **Pull from Remix**. If the current project has unsaved changes, you're asked first. If the selection spans several materials, you choose which one to link.
3. Paint.
4. Choose **Push to Remix**. Only channels that exist in the texture set are pushed. The normal map includes your height detail and any baked normal map.

The link to the Remix material is stored inside the `.spp` file, so pushing still works after you save, close and reopen the project.

## Settings

**Substance2Remix > Settings...**

| Tab | What it controls |
|-----|------------------|
| Connection | Remix API address, request timeout, connection test |
| Project | Auto-import after Pull, texture resolution, normal map format (OpenGL/DirectX), project template, tiling-plane pulls, Blender re-unwrap |
| Export | Export format, aspect-ratio restore, Remix output subfolder, export folder |
| Paths | texconv, Blender, custom unwrap script, plugin log |
| Advanced | Log level, Blender Smart UV parameters |

## Notes

- **Re-unwrapping changes UVs.** With the Blender option on, the project's UVs no longer match the mesh in Remix, so pushed textures only line up after you replace that mesh in Remix.
- **Opacity** is pushed in the albedo alpha channel, which is where Remix's AperturePBR material reads it.
- Pulled textures are staged in `Pulled Textures/<Remix project>/<material hash>/` inside the plugin folder, and the plugin log is `logs/remix_connector.log`.

## Development

Run the tests with Painter's bundled Python, which has PySide6 and matches the vendored Pillow build. See `CLAUDE.md` for the exact command.

## Changelog

### v1.0.0
- Works with RTX Remix Toolkit 1.6: texture assignment uses Remix's validated (non-forced) update path, and ingest keeps Remix's default pipeline so normal maps are converted to octahedral encoding.
- Import Textures now builds a real fill layer. It previously imported the files without assigning them.
- Remix BC5 normal maps convert and decode correctly in Painter.
- Pillow works on Painter 12 (Python 3.13). The bundled copy had only Python 3.11 binaries.
- Painter API calls run on the main thread, operations can't overlap, and unsaved projects are never closed without asking.
- Fails fast with a clear message when Remix isn't running.
- Blender re-unwrap works on Blender 4.x/5.x, and its output no longer lands inside the Remix project's captures.
- New dock panel, menu sections, Link / Show-in-Remix actions and an expanded Diagnostics dialog.
- Removed dead features: the auto-discovery that probed a Remix endpoint which doesn't exist, and the separate opacity map.

### v0.5.0
- Modular refactor, background workers, Force Push (relink), diagnostics and settings dialogs.

## License

[MIT](https://choosealicense.com/licenses/mit/). Third-party components are listed in `THIRD_PARTY_LICENSES.md`.

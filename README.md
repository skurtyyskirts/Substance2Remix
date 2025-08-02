# Substance Painter to RTX Remix Connector

This plugin creates a bridge between Adobe Substance 3D Painter and NVIDIA's RTX Remix, allowing artists to seamlessly send and receive textures and meshes between the two applications.

## Features

- **Pull from Remix**: Create a new Substance Painter project using the selected mesh from RTX Remix. The project is automatically linked for future push/pull operations.
- **Push to Remix**: Export textures from Substance Painter and automatically ingest them into the selected Remix material.
- **Force Push to Remix**: Push textures to a *different* selected material in Remix, allowing you to reuse your Substance Painter work on multiple assets.
- **Import Textures from Remix**: Pull textures from a linked material in Remix into the current Substance Painter project.
- **Auto-unwrap with Blender**: Optionally use Blender to automatically UV unwrap meshes pulled from Remix, streamlining the texturing process.
- **Settings Panel**: Configure plugin settings, including paths to your Blender executable and the `texconv.exe` utility.

## Requirements

- Adobe Substance 3D Painter
- NVIDIA RTX Remix
- Blender (optional, for auto-unwrap feature)
- `texconv.exe` (a copy is included with this plugin)

## Installation

1.  Download the latest release from the [GitHub releases page](https://github.com/skurtyyskirts/Substance2Remix/releases).
2.  Locate your Substance Painter plugins directory. This is typically found at: `Documents\Adobe\Adobe Substance 3D Painter\python\plugins`.
3.  Copy the `Substance2Remix` folder into the `plugins` directory.
4.  Launch Substance Painter. The plugin will be available under the **Window > RTX Remix Connector** menu.

## How to Use

### Connecting to Remix

Before using the push/pull features, ensure that RTX Remix is running and that a project is open.

### Pulling a Mesh from Remix

1.  In RTX Remix, select the mesh you want to texture.
2.  In Substance Painter, go to **Window > RTX Remix Connector > Pull from Remix**.
3.  A new Substance Painter project will be created with the selected mesh. If the **Auto-Unwrap with Blender** option is enabled in the settings, the mesh will be unwrapped before the project is created.

### Importing Existing Textures

After pulling a mesh, you can import its existing textures from Remix:

1.  Go to **Window > RTX Remix Connector > Import Textures from Remix**.
2.  The plugin will find the textures associated with the linked material in Remix and import them into your current Substance Painter project.

### Pushing Textures to Remix

1.  After texturing your mesh in Substance Painter, go to **Window > RTX Remix Connector > Push to Remix**.
2.  The plugin will export your textures and update the material in Remix.

### Force Pushing to a Different Material

If you want to apply your textures to a different material in Remix:

1.  In RTX Remix, select the new target material.
2.  In Substance Painter, go to **Window > RTX Remix Connector > Force Push to Remix**.
3.  The plugin will export the textures and apply them to the newly selected material.

### Settings

The Settings panel (**Window > RTX Remix Connector > Settings...**) allows you to configure the following:

-   **Blender Executable Path**: The path to your `blender.exe` file. This is required for the auto-unwrap feature.
-   **Texconv Path**: The path to the `texconv.exe` utility. This is used to convert `.dds` files from Remix into a format that Substance Painter can use. A copy is included with this plugin and should be detected automatically.
-   **Log Level**: The verbosity of the plugin's logs.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)

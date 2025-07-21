# RTX Remix Substance Painter Connector

This plugin creates a bridge between Substance Painter and NVIDIA's RTX Remix, allowing artists to easily send and receive textures between the two applications.

## Features

- **Push to Remix**: Export textures from Substance Painter and automatically ingest them into the selected Remix material.
- **Pull from Remix**: Create a new Substance Painter project using the selected mesh from Remix, and automatically link it for future push/pull operations.
- **Import Textures from Remix**: Pull textures from a linked material in Remix into the current Substance Painter project.
- **Auto-Unwrap with Blender**: Optionally use Blender to automatically unwrap meshes pulled from Remix.
- **Settings Panel**: Configure plugin settings, including paths to Blender and the 	exconv.exe utility.

## Installation

1.  Download the latest release from https://github.com/skurtyyskirts/Substance2Remix.
2.  Locate your Substance Painter plugins directory. This is typically found in Documents\Adobe\Adobe Substance 3D Painter\python\plugins.
3.  Copy the Substance2Painter folder into the plugins directory.
4.  Launch Substance Painter. The plugin will be available under the Plugins > RTX Remix Connector menu.

## Usage

### Connecting to Remix

Before using the push/pull features, ensure that RTX Remix is running and that a project is open.

### Pulling a Mesh from Remix

1.  In RTX Remix, select the mesh you want to texture.
2.  In Substance Painter, go to Plugins > RTX Remix Connector > Pull from Remix.
3.  A new Substance Painter project will be created with the selected mesh.

### Pushing Textures to Remix

1.  After texturing your mesh in Substance Painter, go to Plugins > RTX Remix Connector > Push to Remix.
2.  The plugin will export the textures and update the material in Remix.

### Settings

The Settings panel (Plugins > RTX Remix Connector > Settings) allows you to configure the following:

-   **Blender Executable Path**: The path to your lender.exe file. This is required for the auto-unwrap feature.
-   **Texconv Path**: The path to the 	exconv.exe utility. This is used to convert .dds files from Remix into a format that Substance Painter can use. A copy is included with this plugin.
-   **Log Level**: The verbosity of the plugin's logs.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)

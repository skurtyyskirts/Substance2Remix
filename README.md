# Substance2Remix 

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This Python plugin (Version 0.1 - Expect bugs!) helps bridge Painter and the Remix Toolkit/Runtime, aiming to make the process faster and more efficient.

---

## What Does It Do?

This plugin connects Painter and Remix for key operations:

* **🚀 Pull Assets:** Instantly grab the selected mesh/material from Remix and set up a new, linked project in Painter.
* **🖼️ Import Textures:** Automatically fetch textures from Remix, convert `.dds` files to `.png` (using `texconv.exe`), and import them into your Painter project shelf. It also attempts assignment to the correct channels. *(View imported textures under Assets > Your Project)*
* **➡️ Push Textures:** Export your work (using a PBR Metallic Roughness profile), send it to Remix for ingestion (conversion back to `.dds`), dynamically update the linked material, and trigger a save in Remix.

---

## Core Features

* **🔗 Direct Linking:** Keeps Painter projects tied to specific Remix materials via metadata.
* **🗺️ Smart Path Finding:** Resolves relative mesh/texture paths provided by Remix.
* **🔄 DDS <-> PNG Conversion:** Handles `.dds` conversion using `texconv.exe` (with fallback).
* **⚙️ Controlled Export:** Exports textures based on configurable settings (Defaults to PBR Metallic Roughness).
* **📡 API Integration:** Communicates directly with the RTX Remix Toolkit API.
* **🎯 Dynamic Updates:** Finds the correct material inputs in Remix automatically during push.
* **🔧 Configurable:** Key settings are editable within the `core.py` script.

---

## Getting Started

Ready to integrate? Here’s how to set it up:

1.  **Grab `core.py`:** Download the script file from this repository. Optionally, download `requirements.txt`.
2.  **Add to Painter:** ✅
    * In Painter: `Python` > `Plugins Folder`.
    * Drop `core.py` into that folder.
3.  **Install Python Dependencies (`Pillow` & `requests`):**
    * The necessary Python packages are listed in `requirements.txt`.
    * **Recommended Method:** Restart Painter. Check the `Python` > `Log` window for the exact `pip install` command needed for your setup. Run that command in a Command Prompt (cmd) or Terminal.
        ```bash
        # Example command from log - DO NOT COPY PASTE - Use paths from YOUR Painter Log!
        "C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\pythonsdk\python.exe" -m pip install --upgrade --target="C:\Users\YourUser\Documents\Adobe\Adobe Substance 3D Painter\python\lib\site-packages" Pillow requests
        ```
    * **Alternative (If you cloned the repo):** Navigate to the repo directory and run `"<path_to_painter_python.exe>" -m pip install --upgrade --target="<path_from_log>" -r requirements.txt`.
    * **Restart Painter again!** 🔄
4.  **Get `texconv.exe` (Required!):** 📍
    * **Important:** `texconv.exe` is an external tool and **cannot** be installed using `pip` or `requirements.txt`. Download it manually. (`texassemble.exe` is **not** needed).
    * Download the latest release from the official **[Microsoft DirectXTex Releases](https://github.com/microsoft/DirectXTex/releases)** page.
    * Find `texconv.exe` inside the downloaded archive (e.g., in a `bin/x64/Release` subfolder).
    * Copy `texconv.exe` somewhere stable on your computer (like `C:\Tools\texconv.exe`) and note the full path.
5.  **Configure the Script:** 🔧
    * Open `core.py` (in the plugins folder) in a text editor.
    * Find `PLUGIN_SETTINGS` near the top.
    * **Most Important:** Update `"texconv_path"` to the full path where you placed `texconv.exe`. Also set `"painter_export_path"` to your desired export folder. Use double backslashes (`\\`) or forward slashes (`/`). See the [detailed README](README.md) for examples.
    * Review other settings like `"painter_import_template_path"` if needed.

---

## How to Use It

Access the plugin via Painter's main menu: **`Python` > `RemixConnector`**

1.  **Pull (Remix -> Painter):**
    * Select a mesh instance or material in the **RTX Remix Toolkit**.
    * In Painter: `Python` > `RemixConnector` > `Pull Selected Remix Asset`.
    * ✨ A new Painter project is created, linked to the Remix asset.
2.  **Import Textures:**
    * In the new Painter project: `Python` > `RemixConnector` > `Import Textures from Remix`.
    * 🖼️ Textures appear in your shelf (Assets > Your Project) and are hopefully assigned.
3.  **Paint:** 🎨
    * Perform your texturing work.
4.  **Push (Painter -> Remix):**
    * Ready to send back to Remix? `Python` > `RemixConnector` > `Push Textures to Remix`.
    * 🚀 Your textures (exported using PBR Met/Rough) are sent, ingested, applied, and saved in Remix.

*(Remember: This is v0.1, so please report any bugs or issues you encounter!)*

---

## Need Help? (Troubleshooting)

Having trouble? Check the [**Detailed README**](README.md#troubleshooting) for common issues and solutions, like:

* Missing Python libraries (`Pillow`, `requests`)
* Incorrect `texconv.exe` path
* Connection errors to Remix API
* Path resolution problems
* Textures not assigning automatically
* Push/Ingest errors

---

## Dependencies & Thanks

This relies on: Python, Pillow, requests, DirectXTex, and the APIs from Adobe and NVIDIA. Check the [**Detailed README**](README.md#dependencies-and-credits) for links and licenses.

---

## Contributing

Got ideas or found a bug? Feel free to open an issue or submit a pull request.

---

## License

Licensed under the **MIT License**. See `LICENSE.md` for the full text.

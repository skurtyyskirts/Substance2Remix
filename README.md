    # Substance Painter <> RTX Remix Connector

    This Python script acts as a plugin for Adobe Substance 3D Painter, facilitating a workflow connection with the NVIDIA RTX Remix Toolkit/Runtime. It allows users to:

    *   **Pull Assets:** Create a new Painter project based on the currently selected mesh and material in RTX Remix.
    *   **Import Textures:** Automatically import textures associated with the linked Remix material into the Painter project (includes DDS -> PNG conversion).
    *   **Push Textures:** Export textures from Painter and update the linked material in RTX Remix via the Remix API.

    **Features:**

    *   Links Painter projects to specific Remix materials via metadata.
    *   Resolves relative mesh/texture paths from Remix using project structure context.
    *   Uses `texconv.exe` for DDS to PNG conversion on import (with fallback to direct DDS).
    *   Programmatic texture export from Painter based on configured settings.
    *   Texture ingestion and material updates via the RTX Remix HTTP API.
    *   Dynamic discovery of target USD material attributes during push.
    *   Configurable settings within the `core.py` script.

    **Requirements:**

    *   **Software:**
        *   Adobe Substance 3D Painter 
        *   NVIDIA RTX Remix Toolkit/Runtime (with the HTTP API enabled at `http://localhost:8011`)
        *   Python 3.x (as provided by Substance Painter)
    *   **Python Libraries:**
        *   `Pillow`: For potential image operations.
        *   `requests`: For communicating with the Remix API.
    *   **External Tools:**
        *   `texconv.exe`: From the [Microsoft DirectXTex library](https://github.com/microsoft/DirectXTex). Required for DDS conversion during texture import.

    **Installation:**

    1.  **Place the Script:** Copy the `core.py` file into your Substance Painter Python plugins directory. You can typically find this via `Painter > Python > Plugins Folder`.
    2.  **Install Python Libraries:**
        *   The script will log instructions if `Pillow` or `requests` are missing when Painter starts.
        *   You need to install them into Painter's specific Python environment. Open a Command Prompt (cmd) and run the commands similar to those logged by the script (adjust paths as necessary):
            ```bash
            # Find Painter's python.exe (e.g., C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\pythonsdk\python.exe)
            "<path_to_painter_python.exe>" -m pip install --upgrade --target="<path_to_painter_python_site-packages>" Pillow requests
            ```
        *   Restart Substance Painter after installation.
    3.  **Install `texconv.exe`:**
        *   Download or build the [DirectXTex library](https://github.com/microsoft/DirectXTex).
        *   Locate `texconv.exe` (often found in a `bin` subfolder after building or downloading releases).
        *   Copy `texconv.exe` to a location of your choice.
    4.  **Configure the Script:**
        *   Open `core.py` in a text editor.
        *   Modify the `PLUGIN_SETTINGS` dictionary near the top:
            *   `"texconv_path"`: Set this to the **full, absolute path** where you placed `texconv.exe`. (e.g., `"C:\\Tools\\DirectXTex\\texconv.exe"`)
            *   `"painter_export_path"`: Set the directory where Painter should export textures *to* during the Push action.
            *   `"painter_import_template_path"` (Optional): Path to an `.spt` template to use when creating projects via the Pull action.
            *   Review other settings like `"api_base_url"`, `"remix_output_subfolder"`, etc.

    **Usage:**

    1.  **Link Asset (Pull):**
        *   In RTX Remix, select the *mesh* and/or *material* prim you want to work on.
        *   In Substance Painter, go to `Python > RemixConnector > Pull Selected Remix Asset`.
        *   This creates a new Painter project using the selected mesh and stores a link to the Remix material.
    2.  **Import Textures:**
        *   With the linked project open in Painter, go to `Python > RemixConnector > Import Textures`.
        *   The script queries Remix for textures linked to the material, converts DDS files to PNG (using `texconv.exe`), imports them into Painter, and attempts to assign them to the correct channels.
        *   *(Note: Automatic channel assignment requires a compatible Painter API version).*
    3.  **Work in Painter:**
        *   Edit your textures as desired.
    4.  **Update Remix (Push):**
        *   When ready, go to `Python > RemixConnector > Push Textures to Remix`.
        *   The script exports textures (as PNGs) based on `PLUGIN_SETTINGS`, ingests them into Remix via the API (converting them back to DDS/RTEX.DDS), discovers the correct material attributes dynamically, updates the material inputs, and requests Remix to save the changes.

    **Dependencies and Credits:**

    This script utilizes several open-source libraries and relies on specific software APIs.

    *   **Python:** ([Python Software Foundation License](https://docs.python.org/3/license.html)) - The core language.
    *   **Pillow:** ([HPND License](https://github.com/python-pillow/Pillow/blob/main/LICENSE)) - Used for image handling. Project: [python-pillow/Pillow](https://github.com/python-pillow/Pillow)
    *   **requests:** ([Apache License 2.0](https://github.com/psf/requests/blob/main/LICENSE)) - Used for HTTP API communication. Project: [psf/requests](https://github.com/psf/requests)
    *   **DirectXTex (`texconv.exe`):** ([MIT License](https://github.com/microsoft/DirectXTex/blob/main/LICENSE)) - Used for DDS texture conversion. Project: [microsoft/DirectXTex](https://github.com/microsoft/DirectXTex)
    *   **Substance Painter API:** Provided by Adobe. Usage subject to Adobe's terms.
    *   **RTX Remix API:** Provided by NVIDIA. Usage subject to NVIDIA's terms.

    **License:**

    This project (`RemixSubstance` connector script) is licensed under the `MIT License`. See the `LICENSE` file for details.
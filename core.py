# -*- coding: utf-8 -*-

"""
Substance Painter Plugin: RTX Remix Connector - Core Logic (core.py)

Contains functions for API communication, settings, workflow handlers, etc.

Version 40.14: Implemented dynamic USD attribute path discovery during push.
               Removed reliance on static PBR_TO_MDL_INPUT_MAP for push.
Version 40.13: Parallelized DDS conversion during import using concurrent.futures.
Version 39.12.3: Corrected indentation error in handle_push_to_remix (line 614).
Version 39.12.2: Corrected export map structure (srcMapName fix for ValueError).
Version 39.12.1: Corrected export map structure for programmatic export (ValueError fix).
Version 39.12: Added explicit export map definitions to handle API preset issues.
Version 39.11: Added placeholder handle_settings function to resolve AttributeError during UI init.
Version 39.10 (Programmatic Export): Reverted to programmatic export trigger.
                     Configures export path, template, format
                     via PLUGIN_SETTINGS. Uses suffix-based
                     filename mapping on export results.
# ... (rest of previous version history) ...
"""

# --- Future Imports (Keep this at the very top) ---
from __future__ import annotations # Allows use of newer type hint syntax (like str | None) in older Python 3 versions

# --- Standard Python Imports ---
import os
import json
import sys
import time # Keep for potential future use
import traceback
import urllib.parse
import ntpath
import tempfile # Keep for potential use elsewhere, though not for push export path
import shutil # Keep for potential use elsewhere
import re # Import regex for path manipulation
import subprocess # Added for running external tools
# import concurrent.futures # Added for parallel DDS conversion (v40.13) - REMOVED in manual edit

# --- Pillow Import (for PNG Alpha Handling) ---
try:
    from PIL import Image, UnidentifiedImageError, __version__ as PIL_VERSION # Import version too
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    PIL_VERSION = "Not Installed"
    # Define dummy classes if Pillow is not available to avoid errors later
    class Image:
        @staticmethod
        def open(path): raise ImportError("Pillow library is not installed.")
    class UnidentifiedImageError(Exception): pass
# --- End Pillow Import ---

# --- Substance Painter API Imports ---
import substance_painter.logging
import substance_painter.project
import substance_painter.export
import substance_painter.resource # Needed for resource usage enum and ResourceID
import substance_painter.textureset # Needed for TextureSet, Channel, Stack, ChannelType types
import _substance_painter.textureset # Import the internal module directly (Use with caution)

# --- FIX START (v38.2): Import specific export types ---
try:
    from substance_painter.export import TextureExportResult, ExportStatus
except ImportError:
    # Define dummy types if import fails (older Painter versions might not have these)
    substance_painter.logging.warning("[RemixConnector Core] Could not import TextureExportResult or ExportStatus. Export might fail if API relies on them.")
    TextureExportResult = type('TextureExportResult', (object,), {})
    # Define a dummy ExportStatus enum-like class
    class ExportStatus: Success = "success" # Assume older versions used string status
# --- FIX END ---


# --- Import specific types with checks ---
_set_channel_texture_resource_func = None # Variable to hold the function if it exists
try:
    # Import specific types if available for type hinting (optional but good practice)
    from substance_painter.textureset import TextureSet, Channel, Stack, ChannelType, Resolution
    # --- FIX START (v38.6 / v39.5): Import set_channel_texture_resource conditionally ---
    if hasattr(substance_painter.textureset, 'set_channel_texture_resource'):
        from substance_painter.textureset import set_channel_texture_resource
        _set_channel_texture_resource_func = set_channel_texture_resource # Store the function
        substance_painter.logging.debug("[RemixConnector Core] Found and imported 'set_channel_texture_resource'.") # Keep debug here as it's guarded
    else:
        substance_painter.logging.warning("[RemixConnector Core] 'set_channel_texture_resource' function not found in substance_painter.textureset module. Texture assignment will require manual steps.")
    # --- FIX END ---
    # Import Resource and ResourceID from resource module
    # Removed ResourceIdentifier import (v39.7)
    from substance_painter.resource import Resource, ResourceID
except ImportError as e:
    substance_painter.logging.error(f"[RemixConnector Core] Failed during core API import: {e}. Some functionality might be limited.")
    # Define dummy types if import fails, so type hints don't break execution
    TextureSet = type('TextureSet', (object,), {})
    Channel = type('Channel', (object,), {})
    Stack = type('Stack', (object,), {})
    ChannelType = type('ChannelType', (object,), {}) # Add dummy ChannelType
    Resolution = type('Resolution', (object,), {}) # Add dummy Resolution
    Resource = type('Resource', (object,), {}) # Add dummy Resource
    ResourceIdentifier = type('ResourceIdentifier', (object,), {}) # Keep dummy for safety
    ResourceID = type('ResourceID', (object,), {}) # Add dummy ResourceID


try:
    import substance_painter.ui
    ui_available = True
except ImportError:
    substance_painter.logging.warning("[RemixConnector Core] substance_painter.ui module not available.")
    ui_available = False

# --- Third-Party Imports ---
try:
    import requests
    requests_available = True
except ImportError:
    requests = None
    requests_available = False
    substance_painter.logging.warning("[RemixConnector Core] 'requests' library not initially found during core module load.")

# ==============================================================================
# Configuration
# ==============================================================================
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"
# --- Default Ingest API Endpoint (v40.12 - Reverting to base queue endpoint / vNEXT - Restoring /material suffix) ---
REMIX_INGEST_API_URL = f"{DEFAULT_REMIX_API_BASE_URL}/ingestcraft/mass-validator/queue/material"
# --- Default Path for Painter Exports (v39.10) ---
# This is where the script will EXPORT textures TO before ingest.
DEFAULT_PAINTER_EXPORT_PATH = r"C:\\Users\\skurtyy\\Documents\\Adobe\\Adobe Substance 3D Painter\\export" # Default based on user image
# ---

PAINTER_CHANNEL_TO_REMIX_PBR_MAP = {
    # Painter Channel Suffix (lowercase) -> Remix PBR Type
    "basecolor": "albedo",
    "base_color": "albedo",
    "albedo": "albedo",
    "diffuse": "albedo",
    "normal": "normal",
    "height": "height",
    "displacement": "height",
    "roughness": "roughness",
    "metallic": "metallic",
    "metalness": "metallic",
    "emissive": "emissive",
    "emission": "emissive",
}
# Create reverse map for texture import (Remix PBR Type -> Painter Channel Name)
# Prioritize common Painter names. Handle variations. Normalize keys to lowercase.
REMIX_PBR_TO_PAINTER_CHANNEL_MAP = {
    "albedo": "baseColor", # Common Painter channel name
    "normal": "normal",
    "height": "height",
    "roughness": "roughness",
    "metallic": "metallic",
    "emissive": "emissive",
}

# Map the string channel names used above to the actual ChannelType enum members
# This map assumes the ChannelType enum is available via substance_painter.textureset.ChannelType
PAINTER_STRING_TO_CHANNELTYPE_MAP = {} # Initialize empty
try:
    if 'ChannelType' in locals() and hasattr(substance_painter.textureset, 'ChannelType'):
        PAINTER_STRING_TO_CHANNELTYPE_MAP = {
            "baseColor": substance_painter.textureset.ChannelType.BaseColor,
            "height": substance_painter.textureset.ChannelType.Height,
            "normal": substance_painter.textureset.ChannelType.Normal,
            "roughness": substance_painter.textureset.ChannelType.Roughness,
            "metallic": substance_painter.textureset.ChannelType.Metallic,
            "emissive": substance_painter.textureset.ChannelType.Emissive,
            # Add other potential mappings if needed
        }
        # Use log_info here to avoid potential AttributeError on older versions (v39.7)
        substance_painter.logging.info("[RemixConnector Core] Successfully created PAINTER_STRING_TO_CHANNELTYPE_MAP.")
    else:
         substance_painter.logging.error("[RemixConnector Core] Cannot create PAINTER_STRING_TO_CHANNELTYPE_MAP. ChannelType enum not available.")
except AttributeError as e:
    # This might still fail if ChannelType itself is missing attributes
    substance_painter.logging.error(f"[RemixConnector Core] Failed to create PAINTER_STRING_TO_CHANNELTYPE_MAP. Error accessing ChannelType attributes: {e}")
except Exception as e:
     substance_painter.logging.error(f"[RemixConnector Core] Unexpected error creating PAINTER_STRING_TO_CHANNELTYPE_MAP: {e}")


PBR_TO_REMIX_SHADER_INPUT_TYPE_MAP = {
    "albedo": "DIFFUSE", "normal": "NORMAL_DX", "height": "HEIGHT",
    "roughness": "ROUGHNESS", "metallic": "METALLIC", "emissive": "EMISSIVE",
}
PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP = {
    "albedo": "DIFFUSE", "normal": "NORMAL_DX", "height": "HEIGHT",
    "roughness": "ROUGHNESS", "metallic": "METALLIC", "emissive": "EMISSIVE",
    "ao": "AO", "opacity": "OPACITY", # Add mappings for AO and Opacity if needed
}
# Map common suffixes found in Remix texture attribute names to PBR types
# Keys should be lowercase
REMIX_ATTR_SUFFIX_TO_PBR_MAP = {
    "diffuse_texture": "albedo",
    "albedo_texture": "albedo",
    "normalmap_texture": "normal",
    "normal_texture": "normal",
    "heightmap_texture": "height",
    "height_texture": "height",
    "roughness_texture": "roughness",
    "metallic_texture": "metallic",
    "metalness_texture": "metallic",
    "emissive_mask_texture": "emissive", # Common naming convention
    "emissive_texture": "emissive",
    "reflectionroughness_texture": "roughness", # Another common name
    # Add more suffixes if encountered
}

# --- START ADD: Define PBR to MDL Input Name Mapping ---
# This map is used to construct the final USD attribute path (e.g., ".inputs:diffuse_texture")
# Keys should be lowercase PBR types. Values are the corresponding MDL input names.
PBR_TO_MDL_INPUT_MAP = {
    "albedo": "diffuse_texture",
    "normal": "normalmap_texture", # Common MDL name for tangent space normals
    "height": "height_texture",
    "roughness": "reflectionroughness_texture", # Common MDL name for roughness
    "metallic": "metallic_texture",
    "emissive": "emissive_mask_texture", # Often used for emissive modulation
    # Add other common maps if needed, ensure they match the target Remix shader inputs
    # "ao": "ambient_occlusion_texture", # Example if AO is used directly
    "opacity": "opacity_texture", # Example if opacity is used
}
# --- END ADD ---

PLUGIN_SETTINGS = {
    "api_base_url": DEFAULT_REMIX_API_BASE_URL,
    # --- Settings for Programmatic Export (v39.10) ---
    "painter_export_path": DEFAULT_PAINTER_EXPORT_PATH, # Where the script exports textures *to*
    "painter_export_preset": "PBR Metallic Roughness", # Template name to use for export (Name MUST EXIST IN PAINTER if not defined below)
    "export_file_format": "png", # File format (should be png)
    "export_padding": "infinite", # Padding algorithm
    "export_filename_pattern": "$mesh_$textureSet_$channel", # Expected filename pattern from template
    # --- Settings for Project Creation (Pull) ---
    "painter_import_template_path": r"C:\\Users\\skurtyy\\Documents\\Adobe\\Adobe Substance 3D Painter\\assets\\templates\\cheese.spt", # Optional path to .spt template for project creation
    # --- General Settings ---
    "poll_timeout": DEFAULT_POLL_TIMEOUT_SECONDS,
    "poll_interval": DEFAULT_POLL_INTERVAL_SECONDS,
    "log_level": "info", # Default log level (options: debug, info, warning, error)
    "remix_output_subfolder": "Textures/PainterConnector_Ingested", # Subfolder within Remix project's *ingested* assets dir (v40.7)
    # --- texconv.exe Path (Used by Import action) ---
    "texconv_path": r"C:\Users\skurtyy\Documents\MyScripts\texconv.exe",
}

# ==============================================================================
# Logging Setup (CORRECTED ORDER)
# ==============================================================================
_logger = substance_painter.logging # Use the standard Painter logger

# --- Define Logging Helper Functions FIRST ---
def log_debug(message):
    """Logs a debug message if the level is set correctly."""
    # Attempt to use info if debug level doesn't exist or causes issues
    if PLUGIN_SETTINGS["log_level"] in ["debug"]:
        if hasattr(_logger, 'debug'):
             _logger.debug(f"[RemixConnector DEBUG] {message}")
        else:
             _logger.info(f"[RemixConnector DEBUG-Fallback] {message}") # Fallback to info

def log_info(message):
    """Logs an info message if the level is set correctly."""
    if PLUGIN_SETTINGS["log_level"] in ["debug", "info"]:
         _logger.info(f"[RemixConnector INFO] {message}")

def log_warning(message):
    """Logs a warning message if the level is set correctly."""
    if PLUGIN_SETTINGS["log_level"] in ["debug", "info", "warning"]:
         _logger.warning(f"[RemixConnector WARN] {message}")

def log_error(message, exc_info=False):
    """Logs an error message."""
    log_message = f"[RemixConnector ERROR] {message}"
    if exc_info:
        tb_str = traceback.format_exc()
        log_message += f"\nTraceback:\n{tb_str}"
    # Use info level if error level doesn't exist (older Painter versions)
    if hasattr(_logger, 'error'):
         _logger.error(log_message)
    else:
        _logger.info(log_message) # Fallback to info

# --- Define Dependency Check Helpers SECOND ---
def get_painter_python_executable():
    """Attempts to find the correct python.exe for Painter's environment."""
    try:
        # sys.executable might point to the main Painter exe, not python
        painter_install_path = os.path.dirname(sys.executable) # Get Painter exe directory
        # Common relative path to python sdk within painter installation
        python_sdk_path = os.path.join(painter_install_path, "resources", "pythonsdk", "python.exe")
        if os.path.isfile(python_sdk_path):
            return python_sdk_path
        else:
            # Fallback for cases where structure might differ or detection failed
            log_warning("Could not auto-detect Painter's python.exe in standard location.")
            # Provide a common default path as a guess
            default_path = r"C:\Program Files\Adobe\Adobe Substance 3D Painter\resources\pythonsdk\python.exe"
            log_warning(f"Assuming default path (PLEASE VERIFY): {default_path}")
            return default_path
    except Exception as e:
        log_error(f"Error detecting Painter's Python executable: {e}")
        # Return a placeholder or default if detection fails completely
        return r"C:\Path\To\Painter\resources\pythonsdk\python.exe" # Placeholder

def check_pillow_installation():
    """ Check if Pillow is installed and log instructions if not. """
    if PIL_AVAILABLE: # Add the missing 'if' check
        log_info(f"Pillow installed: Yes (Version: {PIL_VERSION})")
        return True
    # If import failed:
    log_warning("--- Pillow Dependency ---")
    log_warning("Pillow installed: No (Required for alpha channel handling during DDS conversion)")
    log_warning("To install Pillow:")
    log_warning("1. Open Windows Command Prompt (cmd).")

    # --- Corrected Path Detection ---
    py_exe = get_painter_python_executable()
    log_warning(f"    (Use Painter's Python found at or near: {py_exe})")
    # --- End Correction ---

    # Determine site-packages path robustly
    site_packages_path = ""
    try:
        py_dir = os.path.dirname(py_exe)
        # Common structures
        potential_paths = [
            os.path.join(py_dir, 'Lib', 'site-packages'),
            os.path.join(py_dir, '..', 'Lib', 'site-packages'), # If py_exe is in Scripts
        ]
        for p in potential_paths:
             if os.path.isdir(p):
                  site_packages_path = p
                  log_debug(f"Found site-packages at: {site_packages_path}")
                  break
        if not site_packages_path:
            # Fallback if standard paths not found
            site_packages_path = os.path.join(py_dir, 'Lib', 'site-packages') # Default guess
            log_warning(f"Could not definitively locate site-packages. Assuming: {site_packages_path}")

    except Exception as e:
        log_error(f"Error determining site-packages path: {e}")
        site_packages_path = os.path.join(os.path.dirname(py_exe), 'Lib', 'site-packages') # Fallback guess
        log_warning(f"Using fallback site-packages path: {site_packages_path}")

    log_warning(f"2. Run command: \"{py_exe}\" -m pip install --upgrade --target=\"{site_packages_path}\" Pillow")
    log_warning("(Restart Substance Painter after installation)")
    log_warning("---")
    return False

# --- Define setup_logging LAST (after its dependencies) ---
def setup_logging():
    """Initializes logging and checks dependencies."""
    # Now log_info and check_pillow_installation are guaranteed to be defined
    log_info(f"Remix Connector logging initialized (Level: {PLUGIN_SETTINGS['log_level']}).")
    check_pillow_installation() # Log Pillow status on startup

# ==============================================================================
# Dependency Check & Setup Helpers (Original position - moved above)
# ==============================================================================
def check_requests_dependency():
    """Checks if the 'requests' library is available, attempting import if needed."""
    global requests_available, requests
    if not requests_available or requests is None:
        try:
            import requests as req_check
            requests = req_check
            requests_available = True
            log_info("'requests' library became available after initial check.")
            return True
        except ImportError:
            log_error("'requests' library not available.")
            python_exe = get_painter_python_executable() # Try to get executable path
            log_error(f"Please install it using: \"{python_exe}\" -m pip install requests")
            requests_available = False
            return False
    return True

# --- get_painter_python_executable is now defined above setup_logging ---
# --- check_pillow_installation is now defined above setup_logging ---

# ==============================================================================
# UI Helper
# ==============================================================================
def display_message_safe(message, msg_type_enum=None):
    """Safely displays a message in Painter UI or logs if UI is unavailable."""
    # --- Add diagnostic logging --- (v40.15)
    is_ui_available = ui_available
    has_display_func = hasattr(substance_painter.ui, 'display_message') if ui_available else False # Avoid hasattr on None
    log_debug(f"display_message_safe: ui_available={is_ui_available}, has_display_func={has_display_func}")
    # --- End diagnostic logging ---

    if is_ui_available and has_display_func:
        try:
            log_debug("display_message_safe: Attempting substance_painter.ui.display_message...") # Log attempt
            # Note: msg_type_enum was removed as it caused issues in older versions
            substance_painter.ui.display_message(str(message))
            log_debug("display_message_safe: substance_painter.ui.display_message call succeeded.") # Log success
        except Exception as e:
            log_warning(f"Failed display UI message: {e}. Logging instead.", exc_info=True) # Add exc_info=True
            log_info(f"UI Fallback: {message}") # Log the original message
    else:
        # Log if UI module or display_message function is unavailable
        log_info(f"UI Fallback (UI not available): {message}")

# ==============================================================================
# Helper Functions (Includes NEW conversion functions)
# ==============================================================================
def safe_basename(path):
    """Safely gets the basename of a path, handling potential errors."""
    if not path: return ""
    try:
        # Ensure path is a string before passing to ntpath
        return ntpath.basename(str(path))
    except Exception as e:
        log_warning(f"safe_basename failed for path '{path}': {e}")
        return str(path) # Return the original path as string on error

# --- START: DDS Conversion Helper Functions (Adapted from DDSImporterPlugin) ---

def convert_dds_to_png(texconv_exe, dds_file, output_png):
    """
    Convert a DDS file to PNG using texconv.
    :param texconv_exe: Path to the texconv executable
    :param dds_file: Path to the input DDS file
    :param output_png: Path to the desired output PNG file (texconv controls actual name)
    :raises RuntimeError: If the texconv command fails or executable not found
    :return: Path to the created PNG file if successful, None otherwise.
    """
    if not texconv_exe or not os.path.isfile(texconv_exe):
        raise RuntimeError(f"texconv executable not found or invalid path in settings: {texconv_exe}")
    if not os.path.isfile(dds_file):
        raise RuntimeError(f"Input DDS file not found: {dds_file}")

    output_dir = os.path.dirname(dds_file) # Save PNG alongside DDS for simplicity
    # Ensure output directory exists (should usually be the case)
    os.makedirs(output_dir, exist_ok=True)

    # Define the expected output path based on texconv's behavior
    expected_output_filename = os.path.splitext(os.path.basename(dds_file))[0] + ".png"
    expected_output_path = os.path.join(output_dir, expected_output_filename)

    command = [
        texconv_exe,
        "-ft", "png",  # Output format
        "-o", output_dir,  # Output directory
        "-y",  # Overwrite existing files without prompting
        "-nologo", # Suppress logo banner,
        dds_file # Input DDS file must be last
    ]
    log_info(f"  Running texconv: {' '.join(command)}")
    try:
        # Use CREATE_NO_WINDOW on Windows to prevent console pop-up
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW # More explicit way

        result = subprocess.run(command, capture_output=True, text=True, check=False, startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore')

        if result.returncode != 0:
            error_message = f"texconv failed with code {result.returncode} for {os.path.basename(dds_file)}.\nStderr: {result.stderr.strip()}\nStdout: {result.stdout.strip()}"
            log_error(error_message) # Log as error
            # Do not raise if file exists (v39.8 - allow fallback)
            if not os.path.exists(expected_output_path):
                 raise RuntimeError(error_message) # Raise only if file truly missing
            else:
                # File exists despite error code? Still treat as failure for conversion.
                log_warning(f"  texconv returned error code {result.returncode}, but output file {expected_output_path} was found? Treating as conversion failure.")
                raise RuntimeError(error_message) # Treat as failure
        else:
            log_info(f"  texconv completed successfully for {os.path.basename(dds_file)}.")
            # Log stdout even on success for potential info
            if result.stdout.strip(): log_debug(f"  texconv stdout: {result.stdout.strip()}")
            # Verify output file exists
            if not os.path.exists(expected_output_path):
                 raise RuntimeError(f"texconv reported success but output PNG not found at expected path: {expected_output_path}")
            return expected_output_path

    except FileNotFoundError:
        raise RuntimeError(f"texconv command failed. Ensure '{texconv_exe}' is a valid path and executable.")
    except Exception as e:
        # Re-raise other exceptions, including the RuntimeError from failed conversion
        raise RuntimeError(f"An error occurred running or processing texconv: {e}")


def make_remix_request_with_retries(method, url, headers=None, json_payload=None, params=None, retries=3, delay=2, timeout=60, verify_ssl=False):
    """
    Sends an HTTP request to the Remix API with retry logic.
    """
    if not check_requests_dependency():
        return {"success": False, "status_code": 0, "data": None, "error": "'requests' library not found."}

    try:
        # Construct the full URL safely
        base_url = PLUGIN_SETTINGS.get("api_base_url", DEFAULT_REMIX_API_BASE_URL).rstrip('/')
        endpoint_url = url.lstrip('/')
        full_url = f"{base_url}/{endpoint_url}"
    except Exception as e:
        log_error(f"Error constructing API URL from base '{PLUGIN_SETTINGS.get('api_base_url', DEFAULT_REMIX_API_BASE_URL)}' and endpoint '{url}': {e}")
        return {"success": False, "status_code": 0, "data": None, "error": "URL construction error."}

    # Set default headers required by Remix API
    base_headers = {'Accept': 'application/lightspeed.remix.service+json; version=1.0'}
    if json_payload is not None and 'Content-Type' not in (headers or {}):
        # Add Content-Type only if sending JSON and not already specified
        base_headers['Content-Type'] = 'application/lightspeed.remix.service+json; version=1.0'

    # Merge base headers with any custom headers provided
    effective_headers = {**base_headers, **(headers or {})}

    log_debug(f"API Request: {method} {full_url}")
    if params: log_debug(f"  Params: {params}")
    if json_payload:
        try:
            # Log payload safely (show more detail, especially on error later)
            payload_str = json.dumps(json_payload, indent=2) # Use indent for readability
            log_debug(f"  Payload:\n{payload_str[:1000]}{'...' if len(payload_str) > 1000 else ''}") # Log more initially
        except Exception:
            log_debug("  Payload: <Cannot serialize payload for logging>") # Handle non-serializable data

    last_error_message = None
    for attempt in range(1, retries + 1):
        log_debug(f"  Attempt {attempt}/{retries}...")
        try:
            response = requests.request(
                method,
                full_url,
                headers=effective_headers,
                json=json_payload,
                params=params,
                timeout=timeout,
                verify=verify_ssl # Pass SSL verification flag
            )
            log_debug(f"  Response Status Code: {response.status_code}")

            response_data = None
            response_text = ""
            try:
                # Try parsing JSON first
                 if response.content: # Check if there's content to parse
                     response_data = response.json()
            except json.JSONDecodeError:
                # If JSON parsing fails, try getting the raw text
                log_debug("  Response is not valid JSON.")
                try:
                     response_text = response.text
                     log_debug(f"  Response (non-JSON text): {response_text[:300]}{'...' if len(response_text) > 300 else ''}")
                except Exception as text_err:
                     # Handle rare cases where even getting text fails
                     response_text = "<Could not decode response text>"
                     log_warning(f"  Could not decode response text: {text_err}")
            except Exception as e:
                # Catch other potential errors during response processing (e.g., network issues reading content)
                log_warning(f"  Error processing response body: {e}")
                response_text = "<Error processing response body>"

            # Check if the request was successful (status code 200-299)
            if 200 <= response.status_code < 300:
                 log_debug("  Request Successful.")
                 # Return JSON data if available, otherwise return text
                 return {
                     "success": True,
                     "status_code": response.status_code,
                     "data": response_data if response_data is not None else response_text,
                     "error": None
                 }
            else:
                # Handle HTTP errors (non-2xx status codes)
                 error_prefix = f"Remix API Error (Status: {response.status_code})"
                 # Use JSON error details if available, otherwise text
                 error_details = response_data if response_data is not None else response_text
                 log_warning(f"  {error_prefix}")
                 details_str = "" # Initialize details_str here
                 try:
                     # Log error details safely
                     if isinstance(error_details, (dict, list)):
                         try:
                              details_str = json.dumps(error_details, indent=2) # Indent error details too
                         except TypeError:
                              details_str = str(error_details) # Fallback if not serializable
                              pass # Ignore if details aren't JSON serializable
                     elif error_details: # Check if it exists before converting to string
                          details_str = str(error_details)

                     if details_str:
                          log_warning(f"    Error Detail:\n{details_str[:1500]}{'...' if len(details_str) > 1500 else ''}") # Log more detail on error
                     else:
                          log_debug("    <No error details available or could not be logged>")

                     # Also log the original payload that caused the error
                     if json_payload:
                         try:
                             payload_error_str = json.dumps(json_payload, indent=2)
                             log_warning(f"    Payload Sent (Causing Error):\n{payload_error_str[:1500]}{'...' if len(payload_error_str) > 1500 else ''}")
                         except Exception:
                             log_warning("    Payload Sent (Causing Error): <Cannot serialize payload for logging>")
                 except Exception as log_e:
                      log_debug(f"    <Error logging details: {log_e}>")

                 # Construct last_error_message *after* logging details
                 last_error_message = f"{error_prefix}: {details_str if details_str else '<No Details>'}"

                 # Don't retry client errors (4xx) as they usually indicate a bad request
                 if 400 <= response.status_code < 500:
                     log_warning("  Client error (4xx), not retrying.")
                     return {"success": False, "status_code": response.status_code, "data": error_details, "error": last_error_message} # Return constructed message

        except requests.exceptions.Timeout:
            log_warning(f"  Attempt {attempt}/{retries} Timed out after {timeout} seconds.")
            last_error_message = "Request Timeout"
            if attempt == retries: return {"success": False, "status_code": 0, "data": None, "error": last_error_message}
        except requests.exceptions.ConnectionError as e:
            log_warning(f"  Attempt {attempt}/{retries} ConnectionError: {e}.")
            last_error_message = "Connection Error"
            if attempt == retries: return {"success": False, "status_code": 0, "data": None, "error": last_error_message}
            time.sleep(delay * 2) # Wait longer after connection errors
            continue # Skip standard delay
        except requests.exceptions.RequestException as e:
            # Catch other general request exceptions
            log_error(f"  Attempt {attempt}/{retries} RequestException: {e}", exc_info=True)
            last_error_message = f"Request Exception: {e}"
            if attempt == retries: return {"success": False, "status_code": 0, "data": None, "error": last_error_message}

        # Wait before the next retry if it wasn't the last attempt and wasn't a 4xx error
        if attempt < retries:
            log_debug(f"  Retrying in {delay} seconds...")
            time.sleep(delay)

    # If all retries failed
    log_error(f"All {retries} API attempts failed for {method} {full_url}.")
    return {"success": False, "status_code": 0, "data": None, "error": last_error_message or f"All {retries} attempts failed."}

# ==============================================================================
# Remix API Interaction Functions (Restored/Included)
# ==============================================================================

def get_remix_project_default_output_dir():
    """Gets the default output directory configured in the Remix project."""
    log_info("Getting Remix project default output directory...")
    url = "/stagecraft/assets/default-directory"
    result = make_remix_request_with_retries('GET', url)

    if result["success"] and isinstance(result.get("data"), dict) and isinstance(result["data"].get("asset_path"), str):
        try:
            default_dir_raw = result["data"]["asset_path"]
            default_dir_abs = os.path.abspath(os.path.normpath(default_dir_raw))
            if not os.path.isabs(default_dir_raw): log_warning(f"Remix returned a relative default directory: '{default_dir_raw}'. Resolved to: '{default_dir_abs}'")
            log_info(f"Found Remix default output directory: {default_dir_abs}")
            if not os.path.isdir(default_dir_abs): log_warning(f"Default output directory path found ({default_dir_abs}) but the directory does not actually exist on disk.")
            return default_dir_abs, None
        except Exception as e: log_error(f"Error processing default directory path '{result['data'].get('asset_path')}'", exc_info=True); return None, f"Could not process path: {e}"
    else:
        err_msg = result['error'] or "Failed to get default directory from API."; log_error(f"Error getting default directory (Status: {result['status_code']}): {err_msg}")
        project_data = make_remix_request_with_retries('GET', "/stagecraft/project/")
        if not project_data["success"] or not project_data.get("data", {}).get("layer_id"): err_msg = "Failed to get default directory. Is an RTX Remix project currently open?"
        return None, err_msg

def get_material_from_mesh(mesh_prim_path):
    """Finds the USD material prim bound to a given mesh prim path."""
    log_info(f"Attempting to find material bound to mesh: {safe_basename(mesh_prim_path)}")
    if not mesh_prim_path: return None, "Mesh prim path cannot be empty."
    try:
        # Ensure forward slashes and proper encoding for the API path segment
        encoded_mesh_path = urllib.parse.quote(mesh_prim_path.replace(os.sep, '/'), safe='/'); # Keep slashes
        get_material_url = f"/stagecraft/assets/{encoded_mesh_path}/material";
        log_debug(f"Querying material URL: {get_material_url}")
        result = make_remix_request_with_retries('GET', get_material_url)
        if result["success"] and isinstance(result.get("data"), dict) and isinstance(result["data"].get("asset_path"), str):
            material_path = result["data"]["asset_path"].replace('\\', '/'); log_info(f"Found bound material: {material_path}"); return material_path, None
        else:
            err = result['error'] or "Query failed"; sts = result['status_code']
            if sts == 404: log_info(f"No direct material binding found for mesh '{safe_basename(mesh_prim_path)}'."); return None, f"No material bound to mesh '{safe_basename(mesh_prim_path)}'."
            else: log_error(f"Error querying bound material for '{safe_basename(mesh_prim_path)}' (Status: {sts}): {err}"); return None, f"Failed to query bound material (Status: {sts}): {err}"
    except Exception as e: log_error(f"Exception querying bound material for '{safe_basename(mesh_prim_path)}'", exc_info=True); return None, f"Exception during material query: {e}"

def _get_mesh_file_path_from_prim(prim_path_to_query):
    """Internal helper to query asset file paths and extract the first mesh file path and a potential context path."""
    if not prim_path_to_query: return None, None, "Prim path is empty.", 0
    log_info(f"Querying file paths associated with prim: '{prim_path_to_query}'..."); mesh_file_path = None; context_abs_path = None; error_message = None; status_code = 0
    try:
        encoded_prim_path = urllib.parse.quote(prim_path_to_query.replace(os.sep, '/'), safe='/'); # Keep slashes
        file_paths_url = f"/stagecraft/assets/{encoded_prim_path}/file-paths"; log_debug(f"Querying file paths URL: {file_paths_url}")
        paths_result = make_remix_request_with_retries('GET', file_paths_url); status_code = paths_result.get('status_code', 0)
        if paths_result.get("success") and isinstance(paths_result.get("data"), dict):
            reference_data = paths_result["data"]; potential_paths_data = []
            # Prioritize 'reference_paths' if it exists
            if "reference_paths" in reference_data and isinstance(reference_data["reference_paths"], list): potential_paths_data = reference_data["reference_paths"]
            elif "asset_paths" in reference_data and isinstance(reference_data["asset_paths"], list): log_warning(f"API response missing 'reference_paths', checking 'asset_paths' for '{prim_path_to_query}'."); potential_paths_data = reference_data["asset_paths"]
            log_debug(f"Potential paths data found for '{prim_path_to_query}': {potential_paths_data}")

            for entry in potential_paths_data:
                actual_file_list = []; temp_context_path = None
                # Handle different possible list structures in the response
                if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[1], list):
                    # Format like ['/Prim/Path', ['file1.usd', 'file2.png']]
                    # Use the first element as potential context if it's a path
                    if isinstance(entry[0], str) and os.path.isabs(entry[0]): temp_context_path = os.path.normpath(entry[0])
                    actual_file_list = entry[1]
                elif isinstance(entry, list) and all(isinstance(item, str) for item in entry):
                    # Format like ['file1.usd', 'file2.png']
                    actual_file_list = entry
                elif isinstance(entry, str):
                    # Format like 'file1.usd'
                    actual_file_list = [entry]

                log_debug(f"  Checking file list: {actual_file_list}, Context hint: {temp_context_path}")
                for file_path_to_check in actual_file_list:
                    if isinstance(file_path_to_check, str):
                        # Update context path if we find an absolute path within the list
                        if not temp_context_path and os.path.isabs(file_path_to_check): temp_context_path = os.path.normpath(file_path_to_check); log_debug(f"  Found potential context path within list: {temp_context_path}")
                        # Check if it looks like a mesh file
                        if any(file_path_to_check.lower().endswith(ext) for ext in ['.usd', '.usda', '.usdc', '.obj', '.fbx', '.gltf', '.glb']):
                            mesh_file_path = file_path_to_check.replace('\\', '/'); log_info(f"Found mesh file path via file-paths endpoint for '{prim_path_to_query}': {mesh_file_path}"); # Use the most recently found absolute path as context
                            context_abs_path = temp_context_path
                            if context_abs_path: log_info(f"Associated context path: {context_abs_path}")
                            break # Found a mesh, stop checking this list
                if mesh_file_path: break # Found a mesh, stop checking entries
            if not mesh_file_path: log_warning(f"Could not find a recognizable mesh file path in data returned for '{prim_path_to_query}'. Data: {potential_paths_data}"); error_message = f"No mesh file path found in file paths for '{prim_path_to_query}'."
        else: err = paths_result.get('error', "Failed to get file paths from API."); log_error(f"Failed query file paths for '{prim_path_to_query}' (Status: {status_code}): {err}"); error_message = f"Failed get file paths for '{prim_path_to_query}' (Status: {status_code}): {err}"
    except Exception as e: log_error(f"Exception during file path query for '{prim_path_to_query}'", exc_info=True); error_message = f"Exception during file path query: {e}"; status_code = 0
    return mesh_file_path, context_abs_path, error_message, status_code

def _extract_definition_path(prim_path: str) -> str | None:
    """Extracts a potential base mesh definition path from an instance or suffixed path."""
    if not prim_path: return None
    prim_path = prim_path.replace('\\', '/'); # Pattern for instances like /Root/Stuff/instances/inst_HASH_NUM/mesh
    instance_pattern = r"^(.*)/instances/inst_([A-Z0-9]{16})(?:_[0-9]+)?(?:/.*)?$"
    instance_match = re.match(instance_pattern, prim_path)
    if instance_match:
        base_path = instance_match.group(1); mesh_hash = instance_match.group(2);
        definition_path = f"{base_path}/meshes/mesh_{mesh_hash}";
        log_debug(f"Extracted definition path '{definition_path}' from instance path '{prim_path}'"); return definition_path

    # Pattern for paths already pointing to or within a mesh definition, e.g., /Root/meshes/mesh_HASH/mesh
    suffix_pattern = r"^(.*\/meshes?\/mesh_[A-Z0-9]{16}(?:_[0-9]+)?)(?:\/.*)?$"
    suffix_match = re.match(suffix_pattern, prim_path)
    if suffix_match:
        definition_path = suffix_match.group(1)
        if definition_path != prim_path: log_debug(f"Extracted definition path '{definition_path}' from suffixed path '{prim_path}'"); return definition_path
        else: log_debug(f"Path '{prim_path}' already seems to be a definition path."); return prim_path # Return itself if it matches exactly

    log_debug(f"Could not extract a different definition path from '{prim_path}' using known patterns."); return None # Return None if no pattern matched significantly

def get_selected_remix_asset_details():
    """Gets the mesh file path and material prim path from the current Remix selection."""
    log_info("Getting selected asset details from Remix..."); selection_url = "/stagecraft/assets/"; params = {"selection": "true", "filter_session_assets": "false", "exists": "true"};
    result = make_remix_request_with_retries('GET', selection_url, params=params)
    if not result["success"]: error_msg = result["error"] or "Failed to get selection from Remix API."; log_error(f"Could not get Remix selection (Status: {result['status_code']}): {error_msg}"); return None, None, None, f"Selection Error: {error_msg}"
    asset_paths = result.get("data", {}).get("asset_paths", []) if isinstance(result.get("data"), dict) else [];
    if not asset_paths: log_warning("No assets are currently selected in Remix."); return None, None, None, "No assets selected in Remix."
    log_debug(f"Remix selection raw paths: {asset_paths}"); material_prim = None; mesh_prim = None; shader_prim = None

    # Identify potential material, mesh, and shader prims from selection
    for p in asset_paths:
        path_norm = p.replace('\\', '/'); # Prioritize Shader selection for material context
        if path_norm.endswith("/Shader"):
            if not shader_prim: shader_prim = path_norm; log_info(f"Identified Shader prim: {shader_prim}");
            if not material_prim: material_prim = path_norm[:-len("/Shader")]; log_info(f"Using parent Material from Shader: {material_prim}"); continue # Found shader, implies material
        # Identify Material prims
        if ("/Looks/" in path_norm or "/materials/" in path_norm or "/Material/" in path_norm) and not path_norm.endswith("/Mesh") and "/PreviewSurface" not in path_norm:
            if not material_prim: material_prim = path_norm; log_info(f"Identified Material prim: {material_prim}"); continue
        # Identify Mesh instance prims
        if "/instances/inst_" in path_norm and (path_norm.endswith("/mesh") or path_norm.endswith("/Mesh")):
            if not mesh_prim: mesh_prim = path_norm; log_info(f"Identified Mesh INSTANCE prim: {mesh_prim}")
        # Identify Mesh definition/other prims
        elif ("/meshes/" in path_norm or "/Mesh/" in path_norm or "/Geom/" in path_norm):
             if not mesh_prim: mesh_prim = path_norm; log_info(f"Identified Mesh DEFINITION/OTHER prim: {mesh_prim}")

    # If only Mesh was selected, try to find its bound material
    if not material_prim and mesh_prim:
        log_info(f"Only Mesh prim '{mesh_prim}' selected/identified, attempting to find its bound material..."); # Use the definition path for material lookup if possible
        path_for_mat_lookup = _extract_definition_path(mesh_prim) or mesh_prim; log_debug(f"Using path '{path_for_mat_lookup}' for material lookup.");
        material_prim, err_msg = get_material_from_mesh(path_for_mat_lookup)
        if err_msg: log_error(f"Mesh was selected, but failed to find its bound material: {err_msg}"); return None, None, None, f"Mesh selected, but failed to find its material: {err_msg}"
        if material_prim: log_info(f"Found material '{material_prim}' bound to the selected/derived mesh path.")
        else: log_error(f"Mesh was selected, get_material_from_mesh succeeded but returned no path for '{path_for_mat_lookup}'."); return None, None, None, f"Mesh selected, could not resolve material for '{path_for_mat_lookup}'."
    # If still no material identified (e.g., only non-mesh/mat prim selected), fail
    if not material_prim: log_error(f"Could not identify a usable Material/Shader prim from the selection: {asset_paths}"); return None, None, None, "No recognized Material or Shader prim was selected or found linked to the selected mesh."
    # Now find the mesh file path using various strategies
    mesh_file_path = None; context_abs_path = None; last_query_error = "Mesh file path query not attempted."; paths_tried = set(); prim_to_query = mesh_prim # Start with the identified mesh prim if any

    # Strategy 1: Query the identified mesh prim directly
    if prim_to_query:
        log_debug(f"Attempting mesh file path query on initially identified mesh prim: '{prim_to_query}'")
        mesh_file_path, context_abs_path, last_query_error, status_code = _get_mesh_file_path_from_prim(prim_to_query); paths_tried.add(prim_to_query)
        if mesh_file_path: log_info(f"Success (Attempt 1): Found mesh file path via initially identified mesh prim '{prim_to_query}'."); return mesh_file_path, material_prim, context_abs_path, None

    # Strategy 2: If mesh prim query failed, try its extracted definition path
    if not mesh_file_path and mesh_prim:
        mesh_definition_prim = _extract_definition_path(mesh_prim)
        if mesh_definition_prim and mesh_definition_prim not in paths_tried:
            log_info(f"Attempting query on extracted definition path '{mesh_definition_prim}'..."); mesh_file_path, context_abs_path, definition_error, definition_status = _get_mesh_file_path_from_prim(mesh_definition_prim); paths_tried.add(mesh_definition_prim)
            if mesh_file_path: log_info(f"Success (Attempt 2): Found mesh file path via extracted definition path '{mesh_definition_prim}'."); return mesh_file_path, material_prim, context_abs_path, None
            else: last_query_error = definition_error or last_query_error; log_warning(f"Query on definition path '{mesh_definition_prim}' also failed (Status: {definition_status}). Error: {definition_error}")
        elif mesh_definition_prim: log_debug(f"Definition path '{mesh_definition_prim}' already tried or not applicable, skipping.")

    # Strategy 3: Query the material prim as a fallback
    if not mesh_file_path and material_prim not in paths_tried:
        log_info(f"Mesh file path not found via mesh/definition prims. Attempting query on material prim '{material_prim}' as fallback..."); mesh_file_path, context_abs_path, mat_error, mat_status = _get_mesh_file_path_from_prim(material_prim); paths_tried.add(material_prim)
        if mesh_file_path: log_info(f"Success (Attempt 3): Found mesh file path via material prim '{material_prim}'."); return mesh_file_path, material_prim, context_abs_path, None
        else: last_query_error = mat_error or last_query_error; log_warning(f"Query on material prim '{material_prim}' also failed to find mesh file path (Status: {mat_status}). Error: {mat_error}")
    elif material_prim in paths_tried: log_debug(f"Material path '{material_prim}' already tried, skipping final fallback query.")

    # If all strategies fail
    if not mesh_file_path: log_error("Could not determine mesh file path after checking all potential prim paths."); log_debug(f"Paths tried: {paths_tried}"); return None, material_prim, context_abs_path, last_query_error or "Could not determine source mesh file path after all query attempts."
    # Should not be reached if logic is correct, but acts as a safeguard
    log_error("Reached unexpected end of get_selected_remix_asset_details function."); return mesh_file_path, material_prim, context_abs_path, "Unexpected state reached."

# --- START NEW INGEST FUNCTION (v40.8 - API Based Ingest, Fixed for Remix Toolkit API) ---
def ingest_texture_to_remix(pbr_type, texture_file_path, project_output_dir_abs):
    """Ingests a texture file into the Remix project via the ingest API.

    Uses the proper Remix ingest API to process the texture, convert to DDS, and register
    it with Remix so it can be used in materials.

    Args:
        pbr_type (str): The PBR type (e.g., 'albedo', 'normal') - used for API mapping.
        texture_file_path (str): The absolute path to the source texture file (e.g., exported PNG).
        project_output_dir_abs (str): The absolute path to the Remix project's *ingested*
                                      assets directory (e.g., C:/.../LegoBatmanRTX/assets/ingested).

    Returns:
        tuple[str | None, str | None]: (absolute_path_of_ingested_file, None) on success,
                                     (None, error_message) on failure.
    """
    log_info(f"--- Ingesting {pbr_type} texture via API: {safe_basename(texture_file_path)} ---")

    if not os.path.isfile(texture_file_path):
        return None, f"Source file not found: {texture_file_path}"

    # Use forward slashes for API paths
    abs_path_forward_slash = os.path.abspath(texture_file_path).replace(os.sep, '/')
    log_info(f"  Using source path for API: {abs_path_forward_slash}")

    # Map PBR type to Remix Ingest Validation Type
    ingest_validation_type = None
    if pbr_type.lower() == "albedo":
        ingest_validation_type = "DIFFUSE"
    elif pbr_type.lower() == "normal":
        ingest_validation_type = "NORMAL_DX"
    elif pbr_type.lower() == "height":
        ingest_validation_type = "HEIGHT"
    elif pbr_type.lower() == "roughness":
        ingest_validation_type = "ROUGHNESS"
    elif pbr_type.lower() == "metallic":
        ingest_validation_type = "METALLIC"
    elif pbr_type.lower() == "emissive":
        ingest_validation_type = "EMISSIVE"
    elif pbr_type.lower() == "ao":
        ingest_validation_type = "AO"
    elif pbr_type.lower() == "opacity":
        ingest_validation_type = "OPACITY"
    else:
        ingest_validation_type = "DIFFUSE"  # Fallback
        log_warning(f"  No specific ingest validation type found for PBR type '{pbr_type}', falling back to {ingest_validation_type}.")

    log_info(f"  Using ingest validation type: {ingest_validation_type}")

    if not project_output_dir_abs or not os.path.isdir(project_output_dir_abs):
        # Check if it's just missing the 'ingested' part
        potential_ingested_dir = os.path.join(project_output_dir_abs or "", "ingested")
        if os.path.isdir(potential_ingested_dir):
            log_warning(f"Provided project output directory '{project_output_dir_abs}' seems to be missing '/ingested'. Using '{potential_ingested_dir}' instead.")
            project_output_dir_abs = potential_ingested_dir
        else:
            return None, f"Invalid Remix project 'ingested' directory provided or derived: {project_output_dir_abs}"

    # Define the target output directory within the project structure
    output_subfolder = PLUGIN_SETTINGS.get("remix_output_subfolder", "Textures/PainterConnector_Ingested").strip('/\\\\')
    output_directory_forward_slash = os.path.normpath(os.path.join(project_output_dir_abs, output_subfolder)).replace(os.sep, '/')
    log_info(f"  Targeting ingest output directory: {output_directory_forward_slash}")

    # Ensure the target directory exists (create if doesn't exist)
    os.makedirs(output_directory_forward_slash.replace('/', os.sep), exist_ok=True)

    # Construct the ingest API payload
    ingest_payload = {
        "executor": 1,  # Default executor
        "name": f"Ingest_{pbr_type}_{safe_basename(abs_path_forward_slash)}",
        "context_plugin": {
            "name": "TextureImporter",
            "data": {
                "context_name": "ingestcraft_browser",
                "input_files": [[abs_path_forward_slash, ingest_validation_type]],
                "output_directory": output_directory_forward_slash,
                "allow_empty_input_files_list": True,
                "data_flows": [{"name": "InOutData", "push_output_data": True, "channel": "ingestion_output"}],
                "hide_context_ui": True,
                "create_context_if_not_exist": True,
                "expose_mass_ui": False,
                "cook_mass_template": True
            }
        },
        "check_plugins": [
            {"name": "MaterialShaders", "selector_plugins": [{"name": "AllMaterials", "data": {}}], "data": {"shader_subidentifiers": {"AperturePBR_Opacity": ".*"}}, "stop_if_fix_failed": True, "context_plugin": {"name": "CurrentStage", "data": {}}},
            {"name": "ConvertToOctahedral", "selector_plugins": [{"name": "AllShaders", "data": {}}], "data": {"data_flows": [{"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "cleanup_files_normal"}]}, "stop_if_fix_failed": True, "context_plugin": {"name": "CurrentStage", "data": {}}},
            {"name": "ConvertToDDS", "selector_plugins": [{"name": "AllShaders", "data": {}}], "data": {"data_flows": [{"name": "InOutData", "push_output_data": True, "channel": "ingestion_output"}, {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "cleanup_files"}, {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"}]}, "stop_if_fix_failed": True, "context_plugin": {"name": "CurrentStage", "data": {}}}
        ],
        "resultor_plugins": [
            {"name": "FileCleanup", "data": {"channel": "cleanup_files", "cleanup_output": False}},
            {"name": "FileMetadataWritter", "data": {"channel": "write_metadata"}}
        ]
    }

    # Send the request to the specific ingest queue endpoint
    ingest_url = "/ingestcraft/mass-validator/queue/material"
    log_info(f"  Sending ingest request to {ingest_url}")

    try: # --- START Outer Try block ---
        result = make_remix_request_with_retries("POST", ingest_url, json_payload=ingest_payload)

        # --- Process FAILED Response ---
        if not result["success"]:
            err_msg = result["error"] or "Ingestion request failed or produced an error."
            status_code = result.get('status_code', 0)
            error_detail = result.get("data", "")
            detail_str = ""
            if isinstance(error_detail, (dict, list)):
                try: detail_str = json.dumps(error_detail)
                except TypeError: detail_str = str(error_detail)
            elif error_detail: detail_str = str(error_detail)

            full_err_msg = err_msg
            if detail_str: full_err_msg += f": {detail_str[:200]}{'...' if len(detail_str) > 200 else ''}"

            log_error(f"  Ingestion failed for '{safe_basename(texture_file_path)}'. Status: {status_code}, Error: {full_err_msg}")
            # Return error immediately if API request failed
            return None, f"{err_msg} (Status: {status_code})"

        # --- Process SUCCESSFUL Response ---
        ingested_path = None
        try: # Inner try for parsing the success response
            if isinstance(result.get("data"), dict):
                completed_schemas = result["data"].get("completed_schemas", [])
                if completed_schemas:
                    for schema in completed_schemas:
                        if isinstance(schema, dict):
                            for plugin_result in schema.get("check_plugins", []):
                                if isinstance(plugin_result, dict) and plugin_result.get("name") == "ConvertToDDS":
                                    data_content = plugin_result.get("data", {})
                                    if isinstance(data_content, dict):
                                        flows = data_content.get("data_flows", [])
                                        for flow in flows:
                                            if isinstance(flow, dict) and flow.get("channel") == "ingestion_output":
                                                output_data = flow.get("output_data", [])
                                                if output_data and isinstance(output_data, list):
                                                    for out_path in output_data:
                                                        if isinstance(out_path, str) and (out_path.lower().endswith('.dds') or out_path.lower().endswith('.rtex.dds')):
                                                            ingested_path = out_path
                                                            break
                                                if ingested_path: break
                                    if ingested_path: break
                        if ingested_path: break # Found path in a schema

            # Fallback check of top-level content (if not found in schemas)
            if not ingested_path and isinstance(result.get("data", {}).get("content"), list):
                for item in result["data"]["content"]:
                    if isinstance(item, str) and (item.lower().endswith('.dds') or item.lower().endswith('.rtex.dds')):
                        ingested_path = item
                        break
        except Exception as e:
            log_error(f"  Error parsing successful ingest response: {e}", exc_info=True)
            # Return error if parsing failed even though API reported success
            return None, f"Ingest reported success but failed parsing response: {e}"

        if not ingested_path:
            log_error(f"  Ingest succeeded but no output path found in response.")
            # Return error if path not found in successful response
            return None, "Ingest succeeded but no output path found in response."

        # --- Process and normalize the ingested path ---
        try: # Inner try for path normalization
            normalized_ingested_path = None
            if not os.path.isabs(ingested_path):
                # If relative, assume it's relative to the targeted output directory
                joined_path = os.path.join(output_directory_forward_slash.replace('/', os.sep), ingested_path)
                normalized_ingested_path = os.path.normpath(joined_path)
                log_info(f"  API returned relative path '{ingested_path}'. Resolved to: {normalized_ingested_path}")
            else:
                normalized_ingested_path = os.path.normpath(ingested_path)
                log_info(f"  API returned absolute path: {normalized_ingested_path}")

            log_info(f"  Successfully ingested {pbr_type} texture.")
            return normalized_ingested_path, None # Return successful path
        except Exception as e:
            log_error(f"  Error processing ingested path '{ingested_path}': {e}", exc_info=True)
            # Return error if normalization failed
            return None, f"Error processing ingested path: {e}"

    except Exception as e: # --- CATCH block for Outer Try ---
        # Catches errors from API call itself or unexpected issues during payload prep/response handling
        log_error(f"  Error processing ingest request: {e}", exc_info=True)
        return None, f"Error processing ingest request: {e}"
# --- END CORRECTED INGEST FUNCTION ---

def get_example_usd_attribute_path(material_prim):
    """Gets an example texture input attribute path from a material prim."""
    log_info(f"Querying existing texture inputs for material: {safe_basename(material_prim)}")
    if not material_prim: return None, "Material prim path cannot be empty."
    try:
        encoded_material_prim = urllib.parse.quote(material_prim.replace(os.sep, '/'), safe='/'); # Keep slashes
        get_mat_textures_url = f"/stagecraft/assets/{encoded_material_prim}/textures"; log_debug(f"Querying textures URL: {get_mat_textures_url}")
        result = make_remix_request_with_retries('GET', get_mat_textures_url)
        if result["success"] and isinstance(result.get("data"), dict) and isinstance(result["data"].get("textures"), list):
            for entry in result["data"].get("textures", []):
                # Expecting format like ['/path/to/mat/shader.inputs:diffuse_texture', 'path/to/texture.dds']
                if isinstance(entry, list) and len(entry) > 0 and isinstance(entry[0], str) and entry[0]:
                     example_path = entry[0].replace('\\', '/'); log_info(f"Found example attribute path: {example_path}"); return example_path, None
            log_warning(f"No existing texture input attributes found on material '{safe_basename(material_prim)}'. Cannot determine target attributes."); return None, f"No existing texture inputs found for '{safe_basename(material_prim)}'."
        else: err = result['error'] or "Query failed"; sts = result['status_code']; log_error(f"Error querying existing texture inputs for '{safe_basename(material_prim)}' (Status: {sts}): {err}"); return None, f"Failed query existing textures (Status: {sts}): {err}"
    except Exception as e: log_error(f"Exception querying existing texture inputs for '{safe_basename(material_prim)}'", exc_info=True); return None, f"Exception querying existing textures: {e}"

def get_specific_usd_attribute_path(example_usd_attribute_path, target_remix_texture_type):
    """Gets the specific USD attribute path for a target texture type, using an example path."""
    log_info(f"Querying specific attribute path for type '{target_remix_texture_type}' using example '{example_usd_attribute_path}'")
    if not example_usd_attribute_path: return None, "Example attribute path is missing."
    if not target_remix_texture_type: return None, "Target texture type (e.g., DIFFUSE, NORMAL_DX) is missing."
    try:
        # The API endpoint seems to operate on the texture path, not the attribute path directly?
        # Let's assume the example path IS the texture path for this query based on the structure.
        # This might need adjustment based on the actual API.
        encoded_example_texture = urllib.parse.quote(example_usd_attribute_path.replace(os.sep, '/'), safe='/'); # Assuming example path is texture path
        get_inputs_url = f"/stagecraft/textures/{encoded_example_texture}/material/inputs"; # Hypothetical endpoint structure
        query_params = {"texture_type": target_remix_texture_type}; log_debug(f"Querying specific attribute URL: {get_inputs_url} with params: {query_params}")
        result = make_remix_request_with_retries('GET', get_inputs_url, params=query_params)
        if result["success"] and isinstance(result.get("data"), dict) and isinstance(result["data"].get("asset_paths"), list):
            input_prims_found = result["data"]["asset_paths"]
            if input_prims_found and isinstance(input_prims_found[0], str):
                specific_path = input_prims_found[0].replace('\\', '/'); log_info(f"Found specific attribute path for '{target_remix_texture_type}': {specific_path}"); return specific_path, None
            else: log_warning(f"API returned success but no attribute path found for type '{target_remix_texture_type}'. Response data: {result.get('data')}"); return None, f"Attribute path for type '{target_remix_texture_type}' not found in API response."
        else: err = result['error'] or "Query failed"; sts = result['status_code']; log_error(f"Error querying specific attribute path for '{target_remix_texture_type}' (Status: {sts}): {err}"); return None, f"Failed query specific path (Status: {sts}): {err}"
    except Exception as e: log_error(f"Exception querying specific attribute path for '{target_remix_texture_type}'", exc_info=True); return None, f"Exception query specific path: {e}"

def update_remix_texture_input(pbr_type, ingested_asset_abs_path, target_usd_attribute_path, project_output_dir_abs, material_prim):
    try:
        response = requests.post(
            f"{PLUGIN_SETTINGS['api_base_url']}/stagecraft/assets{material_prim}/textures",
            json={
                "attributePath": target_usd_attribute_path,
                "textureFilePath": ingested_asset_abs_path
            }
        )
        if response.status_code == 405:
            log_warning(f"Method Not Allowed (405) for {pbr_type}. Check Remix API endpoint.")
            return False, "Method Not Allowed (405)"
        response.raise_for_status()
        log_info(f"Successfully updated {pbr_type} input '{target_usd_attribute_path}'.")
        return True, None
    except requests.RequestException as e:
        log_error(f"Failed to update {pbr_type} input '{target_usd_attribute_path}'. Error: {e}")
        return False, str(e)

def get_current_edit_target():
    """Gets the file path of the currently targeted USD layer for editing in Remix."""
    log_info("Getting current edit target layer from Remix..."); target_url = "/stagecraft/layers/target"; target_result = make_remix_request_with_retries('GET', target_url); layer_id = None
    if target_result["success"] and isinstance(target_result.get("data"), dict): layer_id = target_result["data"].get("layer_id"); log_debug(f"Layer ID found via /layers/target endpoint: {layer_id}")
    else:
        log_warning(f"Could not get target layer via /layers/target (Status: {target_result['status_code']}, Error: {target_result['error']}). Trying /stagecraft/project/ fallback..."); project_url = "/stagecraft/project/"; project_result = make_remix_request_with_retries('GET', project_url)
        if project_result["success"] and isinstance(project_result.get("data"), dict): layer_id = project_result["data"].get("layer_id"); log_debug(f"Layer ID found via /stagecraft/project/ fallback endpoint: {layer_id}")
        else: err = project_result['error'] or "Failed get project info"; sts = project_result['status_code']; log_error(f"Failed to get target layer via /project fallback (Status: {sts}): {err}"); return None, f"Could not determine current edit layer from Remix: {err}"
    if isinstance(layer_id, str) and layer_id:
        try:
            # Normalize and ensure absolute path
            if not os.path.isabs(layer_id): log_warning(f"API returned a relative layer ID: '{layer_id}'. Attempting to resolve to absolute path."); layer_id_abs = os.path.abspath(os.path.normpath(layer_id))
            else: layer_id_abs = os.path.normpath(layer_id)
            log_info(f"Found current edit target layer: {layer_id_abs}"); return layer_id_abs, None
        except Exception as e: log_error(f"Error processing layer ID '{layer_id}'", exc_info=True); return None, f"Could not process layer path: {e}"
    else: log_warning(f"No active project or edit target found in Remix (layer_id: {layer_id})."); return None, "No active project or edit target layer found in Remix."

def save_remix_layer(layer_id_abs_path):
    """Requests Remix to save the specified layer file."""
    if not layer_id_abs_path: log_error("Save layer failed: Missing layer ID/path."); return False, "Missing layer ID/path."
    log_info(f"Attempting to request save for layer: {layer_id_abs_path}")
    try:
        # Encode the layer path correctly for the URL segment
        encoded_layer_id = urllib.parse.quote(layer_id_abs_path.replace(os.sep, '/'), safe=':/'); url = f"/stagecraft/layers/{encoded_layer_id}/save"; log_debug(f"Save request URL: {url}");
        result = make_remix_request_with_retries('POST', url) # POST request to trigger save

        if not result["success"]: err = result["error"] or "Save request failed."; status = result['status_code']; log_error(f"Failed save layer request for '{layer_id_abs_path}' (Status: {status}). Error: {err}"); return False, f"Failed save request (Status: {status}): {err}"
        status_code = result['status_code']
        if 200 <= status_code < 300: log_info(f"Layer '{layer_id_abs_path}' save request submitted successfully (Status: {status_code})."); return True, None
        else:
            err = result["error"] or f"Save request returned status {status_code}"; err_detail = result.get("data", ""); full_err_msg = f"{err}"; detail_str = ""
            if err_detail:
                if isinstance(err_detail, (dict, list)):
                    try: detail_str = json.dumps(err_detail)
                    except TypeError: pass
                else: detail_str = str(err_detail)
                if detail_str: full_err_msg += f": {detail_str[:200]}{'...' if len(detail_str) > 200 else ''}"
            log_error(f"Failed save layer request for '{layer_id_abs_path}' (Status: {status_code}). Error: {full_err_msg}"); return False, f"Failed save request (Status: {status_code}): {full_err_msg}"
    except Exception as e: log_error(f"Exception during save layer request for '{layer_id_abs_path}'", exc_info=True); return False, f"Exception during save request: {e}"

# --- START NEW FUNCTION (v40.2, Modified v40.3, Reverted v40.4, Adjusted v40.5, v40.6 / vNEXT Corrected Relative Path Logic) ---
def update_remix_textures_batch(textures_to_update: list[tuple[str, str]], project_output_dir_abs: str) -> tuple[bool, str | None]:
    """Updates multiple texture inputs on the Remix material via a single batch API call.
       Uses PUT /stagecraft/textures/
       Uses absolute texture paths with forward slashes for the API payload.
    """
    log_info(f"Attempting batch update for {len(textures_to_update)} textures via PUT /stagecraft/textures/ ...")
    if not textures_to_update:
        log_warning("Batch update skipped: No textures provided in the list.")
        return True, "No textures to update."
    if not project_output_dir_abs:
        log_error("Batch update failed: Project output directory (ingested) absolute path is missing.")
        return False, "Project output dir missing."

    update_payload_textures = []
    path_processing_errors = []

    for target_usd_attr, abs_copied_texture_path in textures_to_update:
        try:
            # Ensure the copied path is absolute
            if not os.path.isabs(abs_copied_texture_path):
                 log_warning(f"  Skipping '{safe_basename(target_usd_attr)}': Copied path '{abs_copied_texture_path}' is not absolute.")
                 path_processing_errors.append(f"PathError-{safe_basename(target_usd_attr)}: Copied path not absolute.")
                 continue

            # Use absolute path directly with forward slashes for the API
            texture_path_for_payload = abs_copied_texture_path.replace(os.sep, '/')

            target_attribute_path_norm = target_usd_attr.replace('\\', '/')
            update_payload_textures.append([target_attribute_path_norm, texture_path_for_payload])
            log_debug(f"  Prepared update pair: Attribute='{target_attribute_path_norm}', AbsolutePath='{texture_path_for_payload}'")
        except Exception as e:
            err_msg = f"Failed to process paths for update payload entry. Attribute: '{target_usd_attr}', CopiedPath: '{abs_copied_texture_path}'"
            log_error(err_msg, exc_info=True)
            path_processing_errors.append(f"PathError-{safe_basename(target_usd_attr)}: {e}")

    if not update_payload_textures:
        if path_processing_errors:
             log_error(f"Batch update failed: Could not prepare any valid texture update entries due to path processing errors: {path_processing_errors}")
             return False, f"Path processing failed for all entries. Errors: {'; '.join(path_processing_errors)}"
        else:
             log_error("Batch update failed: No textures available to prepare for update payload.")
             return False, "No valid textures to update."

    # Construct the final payload
    update_payload = {
        "force": False,
        "textures": update_payload_textures
    }

    log_info(f"Sending batch update request for {len(update_payload_textures)} textures (using absolute paths)...")
    log_debug(f" Batch Update Payload: {json.dumps(update_payload, indent=2)}")

    # Use PUT method and /stagecraft/textures/ endpoint
    result = make_remix_request_with_retries('PUT', '/stagecraft/textures/', json_payload=update_payload)

    if not result["success"]:
        err_msg = result["error"] or "Batch update API request failed."
        status_code = result.get('status_code', 0)
        error_detail = result.get("data", "")
        detail_str = ""
        if isinstance(error_detail, (dict, list)):
             try: detail_str = json.dumps(error_detail)
             except TypeError: detail_str = str(error_detail)
        elif error_detail: detail_str = str(error_detail)
        if detail_str: err_msg += f": {detail_str}"

        log_error(f"Batch texture update failed (Status: {status_code}). Error: {err_msg}")
        # Provide hint for 422 error in this context
        if status_code == 422:
             log_warning(f"    Hint: A 422 error here likely means the absolute texture paths in the payload (like '{update_payload_textures[0][1] if update_payload_textures else 'N/A'}') are incorrect or inaccessible by Remix, or the target USD attributes are wrong.")

        if path_processing_errors:
             err_msg += f" (Path processing errors also occurred: {'; '.join(path_processing_errors)})"
        return False, f"{err_msg} (Status: {status_code})"

    # If successful, report combined status
    success_msg = f"Successfully submitted batch update request for {len(update_payload_textures)} textures."
    if path_processing_errors:
         log_warning(f"{success_msg} However, some path processing errors occurred: {path_processing_errors}")
         return True, f"{success_msg} (With path processing errors: {'; '.join(path_processing_errors)})"
    else:
         log_info(success_msg)
         return True, None
# --- END CORRECTED FUNCTION ---


def handle_pull_from_remix():
    """Handles the 'Pull Selected Remix Asset' action."""
    log_info("="*20 + " PULL FROM REMIX INITIATED " + "="*20)
    pull_errors = []
    if substance_painter.project.is_open():
        log_info("Current Painter project is open. Closing it before creating a new one for pull...")
        try: substance_painter.project.close(); log_info("Current Painter project closed successfully.")
        except Exception as e: log_error(f"Failed to close the current Painter project: {e}", exc_info=True); display_message_safe(f"Error: Failed to close current project: {e}. Aborting pull."); return
    if not check_requests_dependency(): display_message_safe("Pull failed: 'requests' library is missing. Please install it."); return

    log_info("Querying Remix selection details...");
    mesh_file_path, material_prim, context_abs_path, error_msg = get_selected_remix_asset_details()
    if error_msg: log_error(f"Pull failed during selection query: {error_msg}"); display_message_safe(f"Selection Error: {error_msg}"); return
    if not mesh_file_path: log_error("Pull failed: Mesh file path could not be determined from Remix selection."); display_message_safe("Error: Mesh file path not found for selected asset."); return
    if not material_prim: log_error("Pull failed: Material prim path could not be determined from Remix selection."); display_message_safe("Error: Material prim path not found for selected asset."); return

    log_info(f"  Mesh File Path Found (potentially relative): {mesh_file_path}"); log_info(f"  Material Prim Path Found: {material_prim}");
    if context_abs_path: log_info(f"  Context Absolute Path Found: {context_abs_path}")

    original_mesh_path_for_meta = mesh_file_path; absolute_mesh_path_to_use = None

    # Resolve relative mesh path
    if not os.path.isabs(mesh_file_path):
        log_warning(f"Mesh file path '{mesh_file_path}' is relative. Attempting to resolve absolute path..."); resolved_successfully = False
        # Strategy 1: Use context path if available
        if context_abs_path and os.path.isabs(context_abs_path):
            try:
                context_dir = os.path.dirname(context_abs_path); resolved_path_context = os.path.abspath(os.path.join(context_dir, mesh_file_path)); log_info(f"Attempting resolved path using context dir '{context_dir}': {resolved_path_context}")
                if os.path.isfile(resolved_path_context): log_info(f"Successfully resolved absolute mesh path using context: {resolved_path_context}"); absolute_mesh_path_to_use = resolved_path_context; resolved_successfully = True
                else: log_warning(f"Resolved path using context does not exist: {resolved_path_context}")
            except Exception as context_e: log_warning(f"Error attempting to resolve path using context '{context_abs_path}': {context_e}")
        else: log_debug("Context path not available or not absolute, skipping context-based resolution.")

        # Strategy 2: Use Remix project structure if context failed
        if not resolved_successfully:
            log_info("Context path resolution failed or skipped. Trying default output directory, project root, and deps/captures..."); project_output_dir_abs, dir_err = get_remix_project_default_output_dir()
            if dir_err: error_msg = f"Cannot resolve relative mesh path: Failed to get Remix project directory: {dir_err}"; log_error(error_msg); display_message_safe(f"Project Creation Error: {error_msg}"); return

            try:
                project_base_dir = None; project_root_dir = None
                if project_output_dir_abs: project_base_dir = os.path.dirname(project_output_dir_abs);
                if project_base_dir: project_root_dir = os.path.dirname(project_base_dir)

                # Define potential base directories
                possible_bases = []
                if project_root_dir: possible_bases.append(os.path.join(project_root_dir, 'deps', 'captures')); possible_bases.append(project_root_dir)
                if project_base_dir: possible_bases.append(project_base_dir)
                if project_output_dir_abs: possible_bases.append(project_output_dir_abs)
                unique_possible_bases = []; [unique_possible_bases.append(base) for base in possible_bases if base not in unique_possible_bases]
                log_debug(f"Checking project relative bases: {unique_possible_bases}")

                for base_dir in unique_possible_bases:
                     abs_mesh_path_check = os.path.abspath(os.path.join(base_dir, mesh_file_path)); log_info(f"Attempting resolved path using base '{base_dir}': {abs_mesh_path_check}")
                     if os.path.isfile(abs_mesh_path_check): log_info(f"Successfully resolved absolute mesh path using base '{base_dir}': {abs_mesh_path_check}"); absolute_mesh_path_to_use = abs_mesh_path_check; resolved_successfully = True; break
                     else: log_warning(f"Resolved path using base '{base_dir}' does not exist: {abs_mesh_path_check}")

            except Exception as path_e: log_error(f"Error during fallback path resolution: {path_e}", exc_info=True)

        if not resolved_successfully or absolute_mesh_path_to_use is None: error_msg = f"Could not resolve relative mesh path '{mesh_file_path}' to an existing absolute path after checking context and project structure."; log_error(error_msg); display_message_safe(f"Project Creation Error: {error_msg}"); return
    else:
        log_info("Mesh file path is already absolute."); absolute_mesh_path_to_use = os.path.normpath(mesh_file_path) # Normalize just in case

    log_info(f"Creating new Painter project using mesh: {safe_basename(absolute_mesh_path_to_use)}")
    try:
        # Use default workflow (Metallic/Roughness) and DirectX normal format
        project_settings = substance_painter.project.Settings(
            import_cameras=True, # Keep camera import setting
            normal_map_format=substance_painter.project.NormalMapFormat.DirectX,
            # Removed workflow setting to use default (usually Metallic/Roughness)
            # project_workflow=substance_painter.project.ProjectWorkflow.Default # Or specific like MetallicRoughness if needed
            )
        log_info(f"Using project settings: NormalMap=DirectX, Workflow=Default (Texture Set Per UDIM Tile or Material)")

        # Get optional template path from settings
        template_path = PLUGIN_SETTINGS.get("painter_import_template_path")
        create_kwargs = {
            "mesh_file_path": absolute_mesh_path_to_use,
            "settings": project_settings
        }

        if template_path and os.path.isfile(template_path):
            log_info(f"Using project template specified in settings: {template_path}")
            # Remove settings if template is used, as template defines settings
            del create_kwargs["settings"]
            create_kwargs["template_file_path"] = template_path
            log_debug(f"Attempting project create with template: {template_path} and mesh: {absolute_mesh_path_to_use}")
            substance_painter.project.create(**create_kwargs)
        else:
            if template_path:
                log_warning(f"Template path specified ('{template_path}') but file not found. Creating project with default settings instead.")
            else:
                log_info("No project template specified in settings. Creating project with default settings.")
            log_debug(f"Attempting project create with mesh path: {absolute_mesh_path_to_use} and default settings.")
            substance_painter.project.create(**create_kwargs);

        log_info("Painter project created successfully.")
    except Exception as e:
        log_error(f"Failed to create Painter project for mesh '{absolute_mesh_path_to_use}'", exc_info=True)
        if "could not be found" in str(e).lower() or "cannot find the path" in str(e).lower(): display_message_safe(f"Error: Painter could not find mesh file at '{absolute_mesh_path_to_use}'. Check Remix project structure and paths.")
        elif "uv tile" in str(e).lower() or "udim" in str(e).lower() or "split meshes" in str(e).lower(): display_message_safe(f"Error: Mesh UVs incompatible with UV Tile workflow. Try disabling 'Use UV Tile workflow' in project settings if doing this manually. The script should now be using the default workflow.")
        else: display_message_safe(f"Error creating Painter project: {e}")
        return

    log_info(f"Storing Remix metadata link in Painter project...")
    try:
        metadata = substance_painter.project.Metadata("RTXRemixConnectorLink"); metadata.set("remix_material_prim", material_prim);
        metadata.set("remix_mesh_file_path_original", original_mesh_path_for_meta);
        metadata.set("remix_mesh_file_path_resolved", absolute_mesh_path_to_use);
        log_info("Remix metadata stored successfully in project.")
    except Exception as e: log_error(f"Failed to store Remix metadata in Painter project", exc_info=True); pull_errors.append(f"Metadata Error: {e}"); display_message_safe("Warning: Failed to store Remix metadata link in the project. Push might fail later.")

    log_info("="*20 + " PULL COMPLETED " + "="*20); material_name = safe_basename(material_prim) or "Unknown Material"
    if not pull_errors: display_message_safe(f"Successfully pulled asset '{material_name}'. Use 'Import Textures' action to load textures.")
    else: display_message_safe(f"Pull completed with issues (check logs). Asset '{material_name}' loaded. Use 'Import Textures' action.")

def handle_import_textures():
    """Imports textures from the linked Remix material into the current Painter project.
        Attempts DDS->PNG conversion via texconv.exe first.
        If texconv fails, falls back to importing the original DDS directly.
        Checks if the assignment API function exists before calling it.
        Handles older Painter API returning Resource objects from import.
    """
    log_info("="*20 + " IMPORT TEXTURES INITIATED (v39.8 - Texconv Fallback) " + "="*20)
    import_texture_errors = []
    textures_imported_count = 0
    textures_assigned_count = 0
    texture_list = []
    texconv_path = PLUGIN_SETTINGS.get("texconv_path") # Get configured path
    api_assign_func_available = _set_channel_texture_resource_func is not None # Check if function was stored

    try:
        # --- Initial Setup (Get Metadata, Project Dirs, Target TextureSet) ---
        if not substance_painter.project.is_open(): raise Exception("Project Error: No Painter project is currently open.")
        if not check_requests_dependency(): raise Exception("Dependency Error: 'requests' library missing.")

        material_prim = None; log_info("Retrieving Remix link metadata from current Painter project...")
        try:
            metadata = substance_painter.project.Metadata("RTXRemixConnectorLink"); material_prim = metadata.get("remix_material_prim")
            if not material_prim: raise Exception("Link Error: Project metadata found but 'remix_material_prim' is missing or empty.")
            log_info(f"Found linked Remix material prim: {material_prim}")
        except (RuntimeError, KeyError) as e: raise Exception(f"Link Error: Project not linked to Remix asset (Metadata 'RTXRemixConnectorLink' not found or invalid: {e})")
        except Exception as e: raise Exception(f"Metadata Error: Failed to retrieve Remix link: {e}")

        project_root_dir = None; project_base_dir = None; project_output_dir_abs = None
        try:
            project_output_dir_abs, dir_err = get_remix_project_default_output_dir()
            if dir_err: log_warning(f"Could not get Remix project directory for resolving relative paths: {dir_err}")
            elif project_output_dir_abs:
                 project_base_dir = os.path.dirname(project_output_dir_abs)
            if project_base_dir: project_root_dir = os.path.dirname(project_base_dir)
        except Exception as e: log_warning(f"Error deriving project directories: {e}")

        texture_sets = substance_painter.textureset.all_texture_sets()
        if not texture_sets: raise Exception("Texture Set Error: No texture sets found in the current project.")
        target_ts: TextureSet | None = None; material_name_for_ts = safe_basename(material_prim)
        for ts in texture_sets:
            # Correct way to get name for potentially older APIs
            ts_name_val = None
            if hasattr(ts, 'name'):
                 ts_name_attr = getattr(ts, 'name')
                 ts_name_val = ts_name_attr() if callable(ts_name_attr) else ts_name_attr

            if ts_name_val == material_name_for_ts: target_ts = ts; break
        if not target_ts:
            first_ts = texture_sets[0]
            first_ts_name = 'UNKNOWN'
            if hasattr(first_ts, 'name'):
                 first_ts_name_attr = getattr(first_ts, 'name')
                 first_ts_name = first_ts_name_attr() if callable(first_ts_name_attr) else first_ts_name_attr

            log_warning(f"Could not find TextureSet named '{material_name_for_ts}'. Falling back to the first TextureSet: {first_ts_name}")
            target_ts = first_ts

        ts_display_name = 'UNKNOWN'
        if target_ts and hasattr(target_ts, 'name'):
            ts_name_attr = getattr(target_ts, 'name')
            ts_display_name = ts_name_attr() if callable(ts_name_attr) else ts_name_attr

        log_info(f"Targeting texture set: {ts_display_name}")

        log_debug(f"Querying textures for material: {material_prim}")
        try:
            encoded_material_prim = urllib.parse.quote(material_prim.replace(os.sep, '/'), safe='/'); get_mat_textures_url = f"/stagecraft/assets/{encoded_material_prim}/textures"; tex_result = make_remix_request_with_retries('GET', get_mat_textures_url)
            if tex_result["success"] and isinstance(tex_result.get("data"), dict) and isinstance(tex_result["data"].get("textures"), list):
                 texture_list = tex_result["data"].get("textures", []); log_info(f"Found {len(texture_list)} texture entries associated with material."); log_debug(f"Texture list from API: {texture_list}")
                 if not texture_list: log_info("No textures found associated with the Remix material via API.")
            else: err = tex_result['error'] or "Query failed"; sts = tex_result['status_code']; raise Exception(f"API Error getting textures (Status: {sts}): {err}")
        except Exception as api_e: raise Exception(f"Failed to query Remix textures: {api_e}")

        # --- Process Textures ---
        if texture_list:
            target_stack: Stack | None = None; log_debug(f"  Attempting to get stack for TextureSet '{ts_display_name}'...")
            if hasattr(target_ts, 'get_stack') and callable(target_ts.get_stack): target_stack = target_ts.get_stack(); log_debug(f"  Got stack via get_stack(): {target_stack}")
            elif hasattr(target_ts, 'all_stacks') and callable(target_ts.all_stacks):
                 all_ts_stacks = target_ts.all_stacks()
                 if all_ts_stacks: target_stack = all_ts_stacks[0]; log_debug(f"  Got stack via all_stacks()[0]: {target_stack}")
                 else: log_warning(f"  TextureSet '{ts_display_name}' has no stacks according to all_stacks().")
            else: log_warning(f"  Could not find a method ('get_stack' or 'all_stacks') to get stack from TextureSet '{ts_display_name}'.")
            if not target_stack: raise Exception(f"Could not get a valid stack object for TextureSet '{ts_display_name}'.")

            for entry in texture_list:
                # --- Get Texture Info ---
                if not (isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str) and isinstance(entry[1], str)):
                    log_warning(f"  Skipping invalid texture entry format: {entry}")
                    continue

                remix_attr_path = entry[0].replace('\\', '/'); remix_texture_file_path_raw = entry[1].replace('\\', '/');
                log_debug(f"Processing texture entry: Attr='{remix_attr_path}', File='{remix_texture_file_path_raw}'")
                if not remix_texture_file_path_raw:
                    log_debug(f"  Skipping attribute '{remix_attr_path}' - no file path assigned in Remix."); continue

                remix_pbr_type = None; attr_name_lower = os.path.basename(remix_attr_path).lower()
                # Iterate longest suffixes first
                sorted_suffixes = sorted(REMIX_ATTR_SUFFIX_TO_PBR_MAP.keys(), key=len, reverse=True)
                for suffix in sorted_suffixes:
                    pbr_type = REMIX_ATTR_SUFFIX_TO_PBR_MAP[suffix]
                    if attr_name_lower.endswith(suffix): remix_pbr_type = pbr_type; log_debug(f"  Inferred PBR type '{remix_pbr_type}' from attribute suffix '{suffix}'"); break
                if not remix_pbr_type: log_warning(f"  Could not infer PBR type for attribute '{remix_attr_path}'. Skipping texture import."); continue

                painter_channel_name = REMIX_PBR_TO_PAINTER_CHANNEL_MAP.get(remix_pbr_type)
                if not painter_channel_name: log_warning(f"  No Painter channel mapping found for PBR type '{remix_pbr_type}'. Skipping texture import."); continue
                log_debug(f"  Mapped to Painter channel '{painter_channel_name}'")

                # --- Resolve Texture Path ---
                absolute_texture_path = None
                if os.path.isabs(remix_texture_file_path_raw): absolute_texture_path = os.path.normpath(remix_texture_file_path_raw); log_debug(f"  Texture path is absolute: {absolute_texture_path}")
                elif project_root_dir: # Try resolving relative path
                    log_debug(f"  Texture path is relative: '{remix_texture_file_path_raw}'. Trying to resolve..."); possible_bases = []
                    if project_root_dir: possible_bases.append(os.path.join(project_root_dir, 'deps', 'captures')); possible_bases.append(project_root_dir); possible_bases.append(os.path.join(project_root_dir, 'replacements'))
                    if project_base_dir: possible_bases.append(project_base_dir)
                    if project_output_dir_abs: possible_bases.append(project_output_dir_abs)
                    unique_possible_bases = []; [unique_possible_bases.append(base) for base in possible_bases if base not in unique_possible_bases]
                    log_debug(f"    Checking relative bases: {unique_possible_bases}")
                    for base_dir in unique_possible_bases:
                        try:
                            p_path = os.path.abspath(os.path.join(base_dir, remix_texture_file_path_raw)); log_debug(f"    Checking path: {p_path}")
                            if os.path.isfile(p_path): absolute_texture_path = p_path; log_info(f"  Successfully resolved relative texture path: {absolute_texture_path}"); break
                        except Exception as path_e:
                            log_debug(f"    Error checking path with base {base_dir}: {path_e}")
                            if not absolute_texture_path: log_warning(f"  Could not resolve relative texture path '{remix_texture_file_path_raw}' to an existing file after checking common locations.")
                else: log_warning(f"  Texture path is relative, but couldn't determine project root directory. Cannot resolve.")

                if not absolute_texture_path or not os.path.isfile(absolute_texture_path):
                    log_warning(f"  Skipping texture import: File not found at resolved/checked path '{absolute_texture_path or remix_texture_file_path_raw}'."); import_texture_errors.append(f"Import-{remix_pbr_type}: File not found: {remix_texture_file_path_raw}"); continue

                # --- Prepare for Import (Convert DDS if necessary, with fallback) ---
                file_to_import = absolute_texture_path # Default to original path
                is_png_import = False
                alpha_png_path = None # Path to separate alpha if created

                # Check if it's a DDS file
                if absolute_texture_path.lower().endswith(".dds"):
                    log_info(f"  Detected DDS file. Attempting conversion via texconv...")
                    if not texconv_path or not os.path.isfile(texconv_path):
                        err_msg = f"texconv.exe path not configured or invalid ('{texconv_path}'). Cannot convert DDS. Skipping."
                        log_error(err_msg)
                        import_texture_errors.append(f"Import-{remix_pbr_type}: {err_msg}")
                        continue # Skip this texture

                    try:
                        # --- Try PNG Conversion ---
                        png_output_path_base = os.path.splitext(absolute_texture_path)[0] + ".png"
                        png_output_path_alpha = os.path.splitext(absolute_texture_path)[0] + "_alpha.png"

                        created_png_path = convert_dds_to_png(texconv_path, absolute_texture_path, png_output_path_base)

                        if created_png_path and os.path.exists(created_png_path):
                            log_info(f"  Conversion successful: {safe_basename(created_png_path)}")
                            file_to_import = created_png_path # Import the PNG
                            is_png_import = True

                            # --- Handle Alpha PNG Cleanup (if Pillow available) ---
                            if PIL_AVAILABLE: # Add check for Pillow
                                log_debug("  Pillow is available. Checking for and removing temporary alpha file if it exists.")
                                if os.path.exists(png_output_path_alpha):
                                    try: # Wrap file operation in try/except
                                        os.remove(png_output_path_alpha)
                                        log_debug(f"  Removed temporary alpha file: {png_output_path_alpha}")
                                    except OSError as e: # Catch potential OS errors
                                        log_warning(f"  Could not remove temporary alpha file {png_output_path_alpha}: {e}")
                                else:
                                     log_debug(f"  No separate alpha file found at {png_output_path_alpha} to remove.")
                            else:
                                log_debug("  Pillow not available, skipping alpha handling/cleanup.")
                            # --- End Alpha PNG Cleanup ---
                        else:
                            # Should not happen if convert_dds_to_png doesn't raise error on failure, but good safety check
                            raise RuntimeError(f"texconv conversion reported success but did not produce expected output for {safe_basename(absolute_texture_path)}")

                    except Exception as convert_e:
                        # --- Fallback to Direct DDS Import (v39.8) ---
                        err_msg = f"Failed to convert DDS '{safe_basename(absolute_texture_path)}' via texconv: {convert_e}"
                        log_warning(err_msg) # Log as warning instead of error initially
                        log_warning(f"  FALLBACK: Attempting to import original DDS file directly: {safe_basename(absolute_texture_path)}")
                        file_to_import = absolute_texture_path # Set back to original DDS path
                        is_png_import = False
                        # Add original error to list for tracking
                        import_texture_errors.append(f"Import-{remix_pbr_type} (Texconv): {err_msg}")
                        # Do NOT continue, proceed to import 'file_to_import' which is now the DDS
                else:
                    # Not a DDS file, import directly
                    log_info(f"  File is not DDS, attempting direct import: {safe_basename(file_to_import)}")

                # --- Import the Prepared File (Original, PNG, or Fallback DDS) ---
                imported_resource_id: ResourceID | None = None # Ensure it's reset
                try:
                    log_info(f"  Importing {'PNG' if is_png_import else ('DDS Fallback' if file_to_import.lower().endswith('.dds') else 'original file')}: {safe_basename(file_to_import)}")
                    imported_resource_obj = substance_painter.resource.import_project_resource(file_to_import, substance_painter.resource.Usage.TEXTURE)

                    # --- Simplified Resource Handling (v39.7) ---
                    if imported_resource_obj:
                        if isinstance(imported_resource_obj, ResourceID):
                            imported_resource_id = imported_resource_obj
                            log_debug("  Import returned ResourceID directly.")
                        elif hasattr(imported_resource_obj, 'identifier') and callable(imported_resource_obj.identifier):
                            log_warning("  Import function returned Resource object directly (older API?). Getting identifier.")
                            res_id_candidate = imported_resource_obj.identifier()
                            if isinstance(res_id_candidate, ResourceID):
                                imported_resource_id = res_id_candidate
                                log_debug(f"  Successfully obtained ResourceID via identifier(): {imported_resource_id}")
                            else:
                                log_error(f"  Identifier() did not return a ResourceID object. Got type: {type(res_id_candidate)}")
                        else:
                            log_error(f"  Import returned an unexpected object type without an identifier method: {type(imported_resource_obj)}")
                    else:
                         log_error("  Import function returned None.")

                    if not imported_resource_id:
                        raise RuntimeError(f"Import failed or could not resolve to a valid ResourceID. Original return object: {imported_resource_obj}")
                    # --- End Simplified Resource Handling ---

                    log_info(f"  Import successful: {imported_resource_id}")

                    # --- Import Alpha Channel if Created ---
                    alpha_resource_id = None # Ensure reset
                    if alpha_png_path and os.path.exists(alpha_png_path): # Check if alpha path exists
                        log_info(f"  Attempting to import separate alpha channel file: {safe_basename(alpha_png_path)}")
                        try: # De-indent try
                             alpha_res_obj = substance_painter.resource.import_project_resource(alpha_png_path, substance_painter.resource.Usage.TEXTURE)
                             if alpha_res_obj and isinstance(alpha_res_obj, ResourceID):
                                  alpha_resource_id = alpha_res_obj
                                  log_info(f"    Successfully imported alpha channel: {alpha_resource_id}")
                             elif alpha_res_obj and hasattr(alpha_res_obj, 'identifier') and callable(alpha_res_obj.identifier):
                                  alpha_id_candidate = alpha_res_obj.identifier()
                                  if isinstance(alpha_id_candidate, ResourceID):
                                       alpha_resource_id = alpha_id_candidate
                                       log_info(f"    Successfully imported alpha channel (via identifier): {alpha_resource_id}")
                                  else:
                                       log_warning("    Alpha import returned object with identifier(), but it wasn't a ResourceID.")
                             else:
                                 log_warning("    Alpha import returned unexpected object or None.")

                        except Exception as alpha_import_e: # De-indent except
                             # Don't add to main errors, just log it
                             log_warning(f"    Failed to import alpha channel file '{safe_basename(alpha_png_path)}': {alpha_import_e}")
                             # Keep alpha_resource_id as None

                except Exception as import_e:
                    # Catch errors during the actual import call or ResourceID resolution
                    # This will now catch failures from the direct DDS import fallback as well
                    err_msg = f"Failed to import {'DDS fallback' if not is_png_import and file_to_import.lower().endswith('.dds') else 'file'} '{safe_basename(file_to_import)}': {import_e}"
                    log_error(err_msg, exc_info=True)
                    # Ensure the texconv error isn't duplicated if fallback also fails
                    if f"Import-{remix_pbr_type} (Texconv):" not in err_msg:
                         import_texture_errors.append(f"Import-{remix_pbr_type}: {err_msg}")
                    else: # If texconv error already added, maybe add a note about fallback failure
                         import_texture_errors.append(f"Import-{remix_pbr_type} (DDS Fallback): Import also failed: {import_e}")
                    continue # Skip assignment if import failed

                # --- If import succeeded, count and proceed to assignment ---
                if imported_resource_id:
                    textures_imported_count += 1

                    # --- Attempt assignment ONLY if API function is available ---
                    if api_assign_func_available:
                        try:
                            log_info(f"  Attempting to assign resource '{imported_resource_id}' (from {'PNG' if is_png_import else 'DDS Fallback' if file_to_import.lower().endswith('.dds') else 'Original'}) to channel '{painter_channel_name}'")
                            channel_type_enum = PAINTER_STRING_TO_CHANNELTYPE_MAP.get(painter_channel_name)
                            if not channel_type_enum:
                                err_msg = f"Cannot map Painter channel name '{painter_channel_name}' to a valid ChannelType enum."
                                log_error(err_msg)
                                import_texture_errors.append(f"Assign-{painter_channel_name}: {err_msg}")
                                continue # Skip assignment for this texture

                            log_debug(f"    Getting target channel {channel_type_enum} from stack...")
                            target_channel = target_stack.get_channel(channel_type_enum)

                            if target_channel:
                                log_debug(f"    Calling set_channel_texture_resource(channel={target_channel}, resource_id={imported_resource_id})")
                                # THE ACTUAL ASSIGNMENT CALL (using the stored function):
                                _set_channel_texture_resource_func(target_channel, imported_resource_id)
                                log_info(f"    Successfully assigned resource to channel '{painter_channel_name}'.")
                                textures_assigned_count += 1
                            else:
                                err_msg = f"Channel '{painter_channel_name}' (Enum: {channel_type_enum}) not found on stack."
                                log_error(err_msg)
                                import_texture_errors.append(f"Assign-{painter_channel_name}: Channel not found.")

                        except Exception as assign_e:
                            # Catch any other unexpected errors during assignment
                            err_msg = f"Unexpected error during assignment to channel '{painter_channel_name}': {assign_e}"
                            log_error(err_msg, exc_info=True)
                            import_texture_errors.append(f"Assign-{painter_channel_name}: {assign_e}")
                    else:
                        # Log that manual assignment is needed because the API is missing
                        log_info(f"  Skipping automatic assignment for channel '{painter_channel_name}': API function 'set_channel_texture_resource' is not available in this Painter version.")
                        # Optionally add a specific message to errors if desired, but the main error is the missing API
                        if f"Assign-{painter_channel_name}: API function missing." not in import_texture_errors:
                             import_texture_errors.append(f"Assign-{painter_channel_name}: API function missing.")
                    # --- End Assignment ---
                # else: # This case means import failed - handled by continue in except block

    except Exception as main_e:
        # Catch errors in the main setup part of the function
        log_error(f"Texture import process failed: {main_e}", exc_info=True)
        import_texture_errors.append(f"Process Error: {main_e}")

    # --- Final Status Logging & Message ---
    log_info("="*20 + " IMPORT TEXTURES COMPLETED " + "="*20)
    final_message = f"Texture Import: Attempted={len(texture_list)}, Imported={textures_imported_count}, Assigned={textures_assigned_count}."
    if import_texture_errors:
        log_warning("Texture import completed with issues:")
        # Log only unique errors concisely
        unique_errors = sorted(list(set(import_texture_errors)))
        for i, err in enumerate(unique_errors): log_warning(f"  Issue {i+1}: {err}")
        final_message += f" Issues={len(unique_errors)}." # Report unique issue count

        # Refine final message based on outcome
        if textures_assigned_count == 0 and textures_imported_count > 0:
             # Check if the *only* assignment error was the missing API
             only_missing_api = all("API function missing." in err for err in unique_errors if "Assign-" in err)
             other_assign_errors = any("Assign-" in err and "API function missing." not in err for err in unique_errors)

             if only_missing_api and not other_assign_errors:
                  final_message += " Manual assignment required (API unavailable)."
             elif not api_assign_func_available: # API was never available
                  final_message += " Manual assignment required (API unavailable)."
             else: # API was available but other assignment errors occurred
                  final_message += " All assignments failed."
        elif textures_assigned_count > 0 and textures_assigned_count < textures_imported_count:
             final_message += " Some assignments failed."
        elif textures_imported_count == 0 and len(texture_list) > 0:
             final_message += " Failed to import any textures."

        final_message += " Check logs for details."
        display_message_safe(f"Warning: {final_message}")

    elif textures_imported_count > 0: # and implicitly textures_assigned_count == textures_imported_count
        log_info(final_message)
        display_message_safe(f"Success: {final_message}")
    else: # No textures found in Remix to begin with
        log_info(final_message)
        display_message_safe(f"Info: {final_message} (No textures found in Remix material to import)")


def handle_push_to_remix():
    """Exports textures programmatically based on settings, ingests them via Remix API,
       polls for ingested files, and pushes them to the linked Remix material.
       Uses dynamic attribute path discovery based on the target material. (v40.14)
    """
    log_info("="*20 + " PUSH TO REMIX INITIATED (v40.14 - Dynamic Attributes) " + "="*20)
    all_errors = []
    successfully_updated_types = []
    save_requested = False
    save_errors = []
    exported_files_map = {} # Map PBR Type -> Absolute Path of EXPORTED file (e.g., PNG)
    ingested_paths_map_absolute = {} # Map PBR Type -> Absolute Path of INGESTED file (e.g., DDS)
    actual_material_attributes = {} # Map PBR Type -> Actual USD Attribute Path found on material
    material_prim = None
    painter_export_path = None # Path where script exports files TO

    try:
        # --- Basic Checks ---
        if not check_requests_dependency(): raise Exception("Dependency Error: 'requests' library missing.")
        if not substance_painter.project.is_open(): raise Exception("Project Error: No Painter project is currently open.")

        # --- Get Remix Link Metadata ---
        mesh_file_path_from_meta = None
        log_info("Retrieving Remix link metadata from Painter project...")
        try:
            metadata = substance_painter.project.Metadata("RTXRemixConnectorLink")
            material_prim = metadata.get("remix_material_prim")
            mesh_file_path_from_meta = metadata.get("remix_mesh_file_path_resolved")
            if not material_prim: raise Exception("Link Error: Project metadata found but 'remix_material_prim' is missing or empty.")
            log_info(f"Found linked Remix material prim: {material_prim}")
            if mesh_file_path_from_meta: log_debug(f"  (Linked mesh file used for project: {mesh_file_path_from_meta})")
        except (RuntimeError, KeyError) as e: raise Exception(f"Link Error: Project not linked to Remix asset (Metadata 'RTXRemixConnectorLink' not found or invalid: {e})")
        except Exception as e: raise Exception(f"Metadata Error: Failed to retrieve Remix link: {e}")

        # --- Get Remix Project Dir (Needed for Ingest Target) ---
        log_info("Getting Remix project default output directory (for ingest target and path resolution)...")
        project_output_dir_abs, error_msg = get_remix_project_default_output_dir()
        if error_msg: raise Exception(f"Remix Directory Error: {error_msg}")
        log_info(f"Using Remix output directory: {project_output_dir_abs}")

        # --- Prepare and Trigger Programmatic Export --- (This section remains largely the same)
        log_info("Preparing Painter texture export...")
        export_result = None
        exported_files_list = []
        try:
            # --- Get Export Settings --- (Same as before)
            try:
                painter_export_path = PLUGIN_SETTINGS.get("painter_export_path", DEFAULT_PAINTER_EXPORT_PATH)
                if not painter_export_path: raise ValueError("Painter export path setting ('painter_export_path') is empty.")
                painter_export_path = os.path.abspath(os.path.normpath(painter_export_path))
                log_info(f"Target export directory (from settings): {painter_export_path}")
                os.makedirs(painter_export_path, exist_ok=True) # Ensure directory exists
            except Exception as path_e:
                raise Exception(f"Export Path Error: Failed to prepare export directory '{painter_export_path or 'Not Set'}': {path_e}")

            preset_name_to_use = PLUGIN_SETTINGS.get("painter_export_preset", "PBR Metallic Roughness")
            export_format = PLUGIN_SETTINGS.get("export_file_format", "png")
            export_padding = PLUGIN_SETTINGS.get("export_padding", "infinite")
            filename_format_pattern = PLUGIN_SETTINGS.get("export_filename_pattern", "$mesh_$textureSet_$channel")

            if export_format.lower() != "png":
                log_warning(f"Export file format setting is '{export_format}', forcing to 'png'.")
                export_format = "png"

            # --- Build Export Configuration --- (Same as before)
            log_debug("Getting texture sets using all_texture_sets()...")
            texture_sets = substance_painter.textureset.all_texture_sets()
            if not texture_sets: raise Exception("Export Error: No texture sets found in the current project.")

            export_list = []
            for ts in texture_sets:
                ts_name_val = None
                if hasattr(ts, 'name'):
                     ts_name_attr = getattr(ts, 'name')
                     ts_name_val = ts_name_attr() if callable(ts_name_attr) else ts_name_attr
                else:
                    log_error(f"Cannot retrieve name for texture set object: {ts}. Skipping.")
                    continue
                if not ts_name_val:
                    log_error(f"Retrieved empty name for texture set object: {ts}. Skipping.")
                    continue
                export_list.append({"rootPath": ts_name_val, "exportPreset": preset_name_to_use})

            if not export_list:
                 raise Exception("Export Error: Could not identify any valid texture sets with names.")

            log_debug(f"Exporting for texture sets: {[item['rootPath'] for item in export_list]}")
            log_info(f"Using Painter export preset: '{preset_name_to_use}'")

            export_parameters = {
                "parameters": {
                    "fileFormat": export_format,
                    "bitDepth": "8",
                    "dithering": True,
                    "paddingAlgorithm": export_padding,
                    "filenameFormat": filename_format_pattern
                }
            }

            # --- Define the PBR Metal/Rough preset explicitly (v40.1) ---
            preset_config = {
                "name": preset_name_to_use,
                "maps": [
                    {
                        "fileName": filename_format_pattern.replace("$channel", "BaseColor"),
                        "channels": [
                            {"destChannel": "R", "srcChannel": "R", "srcMap": {"srcMapType": "documentMap", "srcMapName": "baseColor"}, "format": "srgb"},
                            {"destChannel": "G", "srcChannel": "G", "srcMap": {"srcMapType": "documentMap", "srcMapName": "baseColor"}, "format": "srgb"},
                            {"destChannel": "B", "srcChannel": "B", "srcMap": {"srcMapType": "documentMap", "srcMapName": "baseColor"}, "format": "srgb"}
                        ]
                    },
                    {
                        "fileName": filename_format_pattern.replace("$channel", "Roughness"),
                        "channels": [
                            {"destChannel": "G", "srcChannel": "L", "srcMap": {"srcMapType": "documentMap", "srcMapName": "roughness"}, "format": "linear"}
                        ]
                    },
                    {
                        "fileName": filename_format_pattern.replace("$channel", "Metallic"),
                        "channels": [
                            {"destChannel": "G", "srcChannel": "L", "srcMap": {"srcMapType": "documentMap", "srcMapName": "metallic"}, "format": "linear"}
                        ]
                    },
                    {
                        "fileName": filename_format_pattern.replace("$channel", "Normal"),
                        "channels": [
                            {"destChannel": "R", "srcChannel": "R", "srcMap": {"srcMapType": "documentMap", "srcMapName": "normal"}, "format": "linear"},
                            {"destChannel": "G", "srcChannel": "G", "srcMap": {"srcMapType": "documentMap", "srcMapName": "normal"}, "format": "linear"},
                            {"destChannel": "B", "srcChannel": "B", "srcMap": {"srcMapType": "documentMap", "srcMapName": "normal"}, "format": "linear"}
                        ]
                    },
                    {
                        "fileName": filename_format_pattern.replace("$channel", "Height"),
                        "channels": [
                            {"destChannel": "G", "srcChannel": "L", "srcMap": {"srcMapType": "documentMap", "srcMapName": "height"}, "format": "linear"}
                        ]
                    }
                    # Add Emissive/Opacity here if needed, similar structure
                ]
            }
            log_debug(f"Using explicitly defined preset '{preset_name_to_use}' configuration.")

            export_config = {
                "exportShaderParams": False,
                "exportPath": painter_export_path,
                "exportList": export_list,
                "exportPresets": [preset_config],
                "exportParameters": [export_parameters]
            }

            # --- Trigger Export --- (Same as before)
            log_info(f"Starting Painter texture export to '{painter_export_path}' (Using Preset: '{preset_name_to_use}', Format: {export_format})...")
            log_debug(f"Export Config (partial): {json.dumps(export_config, indent=2)[:1000]}...")

            export_call_success = False
            try:
                log_info(">>> BEFORE substance_painter.export.export_project_textures")
                export_result = substance_painter.export.export_project_textures(export_config)
                log_info("<<< AFTER substance_painter.export.export_project_textures")
                export_call_success = True
            except Exception as export_api_error:
                log_error(f"!!! CRITICAL ERROR DURING export_project_textures CALL: {export_api_error}", exc_info=True)
                try:
                    match = re.search(r"at (/[^:]+)", str(export_api_error))
                    if match:
                        path_elements = match.group(1).strip('/').split('/')
                        problematic_section = export_config; valid_path = True
                        for element in path_elements:
                            if element.startswith('#'):
                                try:
                                    index = int(element[1:])
                                    if isinstance(problematic_section, list) and 0 <= index < len(problematic_section):
                                        problematic_section = problematic_section[index]
                                    else: valid_path = False; break
                                except (ValueError, IndexError): valid_path = False; break
                            elif isinstance(problematic_section, dict) and element in problematic_section:
                                problematic_section = problematic_section[element]
                            else:
                                valid_path = False
                                break # Path invalid

                        if valid_path:
                           log_error(f"Problematic section in config (based on error path '{match.group(1)}'):\n{json.dumps(problematic_section, indent=2)}")
                        else:
                           log_error(f"Could not traverse the full error path '{match.group(1)}' in the config.")
                    else:
                        log_error("Could not extract error path from ValueError message.")
                except Exception as log_config_err:
                     log_error(f"Could not extract problematic config section: {log_config_err}")

                raise export_api_error # Re-raise

            if not export_call_success:
                 raise Exception("Export Error: export_project_textures call completed without exception but was marked as failed.")


            # --- Process Export Result ---
            # Assuming TextureExportResult and ExportStatus are defined/imported correctly
            if isinstance(export_result, substance_painter.export.TextureExportResult):
                log_info(f"Export result status: {export_result.status}, message: {export_result.message}")
                if export_result.status == substance_painter.export.ExportStatus.Success:
                    if isinstance(export_result.textures, dict):
                        for ts_name, file_list in export_result.textures.items():
                            if isinstance(file_list, list): exported_files_list.extend(file_list)
                            else: log_warning(f"Expected list of files for texture set '{ts_name}' in export result, but got {type(file_list)}")
                        log_info(f"Successfully processed TextureExportResult. Found {len(exported_files_list)} total exported file path(s).")
                        if exported_files_list: log_debug(f"  Exported file paths: {exported_files_list}")
                        else: log_warning("  'textures' dictionary in result was empty.")
                    else: log_warning(f"Expected export_result.textures to be a dict, but got {type(export_result.textures)}")
                else: raise Exception(f"Export Error: Painter export failed: {export_result.message or f'Export failed with status {export_result.status}'}")
            elif isinstance(export_result, dict) and export_result.get("status") == "success": # Handle older API dict result
                log_warning("Export returned a dictionary (older API?). Processing as dict.")
                # Older API might use 'exportedFiles' key directly at the top level
                if "exportedFiles" in export_result and isinstance(export_result["exportedFiles"], list):
                    exported_files_list = export_result["exportedFiles"]
                elif "textures" in export_result and isinstance(export_result["textures"], dict): # Or maybe nested like newer API?
                    for ts_name, file_list in export_result["textures"].items():
                         if isinstance(file_list, list): exported_files_list.extend(file_list)
                else:
                    log_warning("Could not find 'exportedFiles' list or 'textures' dict in older API dictionary result.")
                log_info(f"Processed older API dict result. Found {len(exported_files_list)} total exported file path(s).")

            else: # Handle other unexpected return types or failures
                err_msg = "Unknown export error"
                if isinstance(export_result, dict): err_msg = export_result.get('message', 'Export failed with dictionary result but no message key.')
                elif export_result is not None:
                     try: err_msg = f"Export failed, returned unexpected object: {str(export_result)}"
                     except Exception: err_msg = f"Export failed, returned unexpected object of type {type(export_result)} that could not be converted to string."
                else: err_msg = "Export function returned None."
                raise Exception(f"Export Error: Painter export failed: {err_msg}")

            # --- Check if any files were actually exported (on disk or in results) ---
            # Prioritize list from results if not empty
            final_exported_files = exported_files_list if exported_files_list else []
            if not final_exported_files:
                log_warning("Export result list was empty. Checking export directory for files...")
                try: # Check disk as fallback
                    disk_files = [os.path.join(painter_export_path, f) for f in os.listdir(painter_export_path) if os.path.isfile(os.path.join(painter_export_path, f))]
                    if disk_files:
                        log_warning(f"Export result processing yielded no file paths, but files WERE found in the export directory: {disk_files}. Attempting to use disk files.")
                        final_exported_files = disk_files # Use disk files as a fallback
                    else:
                        log_error("Export process did not yield any file paths AND no files found in export directory. Check export preset configuration and ensure channels have content.")
                        raise Exception("Export Error: Export reported success but no exported file paths were found in the result or on disk.")
                except Exception as listdir_e:
                     log_error(f"Error checking export directory '{painter_export_path}' for files after empty result: {listdir_e}")
                     raise Exception("Export Error: Export reported success but no exported file paths were found in the result, and checking disk failed.")

            # Use the final list (either from results or disk)
            exported_files_list = final_exported_files
            log_info(f"Painter export successful. Processing {len(exported_files_list)} exported file path(s).")

        except Exception as export_proc_e:
            log_error(f"Error during Painter texture export process: {export_proc_e}", exc_info=True)
            raise Exception(f"Export Failed: {export_proc_e}") # Re-raise to be caught by the outermost handler

        # --- Map Exported Files using Suffixes ---
        log_info("Mapping exported files to PBR types using filename suffixes...")
        try:
            for file_path in exported_files_list:
                if not file_path or not os.path.isfile(file_path):
                    log_warning(f"Skipping invalid or non-existent file path from export result: {file_path}")
                    continue

                filename = safe_basename(file_path)
                base_name, ext = os.path.splitext(filename)
                if ext.lower() != f".{export_format.lower()}": # Check against configured format
                    log_warning(f"Skipping non-{export_format.upper()} file found during mapping: {filename}")
                    continue

                base_name_lower = base_name.lower()
                mapped = False

                # Iterate through known Painter channel suffixes to identify the PBR type
                # Iterate longest suffixes first to avoid partial matches (e.g., _basecolor vs _color)
                sorted_suffixes = sorted(PAINTER_CHANNEL_TO_REMIX_PBR_MAP.keys(), key=len, reverse=True)
                for painter_suffix in sorted_suffixes:
                    remix_pbr_type = PAINTER_CHANNEL_TO_REMIX_PBR_MAP[painter_suffix]
                    check_suffix = "_" + painter_suffix
                    if base_name_lower.endswith(check_suffix):
                        if remix_pbr_type in exported_files_map:
                            log_warning(f"Overwriting existing map for PBR type '{remix_pbr_type}' with file '{filename}'. Check export filenames if unexpected.")
                        exported_files_map[remix_pbr_type] = file_path # Store absolute path
                        log_info(f"Mapped suffix '{check_suffix}' -> Remix PBR type '{remix_pbr_type}': {filename}")
                        mapped = True
                        break # Found a match for this file

                if not mapped:
                    log_warning(f"Cannot map exported file '{filename}' to a known Remix PBR type based on suffix. Skipping this file.")

            log_info(f"Mapping complete. Mapped {len(exported_files_map)} files to PBR types.")
            if not exported_files_map:
                raise Exception("Mapping Error: No exported textures could be mapped to recognized Remix PBR types. Ensure exported filenames end with known suffixes (e.g., '_basecolor.png', '_normal.png').")

        except Exception as map_e:
            log_error(f"Error during file mapping process", exc_info=True)
            raise Exception(f"Mapping Failed: {map_e}") from map_e

        # --- Ingest Mapped Textures into Remix --- (v40.8 API Ingest logic restored)
        ingest_errors = []
        log_info(f"Starting texture ingest process for {len(exported_files_map)} mapped textures via Remix API...")
        for pbr_type, source_abs_path in exported_files_map.items():
            ingested_abs_path, ingest_err_msg = ingest_texture_to_remix(pbr_type, source_abs_path, project_output_dir_abs)
            if ingest_err_msg:
                log_error(f"Ingest failed for {pbr_type} texture '{safe_basename(source_abs_path)}': {ingest_err_msg}")
                ingest_errors.append(f"Ingest-{pbr_type}: {ingest_err_msg}")
            elif ingested_abs_path:
                # Store the path of the *ingested* DDS/RTEX.DDS file
                ingested_paths_map_absolute[pbr_type] = ingested_abs_path
                log_debug(f"Stored ingested path for {pbr_type}: {ingested_abs_path}")
            else:
                log_error(f"Ingest reported success for {pbr_type} but did not return a valid output path.")
                ingest_errors.append(f"Ingest-{pbr_type}: Success reported but no output path found.")

        all_errors.extend(ingest_errors)
        if not ingested_paths_map_absolute and exported_files_map:
            raise Exception("Ingest Error: Failed to ingest any textures via Remix API.")
        elif not exported_files_map:
            log_warning("Skipping ingest step as no files were successfully mapped.")

        # --- Dynamically Discover Target USD Attributes (v40.14) ---
        attribute_errors = []
        existing_texture_bindings = [] # List of [attribute_path, texture_file] from API

        if material_prim:
            log_info(f"Querying existing texture attributes on material: {safe_basename(material_prim)}")
            try:
                encoded_material_prim = urllib.parse.quote(material_prim.replace(os.sep, '/'), safe='/')
                get_mat_textures_url = f"/stagecraft/assets/{encoded_material_prim}/textures"
                tex_result = make_remix_request_with_retries('GET', get_mat_textures_url)

                if tex_result["success"] and isinstance(tex_result.get("data"), dict) and isinstance(tex_result["data"].get("textures"), list):
                    existing_texture_bindings = tex_result["data"].get("textures", [])
                    log_info(f"Found {len(existing_texture_bindings)} existing texture attribute bindings on material.")
                    log_debug(f"Existing bindings: {existing_texture_bindings}")
                    if not existing_texture_bindings:
                         log_warning("Material has no existing texture bindings. Cannot determine target attributes dynamically.")
                         attribute_errors.append("AttrLookup: Material has no existing texture bindings.")
                else:
                    err = tex_result['error'] or "Query failed"
                    sts = tex_result['status_code']
                    err_msg = f"Failed to query existing texture attributes (Status: {sts}): {err}"
                    log_error(err_msg)
                    attribute_errors.append(f"AttrLookup: {err_msg}")

            except Exception as api_e:
                 err_msg = f"Exception during existing texture attribute query: {api_e}"
                 log_error(err_msg, exc_info=True)
                 attribute_errors.append(f"AttrLookup: {err_msg}")

            # --- Map Ingested PBR Types to Found Attribute Paths ---
            if existing_texture_bindings and ingested_paths_map_absolute:
                log_info("Matching ingested PBR types to actual material attributes...")
                pbr_suffix_preferences = {
                    "albedo": ["diffuse_texture", "albedo_texture", "basecolor_texture"],
                    "normal": ["normalmap_texture", "normal_texture"],
                    "height": ["height_texture", "heightmap_texture", "displacement_texture"],
                    "roughness": ["reflectionroughness_texture", "roughness_texture"],
                    "metallic": ["metallic_texture", "metalness_texture"],
                    "emissive": ["emissive_mask_texture", "emissive_texture"],
                    "opacity": ["opacity_texture", "opacity_mask"]
                    # Add AO etc. if needed
                }

                found_attributes_set = set() # Track which API attributes we've already mapped
                unmappable_pbr_types = [] # Keep track of types we couldn't map

                log_debug(f"  Ingested PBR types to map: {list(ingested_paths_map_absolute.keys())}")
                log_debug(f"  Available attributes found on material: {[p for p, _ in existing_texture_bindings]}")

                for pbr_type in ingested_paths_map_absolute.keys(): # Iterate PBR types we *have* ingested
                    log_debug(f"  Attempting to map PBR type: '{pbr_type}'")
                    found_match = False
                    preferred_suffixes = pbr_suffix_preferences.get(pbr_type, [])
                    if not preferred_suffixes:
                        log_warning(f"    No known attribute suffixes defined for PBR type '{pbr_type}'. Cannot map dynamically.")
                        unmappable_pbr_types.append(pbr_type) # Add to unmappable list
                        continue

                    log_debug(f"    Checking preferred suffixes: {preferred_suffixes}")
                    # Try matching based on preferred suffix order
                    for target_suffix in preferred_suffixes:
                        log_debug(f"      Checking for suffix: ':{target_suffix.lower()}'")
                        # Check against actual attributes found on the material
                        for attr_path, _ in existing_texture_bindings:
                            if attr_path.lower().endswith(f":{target_suffix.lower()}"):
                                log_debug(f"        Testing potential match: '{attr_path}'")
                                if attr_path in found_attributes_set:
                                    log_debug(f"          Attribute '{attr_path}' already mapped, skipping for PBR type '{pbr_type}'.")
                                    continue # Skip if this specific path was already used

                                actual_material_attributes[pbr_type] = attr_path # Store the *exact* path from the API
                                found_attributes_set.add(attr_path) # Mark this path as used
                                log_info(f"    Mapped PBR '{pbr_type}' -> Actual Attribute '{attr_path}' (matched suffix ':{target_suffix}')")
                                found_match = True
                                break # Found the best match for this PBR type
                        if found_match: break # Move to next PBR type

                    if not found_match:
                        log_warning(f"    Could not find a suitable existing attribute on material '{safe_basename(material_prim)}' for PBR type '{pbr_type}'. Looked for suffixes: {preferred_suffixes}")
                        unmappable_pbr_types.append(pbr_type) # Add to unmappable list

                log_info(f"Dynamic attribute mapping complete. Found target attributes for {len(actual_material_attributes)} PBR types.")
                if unmappable_pbr_types:
                    log_warning(f"  Could not map the following ingested PBR types: {unmappable_pbr_types}")
                    # Add a specific error if any types couldn't be mapped
                    attribute_errors.append(f"AttrLookup-Mapping: Could not map PBR types: {', '.join(unmappable_pbr_types)}")

            else:
                 if not existing_texture_bindings:
                     log_warning("Skipping dynamic attribute mapping: No existing bindings found on material.")
                 if not ingested_paths_map_absolute:
                     log_warning("Skipping dynamic attribute mapping: No textures were successfully ingested.")

        else: # Material prim was missing
            log_error("Cannot perform attribute lookup: Material prim path is missing.")
            attribute_errors.append("AttrLookup: Material prim path missing.")

        all_errors.extend(attribute_errors) # Add any errors found during lookup/mapping
        if not actual_material_attributes and ingested_paths_map_absolute: # If we ingested but couldn't map any attributes
             log_warning("Attribute Mapping Warning: Failed to map any ingested textures to actual USD attributes on the material. Material update will be skipped.")
             # Don't raise an exception, allow process to finish reporting errors
        elif not ingested_paths_map_absolute:
            log_info("Skipping attribute mapping and update as no textures were successfully ingested.")
        # --- End Dynamic Attribute Discovery ---

        # --- Update Remix Material Inputs --- (Uses dynamically discovered paths)
        update_errors = []
        textures_update_payload = [] # List to hold (target_usd_attr, abs_ingested_path) tuples

        if actual_material_attributes and ingested_paths_map_absolute: # Check for discovered attributes AND ingested paths
            log_info(f"Preparing batch update payload for {len(actual_material_attributes)} dynamically mapped attributes using INGESTED texture paths...")
            for pbr_type, target_usd_attr in actual_material_attributes.items():
                if pbr_type in ingested_paths_map_absolute:
                    abs_ingested_path = ingested_paths_map_absolute[pbr_type]
                    textures_update_payload.append((target_usd_attr, abs_ingested_path))
                    log_debug(f"  Added {pbr_type} to batch update: Attr='{target_usd_attr}', Path='{abs_ingested_path}'")
                else:
                    # This case should be less likely now with dynamic mapping
                    log_warning(f"  Skipping inclusion in batch update for {pbr_type}: Found target attribute '{target_usd_attr}' but no corresponding INGESTED file path in ingested_paths_map_absolute (Should not happen?).")
                    update_errors.append(f"UpdatePrep-{pbr_type}: Mismatch between mapped attribute and ingested path data.")

            # --- Call the batch update function AFTER the loop ---
            if textures_update_payload:
                 # Ensure project_output_dir_abs is valid before calling batch update
                 if not project_output_dir_abs or not os.path.isdir(project_output_dir_abs):
                      batch_err_msg = "Cannot perform batch update: Invalid project output directory."
                      log_error(batch_err_msg)
                      update_errors.append(f"Update-Batch: {batch_err_msg}")
                 else:
                      # Assuming project_output_dir_abs points to the *ingested* directory root
                      batch_success, batch_err_msg = update_remix_textures_batch(textures_update_payload, project_output_dir_abs)
                      if not batch_success:
                          log_error(f"Batch texture update failed: {batch_err_msg}")
                          update_errors.append(f"Update-Batch: {batch_err_msg}")
                          # Check specifically for 422 again, even with dynamic paths
                          if "Status: 422" in batch_err_msg:
                               log_error("  Received 422 error even with dynamic attribute paths. This might indicate issues with the ingested texture paths being inaccessible/invalid for Remix, or deeper API issues.")
                      else:
                          # If batch succeeded, update the count based on payload size
                          # Filter successfully updated types based on the *actual* payload sent
                          successfully_updated_types.extend([pbr for pbr, _ in actual_material_attributes.items() if pbr in ingested_paths_map_absolute])
                          log_info(f"Batch update request successful (Updated {len(successfully_updated_types)} types potentially). Details: {batch_err_msg or 'None'}")
                          if batch_err_msg and "Path processing errors" in batch_err_msg:
                               update_errors.append(f"Update-Batch-Warning: {batch_err_msg}")
            else:
                 log_warning("No valid textures prepared for batch update (likely due to mapping failures or no ingested textures).")

            all_errors.extend(update_errors) # Add any errors collected during prep or batch call

        else:
            if not actual_material_attributes:
                 log_info("Skipping material update as attribute discovery/mapping failed or yielded no paths.")
            elif not ingested_paths_map_absolute:
                 log_info("Skipping material update as texture ingest failed or yielded no paths.")
            else: log_info("Skipping material update due to missing attributes or ingested paths.")

        # --- Save Remix Layer --- (Unchanged, depends on successful updates)
        if successfully_updated_types: # Save only if *something* was successfully submitted for update
            log_info("At least one texture update was successfully submitted. Attempting to save the current Remix edit layer...")
            save_requested = True
            edit_layer_id_abs, err_msg = get_current_edit_target()
            if err_msg:
                log_error(f"Could not get current edit target layer to save: {err_msg}")
                save_errors.append(f"SaveLayer-GetTarget: {err_msg}")
            else:
                save_success, save_err = save_remix_layer(edit_layer_id_abs)
                if not save_success:
                    log_error(f"Failed to submit save request for layer '{edit_layer_id_abs}': {save_err}")
                    save_errors.append(f"SaveLayer-Request: {save_err}")
                else:
                    log_info("Remix layer save request submitted successfully.")
        else:
            log_warning("Skipping Remix layer save because no textures were successfully submitted for update.")
        all_errors.extend(save_errors)

    except Exception as main_e:
        log_error(f"Push process aborted due to a critical error: {main_e}", exc_info=True)
        # Avoid duplicating the error message if it was already added
        if not any(str(main_e) in err for err in all_errors):
             all_errors.append(f"Process Error: {main_e}")

    finally:
        # --- Final Status Reporting --- (v40.14 Adjusted counts)
        log_info("Push process finished. Generating final status...")
        exported_count = len(exported_files_map) # How many we tried to export/map
        ingested_count = len(ingested_paths_map_absolute) # How many were successfully ingested
        mapped_attr_count = len(actual_material_attributes) # How many ingested types we found attributes for
        updated_count = len(successfully_updated_types) # How many types were in the successful batch call
        final_message = ""

        # Check for critical failures at different stages
        export_failed_critically = any("Export Failed" in err for err in all_errors)
        mapping_failed_critically = any("Mapping Failed" in err or "Mapping Error" in err for err in all_errors)
        # Refined ingest check: Did *any* ingest fail critically OR did *no* ingest succeed when expected?
        ingest_failed_critically = any("Ingest Error" in err or ("Ingest-" in err and "Success reported but no output path found" not in err) for err in all_errors) or (exported_count > 0 and ingested_count == 0)
        # Refined attribute lookup check: Did the initial query fail OR did mapping fail for *all* ingested types?
        attribute_lookup_failed = any("AttrLookup: " in err for err in all_errors if "AttrLookup-Mapping" not in err) or (ingested_count > 0 and mapped_attr_count == 0)
        attribute_mapping_failed_partially = any("AttrLookup-Mapping" in err for err in all_errors) # Specific check for partial mapping failure
        update_failed_critically = any("Update-Batch" in err and "Warning" not in err for err in all_errors) # Check for critical update failures

        summary = f"Exported: {exported_count}, Ingested: {ingested_count}, MappedAttrs: {mapped_attr_count}, SubmittedUpdate: {updated_count}, Issues: {len(all_errors)}"

        if all_errors:
            if export_failed_critically: final_message = f"Push Failed! (Export Error). {summary}."
            elif mapping_failed_critically: final_message = f"Push Failed! (File Suffix Mapping Error). {summary}."
            elif ingest_failed_critically: final_message = f"Push Failed! (Ingest Error). {summary}."
            elif attribute_lookup_failed: final_message = f"Push Failed! (Attribute Lookup/Mapping Error). {summary}." # Combined message
            elif update_failed_critically: final_message = f"Push Failed! (Update Error). {summary}."
            # Remove redundant checks that are covered by attribute_lookup_failed
            # elif exported_count == 0: final_message = f"Push Failed! (No Mappable Files Exported). {summary}."
            # elif mapped_attr_count == 0 and ingested_count > 0: final_message = f"Push Failed! (Attribute Mapping Failed). {summary}."
            # elif updated_count == 0 and mapped_attr_count > 0: final_message = f"Push Failed! (Update Submission Error). {summary}." # Keep this one
            elif updated_count == 0 and mapped_attr_count > 0: final_message = f"Push Failed! (Update Submission Error). {summary}."
            else: # Includes partial failures (like partial mapping), save failures, etc.
                 final_message = f"Push Partially Successful or Failed. {summary}."
                 log_warning(f"Push process completed with issues. Summary: {summary}")

            # Log details
            unique_errors = sorted(list(set(all_errors)))
            log_warning("--- Push Issues ---"); [log_warning(f"  Issue {i+1}: {err}") for i, err in enumerate(unique_errors)]; log_warning("-------------------")
            final_message += " Check logs."

        elif exported_count > 0 and updated_count == mapped_attr_count and ingested_count == exported_count and mapped_attr_count == ingested_count: # Ideal success path (all ingested were mapped and updated)
            mat_prim_name = safe_basename(material_prim) if material_prim else 'Unknown Material'
            final_message = f"Push Successful! {summary} for '{mat_prim_name}'."
            log_info(final_message)
        elif exported_count == 0 and not all_errors: # Export ran, but no textures relevant?
            final_message = f"Push Completed. {summary}. No mappable textures were exported. Check project content."
            log_warning(final_message)
        elif attribute_mapping_failed_partially: # Some textures ingested but couldn't find matching attributes
            final_message = f"Push Partially Successful. {summary}. Some textures lacked matching attributes on the material."
            log_warning(final_message) # Keep as warning
        else: # Other unexpected states
            final_message = f"Push Status Uncertain. {summary}. Check logs."
            log_warning(final_message)

        # Display final message in Painter UI
        display_message_safe(final_message) # Use safe wrapper

        log_info("="*20 + " PUSH TO REMIX FINISHED " + "="*20)


def handle_settings():
    """Placeholder function for handling settings action."""
    log_info("="*20 + " SETTINGS ACTION TRIGGERED (Placeholder) " + "="*20)
    # TODO: Implement actual settings dialog or logic here
    # Example: Load settings from a file, display a UI, save settings
    display_message_safe("Settings action is not yet implemented.")
    log_info("Settings action placeholder finished.")

# --- Call setup_logging after all necessary functions/variables are defined ---
# This ensures the logging helpers and dependency checks can run correctly on load.
setup_logging()

# The erroneous example code block previously here has been removed.
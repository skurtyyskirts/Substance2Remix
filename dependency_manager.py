import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR_NAME = "_vendor"
VENDOR_DIR_PATH = os.path.join(PLUGIN_DIR, VENDOR_DIR_NAME)

def _log_info(message):
    print(f"[RemixConnector DependencyManager] INFO: {message}")

def _log_warning(message):
    print(f"[RemixConnector DependencyManager] WARN: {message}")

def ensure_dependencies_installed():
    """
    Ensures that the vendor directory is on sys.path so that
    bundled dependencies (requests, Pillow) can be imported.
    """
    _log_info("Configuring dependencies...")

    if not os.path.isdir(VENDOR_DIR_PATH):
        _log_warning(f"Vendor directory not found at: {VENDOR_DIR_PATH}")
        return False

    if VENDOR_DIR_PATH not in sys.path:
        # Insert at the beginning to prioritize vendored packages
        sys.path.insert(0, VENDOR_DIR_PATH)
        _log_info(f"Added vendor directory to sys.path: {VENDOR_DIR_PATH}")
    else:
        _log_info("Vendor directory already in sys.path.")

    # Verify imports
    try:
        import requests
        import PIL
        _log_info("Dependencies 'requests' and 'PIL' imported successfully.")
        return True
    except ImportError as e:
        _log_warning(f"Failed to import dependencies even after adding vendor path: {e}")
        return False

import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR_NAME = "_vendor"
VENDOR_DIR_PATH = os.path.join(PLUGIN_DIR, VENDOR_DIR_NAME)

# Top-level vendored packages we ship. On plugin reload these may already
# be in sys.modules pointing at Painter's bundled (older) versions, so we
# evict them before re-resolving from _vendor.
_VENDORED_TOP_LEVEL = ("requests", "PIL")


def _log_info(message):
    print(f"[RemixConnector DependencyManager] INFO: {message}")

def _log_warning(message):
    print(f"[RemixConnector DependencyManager] WARN: {message}")


def _purge_stale_vendored_modules():
    """If a non-vendored copy is currently cached in sys.modules, drop it
    along with all of its submodules so the next import resolves through
    sys.path (where _vendor sits at index 0).
    """
    for top in _VENDORED_TOP_LEVEL:
        mod = sys.modules.get(top)
        if mod is None:
            continue
        mod_path = getattr(mod, "__file__", "") or ""
        try:
            from_vendor = os.path.normcase(os.path.abspath(mod_path)).startswith(
                os.path.normcase(os.path.abspath(VENDOR_DIR_PATH))
            )
        except Exception:
            from_vendor = False
        if from_vendor:
            continue
        # Evict the package and all of its submodules.
        prefix = top + "."
        for name in [n for n in sys.modules if n == top or n.startswith(prefix)]:
            sys.modules.pop(name, None)
        _log_info(f"Evicted non-vendored '{top}' from sys.modules ({mod_path or 'unknown path'}).")


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

    _purge_stale_vendored_modules()

    # Verify imports
    try:
        import requests
        import PIL
        _log_info("Dependencies 'requests' and 'PIL' imported successfully.")
        return True
    except ImportError as e:
        _log_warning(f"Failed to import dependencies even after adding vendor path: {e}")
        return False

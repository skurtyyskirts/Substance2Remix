import importlib
import os
import sys
import traceback
from . import dependency_manager
from .plugin_info import PLUGIN_NAME, PLUGIN_DESCRIPTION

# --- Plugin Metadata ---
plugin_name = PLUGIN_NAME
plugin_description = PLUGIN_DESCRIPTION

# --- Global Variables ---
remix_core = None
remix_actions = []
remix_menu = None

def _load_core_module():
    """
    Loads or reloads the main logic from core.py.
    This function will be called after dependencies are checked.
    """
    global remix_core
    from . import core

    try:
        if 'remix_core' in globals() and remix_core:
            remix_core = importlib.reload(core)
            print(f"[RemixConnector] Successfully reloaded 'core.py' module.")
        else:
            remix_core = core
            print(f"[RemixConnector] Successfully loaded 'core.py' module for the first time.")

        if hasattr(remix_core, 'setup_logging') and callable(remix_core.setup_logging):
            remix_core.setup_logging()
        else:
            print("[RemixConnector] WARNING: Core module is missing a callable 'setup_logging' function.")
        
        return True

    except Exception as e:
        print(f"[RemixConnector] CRITICAL ERROR: Failed to load core.py. The plugin cannot run. Error: {e}")
        traceback.print_exc()
        remix_core = None
        return False

def create_plugin_actions():
    """
    Creates the QAction objects for the plugin UI.
    """
    global remix_actions
    remix_actions.clear()

    try:
        from .qt_utils import QAction
        if not QAction: raise ImportError("QAction not found in qt_utils")
    except ImportError:
        print("[RemixConnector] ERROR: Could not import QAction from qt_utils. Cannot create UI.")
        return

    action_definitions = [
        {"text": "Pull From Remix", "handler": "handle_pull_from_remix"},
        {"text": "Import Textures from Remix", "handler": "handle_import_textures"},
        {"text": "Push To Remix", "handler": "handle_push_to_remix"},
        {"text": "Force Push to Remix", "handler": "handle_relink_and_push_to_remix"},
        {"text": "Settings...", "handler": "handle_settings"},
        {"text": "Diagnostics...", "handler": "handle_diagnostics"},
        {"text": "About...", "handler": "handle_about"},
    ]

    import substance_painter.ui

    for adef in action_definitions:
        try:
            if hasattr(remix_core, adef["handler"]):
                action = QAction(adef["text"], None)
                handler_func = getattr(remix_core, adef["handler"])
                action.triggered.connect(handler_func)
                remix_actions.append(action)
                print(f"[RemixConnector] Action '{adef['text']}' created and connected.")
            else:
                print(f"[RemixConnector] ERROR: Handler function '{adef['handler']}' not found in core module!")
        except Exception as e:
            print(f"[RemixConnector] Failed to create action '{adef['text']}': {e}")

def add_actions_to_menu():
    """
    Adds the created actions to a new 'Substance2Remix' menu in the main UI.
    """
    global remix_menu
    try:
        import substance_painter.ui
        from .qt_utils import QtWidgets
        QMenu = QtWidgets.QMenu if QtWidgets else None
    except ImportError:
        QMenu = None

    if not QMenu:
        print("[RemixConnector] ERROR: Could not import QMenu. Adding actions to Plugins menu fallback.")
        target_menu = substance_painter.ui.ApplicationMenu.Plugins
        for action in remix_actions:
            substance_painter.ui.add_action(target_menu, action)
        return

    try:
        remix_menu = QMenu(plugin_name)
        for action in remix_actions:
            remix_menu.addAction(action)

        substance_painter.ui.add_menu(remix_menu)
        print(f"[RemixConnector] Added {len(remix_actions)} action(s) to the 'Substance2Remix' menu.")

    except Exception as e:
        print(f"[RemixConnector] CRITICAL: Failed to create or add submenu: {e}")
        traceback.print_exc()

# === Substance Painter Plugin Entry Points ===

def start_plugin():
    """Called by Substance Painter when the plugin is started."""
    print("[RemixConnector] Starting plugin...")

    if not dependency_manager.ensure_dependencies_installed():
        try:
            import substance_painter.ui
            substance_painter.ui.display_message(
                "Remix Connector: Failed to install/load dependencies. Check logs."
            )
        except: pass
        return

    if _load_core_module():
        create_plugin_actions()
        add_actions_to_menu()
        print("[RemixConnector] Plugin UI initialization sequence completed.")
    else:
        print("[RemixConnector] Halting plugin startup due to critical error in core module.")


def close_plugin():
    """Called by Substance Painter when the plugin is stopped."""
    global remix_actions, remix_menu
    try:
        import substance_painter.ui
        if remix_menu:
            substance_painter.ui.delete_ui_element(remix_menu)
        
        remix_actions.clear()
        remix_menu = None
        print("[RemixConnector] Plugin closed and UI cleaned up.")
    except Exception as e:
        print(f"[RemixConnector] Error during plugin close: {e}")

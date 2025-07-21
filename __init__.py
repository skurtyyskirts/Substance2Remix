import importlib
import os
import sys
import traceback

# --- Plugin Metadata ---
plugin_name = "RTX Remix Connector"
plugin_description = "Connects Substance Painter to NVIDIA RTX Remix for texture/mesh exchange."

# --- Global Variables ---
remix_core = None
remix_actions = []

def reload_core_module():
    """
    Safely imports or reloads the main logic from core.py and runs its setup.
    """
    global remix_core

    plugin_path = os.path.dirname(os.path.abspath(__file__))
    if plugin_path not in sys.path:
        sys.path.append(plugin_path)

    try:
        # Use importlib to reload the module if it's already loaded
        if 'core' in sys.modules and remix_core is not None:
            remix_core = importlib.reload(remix_core)
            print("[RemixConnector] Successfully reloaded 'core.py' module.")
        else:
            import remix_connector
            remix_core = core
            print("[RemixConnector] Successfully loaded 'core.py' module for the first time.")

        # Call the setup function from the newly loaded/reloaded module
        if hasattr(remix_core, 'setup_logging') and callable(remix_core.setup_logging):
            remix_core.setup_logging()
        else:
            print("[RemixConnector] WARNING: Core module is missing a callable 'setup_logging' function.")

    except Exception as e:
        print(f"[RemixConnector] CRITICAL ERROR: Failed to load core.py. The plugin cannot run. Error: {e}")
        traceback.print_exc()
        remix_core = None

def create_plugin_actions():
    """
    Creates the QAction objects for the plugin UI.
    """
    global remix_actions
    remix_actions.clear()

    try:
        from PySide6.QtGui import QAction
    except ImportError:
        try:
            from PySide2.QtGui import QAction
        except ImportError:
            print("[RemixConnector] ERROR: Could not import QAction from PySide6 or PySide2. Cannot create UI.")
            return

    action_definitions = [
        {"text": "Pull From Remix", "handler": "handle_pull_from_remix"},
        {"text": "Import Textures from Remix", "handler": "handle_import_textures"},
        {"text": "Push To Remix", "handler": "handle_push_to_remix"},
        {"text": "Push To Selected Remix Asset", "handler": "handle_push_to_remix", "override_link": True},
        {"text": "Settings...", "handler": "handle_settings"}
    ]

    for adef in action_definitions:
        try:
            if hasattr(remix_core, adef["handler"]):
                action = QAction(adef["text"], None)
                action.triggered.connect(getattr(remix_core, adef["handler"]))
                remix_actions.append(action)
                print(f"[RemixConnector] Action '{adef['text']}' created and connected.")
            else:
                print(f"[RemixConnector] ERROR: Handler function '{adef['handler']}' not found in core module!")
        except Exception as e:
            print(f"[RemixConnector] Failed to create action '{adef['text']}': {e}")

def add_actions_to_menu():
    """
    Adds the created actions to the appropriate menu.
    """
    try:
        import substance_painter.ui

        target_menu = None
        if hasattr(substance_painter.ui.ApplicationMenu, 'Plugins'):
            target_menu = substance_painter.ui.ApplicationMenu.Plugins
        elif hasattr(substance_painter.ui.ApplicationMenu, 'Window'):
            target_menu = substance_painter.ui.ApplicationMenu.Window
        else:
            print("[RemixConnector] ERROR: Could not find 'Plugins' or 'Window' menu.")
            return

        try:
            substance_painter.ui.add_separator(target_menu)
        except Exception:
            pass  # Non-critical

        for action in remix_actions:
            substance_painter.ui.add_action(target_menu, action)

        print(f"[RemixConnector] Added {len(remix_actions)} action(s) to the menu.")

    except Exception as e:
        print(f"[RemixConnector] CRITICAL: Failed to add actions to any menu: {e}")
        traceback.print_exc()

# === Substance Painter Plugin Entry Points ===

def start_plugin():
    """Called by Substance Painter when the plugin is started."""
    print("[RemixConnector] Starting plugin...")

    reload_core_module()

    if remix_core is None:
        # Safely report critical startup failure to the log console
        print("\n" + "="*50)
        print("RTX REMIX CONNECTOR: FATAL ERROR ON STARTUP")
        print("The core logic (core.py) failed to load. Please check the log for the full traceback.")
        print("The plugin will not be available.")
        print("="*50 + "\n")
        return

    create_plugin_actions()
    add_actions_to_menu()
    print("[RemixConnector] Plugin UI initialization sequence completed.")

def close_plugin():
    """Called by Substance Painter when the plugin is stopped."""
    global remix_actions
    try:
        import substance_painter.ui
        for action in remix_actions:
            substance_painter.ui.delete_ui_element(action)
        remix_actions.clear()
        print("[RemixConnector] Plugin closed and UI cleaned up.")
    except Exception as e:
        print(f"[RemixConnector] Error during plugin close: {e}")

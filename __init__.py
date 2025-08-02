import importlib
import os
import sys
import traceback
from . import dependency_manager


# --- Plugin Metadata ---
plugin_name = "RTX Remix Connector"
plugin_description = "Connects Substance Painter to NVIDIA RTX Remix for texture/mesh exchange."

# --- Global Variables ---
remix_core = None
remix_actions = []

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
        {"text": "Force Push to Remix", "handler": "handle_relink_and_push_to_remix"},
        {"text": "Settings...", "handler": "handle_settings"}
    ]

    from . import settings_dialog
    import substance_painter.ui

    for adef in action_definitions:
        try:
            if hasattr(remix_core, adef["handler"]):
                action = QAction(adef["text"], None)
                handler_func = getattr(remix_core, adef["handler"])

                if adef["handler"] == "handle_settings":
                    main_window = substance_painter.ui.get_main_window()
                    # Directly create and show the dialog here
                    def show_settings():
                        dialog = settings_dialog.create_settings_dialog_instance(remix_core, remix_core.PLUGIN_SETTINGS, parent=main_window)
                        if dialog.exec_():
                            remix_core.PLUGIN_SETTINGS = dialog.get_settings()
                            remix_core.save_plugin_settings()
                    action.triggered.connect(show_settings)
                else:
                    action.triggered.connect(handler_func)
                
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

    # Ensure all required packages are installed before loading the main logic
    if not dependency_manager.ensure_dependencies_installed():
        # If dependencies fail, display an error and halt the plugin loading process.
        try:
            import substance_painter.ui
            substance_painter.ui.display_message(
                "Remix Connector: Failed to install required Python dependencies. "
                "The plugin may not work correctly. Check the log for details."
            )
        except (ImportError, AttributeError) as e:
            print(f"[RemixConnector] Could not display UI warning about dependencies: {e}")
        return

    # Once dependencies are confirmed, load the core module and build the UI
    if _load_core_module():
        create_plugin_actions()
        add_actions_to_menu()
        print("[RemixConnector] Plugin UI initialization sequence completed.")
    else:
        # This will be logged by _load_core_module, but we can add a final message.
        print("[RemixConnector] Halting plugin startup due to critical error in core module.")


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
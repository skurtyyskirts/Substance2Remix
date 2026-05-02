import importlib
import traceback

from . import dependency_manager
from .plugin_info import PLUGIN_NAME, PLUGIN_DESCRIPTION

# --- Plugin Metadata ---
plugin_name = PLUGIN_NAME
plugin_description = PLUGIN_DESCRIPTION

# --- Module state ---
remix_core = None
remix_actions = []
remix_menu = None
_fallback_actions_added = False


def _load_core_module():
    """
    Loads or reloads the main logic from core.py.
    Called after dependency setup. On reload, the previous plugin
    instance's shutdown() runs inside core.setup_logging().
    """
    global remix_core
    try:
        if remix_core is not None:
            remix_core = importlib.reload(remix_core)
            print("[RemixConnector] Reloaded 'core.py'.")
        else:
            from . import core
            remix_core = core
            print("[RemixConnector] Loaded 'core.py'.")

        if hasattr(remix_core, 'setup_logging') and callable(remix_core.setup_logging):
            remix_core.setup_logging()
        else:
            print("[RemixConnector] WARNING: core module is missing a callable 'setup_logging' function.")

        return True

    except Exception as e:
        print(f"[RemixConnector] CRITICAL ERROR: Failed to load core.py: {e}")
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
        if not QAction:
            raise ImportError("QAction not found in qt_utils")
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

    for adef in action_definitions:
        try:
            handler_func = getattr(remix_core, adef["handler"], None)
            if not callable(handler_func):
                print(f"[RemixConnector] ERROR: Handler '{adef['handler']}' missing.")
                continue
            action = QAction(adef["text"], None)
            action.triggered.connect(handler_func)
            remix_actions.append(action)
        except Exception as e:
            print(f"[RemixConnector] Failed to create action '{adef['text']}': {e}")


def add_actions_to_menu():
    """
    Adds the created actions to a new menu in the main UI, or falls
    back to the Plugins menu when QMenu cannot be created.
    """
    global remix_menu, _fallback_actions_added
    try:
        import substance_painter.ui
    except ImportError:
        print("[RemixConnector] ERROR: substance_painter.ui not available; skipping menu setup.")
        return

    QMenu = None
    try:
        from .qt_utils import QtWidgets
        QMenu = QtWidgets.QMenu if QtWidgets else None
    except ImportError:
        QMenu = None

    if not QMenu:
        print("[RemixConnector] WARN: QMenu unavailable; using Plugins menu fallback.")
        target_menu = substance_painter.ui.ApplicationMenu.Plugins
        for action in remix_actions:
            try:
                substance_painter.ui.add_action(target_menu, action)
            except Exception as e:
                print(f"[RemixConnector] Failed to add fallback action: {e}")
        _fallback_actions_added = True
        return

    try:
        remix_menu = QMenu(plugin_name)
        for action in remix_actions:
            remix_menu.addAction(action)
        substance_painter.ui.add_menu(remix_menu)
        print(f"[RemixConnector] Added {len(remix_actions)} action(s) to '{plugin_name}' menu.")
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
        except Exception:
            pass
        return

    if _load_core_module():
        create_plugin_actions()
        add_actions_to_menu()
        print("[RemixConnector] Plugin UI initialization sequence completed.")
    else:
        print("[RemixConnector] Halting plugin startup due to critical error in core module.")


def close_plugin():
    """Called by Substance Painter when the plugin is stopped."""
    global remix_actions, remix_menu, remix_core, _fallback_actions_added

    # 1) Tear down the plugin instance (waits for workers, closes dialogs).
    try:
        if remix_core is not None and hasattr(remix_core, 'teardown'):
            remix_core.teardown()
    except Exception as e:
        print(f"[RemixConnector] Error tearing down core: {e}")

    # 2) Remove UI elements.
    try:
        import substance_painter.ui
        if remix_menu is not None:
            try:
                substance_painter.ui.delete_ui_element(remix_menu)
            except Exception as e:
                print(f"[RemixConnector] delete_ui_element(menu) failed: {e}")
        if _fallback_actions_added:
            for action in remix_actions:
                try:
                    substance_painter.ui.delete_ui_element(action)
                except Exception:
                    pass
    except ImportError:
        pass
    except Exception as e:
        print(f"[RemixConnector] UI cleanup error: {e}")

    # 3) Drop strong refs so QActions can be collected.
    remix_actions.clear()
    remix_menu = None
    _fallback_actions_added = False
    print("[RemixConnector] Plugin closed and UI cleaned up.")

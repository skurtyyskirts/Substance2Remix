import importlib
import sys
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
remix_dock = None
remix_panel = None

# Submodules in dependency order. Painter's "Reload plugin" re-executes this
# file but keeps submodules cached, so they are reloaded explicitly (leaves
# first, core last) to pick up edits without restarting Painter.
_SUBMODULES = (
    "plugin_info", "qt_utils", "settings_schema", "remix_api", "texture_processor",
    "painter_controller", "async_utils", "settings_dialog", "diagnostics_dialog",
    "ui_panel", "core",
)

# (label, core handler, tooltip); None draws a separator.
_MENU = (
    ("Pull from Remix", "handle_pull_from_remix", "Create a project from the mesh and material selected in RTX Remix."),
    ("Import Textures from Remix", "handle_import_textures", "Add the linked material's textures as a fill layer."),
    None,
    ("Push to Remix", "handle_push_to_remix", "Export, ingest and assign textures to the linked Remix material."),
    ("Force Push to Selected Material", "handle_relink_and_push_to_remix", "Relink to the Remix selection and push under new file names."),
    None,
    ("Link to Selected Remix Material", "handle_link_to_selection", "Link this project to the material selected in Remix."),
    ("Show Linked Material in Remix", "handle_select_in_remix", "Select the linked material in RTX Remix."),
    None,
    ("Settings...", "handle_settings", None),
    ("Diagnostics...", "handle_diagnostics", None),
    ("Open Log Folder", "handle_open_log_folder", None),
    ("About Substance2Remix", "handle_about", None),
)


def _load_core_module():
    """
    Loads (or reloads) the plugin modules and creates the plugin instance.
    On reload, the previous instance is torn down inside core.setup_logging().
    """
    global remix_core
    try:
        pkg = __name__
        for name in _SUBMODULES:
            full = f"{pkg}.{name}"
            if full in sys.modules:
                importlib.reload(sys.modules[full])
        from . import core
        remix_core = core
        remix_core.setup_logging()
        return True
    except Exception as e:
        print(f"[{PLUGIN_NAME}] CRITICAL ERROR: Failed to load core.py: {e}")
        traceback.print_exc()
        remix_core = None
        return False


def create_plugin_actions():
    """
    Creates the QAction objects for the plugin menu.
    """
    global remix_actions
    remix_actions = []

    from .qt_utils import QAction
    from .ui_panel import plugin_icon

    for entry in _MENU:
        if entry is None:
            remix_actions.append(None)
            continue
        text, handler_name, tooltip = entry
        handler = getattr(remix_core, handler_name, None)
        if not callable(handler):
            print(f"[{PLUGIN_NAME}] ERROR: Handler '{handler_name}' missing.")
            continue
        action = QAction(text, None)
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        if handler_name == "handle_push_to_remix":
            action.setIcon(plugin_icon())
        action.triggered.connect(handler)
        remix_actions.append(action)


def add_actions_to_menu():
    """
    Adds the created actions to a menu in the main menu bar.
    """
    global remix_menu
    import substance_painter.ui
    from .qt_utils import QtWidgets

    remix_menu = QtWidgets.QMenu(plugin_name)
    remix_menu.setObjectName("Substance2RemixMenu")
    remix_menu.setToolTipsVisible(True)
    for action in remix_actions:
        if action is None:
            remix_menu.addSeparator()
        else:
            remix_menu.addAction(action)
    substance_painter.ui.add_menu(remix_menu)


def add_dock_panel():
    """
    Registers the Substance2Remix panel as a Painter dock widget. Its window
    icon becomes the quick button Painter shows to reopen the dock.
    """
    global remix_dock, remix_panel
    import substance_painter.ui
    from .ui_panel import RemixPanel

    remix_panel = RemixPanel(remix_core.plugin_instance, remix_core)
    remix_dock = substance_painter.ui.add_dock_widget(remix_panel)
    remix_core.plugin_instance.attach_panel(remix_panel)


# === Substance Painter Plugin Entry Points ===

def start_plugin():
    """Called by Substance Painter when the plugin is started."""
    print(f"[{PLUGIN_NAME}] Starting plugin...")

    if not dependency_manager.ensure_dependencies_installed():
        try:
            import substance_painter.ui
            from .qt_utils import QtWidgets
            QtWidgets.QMessageBox.warning(
                substance_painter.ui.get_main_window(), PLUGIN_NAME,
                "The bundled dependencies (requests, Pillow) failed to load, so the plugin is disabled. "
                "See Painter's Log window for details.",
            )
        except Exception:
            pass
        return

    if not _load_core_module():
        print(f"[{PLUGIN_NAME}] Halting plugin startup due to critical error in core module.")
        return

    for step in (create_plugin_actions, add_actions_to_menu, add_dock_panel):
        try:
            step()
        except Exception as e:
            print(f"[{PLUGIN_NAME}] {step.__name__} failed: {e}")
            traceback.print_exc()
    print(f"[{PLUGIN_NAME}] Plugin started.")


def close_plugin():
    """Called by Substance Painter when the plugin is stopped."""
    global remix_actions, remix_menu, remix_core, remix_dock, remix_panel

    # 1) Stop the panel's timer before the plugin instance goes away.
    if remix_panel is not None:
        try:
            remix_panel.stop()
        except Exception:
            pass

    # 2) Tear down the plugin instance (waits for workers, closes dialogs).
    try:
        if remix_core is not None and hasattr(remix_core, 'teardown'):
            remix_core.teardown()
    except Exception as e:
        print(f"[{PLUGIN_NAME}] Error tearing down core: {e}")

    # 3) Remove UI elements.
    try:
        import substance_painter.ui
        for element in (remix_dock, remix_menu):
            if element is None:
                continue
            try:
                substance_painter.ui.delete_ui_element(element)
            except Exception as e:
                print(f"[{PLUGIN_NAME}] delete_ui_element failed: {e}")
    except ImportError:
        pass

    # 4) Drop strong refs so QActions can be collected.
    remix_actions = []
    remix_menu = None
    remix_dock = None
    remix_panel = None
    print(f"[{PLUGIN_NAME}] Plugin closed and UI cleaned up.")

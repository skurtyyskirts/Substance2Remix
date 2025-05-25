# -*- coding: utf-8 -*-

"""
Substance Painter Plugin: RTX Remix Connector - Plugin Entry Point (__init__.py)

Initializes the plugin UI and connects actions to core logic.
Version 3: Moved 'global ui_available' to the top of start_plugin to fix SyntaxError.
Version 2: Added traceback import for better error logging during core import.
Version 1: Initial version.
"""

# --- Standard Python Imports ---
import importlib
import logging
import os
import sys
import traceback # <-- FIX: Added import

# --- Substance Painter API Imports ---
# Attempt to import PySide/Qt modules first, as they are essential for UI
try:
    from PySide6 import QtWidgets, QtGui
    from PySide6.QtGui import QAction
    pyside_available = True
except ImportError:
    try:
        # Fallback to PySide2 if PySide6 is not available
        from PySide2 import QtWidgets, QtGui
        from PySide2.QtGui import QAction
        pyside_available = True
    except ImportError:
        # If neither is available, log an error and disable UI features
        pyside_available = False
        # Use standard logging if substance_painter.logging isn't available yet
        logging.basicConfig(level=logging.WARNING)
        logging.warning("[RemixConnector Init] Neither PySide6 nor PySide2 found. UI features will be disabled.")
        # Define dummy classes to prevent NameErrors later if UI code isn't fully guarded
        class QtWidgets: QWidget = type('QWidget', (object,), {}); QTextEdit = type('QTextEdit', (object,), {}) # Add more dummies if needed
        class QtGui: pass
        class QAction: pass

# --- Substance Painter UI Module Import (Crucial for Menu Integration) ---
# Import substance_painter.ui separately and set a flag
try:
    import substance_painter.ui
    ui_available = True # Set flag indicating the UI module itself is available
except ImportError:
    # Log if the core UI module cannot be imported
    logging.warning("[RemixConnector Init] substance_painter.ui module not found. UI menu integration will be disabled.")
    ui_available = False # Set flag indicating UI module is NOT available
    # Define a dummy substance_painter.ui if needed to prevent NameErrors,
    # though checks later should prevent calls if ui_available is False.
    class SubstancePainterUI_Dummy:
        def display_message(self, *args, **kwargs): pass
        def add_action(self, *args, **kwargs): pass
        def delete_ui_element(self, *args, **kwargs): pass
        def add_separator(self, *args, **kwargs): pass
        class ApplicationMenu: Window = "DummyWindowMenu" # Define dummy enum/attribute
    substance_painter = type('SubstancePainterDummy', (object,), {'ui': SubstancePainterUI_Dummy()})()


# --- Plugin Metadata ---
# These are standard variables recognized by Substance Painter's plugin system
plugin_name = "RTX Remix Connector"
plugin_description = "Connects Substance Painter to NVIDIA RTX Remix for texture/mesh exchange."
# Define other metadata if needed (e.g., author, version)

# --- Global Variables ---
core = None # Placeholder for the imported core module
remix_connector_actions = [] # List to hold created QAction objects
_logger = None # Placeholder for the logger

# --- Core Module Loading ---
# Try to import the core logic module (core.py) safely
try:
    # Use importlib for robustness, especially if the plugin is reloaded
    core = importlib.import_module('.core', __name__)
    print("[RemixConnector] Core module imported successfully via importlib. Type:", type(core))

    # Verify key functions are available immediately after import
    required_functions = ['handle_pull_from_remix', 'handle_import_textures', 
                          'handle_push_to_remix', 'handle_settings']
    missing_functions = [f for f in required_functions if not hasattr(core, f)]
    
    if missing_functions:
        logging.warning(f"[RemixConnector Init] The following required functions are missing from core module: {missing_functions}")
        # Try to reload the module in case of out-of-order definitions
        core = importlib.reload(core)
        # Check again after reload
        still_missing = [f for f in required_functions if not hasattr(core, f)]
        if still_missing:
            logging.error(f"[RemixConnector Init] Even after reload, these functions are missing: {still_missing}")
    
    # Setup logging using the core module's logger instance
    # Ensure core and setup_logging exist before calling
    if core and hasattr(core, 'setup_logging') and callable(core.setup_logging):
        core.setup_logging()
        # Ensure _logger exists after setup before assigning
        if hasattr(core, '_logger'):
             _logger = core._logger # Get the logger instance from core
             # Check if logger is valid before using
             if _logger and hasattr(_logger, 'info'):
                 _logger.info(f"[RemixConnector] Core module uses the logger instance: {_logger}")
             else:
                 logging.warning("[RemixConnector Init] Logger object obtained from core is invalid or missing 'info' method.")
                 _logger = None # Reset logger if invalid
        else:
             logging.warning("[RemixConnector Init] Core module loaded but has no _logger attribute.")
             _logger = None # Ensure logger is None
    elif core:
         logging.warning("[RemixConnector Init] Core module loaded but setup_logging is missing or not callable.")
         _logger = None # Ensure logger is None
    else:
         # This case should ideally be caught by the outer except block, but handle defensively
         logging.error("[RemixConnector Init] Core module object is None after import attempt.")
         _logger = None # Ensure logger is None


except ImportError as e:
    # Log detailed error if core module cannot be imported
    log_func = _logger.info if _logger and hasattr(_logger, 'error') else logging.error # Use core logger if available AND valid
    log_func(f"[RemixConnector Init] Failed to import core module: {e}", exc_info=True)
    print(f"[RemixConnector Init] Traceback:\n{traceback.format_exc()}") # Also print traceback
    core = None # Ensure core is None if import fails
except Exception as e:
     # Catch other potential errors during import (like syntax errors in core.py)
     error_msg = f"Unexpected error importing core module using importlib: {e} ({type(e).__name__}). Plugin will not load correctly."
     # Use standard logging as _logger might not be initialized if core import failed early
     logging.error(f"[RemixConnector Init] {error_msg}")
     # --- FIX: Log traceback here if _logger isn't available ---
     print(f"[RemixConnector Init] Traceback:\n{traceback.format_exc()}") # Log full traceback for syntax errors
     core = None


# --- Plugin Entry Points ---
# These functions are called by Substance Painter when the plugin is started or stopped

def start_plugin():
    """Called by Substance Painter when the plugin is started."""
    # --- FIX: Declare global variables at the TOP of the function ---
    global _logger, ui_available, core, remix_connector_actions

    # Use the logger from core if available, otherwise fallback
    log_func = _logger.info if _logger and hasattr(_logger, 'info') else logging.info
    log_func("[RemixConnector] Entering start_plugin.")

    if not pyside_available:
        log_func("[RemixConnector] PySide (QtWidgets/QtGui) not available, skipping UI initialization.")
        # We might still be able to add menu items if substance_painter.ui is available
        # but cannot create QActions without PySide.
        # Let's proceed cautiously.
        # return # Cannot proceed with QAction creation

    if core is None:
        log_func("[RemixConnector] Core module failed to load, cannot start plugin actions.")
        # Optionally display a message to the user in Painter's UI if possible
        # Check if substance_painter.ui was successfully imported earlier
        if ui_available: # Check the flag set during UI module import
             try:
                  # Check again if display_message exists before calling
                  if hasattr(substance_painter.ui, 'display_message'):
                       substance_painter.ui.display_message(
                            "RTX Remix Connector Error: Core logic failed to load. Check logs."
                       )
                  else:
                       log_func("[RemixConnector] substance_painter.ui.display_message not found.")
             except Exception as ui_err:
                  log_func(f"[RemixConnector] Could not display UI error message: {ui_err}")
        else:
            log_func("[RemixConnector] substance_painter.ui module not available, cannot display UI error message.")
        return # Stop plugin initialization

    log_func("[RemixConnector] Initializing RTX Remix Connector Plugin UI...")

    # --- Create Actions (Requires PySide) ---
    if pyside_available:
        try:
            # Pull Action
            pull_action = QAction("Pull Selected Remix Asset", triggered=core.handle_pull_from_remix)
            remix_connector_actions.append(pull_action)
            log_func("[RemixConnector] Pull action created and connected.")

            # Import Textures Action
            import_textures_action = QAction("Import Textures from Remix", triggered=core.handle_import_textures)
            remix_connector_actions.append(import_textures_action)
            log_func("[RemixConnector] Import Textures action created and connected.")

            # Push Action
            push_action = QAction("Push Textures to Remix", triggered=core.handle_push_to_remix)
            remix_connector_actions.append(push_action)
            log_func("[RemixConnector] Push action created and connected.")

            # Settings Action - Check if function exists first
            if hasattr(core, 'handle_settings') and callable(core.handle_settings):
                settings_action = QAction("Connector Settings...", triggered=core.handle_settings)
                remix_connector_actions.append(settings_action)
                log_func("[RemixConnector] Settings action created and connected.")
            else:
                log_func(f"[RemixConnector] Error: 'handle_settings' function not found in core module "
                         f"or not callable (type: {type(getattr(core, 'handle_settings', None))}). "
                         f"Settings menu item will not be available. "
                         f"Available attributes: {[attr for attr in dir(core) if not attr.startswith('_') and callable(getattr(core, attr))]}")

        except Exception as e:
            log_func(f"[RemixConnector] Error creating QActions: {e}")
            # Handle error appropriately, maybe prevent adding to menu
            remix_connector_actions.clear() # Clear any partially created actions
            # Don't return yet, maybe we can still add *something* if ui is available
            # but log that actions failed.
            log_func("[RemixConnector] Failed to create QActions due to PySide error. Menu items will be missing.")
            # return # Optionally return if actions are critical
    else:
        log_func("[RemixConnector] PySide not available, skipping QAction creation.")


    # --- Add Actions to Menu (Requires substance_painter.ui) ---
    # Use the substance_painter.ui module to add actions to the main menu
    try:
        # Check if the ui module and necessary functions are available
        # Use the global ui_available flag checked earlier
        if ui_available and hasattr(substance_painter.ui, 'add_action'):

            # Attempt to add actions to the standard 'Plugins' or 'Window' menu
            log_func("[RemixConnector] Attempting to add actions to a standard menu...")
            # Try 'Plugins' first, then 'Window' as fallback
            menu_target = None
            if hasattr(substance_painter.ui.ApplicationMenu, 'Plugins'):
                menu_target = substance_painter.ui.ApplicationMenu.Plugins
                log_func("[RemixConnector] Targeting 'Plugins' menu.")
            elif hasattr(substance_painter.ui.ApplicationMenu, 'Window'):
                menu_target = substance_painter.ui.ApplicationMenu.Window
                log_func("[RemixConnector] Targeting 'Window' menu as fallback.")
            else:
                log_func("[RemixConnector] Could not find 'Plugins' or 'Window' in ApplicationMenu enum. Cannot add menu items.")
                return # Cannot proceed without a target menu

            # Add a separator if possible (check if function exists)
            if hasattr(substance_painter.ui, 'add_separator'):
                 substance_painter.ui.add_separator(menu_target)
            else:
                 log_func("[RemixConnector] substance_painter.ui.add_separator not available. Skipping separator.")

            # Add actions (only if PySide was available and actions were created)
            if pyside_available and remix_connector_actions:
                for action in remix_connector_actions:
                    substance_painter.ui.add_action(menu_target, action)
                log_func(f"[RemixConnector] Added {len(remix_connector_actions)} action(s) to the menu.")
            elif not pyside_available:
                 log_func("[RemixConnector] Skipping adding actions to menu because PySide was not available to create them.")
            else: # PySide available but remix_connector_actions is empty (likely error during creation)
                 log_func("[RemixConnector] Skipping adding actions to menu because QAction creation failed earlier.")


        elif not ui_available:
             log_func("[RemixConnector] substance_painter.ui module not available. Cannot add actions to menu.")
        elif not hasattr(substance_painter.ui, 'add_action'):
             log_func("[RemixConnector] substance_painter.ui.add_action not available. Cannot add actions to menu.")

    except AttributeError as ae:
         # Catch potential errors if ApplicationMenu enum or its members don't exist
         log_func(f"[RemixConnector] Error adding actions to menu (AttributeError): {ae}. Check API compatibility.")
    except Exception as e:
        # Log any other errors during menu integration
        log_func(f"[RemixConnector] Error adding actions to menu: {e}", exc_info=True)


    log_func("[RemixConnector] RTX Remix Connector Plugin UI initialization sequence completed.")


def close_plugin():
    """Called by Substance Painter when the plugin is stopped."""
    # --- FIX: Declare global variables at the TOP of the function ---
    global _logger, ui_available, remix_connector_actions

    log_func = _logger.info if _logger and hasattr(_logger, 'info') else logging.info
    log_func("[RemixConnector] Entering close_plugin.")

    # No need to check pyside_available here, only ui_available for cleanup

    # Remove actions from the UI (Requires substance_painter.ui)
    try:
        # Check if the ui module and necessary functions are available
        if ui_available and hasattr(substance_painter.ui, 'delete_ui_element'):
            log_func("[RemixConnector] Removing UI elements...")
            # Iterate over a copy of the list if modifying it during iteration is risky
            # Although delete_ui_element might be safe, using a copy is robust.
            actions_to_remove = list(remix_connector_actions)
            for action in actions_to_remove:
                try:
                    substance_painter.ui.delete_ui_element(action)
                except Exception as del_e:
                    # Log error deleting specific widget but continue
                    log_func(f"[RemixConnector] Error deleting UI element {action}: {del_e}")
            log_func(f"[RemixConnector] Attempted removal of {len(actions_to_remove)} actions.")
        elif not ui_available:
            log_func("[RemixConnector] substance_painter.ui module not available. Cannot remove actions.")
        elif not hasattr(substance_painter.ui, 'delete_ui_element'):
             log_func("[RemixConnector] substance_painter.ui.delete_ui_element not available. Cannot remove actions.")

    except Exception as e:
        log_func(f"[RemixConnector] Error removing actions from UI: {e}", exc_info=True)

    remix_connector_actions.clear() # Clear the list regardless of UI cleanup success
    log_func("[RemixConnector] RTX Remix Connector Plugin stopped.")

# --- Main Guard (Optional) ---
# This part is generally not needed for Painter plugins but can be useful for standalone testing
if __name__ == "__main__":
    # This code won't run when Painter loads the plugin,
    # but could be used for testing parts of the init script if run directly.
    print(f"Running {plugin_name} __init__.py directly (for testing purposes only).")
    # Example: You could potentially mock Painter API calls here for testing UI setup logic

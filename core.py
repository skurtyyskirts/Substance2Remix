import os
import json
import sys
import time
import traceback
import urllib.parse
import ntpath
import tempfile
import shutil
import re
import subprocess
import copy

# --- Qt Imports ---
QT_MODULE = None
QtWidgets = None
QtCore = None
QtGui = None
QDialog = None
QPushButton = None
QVBoxLayout = None
QHBoxLayout = None
QLabel = None
QScrollArea = None # Added for consistency
QWidget = None # Added for consistency
QFormLayout = None # Added for consistency
QCheckBox = None # Added for consistency
QComboBox = None # Added for consistency
QLineEdit = None # Added for consistency
QIntValidator = None # Added for consistency
QDoubleValidator = None # Added for consistency

QT_AVAILABLE = False
_QT_BINDING_VERSION_CORE = None

try:
    from PySide6 import QtWidgets as QtW_PS6, QtCore as QtC_PS6, QtGui as QtG_PS6
    print("[RemixConnector Core] Successfully imported PySide6 base modules.") # Changed log slightly

    # Attempt to access and assign core components one by one to catch specific errors
    QtWidgets = QtW_PS6
    QtCore = QtC_PS6
    QtGui = QtG_PS6
    QT_MODULE = QtWidgets
    QDialog = QtWidgets.QDialog
    QPushButton = QtWidgets.QPushButton
    QVBoxLayout = QtWidgets.QVBoxLayout
    QHBoxLayout = QtWidgets.QHBoxLayout
    QLabel = QtWidgets.QLabel
    QScrollArea = QtWidgets.QScrollArea
    QWidget = QtWidgets.QWidget
    QFormLayout = QtWidgets.QFormLayout
    QCheckBox = QtWidgets.QCheckBox
    QComboBox = QtWidgets.QComboBox
    QLineEdit = QtWidgets.QLineEdit
    # QtGui based components
    if hasattr(QtGui, 'QIntValidator'): QIntValidator = QtGui.QIntValidator
    else: print("[RemixConnector Core] PySide6.QtGui.QIntValidator not found."); raise ImportError("Missing QIntValidator")
    if hasattr(QtGui, 'QDoubleValidator'): QDoubleValidator = QtGui.QDoubleValidator
    else: print("[RemixConnector Core] PySide6.QtGui.QDoubleValidator not found."); raise ImportError("Missing QDoubleValidator")

    QT_AVAILABLE = True
    _QT_BINDING_VERSION_CORE = "PySide6"
    print("[RemixConnector Core] Successfully initialized ALL PySide6 components and set QT_AVAILABLE=True.")

except ImportError as e_pyside6_import: # Catches initial "from PySide6 import ..." or explicit raise ImportError
    print(f"[RemixConnector Core] PySide6 not available or component missing: {e_pyside6_import}")
    QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None # Reset all on failure of this block
    QT_AVAILABLE = False # Ensure it's false before trying next
    try:
        from PySide2 import QtWidgets as QtW_PS2, QtCore as QtC_PS2, QtGui as QtG_PS2
        print("[RemixConnector Core] Successfully imported PySide2 base modules.")

        QtWidgets = QtW_PS2; QtCore = QtC_PS2; QtGui = QtG_PS2
        QT_MODULE = QtWidgets
        QDialog = QtWidgets.QDialog; QPushButton = QtWidgets.QPushButton
        QVBoxLayout = QtWidgets.QVBoxLayout; QHBoxLayout = QtWidgets.QHBoxLayout; QLabel = QtWidgets.QLabel
        QScrollArea = QtWidgets.QScrollArea; QWidget = QtWidgets.QWidget; QFormLayout = QtWidgets.QFormLayout
        QCheckBox = QtWidgets.QCheckBox; QComboBox = QtWidgets.QComboBox; QLineEdit = QtWidgets.QLineEdit
        if hasattr(QtGui, 'QIntValidator'): QIntValidator = QtGui.QIntValidator
        else: print("[RemixConnector Core] PySide2.QtGui.QIntValidator not found."); raise ImportError("Missing QIntValidator")
        if hasattr(QtGui, 'QDoubleValidator'): QDoubleValidator = QtGui.QDoubleValidator
        else: print("[RemixConnector Core] PySide2.QtGui.QDoubleValidator not found."); raise ImportError("Missing QDoubleValidator")

        QT_AVAILABLE = True; _QT_BINDING_VERSION_CORE = "PySide2"
        print("[RemixConnector Core] Successfully initialized ALL PySide2 components and set QT_AVAILABLE=True.")

    except ImportError as e_pyside2_import:
        print(f"[RemixConnector Core] PySide2 not available or component missing: {e_pyside2_import}")
        QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None
        QT_AVAILABLE = False
        try:
            from PyQt5 import QtWidgets as QtW_PQ5, QtCore as QtC_PQ5, QtGui as QtG_PQ5
            print("[RemixConnector Core] Successfully imported PyQt5 base modules.")

            QtWidgets = QtW_PQ5; QtCore = QtC_PQ5; QtGui = QtG_PQ5
            QT_MODULE = QtWidgets
            QDialog = QtWidgets.QDialog; QPushButton = QtWidgets.QPushButton
            QVBoxLayout = QtWidgets.QVBoxLayout; QHBoxLayout = QtWidgets.QHBoxLayout; QLabel = QtWidgets.QLabel
            QScrollArea = QtWidgets.QScrollArea; QWidget = QtWidgets.QWidget; QFormLayout = QtWidgets.QFormLayout
            QCheckBox = QtWidgets.QCheckBox; QComboBox = QtWidgets.QComboBox; QLineEdit = QtWidgets.QLineEdit
            if hasattr(QtGui, 'QIntValidator'): QIntValidator = QtGui.QIntValidator
            else: print("[RemixConnector Core] PyQt5.QtGui.QIntValidator not found."); raise ImportError("Missing QIntValidator")
            if hasattr(QtGui, 'QDoubleValidator'): QDoubleValidator = QtGui.QDoubleValidator
            else: print("[RemixConnector Core] PyQt5.QtGui.QDoubleValidator not found."); raise ImportError("Missing QDoubleValidator")

            QT_AVAILABLE = True; _QT_BINDING_VERSION_CORE = "PyQt5"
            print("[RemixConnector Core] Successfully initialized ALL PyQt5 components and set QT_AVAILABLE=True.")

        except ImportError as e_pyqt5_import:
            print(f"[RemixConnector Core] PyQt5 not available or component missing: {e_pyqt5_import}")
            QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None
            QT_AVAILABLE = False # Explicitly ensure QT_AVAILABLE is False if all imports fail
        except Exception as e_pyqt5_runtime: # Catch other runtime errors during PyQt5 component assignment
            print(f"[RemixConnector Core] RUNTIME ERROR during PyQt5 component initialization: {e_pyqt5_runtime}")
            QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None
            QT_AVAILABLE = False
    except Exception as e_pyside2_runtime: # Catch other runtime errors during PySide2 component assignment
        print(f"[RemixConnector Core] RUNTIME ERROR during PySide2 component initialization: {e_pyside2_runtime}")
        QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None
        QT_AVAILABLE = False
except Exception as e_pyside6_runtime: # Catch other runtime errors during PySide6 component assignment
    print(f"[RemixConnector Core] RUNTIME ERROR during PySide6 component initialization: {e_pyside6_runtime}")
    QtWidgets, QtCore, QtGui, QT_MODULE, QDialog = None, None, None, None, None
    QT_AVAILABLE = False

if not QT_AVAILABLE:
    print("[RemixConnector Core] CRITICAL: Could not import PySide6, PySide2, or PyQt5. UI elements will be unavailable or use basic placeholders.")

    class QDialogMetaclass(type):
        @property
        def Rejected(cls): return 0
        @property
        def Accepted(cls): return 1
        def __call__(cls, *args, **kwargs):
            instance = super().__call__(*args, **kwargs)
            if not hasattr(instance, '_dialog_result'):
                instance._dialog_result = cls.Rejected
            return instance

    class _QDialogBase(metaclass=QDialogMetaclass):
        def __init__(self, parent=None, **kwargs):
            self._parent = parent; self._dialog_result = _QDialogBase.Rejected
        def exec_(self): return self._dialog_result # Keep exec_ for compatibility
        def exec(self): return self._dialog_result # Add exec for PySide6 style
        def show(self): pass
        def setWindowTitle(self, title): pass
        def setLayout(self, layout): pass
        def accept(self): self._dialog_result = _QDialogBase.Accepted
        def reject(self): self._dialog_result = _QDialogBase.Rejected
    QDialog = _QDialogBase

    class _QPushButtonBase:
        def __init__(self, text="", parent=None): self._text = text; self._clicked_callbacks = []
        def clicked(self):
            class DummySignal:
                def __init__(self, button_instance): self.button = button_instance
                def connect(self, slot): self.button._clicked_callbacks.append(slot)
            return DummySignal(self)
        def _do_click(self):
            for cb in self._clicked_callbacks: cb()
    QPushButton = _QPushButtonBase

    class _QVBoxLayoutBase:
        def __init__(self, parent=None): self._widgets = []
        def addWidget(self, widget): self._widgets.append(widget)
        def addLayout(self, layout): self._widgets.append(layout) # Basic handling
        def addStretch(self): pass
    QVBoxLayout = _QVBoxLayoutBase

    class _QHBoxLayoutBase(_QVBoxLayoutBase): pass
    QHBoxLayout = _QHBoxLayoutBase

    class _QLabelBase:
        def __init__(self, text="", parent=None): self._text = text
    QLabel = _QLabelBase

    class _QWidgetBase:
        def __init__(self, parent=None): pass
    QWidget = _QWidgetBase

    class _QScrollAreaBase(QWidget):
        def __init__(self, parent=None): super().__init__(parent); self._widget = None
        def setWidgetResizable(self, resizable): pass
        def setWidget(self, widget): self._widget = widget
        def widget(self): return self._widget
    QScrollArea = _QScrollAreaBase

    class _QFormLayoutBase:
        def __init__(self, parent=None): self._rows = []
        def addRow(self, label, field): self._rows.append((label, field))
    QFormLayout = _QFormLayoutBase

    class _QCheckBoxBase(QWidget):
        def __init__(self, text="", parent=None): super().__init__(parent); self._text = text; self._checked = False
        def isChecked(self): return self._checked
        def setChecked(self, checked): self._checked = checked
        def text(self): return self._text # Added for completeness
    QCheckBox = _QCheckBoxBase

    class _QComboBoxBase(QWidget):
        def __init__(self, parent=None): super().__init__(parent); self._items = []; self._current_index = -1
        def addItems(self, items): self._items.extend(items)
        def findText(self, text, flags=None):
            try: return self._items.index(text)
            except ValueError: return -1
        def setCurrentIndex(self, index): self._current_index = index
        def currentText(self): return self._items[self._current_index] if 0 <= self._current_index < len(self._items) else ""
        def currentIndex(self): return self._current_index
    QComboBox = _QComboBoxBase

    class _QLineEditBase(QWidget):
        def __init__(self, text="", parent=None): super().__init__(parent); self._text = text
        def text(self): return self._text
        def setText(self, text): self._text = text
        def setValidator(self, validator): pass
    QLineEdit = _QLineEditBase

    class DummyQtCore:
        class Qt: MatchFixedString = 0
    QtCore = DummyQtCore()

    class _QValidatorBase:
        def __init__(self, parent=None): pass
    class _QIntValidatorBase(_QValidatorBase):
        def __init__(self, bottom=0, top=99, parent=None): super().__init__(parent)
    QIntValidator = _QIntValidatorBase

    class _QDoubleValidatorBase(_QValidatorBase):
        def __init__(self, bottom=0.0, top=99.0, decimals=2, parent=None): super().__init__(parent)
    QDoubleValidator = _QDoubleValidatorBase

    class DummyQtWidgetsModule:
        QDialog = QDialog; QPushButton = QPushButton; QVBoxLayout = QVBoxLayout
        QHBoxLayout = QHBoxLayout; QLabel = QLabel; QScrollArea = QScrollArea
        QWidget = QWidget; QFormLayout = QFormLayout; QCheckBox = QCheckBox
        QComboBox = QComboBox; QLineEdit = QLineEdit
    QtWidgets = DummyQtWidgetsModule()

    class DummyQtGuiModule:
        QIntValidator = QIntValidator
        QDoubleValidator = QDoubleValidator
    QtGui = DummyQtGuiModule()

_create_settings_dialog_func = None
settings_dialog_available = False
_settings_dialog_import_error_message = ""

try:
    from settings_dialog import create_settings_dialog_instance as _ImportedSettingsDialogFactory
    _create_settings_dialog_func = _ImportedSettingsDialogFactory
    settings_dialog_available = True
    print("[RemixConnector Core] Successfully imported SettingsDialog factory 'create_settings_dialog_instance' from settings_dialog module.")
except ImportError as e_dialog_factory:
    _settings_dialog_import_error_message = f"ImportError for settings_dialog.create_settings_dialog_instance: {e_dialog_factory}"
    print(f"[RemixConnector Core] INFO: Could not import SettingsDialog factory: {e_dialog_factory}. Placeholder will be used.")
except Exception as e_general_factory_import:
    _settings_dialog_import_error_message = f"General Exception during import of settings_dialog.create_settings_dialog_instance: {e_general_factory_import}"
    print(f"[RemixConnector Core] CRITICAL ERROR importing SettingsDialog factory: {e_general_factory_import}. Placeholder will be used.")

class CorePlaceholderSettingsDialog(QDialog):
    def __init__(self, current_settings, parent=None, import_failure_reason=""):
        super().__init__(parent)
        self._current_settings = current_settings

        if not QT_AVAILABLE:
            print("[RemixConnector Core] CorePlaceholderSettingsDialog: Qt not available, UI cannot be properly shown.")
            if hasattr(self, 'reject') and callable(self.reject): self.reject()
            return

        self.setWindowTitle("Remix Connector Settings (Placeholder)")
        main_message = "The main Settings Dialog component could not be loaded."
        if import_failure_reason: main_message += f"\nSpecific Error: {import_failure_reason}"
        detailed_instruction = (
            "\nThis is a basic placeholder. The primary settings UI failed to load.\n"
            "This might be due to issues with Qt library access or the dialog script itself.\n"
            "No settings can be changed through this placeholder window."
        )
        full_message = f"{main_message}\n\n{detailed_instruction}"

        self.layout_internal = QVBoxLayout(self)
        self.label_internal = QLabel(full_message, self)
        self.layout_internal.addWidget(self.label_internal)
        self.ok_button = QPushButton("OK", self)

        if hasattr(self.ok_button, 'clicked'):
            try:
                self.ok_button.clicked.connect(self.accept)
                log_debug("[CorePlaceholderSettingsDialog] Connected button signal.")
            except Exception as e_connect:
                log_warning(f"[CorePlaceholderSettingsDialog] Error connecting 'ok_button.clicked': {e_connect}")
        else:
            log_warning("[CorePlaceholderSettingsDialog] 'ok_button' has no 'clicked' attribute.")

        self.layout_internal.addWidget(self.ok_button)
        self.setLayout(self.layout_internal)

    def exec_(self):
        return super().exec_()

    def get_settings(self):
        return self._current_settings

SETTINGS_FILE_PATH = None
def get_settings_file_path():
    """
    Determines the settings file path. Per user requirements, this will be
    'settings.json' located in the same directory as this script.
    This new version is simplified to remove all hardcoded folder and file names.
    """
    global SETTINGS_FILE_PATH
    if SETTINGS_FILE_PATH:
        return SETTINGS_FILE_PATH

    try:
        # This is the correct and simple logic.
        # It finds the directory where this script (core.py) is located.
        plugin_script_dir = os.path.dirname(os.path.abspath(__file__))

        # It joins that directory with the desired filename "settings.json".
        # No new folders are created. The filename is correct.
        final_path = os.path.join(plugin_script_dir, "settings.json")
        
        SETTINGS_FILE_PATH = final_path
        return SETTINGS_FILE_PATH
    except Exception as e:
        # This is a robust fallback in case __file__ is not available,
        # though it's very unlikely in this context.
        print(f"[RemixConnector Core] CRITICAL: Could not determine script directory to store settings.json: {e}")
        # Fallback to a temp directory to avoid crashing, but this is a degraded state.
        fallback_path = os.path.join(tempfile.gettempdir(), "remix_connector_settings_fallback.json")
        SETTINGS_FILE_PATH = fallback_path
        print(f"[RemixConnector Core] Using temporary fallback settings file: {fallback_path}")
        return fallback_path


def load_plugin_settings():
    global PLUGIN_SETTINGS
    s_file_path = get_settings_file_path()
    log_info(f"Attempting to load settings from: {s_file_path}")
    try:
        if os.path.exists(s_file_path):
            with open(s_file_path, 'r') as f:
                loaded_settings_from_file = json.load(f)
            temp_updated_settings = PLUGIN_SETTINGS.copy()
            for key, default_value in PLUGIN_SETTINGS.items():
                if key in loaded_settings_from_file:
                    loaded_value = loaded_settings_from_file[key]
                    if isinstance(default_value, bool) and isinstance(loaded_value, str):
                        if loaded_value.lower() == 'true': temp_updated_settings[key] = True
                        elif loaded_value.lower() == 'false': temp_updated_settings[key] = False
                        else: log_warning(f"Setting '{key}' from file has non-boolean string '{loaded_value}' for a boolean default. Using default.")
                    elif isinstance(default_value, (int, float)) and isinstance(loaded_value, str):
                        try:
                            if isinstance(default_value, float): temp_updated_settings[key] = float(loaded_value)
                            else: temp_updated_settings[key] = int(loaded_value)
                        except ValueError:
                            log_warning(f"Setting '{key}' from file ('{loaded_value}') could not be converted to number. Using default.")
                    elif type(default_value) == type(loaded_value) or loaded_value is None:
                        temp_updated_settings[key] = loaded_value
                    else:
                        log_warning(f"Type mismatch for setting '{key}' from file (Default: {type(default_value)}, File: {type(loaded_value)}). Using default value.")
            PLUGIN_SETTINGS = temp_updated_settings
            log_info(f"Successfully merged settings from file. Current log level: {PLUGIN_SETTINGS.get('log_level')}")
        else:
            log_info(f"Settings file not found at '{s_file_path}'. Using default settings. File will be created on next save.")
            save_plugin_settings()
    except json.JSONDecodeError as json_e:
        log_error(f"Error decoding JSON from {s_file_path}: {json_e}. Using default settings. Problematic file may be overwritten on save.", exc_info=True)
    except Exception as e:
        log_error(f"Error loading settings from {s_file_path}: {e}. Using default settings.", exc_info=True)
    
    # --- NEW: Auto-detect texconv.exe ---
    # After loading settings, check if texconv_path is valid. If not, try to find it bundled with the plugin.
    user_set_path = PLUGIN_SETTINGS.get("texconv_path")
    if not user_set_path or not os.path.isfile(user_set_path):
        if user_set_path:
            log_warning(f"User-configured texconv.exe path is invalid: '{user_set_path}'. Attempting auto-detection.")
        else:
            log_info("Texconv.exe path not set. Attempting auto-detection...")
        
        try:
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            bundled_texconv_path = os.path.join(plugin_dir, "texconv.exe")
            if os.path.isfile(bundled_texconv_path):
                log_info(f"Auto-detected and using bundled texconv.exe: {bundled_texconv_path}")
                PLUGIN_SETTINGS["texconv_path"] = bundled_texconv_path
            else:
                log_warning("Could not auto-detect 'texconv.exe' in the plugin folder. DDS import will fail.")
        except Exception as e:
            log_error(f"An error occurred during texconv.exe auto-detection: {e}")


def save_plugin_settings():
    s_file_path = get_settings_file_path()
    log_info(f"Saving settings to: {s_file_path}")
    try:
        settings_dir = os.path.dirname(s_file_path)
        if not os.path.exists(settings_dir):
            os.makedirs(settings_dir, exist_ok=True)
            log_info(f"Created settings directory: {settings_dir}")
        with open(s_file_path, 'w') as f:
            json.dump(PLUGIN_SETTINGS, f, indent=4, sort_keys=True)
        log_info("Settings saved successfully.")
    except Exception as e:
        log_error(f"Error saving settings to {s_file_path}: {e}", exc_info=True)
        display_message_safe(f"Error: Could not save settings to {s_file_path}. Changes might be lost.")

try:
    from PIL import Image, UnidentifiedImageError, __version__ as PIL_VERSION
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    PIL_VERSION = "Not Installed"
    class Image:
        @staticmethod
        def open(path): raise ImportError("Pillow library is not installed.")
    class UnidentifiedImageError(Exception): pass

import substance_painter.logging
import substance_painter.project
import substance_painter.export
import substance_painter.resource
import substance_painter.textureset

try:
    from substance_painter.export import TextureExportResult, ExportStatus
except ImportError:
    substance_painter.logging.warning("[RemixConnector Core] Could not import TextureExportResult or ExportStatus. Export might fail if API relies on them.")
    TextureExportResult = type('TextureExportResult', (object,), {})
    class ExportStatus: Success = "success"

_ResourceType_enum_obj = None
_SHADER_TYPE_CMP_VALUE = None
try:
    from substance_painter.resource import ResourceType as ResourceTypeActual
    if hasattr(ResourceTypeActual, 'SHADER'):
        _ResourceType_enum_obj = ResourceTypeActual
        _SHADER_TYPE_CMP_VALUE = ResourceTypeActual.SHADER
        substance_painter.logging.info("[RemixConnector Core] Imported 'substance_painter.resource.ResourceType' with .SHADER.")
    else:
        substance_painter.logging.warning("[RemixConnector Core] 'substance_painter.resource.ResourceType' missing .SHADER.")
except ImportError:
    substance_painter.logging.warning("[RemixConnector Core] Could not import 'substance_painter.resource.ResourceType'. Trying 'Type'.")
    try:
        from substance_painter.resource import Type as ResourceTypeFallback
        if hasattr(ResourceTypeFallback, 'SHADER'):
            _ResourceType_enum_obj = ResourceTypeFallback
            _SHADER_TYPE_CMP_VALUE = ResourceTypeFallback.SHADER
            substance_painter.logging.info("[RemixConnector Core] Imported 'substance_painter.resource.Type' as fallback with .SHADER.")
        else:
            substance_painter.logging.warning("[RemixConnector Core] 'substance_painter.resource.Type' as fallback missing .SHADER.")
    except ImportError:
        substance_painter.logging.warning("[RemixConnector Core] Could not import 'substance_painter.resource.Type' either.")
if _SHADER_TYPE_CMP_VALUE is None:
    substance_painter.logging.error("[RemixConnector Core] Failed to get valid .SHADER enum. Shader ID will use fallbacks.")

_set_channel_texture_resource_func = None
try:
    from substance_painter.textureset import TextureSet, Channel, Stack, ChannelType, Resolution, ChannelFormat
    from substance_painter.resource import Resource, ResourceID

    if hasattr(substance_painter.textureset, 'set_channel_texture_resource'):
        from substance_painter.textureset import set_channel_texture_resource
        _set_channel_texture_resource_func = set_channel_texture_resource
        substance_painter.logging.debug("[RemixConnector Core] Imported and will use 'substance_painter.textureset.set_channel_texture_resource'.")
    else:
        _set_channel_texture_resource_func = None
        substance_painter.logging.warning("[RemixConnector Core] 'set_channel_texture_resource' not found. Automatic texture assignment to channels will be disabled.")

except ImportError as e:
    substance_painter.logging.error(f"[RemixConnector Core] Core API import failed (e.g., TextureSet, Channel, ResourceID): {e}. Automatic texture assignment to channels will be disabled.")
    TextureSet, Channel, Stack, ChannelType, Resolution, Resource, ResourceID, ChannelFormat = (type(n, (object,), {}) for n in ['TextureSet', 'Channel', 'Stack', 'ChannelType', 'Resolution', 'Resource', 'ResourceID', 'ChannelFormat'])

try:
    import substance_painter.ui
    ui_available = True
except ImportError:
    substance_painter.logging.warning("[RemixConnector Core] substance_painter.ui module not available.")
    ui_available = False

try:
    import requests
    requests_available = True
except ImportError:
    requests = None; requests_available = False
    substance_painter.logging.warning("[RemixConnector Core] 'requests' library not initially found.")

DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_POLL_TIMEOUT_SECONDS = 60.0
DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"
REMIX_INGEST_API_URL = f"{DEFAULT_REMIX_API_BASE_URL}/ingestcraft/mass-validator/queue/material"
DEFAULT_PAINTER_EXPORT_PATH = os.path.join(tempfile.gettempdir(), "RemixConnector_Export")

PLUGIN_SETTINGS = {
    "api_base_url": DEFAULT_REMIX_API_BASE_URL,
    "painter_export_path": DEFAULT_PAINTER_EXPORT_PATH,
    "painter_export_preset": "pbr-metal-rough-with-alpha-blending",
    "export_file_format": "png",
    "export_padding": "infinite",
    "export_filename_pattern": "$mesh_$textureSet_$channel",
    "painter_import_template_path": "",
    "poll_timeout": DEFAULT_POLL_TIMEOUT_SECONDS,
    "poll_interval": DEFAULT_POLL_INTERVAL_SECONDS,
    "log_level": "debug",
    "remix_output_subfolder": "Textures/PainterConnector_Ingested",
    "texconv_path": "",
    "blender_executable_path": "",
    "blender_unwrap_script_path": "",
    "auto_unwrap_with_blender_on_pull": True,
    "blender_unwrap_output_suffix": "_spUnwrapped",
    "blender_smart_uv_angle_limit": 66.0,
    "blender_smart_uv_island_margin": 0.003,
    "blender_smart_uv_area_weight": 0.0,
    "blender_smart_uv_stretch_to_bounds": "True",
    "use_simple_tiling_mesh_on_pull": False,
    "simple_tiling_mesh_path": "assets/meshes/plane_tiling.usd",
}

PAINTER_CHANNEL_TO_REMIX_PBR_MAP = {
    "basecolor": "albedo", "base_color": "albedo", "albedo": "albedo", "diffuse": "albedo",
    "normal": "normal", "height": "height", "displacement": "height", "roughness": "roughness",
    "metallic": "metallic", "metalness": "metallic", "emissive": "emissive", "emission": "emissive",
    "opacity": "opacity",
}
REMIX_PBR_TO_PAINTER_CHANNEL_MAP = {
    "albedo": "baseColor", "normal": "normal", "height": "height", "roughness": "roughness",
    "metallic": "metallic", "emissive": "emissive", "opacity": "opacity",
}

PAINTER_STRING_TO_CHANNELTYPE_MAP = {}
try:
    if 'ChannelType' in locals() and hasattr(substance_painter.textureset, 'ChannelType'):
        is_dummy_channel_type = (isinstance(ChannelType, type) and ChannelType.__name__ == 'ChannelType' and not hasattr(ChannelType, 'BaseColor'))
        if not is_dummy_channel_type:
            PAINTER_STRING_TO_CHANNELTYPE_MAP = {
                "baseColor": substance_painter.textureset.ChannelType.BaseColor,
                "height": substance_painter.textureset.ChannelType.Height,
                "normal": substance_painter.textureset.ChannelType.Normal,
                "roughness": substance_painter.textureset.ChannelType.Roughness,
                "metallic": substance_painter.textureset.ChannelType.Metallic,
                "emissive": substance_painter.textureset.ChannelType.Emissive,
                "opacity": substance_painter.textureset.ChannelType.Opacity,
            }
            substance_painter.logging.info("[RemixConnector Core] PAINTER_STRING_TO_CHANNELTYPE_MAP created.")
        else:
            substance_painter.logging.error("[RemixConnector Core] Cannot create PAINTER_STRING_TO_CHANNELTYPE_MAP: ChannelType is dummy.")
    else:
        substance_painter.logging.error("[RemixConnector Core] Cannot create PAINTER_STRING_TO_CHANNELTYPE_MAP: substance_painter.textureset.ChannelType not available.")
except Exception as e:
    substance_painter.logging.error(f"[RemixConnector Core] Error creating PAINTER_STRING_TO_CHANNELTYPE_MAP: {e}")

PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP = {
    "albedo": "DIFFUSE", "normal": "NORMAL_DX", "height": "HEIGHT",
    "roughness": "ROUGHNESS", "metallic": "METALLIC", "emissive": "EMISSIVE",
    "ao": "AO", "opacity": "OPACITY",
}

REMIX_ATTR_SUFFIX_TO_PBR_MAP = {
    "diffuse_texture": "albedo", "albedo_texture": "albedo", "basecolor_texture": "albedo", "base_color_texture": "albedo",
    "normalmap_texture": "normal", "normal_texture": "normal", "worldspacenormal_texture": "normal",
    "heightmap_texture": "height", "height_texture": "height", "displacement_texture": "height",
    "roughness_texture": "roughness", "reflectionroughness_texture": "roughness", "specularroughness_texture": "roughness",
    "metallic_texture": "metallic", "metalness_texture": "metallic",
    "emissive_mask_texture": "emissive", "emissive_texture": "emissive", "emissive_color_texture": "emissive",
    "opacity_texture": "opacity", "opacitymask_texture": "opacity", "opacity": "opacity", "transparency_texture": "opacity",
}

PBR_TO_MDL_INPUT_MAP = {
    "albedo": "diffuse_texture",
    "normal": "normalmap_texture",
    "height": "height_texture",
    "roughness": "reflectionroughness_texture",
    "metallic": "metallic_texture",
    "emissive": "emissive_mask_texture",
    "opacity": "opacity_texture",
}

_logger = substance_painter.logging
def log_debug(message):
    if PLUGIN_SETTINGS.get("log_level", "info").lower() == "debug":
        if hasattr(_logger, 'debug'): _logger.debug(f"[RemixConnector DEBUG] {message}")
        else: _logger.info(f"[RemixConnector DEBUG-Fallback] {message}")
def log_info(message):
    if PLUGIN_SETTINGS.get("log_level", "info").lower() in ["debug", "info"]:
         _logger.info(f"[RemixConnector INFO] {message}")
def log_warning(message):
    if PLUGIN_SETTINGS.get("log_level", "info").lower() in ["debug", "info", "warning"]:
         _logger.warning(f"[RemixConnector WARN] {message}")
def log_error(message, exc_info=False):
    log_msg = f"[RemixConnector ERROR] {message}"
    if exc_info: log_msg += f"\nTraceback:\n{traceback.format_exc()}"
    if hasattr(_logger, 'error'): _logger.error(log_msg)
    else: _logger.info(log_msg)

def get_painter_python_executable():
    try:
        painter_base_dir = os.path.dirname(sys.executable)
        potential_paths = [
            os.path.join(painter_base_dir, "resources", "pythonsdk", "python.exe"),
            os.path.join(painter_base_dir, "Contents", "Resources", "pythonsdk", "bin", "python3"),
            os.path.join(painter_base_dir, "pythonsdk", "python"),
        ]
        for py_sdk_path in potential_paths:
            if os.path.isfile(py_sdk_path):
                log_debug(f"Found Painter Python SDK at: {py_sdk_path}")
                return py_sdk_path
        log_warning("Painter's python.exe not found in typical 'resources/pythonsdk'.")
        return "python.exe"
    except Exception as e:
        log_error(f"Error detecting Painter's Python executable: {e}. Falling back to 'python.exe'.")
        return "python.exe"

def check_pillow_installation():
    if PIL_AVAILABLE:
        log_info(f"Pillow (PIL) installed: Yes (Version: {PIL_VERSION})")
        return True
    log_warning("--- Pillow (PIL) Dependency ---")
    log_warning("Pillow library not installed. This is often required for advanced image operations.")
    py_exe = get_painter_python_executable()
    if py_exe and "python.exe" not in py_exe.lower() and "python3" not in py_exe.lower() and "python" not in py_exe.lower() :
        log_warning(f"Could not reliably determine Painter's Python executable path (got: {py_exe}).")
        log_warning("Manual installation of Pillow into Painter's Python site-packages might be needed.")
    elif py_exe:
        py_dir = os.path.dirname(py_exe)
        site_packages_paths_to_try = [
            os.path.join(py_dir, 'Lib', 'site-packages'),
            os.path.join(os.path.dirname(py_dir), 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages'),
        ]
        site_packages_path_found = next((sp_path for sp_path in site_packages_paths_to_try if os.path.isdir(sp_path)), None)
        if site_packages_path_found:
            log_warning(f"To install Pillow (if needed): Open a command prompt/terminal, then run:")
            log_warning(f"  \"{py_exe}\" -m pip install --upgrade --target=\"{site_packages_path_found}\" Pillow")
        else:
            log_warning(f"Could not determine site-packages path for Painter's Python ({py_exe}).")
    log_warning("Please restart Substance Painter after installing any new Python packages.")
    log_warning("---")
    return False

def setup_logging():
    load_plugin_settings()
    log_info(f"Remix Connector logging initialized (Level: {PLUGIN_SETTINGS.get('log_level', 'info')}). Settings loaded from: {SETTINGS_FILE_PATH or 'Unknown (defaults used)'}")
    check_pillow_installation()

def check_requests_dependency():
    global requests_available, requests
    if not requests_available or requests is None:
        try:
            import requests as req_check
            requests = req_check
            requests_available = True
            log_info("'requests' library became available after initial check (or was already).")
            return True
        except ImportError:
            log_error("'requests' library not available. Network operations will fail.")
            requests_available = False
            return False
    return True

def display_message_safe(message, msg_type_enum=None):
    if ui_available and hasattr(substance_painter.ui, 'display_message') and callable(substance_painter.ui.display_message):
        try:
            substance_painter.ui.display_message(str(message))
        except Exception as e:
            log_warning(f"Failed to display UI message via substance_painter.ui: {e}. Logging message instead: {message}", exc_info=True)
    else:
        log_info(f"UI Fallback (display_message): {message}")

def safe_basename(path):
    if not path: return ""
    try: return ntpath.basename(str(path))
    except Exception as e:
        log_warning(f"safe_basename failed for path '{path}': {e}. Returning raw path string.")
        return str(path)

def convert_dds_to_png(texconv_exe, dds_file, output_png_target_name_base):
    if not texconv_exe or not os.path.isfile(texconv_exe): raise RuntimeError(f"texconv.exe path is not configured or invalid: {texconv_exe}")
    if not os.path.isfile(dds_file): raise RuntimeError(f"Input DDS file not found: {dds_file}")

    output_dir = os.path.dirname(dds_file)
    os.makedirs(output_dir, exist_ok=True)

    # texconv simply replaces the last extension. e.g., "foo.rtex.dds" becomes "foo.rtex.png".
    base_name = os.path.splitext(safe_basename(dds_file))[0]
    expected_output_filename = base_name + ".png"

    expected_output_path = os.path.join(output_dir, expected_output_filename)
    command = [texconv_exe, "-ft", "png", "-o", output_dir, "-y", "-nologo", dds_file]
    log_info(f"  Running texconv command: {' '.join(command)}")
    try:
        startupinfo, creationflags = None, 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(command, capture_output=True, text=True, check=False, startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore')

        if result.returncode != 0:
            error_message = f"texconv failed (return code {result.returncode}) for {safe_basename(dds_file)}.\nStderr: {result.stderr.strip()}\nStdout: {result.stdout.strip()}"
            log_error(error_message)
            raise RuntimeError(error_message)

        log_info(f"  texconv execution successful for {safe_basename(dds_file)}. Expected output: {expected_output_path}")

        if not os.path.exists(expected_output_path):
            extra_info = f"\nStdout: {result.stdout.strip()}\nStderr: {result.stderr.strip()}" if result.stdout or result.stderr else ""
            raise RuntimeError(f"texconv reported success, but the expected output PNG file was not found: {expected_output_path}{extra_info}")
        return expected_output_path
    except FileNotFoundError: raise RuntimeError(f"texconv command failed. Ensure '{texconv_exe}' is a valid executable.")
    except Exception as e: raise RuntimeError(f"An error occurred while running texconv: {e}")

def _get_blender_unwrap_script_path():
    script_path_setting = PLUGIN_SETTINGS.get("blender_unwrap_script_path")
    if script_path_setting and os.path.isfile(script_path_setting):
        log_debug(f"Using Blender unwrap script from settings: {script_path_setting}")
        return script_path_setting
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path_default = os.path.join(current_dir, "blender_auto_unwrap.py")
        if os.path.isfile(script_path_default):
            log_debug(f"Using default Blender unwrap script (found next to core.py): {script_path_default}")
            return script_path_default
    except Exception as e:
        log_warning(f"Error determining default blender_auto_unwrap.py path: {e}")
    log_error(f"Blender unwrap script 'blender_auto_unwrap.py' not found.")
    return None

def unwrap_mesh_with_blender(input_mesh_path: str) -> str | None:
    log_info(f"Attempting to unwrap mesh with Blender: {safe_basename(input_mesh_path)}")
    blender_exe = PLUGIN_SETTINGS.get("blender_executable_path")
    unwrap_script_path = _get_blender_unwrap_script_path()

    if not blender_exe or not os.path.isfile(blender_exe):
        log_error(f"Blender executable path not configured or invalid: '{blender_exe}'.")
        display_message_safe("Error: Blender executable path is not set or invalid. Auto-unwrap skipped.")
        return None
    if not unwrap_script_path:
        display_message_safe("Error: Blender unwrap script not found. Auto-unwrap skipped.")
        return None

    base, ext = os.path.splitext(input_mesh_path)
    output_suffix = PLUGIN_SETTINGS.get("blender_unwrap_output_suffix", "_spUnwrapped")
    output_mesh_path = f"{base}{output_suffix}{ext}"
    args_for_blender_script = [
        "--angle_limit", str(PLUGIN_SETTINGS.get("blender_smart_uv_angle_limit", 66.0)),
        "--island_margin", str(PLUGIN_SETTINGS.get("blender_smart_uv_island_margin", 0.003)),
        "--area_weight", str(PLUGIN_SETTINGS.get("blender_smart_uv_area_weight", 0.0)),
        "--stretch_to_bounds", str(PLUGIN_SETTINGS.get("blender_smart_uv_stretch_to_bounds", "False"))
    ]
    command = [blender_exe, "--background", "--python", unwrap_script_path, "--", input_mesh_path, output_mesh_path] + args_for_blender_script
    log_info(f"  Executing Blender command: {' '.join(command)}")
    try:
        startupinfo, creationflags = None, 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(command, capture_output=True, text=True, check=False, startupinfo=startupinfo, creationflags=creationflags, encoding='utf-8', errors='ignore')
        log_level = "error" if result.returncode != 0 or "BlenderScript: ERROR:" in result.stdout or "Error: Python script fail" in result.stderr else "info"
        if result.stdout and result.stdout.strip():
            getattr(sys.modules[__name__], f"log_{log_level}")(f"  Blender stdout (Code: {result.returncode}):\n{result.stdout.strip()}")
        if result.stderr and result.stderr.strip():
            log_warning(f"  Blender stderr:\n{result.stderr.strip()}")

        if log_level == "info" and os.path.exists(output_mesh_path):
            log_info(f"Blender unwrapping successful. Output: {output_mesh_path}")
            return output_mesh_path
        else:
            log_error(f"Blender unwrapping script failed (Code: {result.returncode}). Output exists: {os.path.exists(output_mesh_path)}")
            display_message_safe("Error: Blender auto-unwrap process failed. See logs for details.")
            return None
    except FileNotFoundError:
        log_error(f"Blender command failed. Ensure executable path '{blender_exe}' is correct.")
        display_message_safe(f"Error: Blender executable not found at '{blender_exe}'.")
        return None
    except Exception as e:
        log_error(f"An unexpected error occurred while running Blender for unwrapping: {e}", exc_info=True)
        display_message_safe(f"Error: An unexpected error occurred during Blender auto-unwrap: {e}")
        return None

def make_remix_request_with_retries(method, url_endpoint, headers=None, json_payload=None, params=None, retries=3, delay=2, timeout=None, verify_ssl=False):
    if not check_requests_dependency():
        return {"success": False, "status_code": 0, "data": None, "error": "'requests' library not available."}

    effective_timeout = timeout if timeout is not None else PLUGIN_SETTINGS.get("poll_timeout", DEFAULT_POLL_TIMEOUT_SECONDS)
    try:
        current_api_base = PLUGIN_SETTINGS.get("api_base_url", DEFAULT_REMIX_API_BASE_URL).rstrip('/')
        global REMIX_INGEST_API_URL
        REMIX_INGEST_API_URL = f"{current_api_base}/ingestcraft/mass-validator/queue/material"
        full_url = f"{current_api_base}/{url_endpoint.lstrip('/')}"
    except Exception as e:
        log_error(f"URL construction error: {e}")
        return {"success": False, "status_code": 0, "data": None, "error": "URL construction error."}

    base_headers = {'Accept': 'application/lightspeed.remix.service+json; version=1.0'}
    if json_payload is not None and 'Content-Type' not in (headers or {}):
        base_headers['Content-Type'] = 'application/lightspeed.remix.service+json; version=1.0'
    effective_headers = {**base_headers, **(headers or {})}

    log_debug(f"API Request: {method.upper()} {full_url}")
    if params: log_debug(f"  Params: {params}")
    if json_payload: log_debug(f"  Payload (brief): {str(json_payload)[:200]}...")
    last_error_message = "Request failed after multiple retries."

    for attempt in range(1, retries + 1):
        log_debug(f"  Attempt {attempt}/{retries}...")
        try:
            response = requests.request(method, full_url, headers=effective_headers, json=json_payload, params=params, timeout=effective_timeout, verify=verify_ssl)
            log_debug(f"  Response Status: {response.status_code}")
            response_data, response_text_preview = None, ""
            try:
                if response.content: response_data = response.json()
            except json.JSONDecodeError:
                log_debug("  Response content is not valid JSON.")
                try: response_text_preview = response.text[:200] + ("..." if len(response.text) > 200 else "")
                except Exception as text_e: response_text_preview = f"<Error decoding text: {text_e}>"
                log_debug(f"  Response Text (preview): {response_text_preview}")
            except Exception as e_resp_proc:
                log_warning(f"  Error processing response content: {e_resp_proc}")
                response_text_preview = "<Error processing content>"

            if 200 <= response.status_code < 300:
                return {"success": True, "status_code": response.status_code, "data": response_data if response_data is not None else response.text, "error": None}
            else:
                error_prefix = f"API Error (Status: {response.status_code})"
                error_details = response_data or (response_text_preview or "<No response body>")
                error_details_str = json.dumps(error_details, indent=2) if isinstance(error_details, (dict, list)) else str(error_details)
                log_warning(f"  {error_prefix}. Details (brief): {error_details_str[:1000]}")
                if json_payload: log_warning(f"    Request Payload that caused error (brief): {str(json_payload)[:200]}...")
                last_error_message = f"{error_prefix}: {error_details_str}"
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    return {"success": False, "status_code": response.status_code, "data": error_details, "error": last_error_message}
        except requests.exceptions.Timeout:
            last_error_message = f"Request timed out after {effective_timeout}s."
            log_warning(f"  Timeout on attempt {attempt}.")
        except requests.exceptions.ConnectionError as e:
            last_error_message = f"Connection Error: {e}"
            log_warning(f"  ConnectionError on attempt {attempt}: {e}. Retrying in {delay*2}s...")
            time.sleep(delay*2)
            continue
        except requests.exceptions.RequestException as e:
            last_error_message = f"A general Request Exception occurred: {e}"
            log_error(f"  RequestException on attempt {attempt}: {e}", exc_info=True)
        if attempt < retries:
            log_debug(f"  Retrying in {delay}s...")
            time.sleep(delay)
        else: break
    return {"success": False, "status_code": 0, "data": None, "error": last_error_message}

def get_remix_project_default_output_dir():
    log_info("Getting Remix project default output directory...")
    result = make_remix_request_with_retries('GET', "/stagecraft/assets/default-directory")

    if result["success"] and isinstance(result.get("data"), dict):
        default_dir_raw = result["data"].get("directory_path") or result["data"].get("asset_path")
        log_debug(f"[get_remix_project_default_output_dir] After checks, default_dir_raw: '{default_dir_raw}'.")
        if isinstance(default_dir_raw, str):
            try:
                default_dir_abs = os.path.abspath(os.path.normpath(default_dir_raw))
                log_info(f"Remix default output directory resolved to: '{default_dir_abs}'")
                return default_dir_abs, None
            except Exception as e:
                log_error(f"Error processing default directory path '{default_dir_raw}': {e}", exc_info=True)
                return None, f"Error processing path: {e}"
        else:
            err_msg = "API success but expected directory path missing or not a string in response data."
            log_error(f"{err_msg} Data: {result.get('data')}")
            return None, err_msg
    err_msg = result['error'] or "Failed to get default directory from Remix API."
    log_error(f"Error getting default directory (Status: {result.get('status_code', 'N/A')}): {err_msg}")
    return None, err_msg

def get_material_from_mesh(mesh_prim_path):
    log_info(f"Attempting to find material bound to mesh: {safe_basename(mesh_prim_path)}")
    if not mesh_prim_path: return None, "Mesh prim path cannot be empty."
    try:
        encoded_mesh_path = urllib.parse.quote(mesh_prim_path.replace(os.sep, '/'), safe='/')
        result = make_remix_request_with_retries('GET', f"/stagecraft/assets/{encoded_mesh_path}/material")
        if result["success"] and isinstance(result.get("data"), dict):
            material_path_raw = result["data"].get("asset_path")
            if isinstance(material_path_raw, str):
                material_path = material_path_raw.replace('\\', '/')
                log_info(f"Found material bound to '{safe_basename(mesh_prim_path)}': {material_path}")
                return material_path, None
            else: return None, "API success, but 'asset_path' for material missing or invalid."
        status, error_api = result.get('status_code'), result.get('error', "Unknown error from API.")
        if status == 404:
            log_info(f"No material found bound to mesh '{safe_basename(mesh_prim_path)}'.")
            return None, f"No material is currently bound to the mesh '{safe_basename(mesh_prim_path)}'."
        else:
            log_error(f"Error querying bound material for '{safe_basename(mesh_prim_path)}' (Status: {status}): {error_api}")
            return None, f"Failed to query bound material (Status: {status}): {error_api}"
    except Exception as e:
        log_error(f"Unexpected exception querying bound material: {e}", exc_info=True)
        return None, f"Exception during material query: {e}"

def _get_mesh_file_path_from_prim(prim_path_to_query: str) -> tuple[str | None, str | None, str | None, int]:
    if not prim_path_to_query: return None, None, "Prim path cannot be empty.", 0
    log_info(f"Querying file paths for prim: '{prim_path_to_query}'")
    mesh_file_path, context_abs_path, error_message = None, None, None
    status_code = 0
    try:
        encoded_prim_path = urllib.parse.quote(prim_path_to_query.replace(os.sep, '/'), safe='/')
        paths_result = make_remix_request_with_retries('GET', f"/stagecraft/assets/{encoded_prim_path}/file-paths")
        status_code = paths_result.get('status_code', 0)

        if paths_result.get("success") and isinstance(paths_result.get("data"), dict):
            potential_paths_data = paths_result["data"].get("reference_paths", paths_result["data"].get("asset_paths", []))
            log_debug(f"  Potential paths data from API for '{prim_path_to_query}': {potential_paths_data}")

            abs_context_path_candidate = None
            relative_mesh_path_candidate = None

            for entry in potential_paths_data:
                files_to_check = []
                if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str) and isinstance(entry[1], list):
                    files_to_check = entry[1]
                elif isinstance(entry, list) and all(isinstance(item, str) for item in entry):
                    files_to_check = entry
                elif isinstance(entry, str):
                    files_to_check = [entry]

                # In the list of files, find one absolute path (our context) and one relative mesh path.
                for file_path_str in files_to_check:
                    if isinstance(file_path_str, str):
                        if os.path.isabs(file_path_str):
                            abs_context_path_candidate = file_path_str.replace('\\', '/')
                        elif any(file_path_str.lower().endswith(ext) for ext in ['.usd', '.usda', '.usdc', '.obj', '.fbx', '.gltf', '.glb']):
                            relative_mesh_path_candidate = file_path_str.replace('\\', '/')
                
                if abs_context_path_candidate and relative_mesh_path_candidate:
                    break
            
            if relative_mesh_path_candidate:
                mesh_file_path = relative_mesh_path_candidate
                context_abs_path = abs_context_path_candidate
                log_info(f"  Found relative mesh path: '{mesh_file_path}' with context file: '{context_abs_path}'")
            else:
                error_message = f"Could not determine both a relative mesh and absolute context path for prim '{prim_path_to_query}'."

        else:
            error_message = f"API request for file paths failed (Status: {status_code}): {paths_result.get('error', 'Query failed.')}"
    except Exception as e:
        error_message = f"Exception querying file paths for prim '{prim_path_to_query}': {e}"
        log_error(error_message, exc_info=True)
        
    return mesh_file_path, context_abs_path, error_message, status_code


def _extract_definition_path(prim_path: str) -> str | None:
    if not prim_path: return None
    prim_path_norm = prim_path.replace('\\', '/')
    instance_match = re.match(r"^(.*)/instances/inst_([A-Z0-9]{16}(?:_[0-9]+)?)(?:_[0-9]+)?(?:/.*)?$", prim_path_norm)
    if instance_match:
        base_path, mesh_id_part = instance_match.groups()
        definition_path = f"{base_path}/meshes/mesh_{mesh_id_part}"
        log_debug(f"  Extracted definition path from instance '{prim_path_norm}': {definition_path}")
        return definition_path
    mesh_subpath_match = re.match(r"^(.*(?:/meshes|/Mesh|/Geom)/mesh_[A-Z0-9]{16}(?:_[0-9]+)?)(?:/.*)?$", prim_path_norm)
    if mesh_subpath_match:
        definition_path = mesh_subpath_match.group(1)
        log_debug(f"  Path '{prim_path_norm}' seems to be within or is a mesh definition: {definition_path}")
        return definition_path
    log_debug(f"  Could not extract a standard definition path from '{prim_path_norm}'.")
    return None

def get_selected_remix_asset_details() -> tuple[str | None, str | None, str | None, str | None]:
    log_info("Getting selected asset details from Remix...")
    result = make_remix_request_with_retries('GET', "/stagecraft/assets/", params={"selection": "true", "filter_session_assets": "false", "exists": "true"})
    if not result["success"]:
        error_msg = result['error'] or "API request to get selected assets failed."
        log_error(f"Failed to get selected assets: {error_msg} (Status: {result.get('status_code')})")
        return None, None, None, f"Selection Error: {error_msg}"
    asset_paths = result.get("data", {}).get("prim_paths", result.get("data", {}).get("asset_paths", []))
    if not asset_paths: return None, None, None, "No assets are currently selected in Remix."
    log_debug(f"  Selected asset paths from API: {asset_paths}")
    material_prim, mesh_prim_initial = None, None
    for path in asset_paths:
        p_norm = path.replace('\\', '/')
        if p_norm.endswith("/Shader"):
            material_prim = os.path.dirname(p_norm)
            log_info(f"  Identified Material Prim (from Shader): {material_prim}")
            continue
        if ("/Looks/" in p_norm or "/materials/" in p_norm or "/Material/" in p_norm) and "/PreviewSurface" not in p_norm and not material_prim:
            material_prim = p_norm
            log_info(f"  Identified Material Prim (pattern): {material_prim}")
            continue
        is_mesh_like = "/instances/inst_" in p_norm or "/meshes/" in p_norm or "/Mesh/" in p_norm or "/Geom/" in p_norm
        if is_mesh_like and not mesh_prim_initial:
            mesh_prim_initial = p_norm
            log_info(f"  Identified Mesh Prim (Instance/Def): {mesh_prim_initial}")
            
    if mesh_prim_initial and not material_prim:
        log_info(f"  Mesh '{safe_basename(mesh_prim_initial)}' selected, querying bound material...")
        path_for_mat_lookup = _extract_definition_path(mesh_prim_initial) or mesh_prim_initial
        material_prim, err = get_material_from_mesh(path_for_mat_lookup)
        if err or not material_prim:
            return None, None, None, f"Mesh selected, but failed to find its material: {err or 'No path returned.'}"
    
    if not material_prim: return None, None, None, "Could not identify a Material Prim from selection."

    prim_paths_to_try = []
    if mesh_prim_initial:
        prim_paths_to_try.append(mesh_prim_initial)
        def_path = _extract_definition_path(mesh_prim_initial)
        if def_path and def_path not in prim_paths_to_try: prim_paths_to_try.append(def_path)
    if material_prim not in prim_paths_to_try: prim_paths_to_try.append(material_prim)
    
    mesh_file_path, context_file_path, last_error = None, None, "Mesh path query not attempted."
    for prim_to_query in prim_paths_to_try:
        log_info(f"  Querying mesh file path from prim: '{prim_to_query}'")
        m_file, ctx_file, err, status = _get_mesh_file_path_from_prim(prim_to_query)
        last_error = err or f"Query for '{prim_to_query}' returned no error but no path (Status: {status})."
        if m_file:
            mesh_file_path, context_file_path = m_file, ctx_file
            log_info(f"  Successfully determined mesh file path: '{mesh_file_path}'")
            break
    
    if not mesh_file_path:
        log_error(f"Could not determine mesh file path. Last error: {last_error}")
        return None, material_prim, None, f"Could not determine mesh file path. Last error: {last_error}"
    log_info(f"Final asset details: Mesh File='{mesh_file_path}', Material Prim='{material_prim}', Context='{context_file_path}'")
    return mesh_file_path, material_prim, context_file_path, None

def ingest_texture_to_remix(pbr_type: str, texture_file_path: str, project_output_dir_abs: str) -> tuple[str | None, str | None]:
    log_info(f"--- Ingesting PBR Type '{pbr_type}' Texture: {safe_basename(texture_file_path)} ---")
    if not os.path.isfile(texture_file_path): 
        return None, f"Source texture file not found: {texture_file_path}"
    
    output_subfolder = PLUGIN_SETTINGS.get("remix_output_subfolder", "Textures/PainterConnector_Ingested").strip('/\\')
    target_ingest_dir_abs = os.path.normpath(os.path.join(project_output_dir_abs, output_subfolder))
    
    try: 
        os.makedirs(target_ingest_dir_abs, exist_ok=True)
    except Exception as dir_e: 
        return None, f"Failed to create target ingest directory '{target_ingest_dir_abs}': {dir_e}"

    # Use the original exported texture path as the input.
    # The Remix API will read from this path and write its output to the `target_ingest_dir_api`.
    # This prevents the "input and output directory are the same" error.
    abs_texture_path_for_api = os.path.abspath(texture_file_path).replace(os.sep, '/')
    log_info(f"  Using source texture from temp export location: {abs_texture_path_for_api}")
    target_ingest_dir_api = os.path.abspath(target_ingest_dir_abs).replace(os.sep, '/')

    ingest_validation_type = PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP.get(pbr_type.lower(), "DIFFUSE")
    if ingest_validation_type == "DIFFUSE" and pbr_type.lower() not in ["albedo", "diffuse"]:
        log_warning(f"  No specific ingest validation type for '{pbr_type}'. Defaulting to 'DIFFUSE'.")
    if not project_output_dir_abs or not os.path.isabs(project_output_dir_abs):
        return None, f"Remix project output directory is not absolute: '{project_output_dir_abs}'"
    
    ingest_payload = {
        "executor": 1, "name": f"Ingest_{pbr_type}_{safe_basename(abs_texture_path_for_api)}",
        "context_plugin": {
            "name": "TextureImporter",
            "data": {
                "context_name": "ingestcraft_browser",
                "input_files": [[abs_texture_path_for_api, ingest_validation_type]],
                "output_directory": target_ingest_dir_api,
                "allow_empty_input_files_list": True,
                "data_flows": [
                    {"name": "InOutData", "push_output_data": True, "channel": "ingestion_output"},
                    {"name": "InOutData", "push_output_data": True, "channel": "cleanup_files"},
                    {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"}
                ],
                "hide_context_ui": True,
                "create_context_if_not_exist": True,
                "expose_mass_ui": False,
                "cook_mass_template": True
            }
        },
        "check_plugins": [
            {
                "name": "ConvertToDDS",
                "selector_plugins": [{"name": "AllShaders", "data": {}}],
                "data": {
                    "data_flows": [
                        {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "ingestion_output"},
                        {"name": "InOutData", "push_input_data": True, "push_output_data": True, "channel": "cleanup_files"},
                        {"name": "InOutData", "push_output_data": True, "channel": "write_metadata"}
                    ]
                },
                "stop_if_fix_failed": True,
                "context_plugin": {"name": "CurrentStage", "data": {}}
            }
        ],
        "resultor_plugins": [
            {"name": "FileCleanup", "data": {"channel": "cleanup_files", "cleanup_output": False}},
            {"name": "FileMetadataWritter", "data": {"channel": "write_metadata"}}
        ]
    }

    ingest_api_endpoint = "/ingestcraft/mass-validator/queue/material"
    log_info(f"  Sending ingest request to endpoint '{ingest_api_endpoint}'")
    try:
        result = make_remix_request_with_retries("POST", ingest_api_endpoint, json_payload=ingest_payload)
        if not result["success"]: return None, result['error'] or "Ingestion API request failed."
        
        original_base_name = os.path.splitext(safe_basename(texture_file_path))[0]
        if original_base_name.lower().endswith(".rtex"): original_base_name = os.path.splitext(original_base_name)[0]
        is_normal = pbr_type.lower() == "normal"
        response_data = result.get("data", {})
        output_paths = []

        if isinstance(response_data, dict) and "completed_schemas" in response_data:
            for schema in response_data.get("completed_schemas", []):
                if isinstance(schema, dict):
                    plugin_results = [schema.get("context_plugin", {})] + schema.get("check_plugins", [])
                    for presult in plugin_results:
                        if isinstance(presult, dict):
                            for flow in presult.get("data", {}).get("data_flows", []):
                                if isinstance(flow, dict) and flow.get("channel") == "ingestion_output":
                                    output_paths.extend(p for p in flow.get("output_data", []) if isinstance(p, str))

        if not output_paths and isinstance(response_data, dict) and "content" in response_data:
            output_paths.extend(p for p in response_data.get("content", []) if isinstance(p, str))
        
        output_paths = list(dict.fromkeys(output_paths))
        ingested_path = None

        for path_str in output_paths:
            if not path_str.lower().endswith(('.dds', '.rtex.dds')): continue
            base_no_dds = os.path.splitext(safe_basename(path_str))[0]
            base_no_rtex = os.path.splitext(base_no_dds)[0] if base_no_dds.lower().endswith(".rtex") else base_no_dds
            if base_no_rtex.lower() == original_base_name.lower():
                ingested_path = path_str; break
            if is_normal and (base_no_rtex.lower() == original_base_name.lower() + ".n" or base_no_rtex.lower() == original_base_name.lower().replace("_normal", "_oth_normal") + ".n"):
                ingested_path = path_str; break
            if not is_normal and re.sub(r'\.[armhnoaodse]$', '', base_no_rtex, flags=re.IGNORECASE).lower() == original_base_name.lower():
                ingested_path = path_str; break

        if not ingested_path: return None, f"Could not identify output path for '{original_base_name}' from API response."
        
        final_abs_path = os.path.normpath(ingested_path) if os.path.isabs(ingested_path) else os.path.normpath(os.path.join(target_ingest_dir_api.replace('/', os.sep), ingested_path))
        if not os.path.isfile(final_abs_path): return None, f"Ingest path identified ('{final_abs_path}'), but file does not exist."
        log_info(f"  Successfully ingested PBR type '{pbr_type}'. Verified file: {final_abs_path}");
        return final_abs_path, None
    except Exception as e:
        return None, f"An unexpected error occurred during ingest: {e}"

def get_current_edit_target():
    log_info("Getting current edit target layer from Remix...")
    result = make_remix_request_with_retries('GET', "/stagecraft/layers/target")
    layer_id = result.get("data", {}).get("layer_id") if result["success"] and isinstance(result.get("data"), dict) else None
    if not layer_id:
        log_warning("Could not get target layer via /layers/target. Trying /stagecraft/project/...")
        result_proj = make_remix_request_with_retries('GET', "/stagecraft/project/")
        layer_id = result_proj.get("data", {}).get("layer_id") if result_proj["success"] and isinstance(result_proj.get("data"), dict) else None
    if isinstance(layer_id, str) and layer_id.strip():
        layer_id_norm = os.path.normpath(layer_id.replace('\\', '/'))
        log_info(f"Current edit target layer identified: {layer_id_norm}")
        return layer_id_norm, None
    err_msg = (result_proj if 'result_proj' in locals() else result).get('error', "API request failed.")
    log_error(f"Could not determine current edit layer: {err_msg}")
    return None, f"Could not determine edit layer: {err_msg}"

def save_remix_layer(layer_id_abs_path: str) -> tuple[bool, str | None]:
    if not layer_id_abs_path or not layer_id_abs_path.strip(): return False, "Layer ID/path is missing."
    log_info(f"Requesting save for layer: {layer_id_abs_path}")
    try:
        current_layer, err = get_current_edit_target()
        if err or not current_layer: return False, f"Could not re-verify layer to save: {err or 'No layer found.'}"
        encoded_layer_id = urllib.parse.quote(current_layer.replace(os.sep, '/'), safe=':/')
        result = make_remix_request_with_retries('POST', f"/stagecraft/layers/{encoded_layer_id}/save")
        if not result["success"]:
            err_api = result.get("error", "Save layer API request failed.")
            status = result.get('status_code', 'N/A')
            log_error(f"Failed to save layer '{current_layer}' (Status: {status}): {err_api}")
            return False, f"Failed to save layer (Status: {status}): {err_api}"
        log_info(f"Layer '{current_layer}' save request successfully submitted.")
        return True, None
    except Exception as e:
        log_error(f"Unexpected exception during save layer request for '{layer_id_abs_path}': {e}", exc_info=True)
        return False, f"Exception during save layer request: {e}"

def update_remix_textures_batch(textures_to_update: list[tuple[str, str]], project_output_dir_abs: str) -> tuple[bool, str | None]:
    log_info(f"Batch updating {len(textures_to_update)} textures in Remix...")
    if not textures_to_update: return True, "No textures to update."
    update_payload_list, path_errors = [], []
    for usd_attr, ingested_path in textures_to_update:
        if not ingested_path or not os.path.isabs(ingested_path):
            path_errors.append(f"PathError for {safe_basename(usd_attr)}: Path '{ingested_path}' not absolute.")
            continue
        update_payload_list.append([usd_attr.replace('\\', '/'), ingested_path.replace(os.sep, '/')])
    if not update_payload_list:
        return False, f"Path processing failed for all entries. Errors: {'; '.join(path_errors)}"
    update_payload = {"force": True, "textures": update_payload_list}
    log_debug(f"  Batch Update Payload: {json.dumps(update_payload, indent=2)}")
    result = make_remix_request_with_retries('PUT', '/stagecraft/textures/', json_payload=update_payload)
    if not result["success"]:
        err_msg = result.get("error", "Batch texture update API failed.")
        status, data = result.get('status_code', 'N/A'), result.get("data", "")
        detail = json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        full_error = f"{err_msg}" + (f": {detail}" if detail and detail not in err_msg else "") + f" (Status: {status})"
        log_error(f"Batch texture update failed. Error: {full_error}")
        if status == 422:
            log_warning("Hint: A 422 error often means target USD attribute paths do not exist. Verify shader input names and update PBR_TO_MDL_INPUT_MAP in core.py if needed.")
            log_warning(f"    Example failing path from this attempt: {detail}")
        if path_errors: full_error += f" (Previous path errors: {'; '.join(path_errors)})"
        return False, full_error
    success_msg = f"Batch texture update request submitted for {len(update_payload_list)} textures."
    if path_errors:
        log_warning(f"{success_msg} However, there were path processing errors: {'; '.join(path_errors)}")
        return True, f"{success_msg} (With warnings: {'; '.join(path_errors)})"
    log_info(success_msg)
    return True, None

def handle_pull_from_remix():
    log_info("="*20 + " PULL FROM REMIX INITIATED " + "="*20)
    pull_errors = []
    if substance_painter.project.is_open():
        log_info("Closing current Painter project before pull...")
        try: substance_painter.project.close()
        except Exception as e:
            err_msg = f"Failed to close current project: {e}"
            log_error(err_msg, exc_info=True)
            display_message_safe(f"Error: {err_msg}. Aborting.")
            return
    if not check_requests_dependency():
        display_message_safe("Pull failed: 'requests' library is missing.")
        return

    mesh_path, material_prim, original_mesh_meta, mesh_path_pre_unwrap = None, None, None, None
    use_simple_mesh = PLUGIN_SETTINGS.get("use_simple_tiling_mesh_on_pull", False)
    simple_mesh_path_setting = PLUGIN_SETTINGS.get("simple_tiling_mesh_path")

    if use_simple_mesh and simple_mesh_path_setting:
        log_info("Using pre-defined simple mesh for tiling.")
        
        _, material_prim, _, sel_err = get_selected_remix_asset_details()
        if sel_err:
            if "Could not determine mesh file path" not in sel_err:
                display_message_safe(f"Selection Error: {sel_err}")
                return
        if not material_prim:
            display_message_safe(f"Error: No material selected in Remix. {sel_err or ''}")
            return
        log_info(f"Will apply textures to selected material: {material_prim}")

        try: plugin_root = os.path.dirname(os.path.abspath(__file__))
        except NameError: plugin_root = os.getcwd()
        mesh_path = os.path.normpath(os.path.join(plugin_root, simple_mesh_path_setting))
        mesh_path_pre_unwrap = mesh_path
        if not os.path.isfile(mesh_path):
            display_message_safe(f"Error: Simple tiling mesh not found: {mesh_path}. Aborting.")
            return
        original_mesh_meta = f"simple_tiling_mesh:{simple_mesh_path_setting}"
    else:
        mesh_file_api, material_prim, context_file, sel_err = get_selected_remix_asset_details()
        if sel_err:
            display_message_safe(f"Selection Error: {sel_err}")
            return
        if not mesh_file_api: display_message_safe("Error: Could not determine mesh file path from selection."); return
        if not material_prim: display_message_safe("Error: Could not determine Material Prim from selection."); return
        
        original_mesh_meta = mesh_file_api
        if not os.path.isabs(mesh_file_api):
            log_warning(f"Mesh path '{mesh_file_api}' is relative. Attempting to resolve...")

            if not context_file or not os.path.isabs(context_file):
                display_message_safe(f"Error: Mesh path is relative, but no absolute context file was provided by Remix API. Cannot resolve path.")
                return

            context_dir = os.path.dirname(context_file)
            candidate_path = os.path.abspath(os.path.join(context_dir, mesh_file_api))
            
            if os.path.isfile(candidate_path):
                mesh_path = candidate_path
                log_info(f"  Resolved relative mesh path using context dir '{context_dir}': '{mesh_path}'")
            else:
                display_message_safe(f"Error: Could not resolve relative mesh path '{mesh_file_api}'. Checked at: '{candidate_path}'")
                return
        else:
            mesh_path = os.path.normpath(mesh_file_api)
        
        if not os.path.isfile(mesh_path):
            display_message_safe(f"Error: Mesh file '{mesh_path}' does not exist locally.")
            return
        
        mesh_path_pre_unwrap = mesh_path
        if PLUGIN_SETTINGS.get("auto_unwrap_with_blender_on_pull", False):
            unwrapped = unwrap_mesh_with_blender(mesh_path)
            if unwrapped and os.path.isfile(unwrapped):
                mesh_path = unwrapped
            else:
                log_warning("Blender auto-unwrap failed. Using original mesh.")
                pull_errors.append("Blender Auto-Unwrap: Failed.")

    if not mesh_path or not str(mesh_path).strip():
        display_message_safe("Error: Final mesh path for project is invalid. Aborting.")
        return
    log_info(f"Creating Painter project with mesh: '{safe_basename(mesh_path)}'")
    try:
        proj_settings = substance_painter.project.Settings(normal_map_format=substance_painter.project.NormalMapFormat.DirectX)
        create_kwargs = {"mesh_file_path": mesh_path, "settings": proj_settings}
        template_path = PLUGIN_SETTINGS.get("painter_import_template_path")
        if template_path and os.path.isfile(template_path):
            if "settings" in create_kwargs: del create_kwargs["settings"]
            create_kwargs["template_file_path"] = template_path
            log_info(f"  Using Painter template: {template_path}")
        substance_painter.project.create(**create_kwargs)
        log_info("Painter project created successfully.")
    except Exception as e:
        display_message_safe(f"Error creating Painter project: {e}")
        return
    
    try:
        metadata = substance_painter.project.Metadata("RTXRemixConnectorLink")
        metadata.set("remix_material_prim", material_prim)
        
        material_hash = None
        if material_prim:
            material_hash_match = re.search(r'([A-Z0-9]{16})$', material_prim)
            if material_hash_match:
                material_hash = material_hash_match.group(1)
                metadata.set("remix_material_hash", material_hash)
                log_info(f"Extracted and stored material hash: {material_hash}")

        metadata.set("remix_mesh_file_path_original_api", original_mesh_meta)
        metadata.set("remix_mesh_file_path_resolved_before_unwrap", mesh_path_pre_unwrap)
        metadata.set("remix_mesh_file_path_used_by_painter", mesh_path)
        log_info("Remix linkage metadata stored in Painter project.")
    except Exception as e:
        err_str = f"Failed to store linkage metadata: {e}"
        pull_errors.append(f"Metadata Error: {err_str}")
        display_message_safe(f"Warning: {err_str}.")
    
    log_info("="*20 + " PULL FROM REMIX COMPLETED " + "="*20)
    mat_name = safe_basename(material_prim) or "Unknown Material"
    if not pull_errors:
        display_message_safe(f"Successfully pulled material '{mat_name}'. You can now 'Import Textures from Remix'.")
    else:
        display_message_safe(f"Pull for '{mat_name}' completed with issues (e.g., {pull_errors[0]}). Check logs.")

def handle_import_textures():
    log_info("="*20 + " IMPORT TEXTURES FROM REMIX INITIATED " + "="*20)
    import_errors, imported_count, assigned_count = [], 0, 0
    can_auto_assign = _set_channel_texture_resource_func is not None
    try:
        if not substance_painter.project.is_open(): raise Exception("No Painter project is open.")
        if not check_requests_dependency(): raise Exception("'requests' library is missing.")
        metadata = substance_painter.project.Metadata("RTXRemixConnectorLink")
        linked_material_prim = metadata.get("remix_material_prim")
        if not linked_material_prim: raise Exception("Project not linked to a Remix material.")
        log_info(f"  Linked Remix Material: {linked_material_prim}")

        remix_proj_dir, dir_err = get_remix_project_default_output_dir()
        if dir_err: log_warning(f"Could not get Remix project directory: {dir_err}. Relative texture paths may fail.")

        texture_sets = substance_painter.textureset.all_texture_sets()
        if not texture_sets: raise Exception("No TextureSets found in project.")
        target_ts = texture_sets[0] # Default to first
        log_info(f"  Targeting Painter TextureSet: '{target_ts.name()}'")
        
        encoded_material = urllib.parse.quote(linked_material_prim.replace(os.sep, '/'), safe='/')
        textures_result = make_remix_request_with_retries('GET', f"/stagecraft/assets/{encoded_material}/textures")
        if not textures_result["success"] or not isinstance(textures_result.get("data"), dict):
            raise Exception(f"API Error getting textures: {textures_result.get('error', 'Query failed.')}")
        
        texture_entries = textures_result["data"].get("textures", [])
        total_from_api = len(texture_entries)
        if not texture_entries:
            display_message_safe(f"No textures assigned to '{linked_material_prim}' in Remix.")
            return

        target_stack = target_ts.get_stack()
        if not target_stack and can_auto_assign:
            log_warning(f"Could not get stack for TextureSet '{target_ts.name()}'. Disabling auto-assignment.")
            can_auto_assign = False

        for usd_attr, tex_path_raw in texture_entries:
            if not isinstance(usd_attr, str) or not isinstance(tex_path_raw, str) or not tex_path_raw.strip(): continue
            input_name = (usd_attr.split(':')[-1] if ':' in usd_attr else os.path.basename(usd_attr)).lower()
            pbr_type = REMIX_ATTR_SUFFIX_TO_PBR_MAP.get(input_name)
            if not pbr_type:
                log_warning(f"  Could not infer PBR type from '{usd_attr}'. Skipping.")
                continue
            
            painter_channel = REMIX_PBR_TO_PAINTER_CHANNEL_MAP.get(pbr_type)
            if not painter_channel:
                log_warning(f"  No Painter channel mapping for PBR type '{pbr_type}'. Skipping.")
                continue
            
            abs_tex_path = os.path.normpath(tex_path_raw) if os.path.isabs(tex_path_raw) else (os.path.normpath(os.path.join(remix_proj_dir, tex_path_raw)) if remix_proj_dir else None)
            
            if not abs_tex_path or not os.path.isfile(abs_tex_path):
                log_warning(f"    Skipping: Texture file not found locally for '{pbr_type}'. Path: '{abs_tex_path or tex_path_raw}'.")
                import_errors.append(f"Import-{pbr_type}: File not found.")
                continue

            file_to_import = abs_tex_path
            is_converted = False
            if abs_tex_path.lower().endswith((".dds", ".rtex.dds")):
                texconv_path = PLUGIN_SETTINGS.get("texconv_path")
                if texconv_path and os.path.isfile(texconv_path):
                    try:
                        file_to_import = convert_dds_to_png(texconv_path, abs_tex_path, "")
                        is_converted = True
                    except Exception as e:
                        log_error(f"    DDS conversion failed for '{safe_basename(abs_tex_path)}': {e}", exc_info=True)
                        import_errors.append(f"TexconvError: {safe_basename(abs_tex_path)}")
                        continue # Skip this texture if conversion fails, as direct import is unreliable
                else:
                    log_warning(f"    texconv.exe not configured or path invalid. Cannot convert '{safe_basename(abs_tex_path)}'. Skipping.")
                    import_errors.append("TexconvConfigError: Path not set")
                    continue # Skip this texture
            
            imported_res_id = substance_painter.resource.import_project_resource(file_to_import, substance_painter.resource.Usage.TEXTURE).identifier()
            if not imported_res_id:
                # This can happen if Painter fails to decode the image even after conversion (unlikely for PNG)
                log_error(f"    Substance Painter failed to import resource '{safe_basename(file_to_import)}'. It might be invalid.")
                import_errors.append(f"ImportFail: {safe_basename(file_to_import)}")
                continue

            imported_count += 1
            log_info(f"    Imported '{safe_basename(file_to_import)}' ({'converted' if is_converted else 'original'}) to Painter.")

            if can_auto_assign and target_stack:
                try:
                    channel_type = PAINTER_STRING_TO_CHANNELTYPE_MAP.get(painter_channel)
                    if not channel_type: raise ValueError(f"No ChannelType enum for '{painter_channel}'.")
                    channel_obj = target_stack.get_channel(channel_type)
                    if not channel_obj:
                        log_warning(f"    Channel '{painter_channel}' not found. Attempting to add.")
                        channel_obj = target_stack.add_channel(channel_type)
                    if not channel_obj: raise ValueError("Channel could not be found or created.")
                    _set_channel_texture_resource_func(channel_obj, imported_res_id)
                    log_info(f"      Assigned to Painter channel '{painter_channel}'.")
                    assigned_count += 1
                except Exception as e:
                    log_error(f"    Error assigning to channel '{painter_channel}': {e}", exc_info=True)
                    import_errors.append(f"Assign-{painter_channel}: {str(e)[:100]}")
    except Exception as e:
        log_error(f"Texture import process failed: {e}", exc_info=True)
        import_errors.append(f"MainProcessError: {str(e)[:100]}")
    finally:
        log_info("="*20 + " IMPORT TEXTURES FROM REMIX COMPLETED " + "="*20)
        summary = f"Import: Processed={total_from_api if 'total_from_api' in locals() else 'N/A'}, Imported={imported_count}, Assigned={assigned_count}."
        if import_errors:
            unique_errors = set(import_errors)
            summary += f" Encountered {len(unique_errors)} unique issue(s)."
            if "TexconvConfigError: Path not set" in unique_errors:
                summary += " CRITICAL: texconv.exe is not configured in settings."
        display_message_safe(f"{'Warning' if import_errors else 'Success'}: {summary}")


def handle_push_to_remix():
    log_info("="*20 + " PUSH TO REMIX INITIATED " + "="*20)
    all_errors, updated_types, save_requested = [], [], False
    exported_files, ingested_paths, textures_to_update = {}, {}, []
    try:
        if not check_requests_dependency(): raise Exception("'requests' library is missing.")
        if not substance_painter.project.is_open(): raise Exception("No Painter project open.")
        
        metadata = substance_painter.project.Metadata("RTXRemixConnectorLink")
        linked_material_prim = metadata.get("remix_material_prim")
        material_hash = metadata.get("remix_material_hash")

        if not linked_material_prim or not material_hash:
            raise Exception("Project not linked to a Remix material or material hash is missing from metadata.")
        log_info(f"Found linked Remix material prim: {linked_material_prim} (Hash: {material_hash})")

        remix_proj_dir, dir_err = get_remix_project_default_output_dir()
        if dir_err: raise Exception(f"Could not get Remix project directory: {dir_err}")
        
        painter_export_path = PLUGIN_SETTINGS.get("painter_export_path") or os.path.join(tempfile.gettempdir(), "RemixConnector_Export")
        os.makedirs(painter_export_path, exist_ok=True)
        log_info(f"Using Painter export directory: {painter_export_path}")

        all_ts = substance_painter.textureset.all_texture_sets()
        log_info("Checking for and adding missing channels...")
        for ts in all_ts:
            ts_stack = ts.get_stack()
            if ts_stack and hasattr(ts_stack, 'add_channel'):
                for name, type_enum in PAINTER_STRING_TO_CHANNELTYPE_MAP.items():
                    try:
                        ts_stack.get_channel(type_enum)
                    except (ValueError, RuntimeError):
                        try:
                            fmt = ChannelFormat.L8
                            if name in ["baseColor", "normal", "emissive"]: fmt = ChannelFormat.sRGB8
                            elif name == "height": fmt = ChannelFormat.L16F
                            ts_stack.add_channel(type_enum, fmt)
                            log_info(f"  Added '{name}' channel to '{ts.name()}'.")
                        except Exception as e:
                            log_warning(f"Could not add '{name}' to '{ts.name()}': {e}")
        
        texture_sets_to_export = [ts.name() for ts in all_ts]
        if not texture_sets_to_export: raise Exception("No valid texture sets to export.")
        
        export_format = PLUGIN_SETTINGS.get("export_file_format", "png")
        export_padding = PLUGIN_SETTINGS.get("export_padding", "infinite")
        dynamic_preset_name = f"Remix_Dynamic_{material_hash}"
        log_info(f"Creating dynamic export preset '{dynamic_preset_name}'")

        dynamic_preset_maps = []
        filename_map_for_lookup = {}

        # Based on the structure in the static Remix.spexp preset file
        maps_to_create = [
            {"p_channel": "baseColor", "pbr_type": "albedo"},
            {"p_channel": "normal", "pbr_type": "normal"},
            {"p_channel": "roughness", "pbr_type": "roughness"},
            {"p_channel": "metallic", "pbr_type": "metallic"},
            {"p_channel": "height", "pbr_type": "height"},
            {"p_channel": "emissive", "pbr_type": "emissive"}
        ]

        base_params = {
            "fileFormat": export_format, "bitDepth": "8", "paddingAlgorithm": export_padding,
            "dithering": False, "sizeMultiplier": 1, "keepAlpha": True
        }

        for map_info in maps_to_create:
            painter_channel = map_info["p_channel"]
            pbr_type = map_info["pbr_type"]
            
            filename_no_ext = f"{material_hash}_{pbr_type}"
            full_filename_with_ext = f"{filename_no_ext}.{export_format}"
            
            log_info(f"  Map for Painter channel '{painter_channel}' will be exported as '{full_filename_with_ext}'")
            
            full_path_for_lookup = os.path.join(painter_export_path, full_filename_with_ext).replace('\\', '/')
            filename_map_for_lookup[full_path_for_lookup] = pbr_type

            channels_config = []
            if painter_channel == 'baseColor':
                channels_config = [
                    {"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "R", "destChannel": "R"},
                    {"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "G", "destChannel": "G"},
                    {"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "B", "destChannel": "B"},
                    {"srcMapType": "documentMap", "srcMapName": "opacity", "srcChannel": "L", "destChannel": "A"}]
            elif painter_channel == 'normal':
                 channels_config = [
                    {"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "R", "destChannel": "R"},
                    {"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "G", "destChannel": "G"},
                    {"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "B", "destChannel": "B"}]
            elif painter_channel == 'emissive':
                channels_config = [
                    {"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "R", "destChannel": "R"},
                    {"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "G", "destChannel": "G"},
                    {"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "B", "destChannel": "B"}]
            else:
                channels_config = [{"srcMapType": "documentMap", "srcMapName": painter_channel, "srcChannel": "L", "destChannel": "L"}]

            dynamic_preset_maps.append({
                "fileName": filename_no_ext,
                "parameters": base_params.copy(), # Use copy to be safe
                "channels": channels_config
            })

        export_settings = {
            "exportShaderParams": False, "exportPath": painter_export_path,
            "exportPresets": [{ "name": dynamic_preset_name, "maps": dynamic_preset_maps }],
            "exportList": [{"rootPath": name, "exportPreset": dynamic_preset_name} for name in texture_sets_to_export]
        }
        
        log_info(f"Starting Painter texture export...")
        export_result = substance_painter.export.export_project_textures(export_settings)
        
        if export_result.status != substance_painter.export.ExportStatus.Success:
            raise Exception(f"Texture export failed: {export_result.message}")

        total_exported_textures = sum(len(file_list) for file_list in export_result.textures.values())
        log_info(f"Export successful. Exported {total_exported_textures} textures from {len(export_result.textures)} texture set(s).")
        
        for ts, file_list in export_result.textures.items():
            for file_path in file_list:
                normalized_path = file_path.replace('\\', '/')
                if normalized_path in filename_map_for_lookup:
                    pbr_type = filename_map_for_lookup[normalized_path]
                    exported_files[pbr_type] = file_path
                    log_info(f"  Mapped '{os.path.basename(file_path)}' to PBR type '{pbr_type}'.")
                else:
                    log_warning(f"  Exported file '{os.path.basename(file_path)}' was not found in our pre-defined filename map. Skipping.")
        
        if not exported_files:
            raise Exception("Export succeeded, but no recognized texture files were mapped. Check preset and filename map generation.")

        log_info("--- Starting Texture Ingestion ---")
        for pbr_type, path in exported_files.items():
            ingested_path, err = ingest_texture_to_remix(pbr_type, path, remix_proj_dir)
            if err:
                all_errors.append(f"IngestFail-{pbr_type}: {err}")
                continue
            ingested_paths[pbr_type] = ingested_path
        if not ingested_paths:
            raise Exception("Ingestion failed for all textures.")
        
        log_info("--- Preparing batch update for Remix ---")
        for pbr_type, path in ingested_paths.items():
            mdl_input = PBR_TO_MDL_INPUT_MAP.get(pbr_type)
            if pbr_type == "metallic" and mdl_input == "metalness_texture":
                log_warning("Overriding 'metalness_texture' with 'metallic_texture' for metallic PBR type.")
                mdl_input = "metallic_texture"

            if not mdl_input:
                all_errors.append(f"MDLMapFail-{pbr_type}")
                continue
            textures_to_update.append((f"{linked_material_prim}/Shader.inputs:{mdl_input}", path))
            updated_types.append(pbr_type)
        
        if textures_to_update:
            success, err = update_remix_textures_batch(textures_to_update, remix_proj_dir)
            if not success:
                raise Exception(f"Failed to update textures in Remix: {err}")
            save_requested = True
        else:
            log_warning("No textures prepared for batch update.")
    except Exception as e:
        all_errors.append(f"CriticalError: {str(e)}")
        log_error(f"A critical error occurred during push: {e}", exc_info=True)
        display_message_safe(f"Error during Push: {e}")
    finally:
        if save_requested and linked_material_prim and not all_errors:
            try:
                log_info("Attempting to save Remix layer changes...")
                success, err = save_remix_layer(linked_material_prim)
                if not success:
                    all_errors.append(f"LayerSaveFail: {err}")
            except Exception as e_save:
                all_errors.append(f"LayerSaveException: {e_save}")
        elif all_errors:
            log_warning("Skipping Remix layer save due to previous errors.")
        
        summary = f"Push to Remix finished with {len(all_errors)} issue(s). " if all_errors else "Push to Remix completed successfully! "
        summary += f"Updated: {len(updated_types)}/{len(exported_files)} textures."
        display_message_safe(summary)
        log_info(summary)
        if all_errors:
            log_error(f"Push errors encountered: {all_errors}")
        log_info("="*20 + " PUSH TO REMIX FINISHED " + "="*20)

def handle_settings():
    log_info("="*20 + " SETTINGS ACTION TRIGGERED " + "="*20)
    global PLUGIN_SETTINGS
    dialog_instance = None
    core_ref = sys.modules[__name__]
    err_msg = _settings_dialog_import_error_message
    if settings_dialog_available and _create_settings_dialog_func:
        log_info("Attempting to create dialog using imported factory.")
        try:
            parent_win = substance_painter.ui.main_window() if ui_available and hasattr(substance_painter.ui, 'main_window') else None
            dialog_instance = _create_settings_dialog_func(core_ref, PLUGIN_SETTINGS, parent=parent_win)
            if dialog_instance and hasattr(dialog_instance, '_functional_ui') and dialog_instance._functional_ui:
                log_info("Factory-created dialog is functional.")
            else:
                err_msg += " | Factory dialog instance non-functional or creation failed."
                dialog_instance = None
        except Exception as e:
            log_error(f"Error creating dialog via factory: {e}", exc_info=True)
            err_msg = f"Runtime error in factory: {e}"
            dialog_instance = None
    
    if not dialog_instance:
        log_warning("Using CorePlaceholderSettingsDialog.")
        if not QT_AVAILABLE:
            display_message_safe("Error: Settings UI cannot be displayed (Qt unavailable).")
            return
        parent_win = substance_painter.ui.main_window() if ui_available and hasattr(substance_painter.ui, 'main_window') else None
        dialog_instance = CorePlaceholderSettingsDialog(PLUGIN_SETTINGS, parent=parent_win, import_failure_reason=err_msg)

    try:
        result = dialog_instance.exec() if hasattr(dialog_instance, 'exec') else dialog_instance.exec_()
        is_accepted = (result == QDialog.Accepted) if QT_AVAILABLE else (result == _QDialogBase.Accepted)
        if is_accepted:
            if hasattr(dialog_instance, 'get_settings'):
                new_settings = dialog_instance.get_settings()
                if new_settings:
                    PLUGIN_SETTINGS.update(new_settings)
                    save_plugin_settings()
                    # Re-run the setup logic to apply new settings like log level and texconv path immediately
                    setup_logging()
                    display_message_safe("Settings saved successfully.")
                else: log_warning("Settings accepted, but no new settings returned.")
            else: log_error("Settings accepted, but 'get_settings' method is missing.")
        else:
            log_info("Settings dialog cancelled. No changes applied.")
    except Exception as e:
        log_error(f"Error displaying settings dialog: {e}", exc_info=True)
        display_message_safe(f"Error with settings dialog: {e}")
    log_info("Settings action finished.")
_CACHED_SETTINGS_DIALOG_CLASS = None

def get_settings_dialog_class(core_for_dialog):

    global _CACHED_SETTINGS_DIALOG_CLASS
    if _CACHED_SETTINGS_DIALOG_CLASS is not None:
        # Basic caching: Assumes core_for_dialog's Qt state doesn't change incompatibly between calls.
        # A more robust cache might check core_for_dialog's Qt binding version.
        return _CACHED_SETTINGS_DIALOG_CLASS

    # Determine the base class for SettingsDialog using the passed core_for_dialog
    ParentDialogClass = object
    QtWidgets_from_core = None
    QtCore_from_core = None
    QtGui_from_core = None

    core_has_qt_available_check = hasattr(core_for_dialog, 'QT_AVAILABLE') and core_for_dialog.QT_AVAILABLE
    core_has_QtWidgets_check = hasattr(core_for_dialog, 'QtWidgets') and core_for_dialog.QtWidgets is not None
    QtWidgets_has_QDialog_check = False

    if core_has_QtWidgets_check:
        QtWidgets_from_core = core_for_dialog.QtWidgets
        QtCore_from_core = core_for_dialog.QtCore
        QtGui_from_core = core_for_dialog.QtGui
        QtWidgets_has_QDialog_check = hasattr(QtWidgets_from_core, 'QDialog')

    if core_has_qt_available_check and core_has_QtWidgets_check and QtWidgets_has_QDialog_check:
        ParentDialogClass = QtWidgets_from_core.QDialog
        print(f"[RemixConnector SettingsDialog Factory] Defining SettingsDialog to inherit from QDialog provided by core: {ParentDialogClass}")
    else:
        print(f"[RemixConnector SettingsDialog Factory] Defining SettingsDialog to inherit from object. Qt checks: available={core_has_qt_available_check}, QtWidgets={core_has_QtWidgets_check}, QDialog={QtWidgets_has_QDialog_check}")
        # Ensure dummy Qt modules are captured if real ones weren't available or checks failed
        # core_for_dialog should provide dummy versions from its own logic if real ones failed.
        if not QtWidgets_from_core: QtWidgets_from_core = core_for_dialog.QtWidgets
        if not QtCore_from_core: QtCore_from_core = core_for_dialog.QtCore
        if not QtGui_from_core: QtGui_from_core = core_for_dialog.QtGui

    class SettingsDialog(ParentDialogClass):
        def __init__(self, current_settings, parent=None):
            # print(f"[RemixConnector SettingsDialog DEBUG __init__] Entered (Factory Version). Using core module provided by factory.")

            self.effective_core_module = core_for_dialog
            self.QtWidgets = QtWidgets_from_core
            self.QtCore = QtCore_from_core
            self.QtGui = QtGui_from_core

            self._functional_ui = False

            # Initialize super class. ParentDialogClass was determined by the factory.
            if ParentDialogClass is not object and \
               hasattr(self.QtWidgets, 'QDialog') and self.QtWidgets.QDialog is not None and \
               isinstance(self, self.QtWidgets.QDialog): # Double check instance type for safety

                super().__init__(parent)
                self._functional_ui = True
                print("[RemixConnector SettingsDialog] Initialized super() as QDialog.")
            else:
                object.__init__(self)
                self._functional_ui = False
                print(f"[RemixConnector SettingsDialog] Initialized super() as object. ParentDialogClass was {ParentDialogClass.__name__}. UI will not be functional.")

            if not self._functional_ui:
                print("[RemixConnector SettingsDialog] UI is not functional. Widget construction skipped.")
                # Still need to store settings for get_settings() to work consistently
                self.current_settings = current_settings.copy()
                self.new_settings = current_settings.copy()
                return

            self.setWindowTitle("Remix Connector Settings")
            self.current_settings = current_settings.copy()
            self.new_settings = current_settings.copy()

            self.layout = self.QtWidgets.QVBoxLayout(self)
            self.scroll_area = self.QtWidgets.QScrollArea(self)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_widget = self.QtWidgets.QWidget()
            self.form_layout = self.QtWidgets.QFormLayout(self.scroll_widget)
            self.scroll_area.setWidget(self.scroll_widget)
            self.layout.addWidget(self.scroll_area)

            self.setting_widgets = {}

            for key, value in self.current_settings.items():
                label_text = key.replace("_", " ").title() + ":"
                self.add_setting_field(key, label_text, value)

            self.button_layout = self.QtWidgets.QHBoxLayout()
            self.apply_button = self.QtWidgets.QPushButton("Apply")
            self.cancel_button = self.QtWidgets.QPushButton("Cancel")
            self.button_layout.addStretch()
            self.button_layout.addWidget(self.apply_button)
            self.button_layout.addWidget(self.cancel_button)
            self.layout.addLayout(self.button_layout)

            self.apply_button.clicked.connect(self.accept_settings)
            self.cancel_button.clicked.connect(self.reject)

            self.load_settings()
            self.setMinimumWidth(600)
            self.setMinimumHeight(400)

        def add_setting_field(self, key, label_text, current_value):
            if not self._functional_ui: return
            label = self.QtWidgets.QLabel(label_text)
            widget = None

            if isinstance(current_value, bool):
                widget = self.QtWidgets.QCheckBox()
            elif key == "log_level":
                widget = self.QtWidgets.QComboBox()
                widget.addItems(["debug", "info", "warning", "error"])
            elif key == "texture_workflow":
                widget = self.QtWidgets.QComboBox()
                widget.addItems(["Metallic/Roughness", "Specular/Glossiness"])
            elif key == "normal_format":
                widget = self.QtWidgets.QComboBox()
                widget.addItems(["DirectX", "OpenGL"])
            elif key == "blender_smart_uv_stretch_to_bounds": # Also a bool handled by QCheckBox
                widget = self.QtWidgets.QCheckBox()
            elif isinstance(current_value, (int, float)): # Handle numbers that might need validators
                widget = self.QtWidgets.QLineEdit()
                if isinstance(current_value, int) and self.QtGui and hasattr(self.QtGui, 'QIntValidator'):
                    widget.setValidator(self.QtGui.QIntValidator())
                # Use isinstance for float check, as current_value could be int here if first check failed
                elif isinstance(current_value, float) and self.QtGui and hasattr(self.QtGui, 'QDoubleValidator'):
                    widget.setValidator(self.QtGui.QDoubleValidator(self)) # Pass self as parent
            else: # Default to QLineEdit for strings or other types
                widget = self.QtWidgets.QLineEdit()

            if widget:
                self.form_layout.addRow(label, widget)
                self.setting_widgets[key] = widget

        def load_settings(self):
            if not self._functional_ui: return
            for key, widget in self.setting_widgets.items():
                if key in self.current_settings:
                    value = self.current_settings[key]
                    if isinstance(widget, self.QtWidgets.QCheckBox):
                        if key == "blender_smart_uv_stretch_to_bounds":
                            widget.setChecked(str(value).lower() == 'true')
                        else:
                            widget.setChecked(bool(value))
                    elif isinstance(widget, self.QtWidgets.QComboBox):
                        match_flag = self.QtCore.Qt.MatchFixedString if hasattr(self.QtCore, 'Qt') and hasattr(self.QtCore.Qt, 'MatchFixedString') else 0
                        index = widget.findText(str(value), match_flag)
                        if index >= 0:
                            widget.setCurrentIndex(index)
                    elif isinstance(widget, self.QtWidgets.QLineEdit):
                        widget.setText(str(value))

        def _save_settings_to_dict(self):
            if not self._functional_ui: return self.current_settings.copy() # Return a copy of original if not functional

            # Ensure new_settings starts fresh from current_settings if modified
            # self.new_settings = self.current_settings.copy() # Or ensure it's correctly initialized

            for key, widget in self.setting_widgets.items():
                # original_default_value = self.current_settings.get(key) # This is the value when dialog opened
                # Ensure key exists in new_settings, if not already a full copy
                if key not in self.new_settings: self.new_settings[key] = self.current_settings.get(key)


                if isinstance(widget, self.QtWidgets.QCheckBox):
                    if key == "blender_smart_uv_stretch_to_bounds":
                        self.new_settings[key] = "True" if widget.isChecked() else "False"
                    else:
                        self.new_settings[key] = widget.isChecked()
                elif isinstance(widget, self.QtWidgets.QComboBox):
                    self.new_settings[key] = widget.currentText()
                elif isinstance(widget, self.QtWidgets.QLineEdit):
                    text_value = widget.text()
                    original_value_type_sample = self.current_settings.get(key) # Get original value to infer type

                    if isinstance(original_value_type_sample, float):
                        try: self.new_settings[key] = float(text_value)
                        except ValueError:
                            self.new_settings[key] = original_value_type_sample # Revert to original
                            print(f"[SettingsDialog] WARN: Could not convert '{text_value}' to float for '{key}'. Keeping original.")
                    elif isinstance(original_value_type_sample, int):
                        try: self.new_settings[key] = int(text_value)
                        except ValueError:
                            self.new_settings[key] = original_value_type_sample # Revert to original
                            print(f"[SettingsDialog] WARN: Could not convert '{text_value}' to int for '{key}'. Keeping original.")
                    else: # String or other
                        self.new_settings[key] = text_value
            return self.new_settings

        def accept_settings(self):
            if not self._functional_ui:
                if hasattr(super(), "accept"):
                     try: super().accept()
                     except AttributeError: pass
                return
            self._save_settings_to_dict() # This now populates self.new_settings
            super().accept()

        def reject(self):
            if not self._functional_ui:
                if hasattr(super(), "reject"):
                    try: super().reject()
                    except AttributeError: pass
                return
            super().reject()

        def get_settings(self):
            if not self._functional_ui: return self.current_settings # Return original if not functional
            # If functional, accept_settings would have called _save_settings_to_dict to populate self.new_settings.
            # If dialog was accepted, self.new_settings holds the applied values.
            # If rejected, self.new_settings might hold unapplied changes; caller usually ignores if result is Rejected.
            return self.new_settings

        def exec_(self):
            if not self._functional_ui:
                dummy_qdialog_rejected = 0
                if hasattr(self.effective_core_module, 'QtWidgets') and \
                   self.effective_core_module.QtWidgets and \
                   hasattr(self.effective_core_module.QtWidgets, 'QDialog') and \
                   hasattr(self.effective_core_module.QtWidgets.QDialog, 'Rejected'):
                    dummy_qdialog_rejected = self.effective_core_module.QtWidgets.QDialog.Rejected
                return dummy_qdialog_rejected
            return super().exec_()

        def exec(self):
            if not self._functional_ui:
                dummy_qdialog_rejected = 0
                if hasattr(self.effective_core_module, 'QtWidgets') and \
                   self.effective_core_module.QtWidgets and \
                   hasattr(self.effective_core_module.QtWidgets, 'QDialog') and \
                   hasattr(self.effective_core_module.QtWidgets.QDialog, 'Rejected'):
                    dummy_qdialog_rejected = self.effective_core_module.QtWidgets.QDialog.Rejected
                return dummy_qdialog_rejected

            if hasattr(super(), 'exec'):
                return super().exec()
            elif hasattr(super(), 'exec_'):
                 return super().exec_()
            # Fallback if superclass (e.g. object) has no exec/exec_
            # This path should ideally not be hit if _functional_ui is True
            # and ParentDialogClass was a Qt Dialog.
            # If ParentDialogClass was 'object', _functional_ui would be False.
            print("[RemixConnector SettingsDialog exec] Warning: super().exec() and super().exec_() not found. Returning Rejected (0).")
            return 0 if not (self.QtWidgets and hasattr(self.QtWidgets.QDialog, 'Rejected')) else self.QtWidgets.QDialog.Rejected


    _CACHED_SETTINGS_DIALOG_CLASS = SettingsDialog
    return SettingsDialog


def create_settings_dialog_instance(core_module, current_settings, parent=None):
    """
    Factory function to create an instance of the SettingsDialog.
    Ensures the dialog class is defined with knowledge of the fully initialized core module.
    """
    DialogClass = get_settings_dialog_class(core_module)
    return DialogClass(current_settings, parent=parent)

# Example usage (for testing, not for final plugin)
if __name__ == "__main__":
    # Mock a 'core_module' for standalone testing.
    class MockCoreModule:
        def __init__(self):
            self.QT_AVAILABLE = False
            self.QtWidgets = None
            self.QtCore = None
            self.QtGui = None
            self._QT_BINDING_VERSION_CORE = "Unknown_Test"

            try:
                from PySide6 import QtWidgets, QtCore, QtGui
                print("Using PySide6 for __main__ test.")
                self.QtWidgets = QtWidgets
                self.QtCore = QtCore
                self.QtGui = QtGui
                self.QT_AVAILABLE = True
                self._QT_BINDING_VERSION_CORE = "PySide6_Test"
            except ImportError:
                try:
                    from PySide2 import QtWidgets, QtCore, QtGui
                    print("Using PySide2 for __main__ test.")
                    self.QtWidgets = QtWidgets
                    self.QtCore = QtCore
                    self.QtGui = QtGui
                    self.QT_AVAILABLE = True
                    self._QT_BINDING_VERSION_CORE = "PySide2_Test"
                except ImportError:
                    print("PySide6 or PySide2 not found for __main__ test. Using dummy Qt.")
                    # Setup dummy Qt attributes on mock_core (simplified)
                    class QObject: pass # Base for QDialog dummy
                    class QDialog(QObject): # Must have Rejected, Accepted as class attributes for exec_
                        Rejected = 0
                        Accepted = 1
                        def __init__(self, parent=None): pass
                        def exec_(self): return QDialog.Rejected # Dummy exec
                        def accept(self): pass
                        def reject(self): pass
                        def setWindowTitle(self,t): pass
                        def setLayout(self,l): pass
                        def setMinimumWidth(self,w):pass
                        def setMinimumHeight(self,h):pass

                    class DummyQtWidgetsModule:
                        QDialog = QDialog; QPushButton = type('QPushButton', (QObject,), {'clicked': lambda: type('Signal', (), {'connect': lambda s: None})()}); QVBoxLayout = type('QVBoxLayout', (QObject,), {}); QHBoxLayout = type('QHBoxLayout', (QObject,), {})
                        QLabel = type('QLabel', (QObject,), {}); QScrollArea = type('QScrollArea', (QObject,), {}); QWidget = type('QWidget', (QObject,), {})
                        QFormLayout = type('QFormLayout', (QObject,), {}); QCheckBox = type('QCheckBox', (QObject,), {}); QComboBox = type('QComboBox', (QObject,), {})
                        QLineEdit = type('QLineEdit', (QObject,), {})
                        def __getattr__(self, name): # Generic fallback for any missing QtWidget
                            if name == 'QApplication': return type('QApplication', (QObject,), {'instance': lambda: None, '__init__':lambda s,a:None})
                            return type(name, (QObject,), {})
                    class QtModule: MatchFixedString = 0
                    class DummyQtCoreModule: Qt = QtModule()
                    class DummyQtGuiModule: QIntValidator = type('QIntValidator', (QObject,), {}); QDoubleValidator = type('QDoubleValidator', (QObject,), {})

                    self.QtWidgets = DummyQtWidgetsModule()
                    self.QtCore = DummyQtCoreModule()
                    self.QtGui = DummyQtGuiModule()
                    self.QT_AVAILABLE = True # Let factory try to use these dummies
                    self._QT_BINDING_VERSION_CORE = "Dummy_Test_Main"


    mock_core_instance = MockCoreModule()

    try:
        import sys
        app = None
        if hasattr(mock_core_instance.QtWidgets, 'QApplication'):
            app = mock_core_instance.QtWidgets.QApplication.instance()
            if not app:
                app = mock_core_instance.QtWidgets.QApplication(sys.argv if 'sys' in globals() and hasattr(sys, 'argv') else [])

        mock_settings_data = {
            "api_base_url": "http://localhost:8011", "painter_export_path": "C:/temp/painter_export",
            "export_file_format": "png", "poll_timeout": 60.0, "log_level": "debug",
            "auto_unwrap_with_blender_on_pull": True, "blender_smart_uv_stretch_to_bounds": "True",
            "blender_smart_uv_angle_limit": 66.0, "some_integer_setting": 123,
            "a_float_setting": 45.6,
            "texture_workflow": "Metallic/Roughness",
            "normal_format": "DirectX",
            "unrepresented_setting": "should_pass_through"
        }

        dialog_instance = create_settings_dialog_instance(mock_core_instance, mock_settings_data)

        qdialog_accepted_val = 1 # Default
        if hasattr(mock_core_instance.QtWidgets.QDialog, 'Accepted'):
             qdialog_accepted_val = mock_core_instance.QtWidgets.QDialog.Accepted

        print(f"Is dialog functional before exec?: {dialog_instance._functional_ui}")
        result_code = dialog_instance.exec_()

        if result_code == qdialog_accepted_val:
            print("Settings Applied:", dialog_instance.get_settings())
        else:
            print(f"Settings Cancelled or UI not functional (Result code: {result_code})")
            if not dialog_instance._functional_ui:
                 print("Dialog UI itself reported as not functional.")
    except Exception as e_main:
        print(f"Error in __main__ example of settings_dialog.py (factory version): {e_main}")
        import traceback
        traceback.print_exc()
        print("This example is primarily for testing. Ensure compatible Qt bindings are available if a real UI is expected.")
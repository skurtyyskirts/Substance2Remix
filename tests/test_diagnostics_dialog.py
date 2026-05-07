import sys
import os
import builtins
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

class TestDiagnosticsDialog(unittest.TestCase):
    def setUp(self):
        # Save original state to avoid test pollution
        self.orig_sys_modules = dict(sys.modules)
        self.orig_import = builtins.__import__

        # Clean up any existing import of the module to allow testing both QT_AVAILABLE states
        if 'diagnostics_dialog' in sys.modules:
            del sys.modules['diagnostics_dialog']

    def tearDown(self):
        # Restore original state
        builtins.__import__ = self.orig_import

        # Remove any newly imported modules during the test to avoid polluting other tests
        keys_to_remove = [k for k in sys.modules if k not in self.orig_sys_modules]
        for k in keys_to_remove:
            del sys.modules[k]

        # Restore any modified modules
        for k, v in self.orig_sys_modules.items():
            sys.modules[k] = v

    def _import_with_qt(self, qt_available=True):
        mock_qt_utils = MagicMock()
        mock_qt_utils.QT_AVAILABLE = qt_available

        class MockDialog:
            def __init__(self, parent=None, **kwargs):
                self.parent = parent
                self.mock_calls_record = []

            def setWindowTitle(self, title):
                self.mock_calls_record.append(('setWindowTitle', title))

            def setMinimumWidth(self, w):
                self.mock_calls_record.append(('setMinimumWidth', w))

            def setMinimumHeight(self, h):
                self.mock_calls_record.append(('setMinimumHeight', h))

            def accept(self):
                self.mock_calls_record.append(('accept',))

            def exec(self):
                return 1

            def exec_(self):
                return 2

        if qt_available:
            mock_qt_utils.QtWidgets.QDialog = MockDialog
        else:
            mock_qt_utils.QtWidgets.QDialog = object

        def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "qt_utils" and level == 1:
                return mock_qt_utils
            return self.orig_import(name, globals, locals, fromlist, level)

        builtins.__import__ = custom_import

        # Import the module
        import diagnostics_dialog
        return diagnostics_dialog, mock_qt_utils

    def test_init_with_qt_available(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test Diagnostics Text")

        # Verify the actual methods from the file are called
        self.assertIn(('setWindowTitle', "RTX Remix Connector - Diagnostics"), dialog.mock_calls_record)
        self.assertIn(('setMinimumWidth', 760), dialog.mock_calls_record)
        self.assertIn(('setMinimumHeight', 520), dialog.mock_calls_record)

        # Verify text was set to the text_edit component
        mock_qt.QtWidgets.QPlainTextEdit.return_value.setPlainText.assert_called_with("Test Diagnostics Text")

        # Verify copy and close button connections
        mock_qt.QtWidgets.QPushButton.return_value.clicked.connect.assert_any_call(dialog._copy)
        mock_qt.QtWidgets.QPushButton.return_value.clicked.connect.assert_any_call(dialog.accept)

    def test_init_without_qt_available(self):
        dd_module, mock_qt = self._import_with_qt(False)
        dialog = dd_module.DiagnosticsDialog("Test Diagnostics Text")

        # When QT is not available, it simply stores the text and returns
        self.assertEqual(dialog._text, "Test Diagnostics Text")
        self.assertFalse(hasattr(dialog, "text_edit"))

    def test_copy_success(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test text")

        mock_clipboard = MagicMock()
        mock_qt.QtWidgets.QApplication.clipboard.return_value = mock_clipboard
        dialog.text_edit.toPlainText.return_value = "Copied text"

        dialog._copy()

        mock_clipboard.setText.assert_called_with("Copied text")

    def test_copy_clipboard_none(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test text")

        mock_qt.QtWidgets.QApplication.clipboard.return_value = None

        # Should not raise any exception
        dialog._copy()

    def test_copy_exception_handled(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test text")

        mock_qt.QtWidgets.QApplication.clipboard.side_effect = Exception("Clipboard error")

        # Exception should be caught and ignored silently
        dialog._copy()

    def test_exec_compatibility_exec(self):
        dd_module, mock_qt = self._import_with_qt(True)

        # Test with exec() available
        class MockQDialogWithExec:
            def __init__(self, parent=None): pass
            def setWindowTitle(self, title): pass
            def setMinimumWidth(self, w): pass
            def setMinimumHeight(self, h): pass
            def accept(self): pass
            def exec(self): return "exec_result"

        dd_module.DiagnosticsDialog.__bases__ = (MockQDialogWithExec,)
        dialog = dd_module.DiagnosticsDialog("Test")
        self.assertEqual(dialog.exec_(), "exec_result")

    def test_exec_compatibility_exec_underscore(self):
        dd_module, mock_qt = self._import_with_qt(True)

        # Test with only exec_() available
        class MockQDialogWithExecUnderscore:
            def __init__(self, parent=None): pass
            def setWindowTitle(self, title): pass
            def setMinimumWidth(self, w): pass
            def setMinimumHeight(self, h): pass
            def accept(self): pass
            def exec_(self): return "exec_underscore_result"

        dd_module.DiagnosticsDialog.__bases__ = (MockQDialogWithExecUnderscore,)
        dialog = dd_module.DiagnosticsDialog("Test")
        self.assertEqual(dialog.exec_(), "exec_underscore_result")


if __name__ == '__main__':
    unittest.main()

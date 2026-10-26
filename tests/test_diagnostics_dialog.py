import unittest
from unittest.mock import MagicMock

from ._isolated import load_isolated


class TestDiagnosticsDialog(unittest.TestCase):
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

        return load_isolated("diagnostics_dialog", qt_utils=mock_qt_utils), mock_qt_utils

    def test_init_with_qt_available(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test Diagnostics Text")

        # Verify the actual methods from the file are called
        self.assertIn(('setWindowTitle', "Substance2Remix - Diagnostics"), dialog.mock_calls_record)
        self.assertIn(('setMinimumWidth', 760), dialog.mock_calls_record)
        self.assertIn(('setMinimumHeight', 520), dialog.mock_calls_record)

        # Verify text was set to the text_edit component
        mock_qt.QtWidgets.QPlainTextEdit.return_value.setPlainText.assert_called_with("Test Diagnostics Text")

        # Verify log folder, copy and close button connections
        mock_qt.QtWidgets.QPushButton.return_value.clicked.connect.assert_any_call(dialog._open_log_folder)
        mock_qt.QtWidgets.QPushButton.return_value.clicked.connect.assert_any_call(dialog._copy)
        mock_qt.QtWidgets.QPushButton.return_value.clicked.connect.assert_any_call(dialog.accept)

    def test_open_log_folder_uses_desktop_services(self):
        dd_module, mock_qt = self._import_with_qt(True)
        dialog = dd_module.DiagnosticsDialog("Test", log_file_path="C:/plugin/logs/remix_connector.log")
        dialog._open_log_folder()
        mock_qt.QtCore.QUrl.fromLocalFile.assert_called_with("C:/plugin/logs")
        mock_qt.QtGui.QDesktopServices.openUrl.assert_called_once()

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

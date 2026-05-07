"""Tests for qt_utils.py — testing dynamic import logic for PySide6, PySide2, and PyQt5."""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch
import importlib

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestQtUtils(unittest.TestCase):
    """Test dynamically loading different Qt bindings."""

    def setUp(self):
        # Save original modules to restore later
        self.original_modules = sys.modules.copy()

    def tearDown(self):
        # Restore sys.modules
        sys.modules.clear()
        sys.modules.update(self.original_modules)

    def test_pyside6_fallback(self):
        """Test fallback to PySide6 when available."""
        mock_pyside6 = MagicMock()
        mock_pyside6.QtWidgets = MagicMock()
        mock_pyside6.QtCore = MagicMock()
        mock_pyside6.QtCore.Signal = 'PySide6_Signal'
        mock_pyside6.QtCore.Slot = 'PySide6_Slot'
        mock_pyside6.QtCore.QThread = 'PySide6_QThread'
        mock_pyside6.QtCore.QObject = 'PySide6_QObject'
        mock_pyside6.QtCore.QRunnable = 'PySide6_QRunnable'
        mock_pyside6.QtCore.QThreadPool = 'PySide6_QThreadPool'
        mock_pyside6.QtGui = MagicMock()
        mock_pyside6.QtGui.QAction = 'PySide6_QAction'

        sys.modules['PySide6'] = mock_pyside6

        # Remove any other Qt bindings to be safe
        for m in ['PySide2', 'PyQt5']:
            sys.modules[m] = None

        import qt_utils
        importlib.reload(qt_utils)

        self.assertEqual(qt_utils.QT_AVAILABLE, True)
        self.assertEqual(qt_utils.QT_BINDING, "PySide6")
        self.assertEqual(qt_utils.Signal, 'PySide6_Signal')
        self.assertEqual(qt_utils.QAction, 'PySide6_QAction')

    def test_pyside2_fallback(self):
        """Test fallback to PySide2 when PySide6 is unavailable."""
        sys.modules['PySide6'] = None

        mock_pyside2 = MagicMock()
        mock_pyside2.QtWidgets = MagicMock()
        mock_pyside2.QtCore = MagicMock()
        mock_pyside2.QtCore.Signal = 'PySide2_Signal'
        mock_pyside2.QtGui = MagicMock()
        mock_pyside2.QtWidgets.QAction = 'PySide2_QAction'
        sys.modules['PySide2'] = mock_pyside2

        sys.modules['PyQt5'] = None

        import qt_utils
        importlib.reload(qt_utils)

        self.assertEqual(qt_utils.QT_AVAILABLE, True)
        self.assertEqual(qt_utils.QT_BINDING, "PySide2")
        self.assertEqual(qt_utils.Signal, 'PySide2_Signal')
        self.assertEqual(qt_utils.QAction, 'PySide2_QAction')

    def test_pyqt5_fallback(self):
        """Test fallback to PyQt5 when PySide6 and PySide2 are unavailable."""
        sys.modules['PySide6'] = None
        sys.modules['PySide2'] = None

        mock_pyqt5 = MagicMock()
        mock_pyqt5.QtWidgets = MagicMock()
        mock_pyqt5.QtCore = MagicMock()
        mock_pyqt5.QtCore.pyqtSignal = 'PyQt5_Signal'
        mock_pyqt5.QtGui = MagicMock()
        mock_pyqt5.QtWidgets.QAction = 'PyQt5_QAction'
        sys.modules['PyQt5'] = mock_pyqt5

        import qt_utils
        importlib.reload(qt_utils)

        self.assertEqual(qt_utils.QT_AVAILABLE, True)
        self.assertEqual(qt_utils.QT_BINDING, "PyQt5")
        self.assertEqual(qt_utils.Signal, 'PyQt5_Signal')
        self.assertEqual(qt_utils.QAction, 'PyQt5_QAction')

    def test_no_bindings_available(self):
        """Test fallback when no Qt bindings are available."""
        sys.modules['PySide6'] = None
        sys.modules['PySide2'] = None
        sys.modules['PyQt5'] = None

        with patch('builtins.print') as mock_print:
            import qt_utils
            importlib.reload(qt_utils)

            self.assertEqual(qt_utils.QT_AVAILABLE, False)
            self.assertEqual(qt_utils.QT_BINDING, None)
            self.assertEqual(qt_utils.Signal, None)

            mock_print.assert_called_with(
                "[RemixConnector QtUtils] CRITICAL: No compatible Qt binding found "
                "(PySide6, PySide2, PyQt5). UI will not work."
            )

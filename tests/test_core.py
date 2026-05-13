import unittest
import sys
import os
import builtins
from unittest.mock import patch, MagicMock

# Insert the parent directory into sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup mocks for Qt base classes because they aren't available in standard CI context
class MockQObject:
    def __init__(self, *args, **kwargs):
        pass

class SignalDescriptor:
    def __init__(self, *args):
        self.args = args
    def __get__(self, obj, objtype=None):
        return MagicMock()

def MockSlot(*args):
    def decorator(func): return func
    return decorator

class MockQThreadPoolInstance:
    def setMaxThreadCount(self, *args): pass
    def maxThreadCount(self): return 4

class MockQThreadPool:
    def __init__(self):
        self._maxThreadCount = 4
    def setMaxThreadCount(self, count):
        self._maxThreadCount = count
    def maxThreadCount(self):
        return self._maxThreadCount
    @staticmethod
    def globalInstance(): return MockQThreadPoolInstance()

# Create a mock representation for `qt_utils`
mock_qt = MagicMock()
mock_qt.QObject = MockQObject
mock_qt.Signal = SignalDescriptor
mock_qt.Slot = MockSlot
mock_qt.QThreadPool = MockQThreadPool
mock_qt.QRunnable = MagicMock()
mock_qt.QThread = MagicMock()
mock_qt.QtWidgets = MagicMock()
mock_qt.QtCore = MagicMock()
mock_qt.QT_BINDING = "None"


class TestCoreSettingsError(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to temporarily modify __import__ to intercept local module imports during `core` init
        cls.original_import = builtins.__import__
        cls.original_modules = dict(sys.modules)

        # Ensure cleanup runs even if setUpClass fails
        cls.addClassCleanup(cls._cleanup)

        def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 1:
                if name == 'qt_utils':
                    return mock_qt
                elif name == 'plugin_info':
                    m = MagicMock()
                    m.PLUGIN_NAME = "MockPlugin"
                    m.PLUGIN_VERSION = "1.0.0"
                    m.PLUGIN_REPO_URL = ""
                    m.PLUGIN_DESCRIPTION = ""
                    return m
                elif name == 'settings_schema':
                    m = MagicMock()
                    m.sanitize_settings = lambda x, y: x
                    m.atomic_write_json = MagicMock()
                    return m
                else:
                    return MagicMock()
            return cls.original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = custom_import

        if 'core' in sys.modules:
            del sys.modules['core']

        import core
        cls.core_module = core

    @classmethod
    def _cleanup(cls):
        builtins.__import__ = getattr(cls, 'original_import', builtins.__import__)

        # Clean up added modules from sys.modules to prevent pollution
        if 'core' in sys.modules:
            del sys.modules['core']

        if hasattr(cls, 'original_modules'):
            keys_to_remove = [k for k in sys.modules if k not in cls.original_modules]
            for k in keys_to_remove:
                del sys.modules[k]
            sys.modules.update(cls.original_modules)

    @classmethod
    def tearDownClass(cls):
        pass # Work is done in addClassCleanup

    def test_load_settings_error(self):
        """Test that load_settings properly catches exceptions and falls back to defaults."""
        # Mock os.makedirs to avoid actually writing to the file system when the plugin initializes
        with patch('os.makedirs'):
            plugin = self.core_module.RemixConnectorPlugin()

        # Replace the logging method to observe if it logs the error correctly
        plugin.log_error = MagicMock()

        # Force os.path.exists to raise an Exception inside the try block of load_settings
        with patch('os.path.exists', side_effect=Exception("Simulated error reading settings")):
            plugin.load_settings()

        # Verify log_error was called with the correct message indicating fallback
        plugin.log_error.assert_called_once()
        self.assertTrue(
            "Failed to load settings (using defaults)" in plugin.log_error.call_args[0][0]
        )
        # Verify the settings are successfully sanitized into an empty dict because of the mock lambda x,y:x
        # and the fallback raw={} in core.py
        self.assertEqual(plugin.settings, {})

if __name__ == '__main__':
    unittest.main()

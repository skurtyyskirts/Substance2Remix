import unittest
import sys
import os
import json
import builtins
import importlib
from unittest.mock import MagicMock, patch, mock_open, call

# Insert the parent directory of the app into sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up mock QT before importing core
class MockQObject:
    def __init__(self, *args, **kwargs): pass
class MockQRunnable: pass
class MockQThreadPool:
    def setMaxThreadCount(self, c): pass
    @staticmethod
    def globalInstance():
        m = MagicMock()
        m.maxThreadCount.return_value = 4
        return m

class SignalDescriptor:
    def __init__(self, *args): self.args = args
    def __get__(self, obj, objtype=None):
        if obj is None: return self
        if not hasattr(obj, '_mock_signals'): obj._mock_signals = {}
        name = id(self)
        if name not in obj._mock_signals: obj._mock_signals[name] = MagicMock()
        return obj._mock_signals[name]
def MockSlot(*args): return lambda f: f

class MockQtWidgets:
    class QMenu: pass
    class QAction: pass
class MockQtCore:
    class Qt:
        QueuedConnection = 2

mock_qt_utils = MagicMock()
mock_qt_utils.QObject = MockQObject
mock_qt_utils.QRunnable = MockQRunnable
mock_qt_utils.QThreadPool = MockQThreadPool
mock_qt_utils.Signal = SignalDescriptor
mock_qt_utils.Slot = MockSlot
mock_qt_utils.QtWidgets = MockQtWidgets
mock_qt_utils.QtCore = MockQtCore
mock_qt_utils.QT_BINDING = "Mock"

# mock substance_painter logging
mock_sp_logging = MagicMock()
sys.modules['substance_painter'] = MagicMock()
sys.modules['substance_painter.logging'] = mock_sp_logging
sys.modules['substance_painter.ui'] = MagicMock()

# Instead of fighting __import__, let's copy the code and test just the class
# by compiling it dynamically or simply modifying sys.path to run as package

class TestCore(unittest.TestCase):
    def setUp(self):
        self.orig_modules = dict(sys.modules)

        # Load as module
        import importlib.util

        # First setup all the local dependencies in sys.modules
        sys.modules['qt_utils'] = mock_qt_utils

        pi = MagicMock()
        pi.PLUGIN_NAME = "TestPlugin"
        pi.PLUGIN_VERSION = "1.0.0"
        pi.PLUGIN_REPO_URL = "test"
        pi.PLUGIN_DESCRIPTION = "test"
        sys.modules['plugin_info'] = pi
        sys.modules['dependency_manager'] = MagicMock()
        sys.modules['remix_api'] = MagicMock()
        sys.modules['texture_processor'] = MagicMock()
        sys.modules['painter_controller'] = MagicMock()
        sys.modules['async_utils'] = MagicMock()
        sys.modules['settings_dialog'] = MagicMock()
        sys.modules['settings_schema'] = MagicMock()
        sys.modules['diagnostics_dialog'] = MagicMock()

        # Hack to change relative to absolute imports temporarily
        core_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core.py')
        with open(core_path, 'r') as f:
            content = f.read()

        content = content.replace("from . import", "import")
        content = content.replace("from .", "from ")

        # Write to a temp file and load it
        import tempfile
        fd, temp_path = tempfile.mkstemp(suffix='.py')
        os.close(fd)
        with open(temp_path, 'w') as f:
            f.write(content)

        spec = importlib.util.spec_from_file_location("dynamic_core", temp_path)
        self.dynamic_core = importlib.util.module_from_spec(spec)
        sys.modules["dynamic_core"] = self.dynamic_core
        spec.loader.exec_module(self.dynamic_core)
        os.remove(temp_path)

        # After importing core, patch out the heavy parts
        self.patcher1 = patch.object(self.dynamic_core, 'RemixAPIClient', create=True)
        self.patcher2 = patch.object(self.dynamic_core, 'TextureProcessor', create=True)
        self.patcher3 = patch.object(self.dynamic_core, 'PainterController', create=True)
        self.patcher4 = patch.object(self.dynamic_core, 'sanitize_settings', create=True)

        self.patcher1.start()
        self.patcher2.start()
        self.patcher3.start()
        self.patcher4.start()

    def tearDown(self):
        self.patcher1.stop()
        self.patcher2.stop()
        self.patcher3.stop()
        self.patcher4.stop()

        sys.modules.clear()
        sys.modules.update(self.orig_modules)

    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open)
    @patch('json.load')
    def test_load_settings_error(self, mock_json_load, mock_file, mock_exists):
        # Mock settings file exists but json.load throws an exception
        mock_exists.return_value = True
        mock_json_load.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        self.dynamic_core.sanitize_settings.return_value = {"mocked": "settings"}

        # We need to suppress the log_error during init
        with patch.object(self.dynamic_core.RemixConnectorPlugin, 'log_error') as mock_log_error:
            # Instantiate RemixConnectorPlugin
            plugin = self.dynamic_core.RemixConnectorPlugin()

            # Reset mock after __init__ calls load_settings
            mock_log_error.reset_mock()
            self.dynamic_core.sanitize_settings.reset_mock()

            # Call load_settings manually
            plugin.load_settings()

            # Assertions
            mock_log_error.assert_called_once()
            self.assertIn("Failed to load settings (using defaults)", mock_log_error.call_args[0][0])
            self.dynamic_core.sanitize_settings.assert_called_once_with({}, self.dynamic_core.PLUGIN_DIR)
            self.assertEqual(plugin.settings, {"mocked": "settings"})

if __name__ == '__main__':
    unittest.main()

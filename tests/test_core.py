import unittest
import sys
import os
import builtins
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestCoreSettings(unittest.TestCase):
    def setUp(self):
        self.orig_modules = dict(sys.modules)

        # Mocks for testing environment
        mock_dep = MagicMock()
        mock_qt = MagicMock()
        mock_qt.QObject = object
        mock_qt.Signal = MagicMock()
        mock_qt.Slot = MagicMock()
        mock_qt.QThread = MagicMock()
        mock_qt.QRunnable = MagicMock()

        class MockThreadPool:
            def setMaxThreadCount(self, count):
                pass
            @classmethod
            def globalInstance(cls):
                m = MagicMock()
                m.maxThreadCount.return_value = 4
                return m

        mock_qt.QThreadPool = MockThreadPool
        mock_qt.QtWidgets = MagicMock()
        mock_qt.QtCore = MagicMock()
        mock_qt.QT_BINDING = "Mocked"

        mock_plugin_info = MagicMock()
        mock_plugin_info.PLUGIN_NAME = "test"
        mock_plugin_info.PLUGIN_VERSION = "1.0"
        mock_plugin_info.PLUGIN_REPO_URL = "test"
        mock_plugin_info.PLUGIN_DESCRIPTION = "test"

        mock_remix_api = MagicMock()
        mock_remix_api.REMIX_ATTR_SUFFIX_TO_PBR_MAP = {}
        mock_remix_api.PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP = {}

        mock_texture_processor = MagicMock()
        mock_painter_controller = MagicMock()
        mock_async_utils = MagicMock()
        mock_settings_dialog = MagicMock()

        mock_settings_schema = MagicMock()
        # Ensure sanitize_settings acts as a simple pass-through.
        # MagicMock.__getattr__ returning MagicMocks causes raw variables
        # to become mocks.
        def _sanitize_settings(raw, *args, **kwargs):
            return raw
        mock_settings_schema.sanitize_settings = _sanitize_settings
        mock_settings_schema.atomic_write_json = MagicMock()

        mock_diagnostics = MagicMock()

        sys.modules['dependency_manager'] = mock_dep
        sys.modules['qt_utils'] = mock_qt
        sys.modules['plugin_info'] = mock_plugin_info
        sys.modules['remix_api'] = mock_remix_api
        sys.modules['texture_processor'] = mock_texture_processor
        sys.modules['painter_controller'] = mock_painter_controller
        sys.modules['async_utils'] = mock_async_utils
        sys.modules['settings_dialog'] = mock_settings_dialog
        sys.modules['settings_schema'] = mock_settings_schema
        sys.modules['diagnostics_dialog'] = mock_diagnostics

        self.orig_import = builtins.__import__
        def mock_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level > 0:
                # Mock module that returns components dynamically
                class MockModule:
                    def __getattr__(self, key):
                        if key in sys.modules:
                            return sys.modules[key]
                        if key == 'QObject':
                            return object
                        if key == 'QThreadPool':
                            return MockThreadPool
                        if key == 'sanitize_settings':
                            return _sanitize_settings
                        return MagicMock()
                return MockModule()
            return self.orig_import(name, globals, locals, fromlist, level)

        builtins.__import__ = mock_import

        # Force reload of core if it was already imported
        if 'core' in sys.modules:
            del sys.modules['core']

        import core
        self.core = core

    def tearDown(self):
        builtins.__import__ = self.orig_import
        sys.modules.clear()
        sys.modules.update(self.orig_modules)

    @patch('core.os.path.exists')
    @patch('core.json.load')
    @patch('builtins.open')
    def test_load_settings_exception(self, mock_open, mock_json_load, mock_exists):
        # Prevent load_settings being called in __init__
        with patch.object(self.core.RemixConnectorPlugin, 'load_settings') as mock_load:
            plugin = self.core.RemixConnectorPlugin()

        # Now mock log_error
        plugin.log_error = MagicMock()

        # Setup error conditions
        mock_exists.return_value = True
        mock_json_load.side_effect = Exception("Corrupt JSON")

        # Call manually
        self.core.RemixConnectorPlugin.load_settings(plugin)

        plugin.log_error.assert_called_with("Failed to load settings (using defaults): Corrupt JSON", exc_info=True)
        self.assertEqual(plugin.settings, {})

if __name__ == '__main__':
    unittest.main()

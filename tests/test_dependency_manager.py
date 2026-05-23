import unittest
import sys
import os
from unittest.mock import patch, MagicMock

class TestDependencyManager(unittest.TestCase):
    def setUp(self):
        self.orig_modules = dict(sys.modules)
        if 'dependency_manager' in sys.modules:
            del sys.modules['dependency_manager']

    def tearDown(self):
        sys.modules.clear()
        sys.modules.update(self.orig_modules)

    @patch('builtins.print')
    def test_ensure_dependencies_installed_success(self, mock_print):
        import dependency_manager

        with patch('dependency_manager._purge_stale_vendored_modules'):
            result = dependency_manager.ensure_dependencies_installed()
            self.assertTrue(result)
            mock_print.assert_any_call("[RemixConnector DependencyManager] INFO: Dependency 'requests' imported successfully.")

    @patch('builtins.print')
    def test_ensure_dependencies_installed_import_error(self, mock_print):
        import dependency_manager

        # Simulate import error
        original_import = __import__
        def mock_import(name, *args, **kwargs):
            if name == 'requests':
                raise ImportError("Mocked import error")
            return original_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=mock_import):
            with patch('dependency_manager._purge_stale_vendored_modules'):
                result = dependency_manager.ensure_dependencies_installed()
                self.assertFalse(result)
                mock_print.assert_any_call("[RemixConnector DependencyManager] WARN: Failed to import dependencies even after adding vendor path: Mocked import error")

    @patch('builtins.print')
    def test_ensure_dependencies_installed_no_vendor_dir(self, mock_print):
        import dependency_manager

        with patch('os.path.isdir', return_value=False):
            result = dependency_manager.ensure_dependencies_installed()
            self.assertFalse(result)
            mock_print.assert_any_call(f"[RemixConnector DependencyManager] WARN: Vendor directory not found at: {dependency_manager.VENDOR_DIR_PATH}")

    @patch('builtins.print')
    def test_purge_stale_vendored_modules(self, mock_print):
        import dependency_manager

        # Add a dummy module to sys.modules that looks stale
        dummy_mod = MagicMock()
        dummy_mod.__file__ = "/some/other/path/requests/__init__.py"

        sys.modules['requests'] = dummy_mod
        sys.modules['requests.models'] = MagicMock()

        dependency_manager._purge_stale_vendored_modules()

        self.assertNotIn('requests', sys.modules)
        self.assertNotIn('requests.models', sys.modules)

if __name__ == '__main__':
    unittest.main()

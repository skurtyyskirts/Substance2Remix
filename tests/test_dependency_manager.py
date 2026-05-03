import unittest
from unittest.mock import patch, MagicMock
import os
import sys

import dependency_manager

class TestDependencyManager(unittest.TestCase):

    @patch('dependency_manager.os.path.isdir')
    @patch('dependency_manager._log_warning')
    def test_vendor_dir_not_found(self, mock_log_warning, mock_isdir):
        mock_isdir.return_value = False
        result = dependency_manager.ensure_dependencies_installed()
        self.assertFalse(result)
        mock_isdir.assert_called_once_with(dependency_manager.VENDOR_DIR_PATH)
        mock_log_warning.assert_called_once()

    @patch('dependency_manager.os.path.isdir')
    @patch('dependency_manager._log_info')
    def test_vendor_dir_not_in_sys_path(self, mock_log_info, mock_isdir):
        mock_isdir.return_value = True

        test_sys_path = []

        with patch.object(sys, 'path', test_sys_path):
            with patch.dict('sys.modules', {'requests': MagicMock(), 'PIL': MagicMock()}):
                result = dependency_manager.ensure_dependencies_installed()

                self.assertTrue(result)
                self.assertIn(dependency_manager.VENDOR_DIR_PATH, sys.path)
                self.assertEqual(sys.path[0], dependency_manager.VENDOR_DIR_PATH)

    @patch('dependency_manager.os.path.isdir')
    @patch('dependency_manager._log_info')
    def test_vendor_dir_already_in_sys_path(self, mock_log_info, mock_isdir):
        mock_isdir.return_value = True

        test_sys_path = [dependency_manager.VENDOR_DIR_PATH, 'other_path']

        with patch.object(sys, 'path', test_sys_path):
            with patch.dict('sys.modules', {'requests': MagicMock(), 'PIL': MagicMock()}):
                result = dependency_manager.ensure_dependencies_installed()

                self.assertTrue(result)
                self.assertEqual(sys.path, [dependency_manager.VENDOR_DIR_PATH, 'other_path'])

    @patch('dependency_manager.os.path.isdir')
    @patch('dependency_manager._log_warning')
    def test_import_failure(self, mock_log_warning, mock_isdir):
        mock_isdir.return_value = True

        test_sys_path = [dependency_manager.VENDOR_DIR_PATH]

        with patch.object(sys, 'path', test_sys_path):
            with patch.dict('sys.modules', {'requests': None, 'PIL': None}):
                result = dependency_manager.ensure_dependencies_installed()

                self.assertFalse(result)
                mock_log_warning.assert_called_once()

if __name__ == '__main__':
    unittest.main()

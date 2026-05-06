import os
import sys
import unittest
import json
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import plugin_info
import builtins

real_import = builtins.__import__
def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'plugin_info' and level == 1:
        return plugin_info
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = custom_import
import settings_schema
builtins.__import__ = real_import

class TestSettingsSchema(unittest.TestCase):
    def test_atomic_write_json_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = os.path.join(temp_dir, "test.json")
            data = {"key": "value"}

            success, err = settings_schema.atomic_write_json(file_path, data)

            self.assertTrue(success)
            self.assertEqual(err, "")
            self.assertTrue(os.path.exists(file_path))
            with open(file_path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), data)

    def test_atomic_write_json_directory_creation_fails(self):
        # Even if makedirs fails, it should still try to write
        with patch('os.makedirs') as mock_makedirs:
            mock_makedirs.side_effect = PermissionError("Cannot create dir")

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, "test2.json")
                data = {"key": "value"}

                success, err = settings_schema.atomic_write_json(file_path, data)

                self.assertTrue(success)
                self.assertEqual(err, "")
                with open(file_path, "r", encoding="utf-8") as f:
                    self.assertEqual(json.load(f), data)

    def test_atomic_write_json_write_fails(self):
        # If writing the temp file fails, it should catch the exception and clean up if possible
        with patch('builtins.open') as mock_open_func:
            mock_open_func.side_effect = IOError("Disk full")

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, "test3.json")
                data = {"key": "value"}

                success, err = settings_schema.atomic_write_json(file_path, data)

                self.assertFalse(success)
                self.assertEqual(err, "Disk full")
                self.assertFalse(os.path.exists(file_path))

    def test_atomic_write_json_replace_fails(self):
        # If os.replace fails, it should catch the exception and remove tmp file
        with patch('os.replace') as mock_replace:
            mock_replace.side_effect = PermissionError("Cannot replace")

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, "test4.json")
                tmp_path = file_path + ".tmp"
                data = {"key": "value"}

                # Verify tmp file is not there initially
                self.assertFalse(os.path.exists(tmp_path))

                success, err = settings_schema.atomic_write_json(file_path, data)

                self.assertFalse(success)
                self.assertEqual(err, "Cannot replace")

                # Check that cleanup was performed
                self.assertFalse(os.path.exists(tmp_path))
                self.assertFalse(os.path.exists(file_path))

if __name__ == '__main__':
    unittest.main()

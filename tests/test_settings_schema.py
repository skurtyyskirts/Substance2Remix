import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

# Ensure the parent directory is in the path to import settings_schema
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Handle relative import inside settings_schema by mocking the package
import plugin_info
import importlib.util
spec = importlib.util.spec_from_file_location("remix_plugin.settings_schema", os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings_schema.py"))
settings_schema = importlib.util.module_from_spec(spec)
sys.modules["remix_plugin"] = sys.modules[__name__] # dummy package
sys.modules["remix_plugin.plugin_info"] = plugin_info
sys.modules["remix_plugin.settings_schema"] = settings_schema
spec.loader.exec_module(settings_schema)

_coerce_bool = settings_schema._coerce_bool
_coerce_float = settings_schema._coerce_float
_coerce_str = settings_schema._coerce_str
_detect_texconv_path = settings_schema._detect_texconv_path
default_settings = settings_schema.default_settings
sanitize_settings = settings_schema.sanitize_settings
atomic_write_json = settings_schema.atomic_write_json

class TestSettingsSchema(unittest.TestCase):

    def test_coerce_bool(self):
        # Boolean inputs
        self.assertTrue(_coerce_bool(True))
        self.assertFalse(_coerce_bool(False))

        # Integer/Float inputs
        self.assertTrue(_coerce_bool(1))
        self.assertFalse(_coerce_bool(0))
        self.assertTrue(_coerce_bool(1.0))
        self.assertFalse(_coerce_bool(0.0))

        # Truthy strings
        for s in ["1", "true", "yes", "y", "on", "  True  ", "YES"]:
            self.assertTrue(_coerce_bool(s), f"Failed truthy string: {s}")

        # Falsy strings
        for s in ["0", "false", "no", "n", "off", "  False  ", "NO"]:
            self.assertFalse(_coerce_bool(s), f"Failed falsy string: {s}")

        # Invalid types/strings returning default
        self.assertFalse(_coerce_bool("invalid", default=False))
        self.assertTrue(_coerce_bool("invalid", default=True))
        self.assertTrue(_coerce_bool({}, default=True))

    def test_coerce_float(self):
        # Numeric inputs
        self.assertEqual(_coerce_float(1, 0.0), 1.0)
        self.assertEqual(_coerce_float(1.5, 0.0), 1.5)

        # String representations
        self.assertEqual(_coerce_float(" 2.5 ", 0.0), 2.5)
        self.assertEqual(_coerce_float("3", 0.0), 3.0)

        # Invalid string representations returning default
        self.assertEqual(_coerce_float("invalid", 4.0), 4.0)
        self.assertEqual(_coerce_float({}, 5.0), 5.0)

    def test_coerce_str(self):
        # String inputs
        self.assertEqual(_coerce_str("test", "default"), "test")

        # None input
        self.assertEqual(_coerce_str(None, "default"), "default")

        # Other types
        self.assertEqual(_coerce_str(123, "default"), "123")
        self.assertEqual(_coerce_str(1.5, "default"), "1.5")

    @patch('os.path.isfile')
    def test_detect_texconv_path(self, mock_isfile):
        # Existing file
        mock_isfile.return_value = True
        _detect_texconv_path.cache_clear()
        expected_path = os.path.join("dummy_dir", "texconv.exe")
        self.assertEqual(_detect_texconv_path("dummy_dir"), expected_path)

        # Missing file
        mock_isfile.return_value = False
        _detect_texconv_path.cache_clear()
        self.assertEqual(_detect_texconv_path("dummy_dir"), "")

        # Exception
        mock_isfile.side_effect = Exception("mocked error")
        _detect_texconv_path.cache_clear()
        self.assertEqual(_detect_texconv_path("dummy_dir"), "")
        _detect_texconv_path.cache_clear()

    @patch('os.path.isfile')
    def test_default_settings(self, mock_isfile):
        mock_isfile.return_value = True
        _detect_texconv_path.cache_clear()

        settings = default_settings("dummy_dir")
        self.assertEqual(settings["settings_version"], 1)
        self.assertEqual(settings["api_base_url"], "http://localhost:8011")
        self.assertEqual(settings["poll_timeout"], 60.0)
        self.assertEqual(settings["log_level"], "info")

        expected_path = os.path.join("dummy_dir", "texconv.exe")
        self.assertEqual(settings["texconv_path"], expected_path)

    @patch('os.path.isfile')
    def test_sanitize_settings(self, mock_isfile):
        mock_isfile.return_value = True
        _detect_texconv_path.cache_clear()

        # Empty dict should return defaults
        sanitized_empty = sanitize_settings({}, "dummy_dir")
        self.assertEqual(sanitized_empty["api_base_url"], "http://localhost:8011")
        self.assertEqual(sanitized_empty["poll_timeout"], 60.0)

        # Test specific coercions and fallbacks
        input_settings = {
            "api_base_url": "http://custom:1234",
            "poll_timeout": "30.5",
            "log_level": "INVALID",
            "unknown_key": "preserved"
        }

        sanitized = sanitize_settings(input_settings, "dummy_dir")
        self.assertEqual(sanitized["api_base_url"], "http://custom:1234")
        self.assertEqual(sanitized["poll_timeout"], 30.5)
        # log_level fallback
        self.assertEqual(sanitized["log_level"], "info")
        # Preservation of unknown keys
        self.assertEqual(sanitized["unknown_key"], "preserved")

        # Test texconv_path fallback to detect when invalid/empty
        mock_isfile.return_value = False
        _detect_texconv_path.cache_clear()
        input_settings_texconv = {"texconv_path": ""}
        sanitized_texconv = sanitize_settings(input_settings_texconv, "dummy_dir")
        self.assertEqual(sanitized_texconv["texconv_path"], "")

    def test_atomic_write_json(self):
        data = {"key": "value"}

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = os.path.join(tmpdir, "settings.json")

            # Successful write
            success, err = atomic_write_json(file_path, data)
            self.assertTrue(success)
            self.assertEqual(err, "")

            with open(file_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(loaded, data)

            # Failure simulation: mock os.replace
            with patch('os.replace', side_effect=Exception("mocked replace error")):
                success, err = atomic_write_json(file_path, data)
                self.assertFalse(success)
                self.assertEqual(err, "mocked replace error")

                # Verify .tmp file is cleaned up
                self.assertFalse(os.path.exists(f"{file_path}.tmp"))

if __name__ == '__main__':
    unittest.main()

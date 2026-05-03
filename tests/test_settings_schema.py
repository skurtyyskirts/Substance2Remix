import os
import sys
import tempfile
import unittest

# Fix the import path so we can import from the root directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The main problem is that `settings_schema.py` uses `from .plugin_info import PLUGIN_ID`.
# When we run `python -m unittest discover tests`, the top-level scripts aren't loaded as a package.
# To let relative imports work when importing `settings_schema` directly, we can define a dummy module for the package!

import types
import plugin_info

# Create a fake package module for the root
pkg = types.ModuleType("substance2remix")
pkg.__path__ = [os.path.dirname(os.path.dirname(__file__))]
sys.modules["substance2remix"] = pkg

# Also register plugin_info under this package
sys.modules["substance2remix.plugin_info"] = plugin_info

# Now we can import settings_schema as part of this package!
import importlib.util
spec = importlib.util.spec_from_file_location("substance2remix.settings_schema", os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings_schema.py"))
settings_schema = importlib.util.module_from_spec(spec)
sys.modules["substance2remix.settings_schema"] = settings_schema
# This will execute the module. The relative import `from .plugin_info` will resolve to `substance2remix.plugin_info`.
spec.loader.exec_module(settings_schema)


sanitize_settings = settings_schema.sanitize_settings
default_settings = settings_schema.default_settings
DEFAULT_REMIX_API_BASE_URL = settings_schema.DEFAULT_REMIX_API_BASE_URL
SETTINGS_VERSION = settings_schema.SETTINGS_VERSION
from plugin_info import PLUGIN_ID

class TestSanitizeSettings(unittest.TestCase):
    def setUp(self):
        self.plugin_dir = "/fake/plugin/dir"

    def test_empty_settings(self):
        settings = {}
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["api_base_url"], DEFAULT_REMIX_API_BASE_URL)
        self.assertEqual(result["poll_timeout"], 60.0)
        self.assertEqual(result["log_level"], "info")
        self.assertEqual(result["use_simple_tiling_mesh_on_pull"], False)
        self.assertEqual(result["settings_version"], SETTINGS_VERSION)
        self.assertEqual(result["plugin_id"], PLUGIN_ID)

    def test_type_coercion_bool(self):
        settings = {
            "use_simple_tiling_mesh_on_pull": "true",
            "auto_unwrap_with_blender_on_pull": "1",
            "blender_smart_uv_stretch_to_bounds": "yes"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertTrue(result["use_simple_tiling_mesh_on_pull"])
        self.assertTrue(result["auto_unwrap_with_blender_on_pull"])
        self.assertTrue(result["blender_smart_uv_stretch_to_bounds"])

    def test_type_coercion_bool_false(self):
        settings = {
            "use_simple_tiling_mesh_on_pull": "false",
            "auto_unwrap_with_blender_on_pull": "0",
            "blender_smart_uv_stretch_to_bounds": "no"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertFalse(result["use_simple_tiling_mesh_on_pull"])
        self.assertFalse(result["auto_unwrap_with_blender_on_pull"])
        self.assertFalse(result["blender_smart_uv_stretch_to_bounds"])

    def test_type_coercion_float(self):
        settings = {
            "poll_timeout": "30.5",
            "blender_smart_uv_angle_limit": "45"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["poll_timeout"], 30.5)
        self.assertEqual(result["blender_smart_uv_angle_limit"], 45.0)

    def test_invalid_log_level_fallback(self):
        settings = {
            "log_level": "invalid_level"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["log_level"], "info")

    def test_invalid_export_format_fallback(self):
        settings = {
            "export_file_format": "tiff"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["export_file_format"], "png")

    def test_unknown_keys_preserved(self):
        settings = {
            "unknown_key": "some_value",
            "another_unknown": 123
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["unknown_key"], "some_value")
        self.assertEqual(result["another_unknown"], 123)

    def test_valid_custom_settings(self):
        settings = {
            "api_base_url": "http://127.0.0.1:9000",
            "log_level": "debug",
            "export_file_format": "jpg"
        }
        result = sanitize_settings(settings, self.plugin_dir)
        self.assertEqual(result["api_base_url"], "http://127.0.0.1:9000")
        self.assertEqual(result["log_level"], "debug")
        self.assertEqual(result["export_file_format"], "jpg")

if __name__ == "__main__":
    unittest.main()

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

# Insert the parent directory so we can import modules
parent_dir = os.path.dirname(os.path.dirname(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Mock the current module as a package to satisfy relative imports
class DummyPluginInfo:
    PLUGIN_ID = 'test_plugin_id'

# In python testing, the file under test might have relative imports.
# We map it to pretend the module is loaded inside a package called 'app'.
import importlib.util
sys.modules['app.plugin_info'] = DummyPluginInfo()

spec = importlib.util.spec_from_file_location("app.settings_schema", os.path.join(parent_dir, "settings_schema.py"))
settings_schema = importlib.util.module_from_spec(spec)
sys.modules["app.settings_schema"] = settings_schema

# Execute it as part of 'app'
settings_schema.__name__ = 'app.settings_schema'
settings_schema.__package__ = 'app'
spec.loader.exec_module(settings_schema)

class TestSettingsSchema(unittest.TestCase):
    def test_sanitize_empty_settings(self):
        """Test that an empty dictionary falls back to default settings."""
        plugin_dir = "/dummy/plugin/dir"
        result = settings_schema.sanitize_settings({}, plugin_dir)

        expected_defaults = settings_schema.default_settings(plugin_dir)

        # Ensure critical defaults are present and correct
        self.assertEqual(result["api_base_url"], settings_schema.DEFAULT_REMIX_API_BASE_URL)
        self.assertEqual(result["poll_timeout"], 60.0)
        self.assertEqual(result["log_level"], "info")
        self.assertFalse(result["use_simple_tiling_mesh_on_pull"])
        self.assertEqual(result["export_file_format"], "png")
        self.assertEqual(result["settings_version"], settings_schema.SETTINGS_VERSION)

        # Check that unknown keys in expected aren't missing
        for key, val in expected_defaults.items():
            self.assertIn(key, result)

    def test_sanitize_preserves_unknown_keys(self):
        """Test that keys not in default settings are kept intact."""
        plugin_dir = "/dummy"
        input_settings = {"my_custom_key": "my_custom_value", "another_key": 123}
        result = settings_schema.sanitize_settings(input_settings, plugin_dir)

        self.assertEqual(result["my_custom_key"], "my_custom_value")
        self.assertEqual(result["another_key"], 123)

    def test_sanitize_type_coercion_bool(self):
        """Test that various boolean string representations are coerced correctly."""
        plugin_dir = "/dummy"
        input_settings = {
            "use_simple_tiling_mesh_on_pull": "yes",
            "auto_unwrap_with_blender_on_pull": "1",
            "blender_smart_uv_stretch_to_bounds": "true",
            "include_opacity_map": "Y",
        }
        result = settings_schema.sanitize_settings(input_settings, plugin_dir)

        self.assertTrue(result["use_simple_tiling_mesh_on_pull"])
        self.assertTrue(result["auto_unwrap_with_blender_on_pull"])
        self.assertTrue(result["blender_smart_uv_stretch_to_bounds"])
        self.assertTrue(result["include_opacity_map"])

        input_settings_false = {
            "use_simple_tiling_mesh_on_pull": "no",
            "auto_unwrap_with_blender_on_pull": "0",
            "blender_smart_uv_stretch_to_bounds": "false",
            "include_opacity_map": "N",
        }
        result_false = settings_schema.sanitize_settings(input_settings_false, plugin_dir)

        self.assertFalse(result_false["use_simple_tiling_mesh_on_pull"])
        self.assertFalse(result_false["auto_unwrap_with_blender_on_pull"])
        self.assertFalse(result_false["blender_smart_uv_stretch_to_bounds"])
        self.assertFalse(result_false["include_opacity_map"])

    def test_sanitize_type_coercion_float(self):
        """Test float coercion for string representations and invalid strings."""
        plugin_dir = "/dummy"
        input_settings = {
            "poll_timeout": "120.5",
            "blender_smart_uv_angle_limit": "45",
        }
        result = settings_schema.sanitize_settings(input_settings, plugin_dir)

        self.assertEqual(result["poll_timeout"], 120.5)
        self.assertEqual(result["blender_smart_uv_angle_limit"], 45.0)

        # Invalid string should fallback to default
        input_settings_invalid = {
            "poll_timeout": "invalid",
        }
        result_invalid = settings_schema.sanitize_settings(input_settings_invalid, plugin_dir)
        self.assertEqual(result_invalid["poll_timeout"], 60.0)

    def test_sanitize_fallback_enums(self):
        """Test enum strings fall back to default if invalid."""
        plugin_dir = "/dummy"
        input_settings = {
            "log_level": "INVALID_LEVEL",
            "export_file_format": "tiff", # Unsupported
        }
        result = settings_schema.sanitize_settings(input_settings, plugin_dir)

        self.assertEqual(result["log_level"], "info")
        self.assertEqual(result["export_file_format"], "png")

        input_settings_valid = {
            "log_level": "DEBUG", # Test case insensitivity
            "export_file_format": "JPG",
        }
        result_valid = settings_schema.sanitize_settings(input_settings_valid, plugin_dir)

        self.assertEqual(result_valid["log_level"], "debug")
        self.assertEqual(result_valid["export_file_format"], "jpg")

    def test_sanitize_texconv_path_detection(self):
        """Test that texconv_path detects correctly if missing or invalid."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Setup a dummy texconv.exe
            dummy_texconv = os.path.join(temp_dir, "texconv.exe")
            with open(dummy_texconv, 'w') as f:
                f.write("dummy")

            # Input with invalid path should fall back to auto-detection
            input_settings = {
                "texconv_path": "/path/to/nonexistent/texconv.exe"
            }
            result = settings_schema.sanitize_settings(input_settings, temp_dir)
            self.assertEqual(result["texconv_path"], dummy_texconv)

            # Input with valid path should be preserved
            input_settings_valid = {
                "texconv_path": dummy_texconv
            }
            result_valid = settings_schema.sanitize_settings(input_settings_valid, "/dummy")
            self.assertEqual(result_valid["texconv_path"], dummy_texconv)

            # Empty string should fall back to auto-detection
            input_settings_empty = {
                "texconv_path": ""
            }
            result_empty = settings_schema.sanitize_settings(input_settings_empty, temp_dir)
            self.assertEqual(result_empty["texconv_path"], dummy_texconv)

if __name__ == "__main__":
    unittest.main()

import unittest
import sys
import os
import tempfile
from unittest.mock import patch, mock_open, MagicMock

# Insert the parent directory to allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Python relative imports fail if not run as a module.
# Since we just want to test settings_schema, we can mock `plugin_info` and override sys.modules
# just for the duration of the test, and remove it after.
import types
dummy_plugin_info = types.ModuleType("plugin_info")
dummy_plugin_info.PLUGIN_ID = "MockPlugin"
sys.modules["plugin_info"] = dummy_plugin_info

# Now we can mock builtins.__import__ temporarily just to intercept `.plugin_info`
import builtins
orig_import = builtins.__import__
def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 1 and name == 'plugin_info':
        return dummy_plugin_info
    return orig_import(name, globals, locals, fromlist, level)

builtins.__import__ = custom_import

try:
    from settings_schema import (
        _coerce_bool,
        _coerce_float,
        _coerce_str,
        _detect_texconv_path,
        default_settings,
        sanitize_settings,
        atomic_write_json,
        DEFAULT_REMIX_API_BASE_URL,
        SETTINGS_VERSION,
    )
    PLUGIN_ID = dummy_plugin_info.PLUGIN_ID
finally:
    builtins.__import__ = orig_import


class CustomErrorStr:
    def __str__(self):
        raise ValueError("Cannot cast to string")

class TestSettingsSchema(unittest.TestCase):

    def test_coerce_bool(self):
        # Truthy valid
        for val in [True, 1, 1.5, "1", "true", "yes", "y", "on", " TRUE ", "On"]:
            self.assertTrue(_coerce_bool(val))

        # Falsy valid
        for val in [False, 0, 0.0, "0", "false", "no", "n", "off", " FALSE ", "Off"]:
            self.assertFalse(_coerce_bool(val, default=True))

        # Invalid fallbacks
        self.assertFalse(_coerce_bool("abc"))
        self.assertTrue(_coerce_bool("abc", default=True))
        self.assertFalse(_coerce_bool([1, 2]))

    def test_coerce_float(self):
        self.assertEqual(_coerce_float(1, 0.0), 1.0)
        self.assertEqual(_coerce_float(1.5, 0.0), 1.5)
        self.assertEqual(_coerce_float(" 2.5 ", 0.0), 2.5)

        # Invalid fallbacks
        self.assertEqual(_coerce_float("abc", 4.2), 4.2)
        self.assertEqual(_coerce_float(None, 4.2), 4.2)
        self.assertEqual(_coerce_float([], 4.2), 4.2)

    def test_coerce_str(self):
        self.assertEqual(_coerce_str("hello", "def"), "hello")
        self.assertEqual(_coerce_str(123, "def"), "123")
        self.assertEqual(_coerce_str(None, "def"), "def")

        # Exception in str() fallback
        self.assertEqual(_coerce_str(CustomErrorStr(), "def"), "def")

    @patch("os.path.isfile")
    def test_detect_texconv_path(self, mock_isfile):
        _detect_texconv_path.cache_clear()

        # Found
        mock_isfile.return_value = True
        plugin_dir = "my_plugin_dir"
        expected_path = os.path.join(plugin_dir, "texconv.exe")
        self.assertEqual(_detect_texconv_path(plugin_dir), expected_path)

        _detect_texconv_path.cache_clear()

        # Not found
        mock_isfile.return_value = False
        self.assertEqual(_detect_texconv_path(plugin_dir), "")

        _detect_texconv_path.cache_clear()

        # Exception during stat/join
        mock_isfile.side_effect = Exception("access denied")
        self.assertEqual(_detect_texconv_path(plugin_dir), "")

    @patch("settings_schema._detect_texconv_path", return_value="fake_texconv")
    def test_default_settings(self, mock_detect):
        plugin_dir = "dir"
        defaults = default_settings(plugin_dir)

        self.assertEqual(defaults["settings_version"], SETTINGS_VERSION)
        self.assertEqual(defaults["api_base_url"], DEFAULT_REMIX_API_BASE_URL)
        self.assertEqual(defaults["poll_timeout"], 60.0)
        self.assertEqual(defaults["log_level"], "info")
        self.assertEqual(defaults["use_simple_tiling_mesh_on_pull"], False)
        self.assertEqual(defaults["simple_tiling_mesh_path"], "assets/meshes/plane_tiling.usd")
        self.assertEqual(defaults["painter_import_template_path"], "")
        self.assertEqual(defaults["auto_unwrap_with_blender_on_pull"], False)
        self.assertEqual(defaults["blender_executable_path"], "")
        self.assertEqual(defaults["blender_unwrap_script_path"], "")
        self.assertEqual(defaults["blender_unwrap_output_suffix"], "_spUnwrapped")
        self.assertEqual(defaults["blender_smart_uv_angle_limit"], 66.0)
        self.assertEqual(defaults["blender_smart_uv_area_weight"], 0.0)
        self.assertEqual(defaults["blender_smart_uv_island_margin"], 0.003)
        self.assertEqual(defaults["blender_smart_uv_stretch_to_bounds"], False)
        self.assertEqual(defaults["painter_export_path"], os.path.join(tempfile.gettempdir(), "RemixConnector_Export"))
        self.assertEqual(defaults["export_file_format"], "png")
        self.assertEqual(defaults["include_opacity_map"], False)
        self.assertEqual(defaults["remix_output_subfolder"], "Textures/PainterConnector_Ingested")
        self.assertEqual(defaults["texconv_path"], "fake_texconv")
        self.assertEqual(defaults["plugin_id"], PLUGIN_ID)

    @patch("os.path.isfile")
    def test_sanitize_settings(self, mock_isfile):
        # Test empty input uses defaults
        res_none = sanitize_settings(None, "dir")
        res_empty = sanitize_settings({}, "dir")
        self.assertEqual(res_none["api_base_url"], DEFAULT_REMIX_API_BASE_URL)
        self.assertEqual(res_empty["api_base_url"], DEFAULT_REMIX_API_BASE_URL)

        # api_base_url
        res = sanitize_settings({"api_base_url": "  http://my-url  "}, "dir")
        self.assertEqual(res["api_base_url"], "http://my-url")
        res = sanitize_settings({"api_base_url": "   "}, "dir")
        self.assertEqual(res["api_base_url"], DEFAULT_REMIX_API_BASE_URL)

        # poll_timeout
        res = sanitize_settings({"poll_timeout": "30.5"}, "dir")
        self.assertEqual(res["poll_timeout"], 30.5)

        # log_level
        for level in ["debug", "info", "warning", "error"]:
            res = sanitize_settings({"log_level": f" {level.upper()} "}, "dir")
            self.assertEqual(res["log_level"], level)
        res = sanitize_settings({"log_level": "foo"}, "dir")
        self.assertEqual(res["log_level"], "info")

        # export_file_format
        for fmt in ["png", "tga", "jpg", "jpeg"]:
            res = sanitize_settings({"export_file_format": f" {fmt.upper()} "}, "dir")
            self.assertEqual(res["export_file_format"], fmt)
        res = sanitize_settings({"export_file_format": "bmp"}, "dir")
        self.assertEqual(res["export_file_format"], "png")

        # string coercions
        res = sanitize_settings({
            "simple_tiling_mesh_path": "a",
            "painter_import_template_path": "b",
            "blender_executable_path": "c",
            "blender_unwrap_script_path": "d",
            "blender_unwrap_output_suffix": "e",
            "painter_export_path": "f",
            "remix_output_subfolder": " g "
        }, "dir")
        self.assertEqual(res["simple_tiling_mesh_path"], "a")
        self.assertEqual(res["painter_import_template_path"], "b")
        self.assertEqual(res["blender_executable_path"], "c")
        self.assertEqual(res["blender_unwrap_script_path"], "d")
        self.assertEqual(res["blender_unwrap_output_suffix"], "e")
        self.assertEqual(res["painter_export_path"], "f")
        self.assertEqual(res["remix_output_subfolder"], "g")

        # float coercions
        res = sanitize_settings({
            "blender_smart_uv_angle_limit": "42",
            "blender_smart_uv_area_weight": "1.2",
            "blender_smart_uv_island_margin": "0.1",
        }, "dir")
        self.assertEqual(res["blender_smart_uv_angle_limit"], 42.0)
        self.assertEqual(res["blender_smart_uv_area_weight"], 1.2)
        self.assertEqual(res["blender_smart_uv_island_margin"], 0.1)

        # boolean coercions
        res = sanitize_settings({
            "use_simple_tiling_mesh_on_pull": "yes",
            "auto_unwrap_with_blender_on_pull": 1,
            "blender_smart_uv_stretch_to_bounds": "true",
            "include_opacity_map": True
        }, "dir")
        self.assertTrue(res["use_simple_tiling_mesh_on_pull"])
        self.assertTrue(res["auto_unwrap_with_blender_on_pull"])
        self.assertTrue(res["blender_smart_uv_stretch_to_bounds"])
        self.assertTrue(res["include_opacity_map"])

        # texconv_path fallback behavior
        mock_isfile.return_value = False
        _detect_texconv_path.cache_clear()
        # when provided path doesn't exist, it uses detect_texconv_path (which is mocked isfile=False, so empty str)
        res = sanitize_settings({"texconv_path": "fake/path/texconv.exe"}, "dir")
        self.assertEqual(res["texconv_path"], "")

        # when provided path exists
        mock_isfile.return_value = True
        res = sanitize_settings({"texconv_path": "fake/path/texconv.exe"}, "dir")
        self.assertEqual(res["texconv_path"], "fake/path/texconv.exe")

        # Preserves unknown keys
        res = sanitize_settings({"unknown_custom_key": 123}, "dir")
        self.assertEqual(res["unknown_custom_key"], 123)

    @patch("os.makedirs")
    @patch("os.replace")
    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_atomic_write_json_success(self, mock_dump, mock_open, mock_replace, mock_makedirs):
        path = "fake/path/settings.json"
        data = {"key": "value"}

        success, err = atomic_write_json(path, data)
        self.assertTrue(success)
        self.assertEqual(err, "")
        mock_makedirs.assert_called_once_with("fake/path", exist_ok=True)
        mock_open.assert_called_once_with("fake/path/settings.json.tmp", "w", encoding="utf-8")
        mock_dump.assert_called_once()
        mock_replace.assert_called_once_with("fake/path/settings.json.tmp", path)

    @patch("os.makedirs", side_effect=Exception("makedirs failed"))
    @patch("os.replace")
    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_atomic_write_json_makedirs_fails_but_continues(self, mock_dump, mock_open, mock_replace, mock_makedirs):
        path = "fake/path/settings.json"
        data = {"key": "value"}

        success, err = atomic_write_json(path, data)
        self.assertTrue(success)
        self.assertEqual(err, "")
        mock_open.assert_called_once()
        mock_replace.assert_called_once()

    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    @patch("os.replace", side_effect=Exception("replace failed"))
    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_atomic_write_json_failure_cleans_up(self, mock_dump, mock_open, mock_replace, mock_remove, mock_exists):
        path = "fake/path/settings.json"
        data = {"key": "value"}

        success, err = atomic_write_json(path, data)
        self.assertFalse(success)
        self.assertEqual(err, "replace failed")
        mock_remove.assert_called_once_with("fake/path/settings.json.tmp")

    @patch("os.path.exists", return_value=True)
    @patch("os.remove", side_effect=Exception("remove failed"))
    @patch("os.replace", side_effect=Exception("replace failed"))
    @patch("builtins.open", new_callable=mock_open)
    @patch("json.dump")
    def test_atomic_write_json_failure_cleanup_fails_gracefully(self, mock_dump, mock_open, mock_replace, mock_remove, mock_exists):
        path = "fake/path/settings.json"
        data = {"key": "value"}

        success, err = atomic_write_json(path, data)
        self.assertFalse(success)
        self.assertEqual(err, "replace failed")
        mock_remove.assert_called_once()

if __name__ == '__main__':
    unittest.main()

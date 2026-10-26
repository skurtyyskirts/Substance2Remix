import os
import json
import tempfile
import unittest
from unittest.mock import patch

from ._isolated import import_plugin_module

settings_schema = import_plugin_module("settings_schema")

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
        self.assertEqual(settings["settings_version"], settings_schema.SETTINGS_VERSION)
        self.assertEqual(settings["api_base_url"], "http://localhost:8011")
        self.assertEqual(settings["normal_map_format"], "opengl")
        self.assertEqual(settings["project_texture_resolution"], 2048)
        self.assertTrue(settings["auto_import_textures_on_pull"])
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

    @patch.object(settings_schema, "_detect_blender_path", return_value="C:/Blender 5.2/blender.exe")
    def test_migrations_and_new_keys(self, _mock_blender):
        sanitized = sanitize_settings({
            "include_opacity_map": True,  # retired: Remix has no opacity texture input
            "normal_map_format": "DirectX",
            "project_texture_resolution": "3000",
            "blender_executable_path": "C:/missing/Blender 5.0/blender.exe",
        }, "dummy_dir")
        self.assertNotIn("include_opacity_map", sanitized)
        self.assertEqual(sanitized["normal_map_format"], "directx")
        self.assertEqual(sanitized["project_texture_resolution"], 2048)
        # A stale Blender path (uninstalled version) falls back to the newest install.
        self.assertEqual(sanitized["blender_executable_path"], "C:/Blender 5.2/blender.exe")

    def test_detect_blender_prefers_newest(self):
        found = [r"C:\Program Files\Blender Foundation\Blender 4.4\blender.exe",
                 r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
                 r"C:\Program Files\Blender Foundation\Blender 5.10\blender.exe"]
        settings_schema._detect_blender_path.cache_clear()
        try:
            with patch.object(settings_schema.glob, "glob", return_value=found), \
                    patch.object(settings_schema.os.path, "isfile", return_value=True):
                self.assertTrue(settings_schema._detect_blender_path().endswith(r"Blender 5.10\blender.exe"))
        finally:
            settings_schema._detect_blender_path.cache_clear()

    def test_texture_maps_are_complete_bools(self):
        maps = sanitize_settings({"texture_maps": {"anisotropy": "false", "opacity": 0, "bogus": True}}, "dummy_dir")["texture_maps"]
        self.assertEqual(set(maps), set(settings_schema.TOGGLE_KEYS))
        self.assertFalse(maps["anisotropy"])
        self.assertFalse(maps["opacity"])
        self.assertTrue(maps["thickness"])  # missing keys default to on
        self.assertEqual(settings_schema.enabled_maps({"texture_maps": {"albedo": False}}),
                         set(settings_schema.TOGGLE_KEYS) - {"albedo"})
        # Settings from before the maps existed still push everything.
        self.assertEqual(settings_schema.enabled_maps({}), set(settings_schema.TOGGLE_KEYS))

    def test_poll_timeout_is_clamped(self):
        self.assertEqual(sanitize_settings({"poll_timeout": 0}, "dummy_dir")["poll_timeout"], 0.5)
        self.assertEqual(sanitize_settings({"poll_timeout": "9999"}, "dummy_dir")["poll_timeout"], 300.0)

    def test_preset_values_exclude_machine_paths(self):
        settings = sanitize_settings({"api_base_url": "http://x:1", "normal_map_format": "directx"}, "dummy_dir")
        values = settings_schema.preset_values(settings)
        self.assertEqual(values["normal_map_format"], "directx")
        for key in ("api_base_url", "texconv_path", "blender_executable_path", "painter_export_path", "log_level"):
            self.assertNotIn(key, values)
        values["texture_maps"]["albedo"] = False  # a copy, not the live settings
        self.assertTrue(settings["texture_maps"]["albedo"])

    def test_user_config_dir_is_outside_the_plugin(self):
        with patch.dict(os.environ, {"APPDATA": r"C:\Users\me\AppData\Roaming"}):
            self.assertEqual(settings_schema.user_config_dir(), os.path.join(r"C:\Users\me\AppData\Roaming", "Substance2Remix"))

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

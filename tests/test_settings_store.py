"""Tests for settings_store.py: autosaved settings that load on the next start."""
import json
import os
import tempfile
import unittest

from ._isolated import import_plugin_module

settings_store = import_plugin_module("settings_store")
SettingsStore = settings_store.SettingsStore


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = os.path.join(self.tmp.name, "config")
        self.plugin = os.path.join(self.tmp.name, "plugin")
        os.makedirs(self.plugin)
        self.legacy = os.path.join(self.plugin, "settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _store(self):
        store = SettingsStore(self.plugin, config_dir=self.config, legacy_settings_path=self.legacy)
        store.load()
        return store

    def _saved(self):
        with open(os.path.join(self.config, "settings.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_defaults_without_any_file(self):
        store = self._store()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertEqual(store.errors, [])

    def test_changes_load_again_on_the_next_start(self):
        self._store().update({"normal_map_format": "directx", "restore_original_aspect_ratio_on_export": False})
        reloaded = self._store()
        self.assertEqual(reloaded.settings["normal_map_format"], "directx")
        self.assertFalse(reloaded.settings["restore_original_aspect_ratio_on_export"])
        self.assertTrue(reloaded.settings["auto_import_textures_on_pull"])

    def test_old_plugin_folder_settings_are_migrated(self):
        with open(self.legacy, "w", encoding="utf-8") as f:
            json.dump({"normal_map_format": "directx", "project_texture_resolution": 4096, "custom_key": 1}, f)
        store = self._store()
        self.assertEqual(store.settings["normal_map_format"], "directx")
        saved = self._saved()
        self.assertEqual(saved["project_texture_resolution"], 4096)
        self.assertEqual(saved["custom_key"], 1)
        # Once migrated, the config-folder copy wins over the old file.
        with open(self.legacy, "w", encoding="utf-8") as f:
            json.dump({"normal_map_format": "opengl"}, f)
        self.assertEqual(self._store().settings["normal_map_format"], "directx")

    def test_v1_0_preset_keys_are_dropped(self):
        os.makedirs(self.config)
        with open(os.path.join(self.config, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"active_preset": "Mine", "normal_map_format": "directx"}, f)
        store = self._store()
        self.assertNotIn("active_preset", store.settings)
        self.assertEqual(store.settings["normal_map_format"], "directx")

    def test_every_update_is_saved(self):
        store = self._store()
        before = store.settings
        after = store.update({"normal_map_format": "directx"})
        self.assertIsNot(before, after)  # readers on other threads keep their snapshot
        self.assertEqual(before["normal_map_format"], "opengl")
        self.assertEqual(self._saved()["normal_map_format"], "directx")

    def test_reset_restores_and_saves_defaults(self):
        store = self._store()
        store.update({"normal_map_format": "directx"})
        store.reset_to_defaults()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertEqual(self._saved()["normal_map_format"], "opengl")

    def test_corrupt_settings_are_backed_up_before_being_replaced(self):
        os.makedirs(self.config)
        path = os.path.join(self.config, "settings.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not json")
        store = self._store()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertIn("unreadable", store.errors[0])
        store.update({"normal_map_format": "directx"})
        with open(path + ".bak", encoding="utf-8") as f:
            self.assertEqual(f.read(), "{not json")
        self.assertIn(".bak", store.errors[0])


if __name__ == "__main__":
    unittest.main()

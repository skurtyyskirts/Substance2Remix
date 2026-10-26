"""Tests for settings_store.py: autosaved settings, presets and migration."""
import json
import os
import tempfile
import unittest
import unittest.mock

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

    def _saved(self, name="settings.json"):
        with open(os.path.join(self.config, name), encoding="utf-8") as f:
            return json.load(f)

    def test_defaults_without_any_file(self):
        store = self._store()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertEqual(store.errors, [])
        self.assertEqual(store.preset_names(), [])

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

    def test_every_update_is_saved(self):
        store = self._store()
        before = store.settings
        after = store.update({"normal_map_format": "directx", "texture_maps": {"height": False}})
        self.assertIsNot(before, after)  # readers on other threads keep their snapshot
        self.assertEqual(before["normal_map_format"], "opengl")
        saved = self._saved()
        self.assertEqual(saved["normal_map_format"], "directx")
        self.assertFalse(saved["texture_maps"]["height"])
        self.assertTrue(saved["texture_maps"]["albedo"])

    def test_corrupt_settings_fall_back_to_defaults(self):
        os.makedirs(self.config)
        with open(os.path.join(self.config, "settings.json"), "w") as f:
            f.write("{not json")
        store = self._store()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertIn("unreadable", store.errors[0])

    def test_corrupt_settings_are_backed_up_before_being_replaced(self):
        os.makedirs(self.config)
        path = os.path.join(self.config, "settings.json")
        with open(path, "w") as f:
            f.write("{not json")
        store = self._store()
        store.update({"normal_map_format": "directx"})
        with open(path + ".bak") as f:
            self.assertEqual(f.read(), "{not json")
        self.assertIn(".bak", store.errors[0])

    def test_unreadable_presets_are_merged_back_not_overwritten(self):
        os.makedirs(self.config)
        path = os.path.join(self.config, "presets.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"presets": {"Mine": {"normal_map_format": "directx"}, "Old": {}}}, f)
        real_read = settings_store._read_json
        locked = {"on": True}

        def flaky_read(p):
            if p == path and locked["on"]:
                return {}, f"{p}: [Errno 13] Permission denied"
            return real_read(p)

        with unittest.mock.patch.object(settings_store, "_read_json", side_effect=flaky_read):
            store = self._store()  # presets.json locked at startup
            self.assertEqual(store.preset_names(), [])
            locked["on"] = False
            store.delete_preset("Old")  # not loaded, so nothing to delete yet
            store.save_preset("New")
        saved = self._saved("presets.json")["presets"]
        self.assertEqual(sorted(saved), ["Mine", "New", "Old"])
        self.assertEqual(saved["Mine"]["normal_map_format"], "directx")

    def test_preset_deleted_this_session_is_not_merged_back(self):
        store = self._store()
        store.save_preset("A")
        store.save_preset("B")
        store._presets_unread = True  # pretend the file was unreadable at startup
        store.delete_preset("A")
        self.assertEqual(sorted(self._saved("presets.json")["presets"]), ["B"])

    def test_preset_round_trip(self):
        store = self._store()
        store.update({"normal_map_format": "directx", "project_texture_resolution": 4096, "api_base_url": "http://box:9"})
        store.save_preset("Characters")
        self.assertEqual(store.active_preset, "Characters")
        self.assertFalse(store.is_modified())

        store.update({"normal_map_format": "opengl"})
        self.assertTrue(store.is_modified())
        store.save_preset("Props")
        store.apply_preset("Characters")
        self.assertEqual(store.settings["normal_map_format"], "directx")
        self.assertEqual(store.settings["active_preset"], "Characters")
        # Machine settings aren't part of a preset, so loading one leaves them alone.
        self.assertEqual(store.settings["api_base_url"], "http://box:9")
        self.assertNotIn("api_base_url", self._saved("presets.json")["presets"]["Characters"])

        reloaded = self._store()
        self.assertEqual(reloaded.preset_names(), ["Characters", "Props"])
        self.assertEqual(reloaded.active_preset, "Characters")

    def test_delete_active_preset_detaches(self):
        store = self._store()
        store.save_preset("Tiling")
        store.delete_preset("Tiling")
        self.assertEqual(store.preset_names(), [])
        self.assertEqual(store.active_preset, "")
        self.assertEqual(store.settings["active_preset"], "")

    def test_reset_keeps_presets(self):
        store = self._store()
        store.update({"normal_map_format": "directx"})
        store.save_preset("Mine")
        store.reset_to_defaults()
        self.assertEqual(store.settings["normal_map_format"], "opengl")
        self.assertEqual(store.preset_names(), ["Mine"])
        self.assertEqual(store.active_preset, "")

    def test_unknown_preset_and_empty_name(self):
        store = self._store()
        with self.assertRaises(KeyError):
            store.apply_preset("missing")
        with self.assertRaises(ValueError):
            store.save_preset("   ")

    def test_presets_file_is_sanitized_on_load(self):
        os.makedirs(self.config)
        with open(os.path.join(self.config, "presets.json"), "w", encoding="utf-8") as f:
            json.dump({"presets": {"Odd": {"normal_map_format": "DirectX", "texconv_path": "x"}, "": {}}}, f)
        store = self._store()
        self.assertEqual(store.preset_names(), ["Odd"])
        self.assertEqual(store.presets["Odd"]["normal_map_format"], "directx")
        self.assertNotIn("texconv_path", store.presets["Odd"])


if __name__ == "__main__":
    unittest.main()

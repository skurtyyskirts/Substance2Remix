"""Tests for settings_dialog.py with real PySide6 widgets (offscreen)."""
import os
import tempfile
import unittest
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtWidgets  # noqa: E402

from ._isolated import import_plugin_module  # noqa: E402

settings_dialog = import_plugin_module("settings_dialog")
SettingsStore = import_plugin_module("settings_store").SettingsStore

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Controller:
    """The settings API RemixConnectorPlugin offers the dialog, over a real store."""

    def __init__(self, config_dir):
        self.store = SettingsStore(os.path.dirname(settings_dialog.__file__), config_dir=config_dir)
        self.store.load()
        self.updates = []

    @property
    def settings(self):
        return self.store.settings

    def update_settings(self, values):
        self.updates.append(values)
        return self.store.update(values)

    def reset_settings(self):
        return self.store.reset_to_defaults()

    def preset_names(self):
        return self.store.preset_names()

    def active_preset(self):
        return self.store.active_preset

    def preset_modified(self):
        return self.store.is_modified()

    def save_preset(self, name):
        return self.store.save_preset(name)

    def apply_preset(self, name):
        return self.store.apply_preset(name)

    def delete_preset(self, name):
        return self.store.delete_preset(name)


class TestSettingsDialog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.controller = _Controller(self.tmp.name)
        self.dialog = settings_dialog.SettingsDialog(self.controller)

    def tearDown(self):
        self.dialog.deleteLater()
        self.tmp.cleanup()

    def test_opening_saves_nothing(self):
        self.assertEqual(self.controller.updates, [])
        self.assertFalse(self.dialog._save_timer.isActive())

    def test_a_change_is_saved_without_ok(self):
        self.dialog.normal_format.setCurrentIndex(self.dialog.normal_format.findData("directx"))
        self.assertTrue(self.dialog._save_timer.isActive())  # debounced
        self.dialog._commit()
        self.assertEqual(self.controller.store.settings["normal_map_format"], "directx")
        self.assertEqual(SettingsStore(".", config_dir=self.tmp.name).load()["normal_map_format"], "directx")

    def test_closing_flushes_a_pending_change(self):
        self.dialog.map_checks["height"].setChecked(False)
        self.dialog.close_btn.click()
        self.assertFalse(self.controller.store.settings["texture_maps"]["height"])

    def test_closing_saves_a_typed_field_without_editing_finished(self):
        self.dialog.remix_output_subfolder.setText("Textures/Typed")  # setText emits no editingFinished
        self.dialog.reject()  # window close button
        self.assertEqual(self.controller.store.settings["remix_output_subfolder"], "Textures/Typed")

    def test_opacity_follows_albedo(self):
        self.dialog.map_checks["albedo"].setChecked(False)
        self.assertFalse(self.dialog.map_checks["opacity"].isEnabled())
        self.dialog.map_checks["albedo"].setChecked(True)
        self.assertTrue(self.dialog.map_checks["opacity"].isEnabled())

    def test_every_remix_map_has_a_toggle(self):
        self.assertEqual(set(self.dialog.map_checks), set(settings_dialog.MAPS_BY_KEY) | {"opacity"})

    def test_save_as_then_switch_presets(self):
        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("DirectX props", True)):
            self.dialog.normal_format.setCurrentIndex(self.dialog.normal_format.findData("directx"))
            self.dialog._save_preset_as()
        self.assertEqual(self.dialog.preset_combo.currentData(), "DirectX props")
        self.assertFalse(self.dialog.preset_save_btn.isEnabled())  # nothing modified yet

        self.dialog.normal_format.setCurrentIndex(self.dialog.normal_format.findData("opengl"))
        self.dialog._commit()
        self.assertTrue(self.dialog.preset_save_btn.isEnabled())
        self.assertEqual(self.dialog.preset_state.text(), "Unsaved changes")

        with patch.object(QtWidgets.QInputDialog, "getText", return_value=("OpenGL", True)):
            self.dialog._save_preset_as()
        idx = self.dialog.preset_combo.findData("DirectX props")
        self.dialog.preset_combo.setCurrentIndex(idx)
        self.dialog._on_preset_chosen(idx)
        self.assertEqual(self.dialog.normal_format.currentData(), "directx")
        self.assertEqual(self.controller.store.settings["normal_map_format"], "directx")

    def test_switching_away_from_modified_preset_asks_first(self):
        self.controller.save_preset("A")
        self.controller.update_settings({"normal_map_format": "directx"})
        self.controller.save_preset("B")
        self.controller.apply_preset("A")
        self.controller.update_settings({"project_texture_resolution": 4096})  # modify A
        self.dialog._refresh_presets()
        idx = self.dialog.preset_combo.findData("B")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No):
            self.dialog._on_preset_chosen(idx)
        self.assertEqual(self.controller.active_preset(), "A")
        self.assertEqual(self.controller.store.settings["project_texture_resolution"], 4096)

    def test_restore_defaults_asks_and_keeps_presets(self):
        self.controller.update_settings({"normal_map_format": "directx"})
        self.controller.save_preset("Keep me")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes):
            self.dialog._reset_defaults()
        self.assertEqual(self.controller.store.settings["normal_map_format"], "opengl")
        self.assertEqual(self.controller.preset_names(), ["Keep me"])
        self.assertEqual(self.dialog.normal_format.currentData(), "opengl")


if __name__ == "__main__":
    unittest.main()

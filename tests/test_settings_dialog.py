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

    def test_preview_shader_checkbox_is_saved(self):
        self.assertTrue(self.dialog.preview_shader.isChecked())  # on by default
        self.dialog.preview_shader.setChecked(False)
        self.dialog._commit()
        self.assertFalse(self.controller.store.settings["use_remix_preview_shader"])

    def test_dialog_has_no_presets(self):
        self.assertFalse(hasattr(self.dialog, "preset_combo"))

    def test_restore_defaults_asks_first(self):
        self.controller.update_settings({"normal_map_format": "directx"})
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No):
            self.dialog._reset_defaults()
        self.assertEqual(self.controller.store.settings["normal_map_format"], "directx")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.Yes):
            self.dialog._reset_defaults()
        self.assertEqual(self.controller.store.settings["normal_map_format"], "opengl")
        self.assertEqual(self.dialog.normal_format.currentData(), "opengl")


if __name__ == "__main__":
    unittest.main()

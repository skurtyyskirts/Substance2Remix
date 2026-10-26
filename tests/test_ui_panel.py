"""Tests for ui_panel.py with real PySide6 widgets (offscreen) and a fake plugin."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from ._isolated import import_plugin_module  # noqa: E402

ui_panel = import_plugin_module("ui_panel")

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _FakePlugin(QtCore.QObject):
    state_changed = QtCore.Signal()

    def __init__(self, link=None, presets=(), active="", modified=False):
        super().__init__()
        self.link = link
        self.presets = list(presets)
        self.active = active
        self.modified = modified
        self.current_operation = None
        self.last_message = ""
        self.painter_controller = MagicMock()
        self.painter_controller.is_project_open.return_value = True
        self.applied = []

    def connection_state(self):
        return {"ok": True, "message": "Connected - Mod"}

    def refresh_connection(self):
        pass

    def read_link(self):
        return self.link

    def project_normal_format(self, link=None):
        return (link or {}).get("normal_format") or "opengl"

    def preset_names(self):
        return self.presets

    def active_preset(self):
        return self.active

    def preset_modified(self):
        return self.modified

    def apply_preset(self, name):
        self.applied.append(name)
        self.active = name

    def update_settings(self, values):
        self.active = values.get("active_preset", self.active)

    def show_error(self, *args):
        pass


def _handlers():
    return SimpleNamespace(**{name: MagicMock() for name in (
        "handle_select_in_remix", "handle_pull_from_remix", "handle_import_textures", "handle_push_to_remix",
        "handle_relink_and_push_to_remix", "handle_link_to_selection", "handle_add_channels",
        "handle_settings", "handle_diagnostics")})


class TestRemixPanel(unittest.TestCase):
    def _panel(self, plugin):
        panel = ui_panel.RemixPanel(plugin, _handlers())
        self.addCleanup(panel.stop)
        self.addCleanup(panel.deleteLater)
        return panel

    def test_normals_label_says_when_it_comes_from_settings(self):
        plugin = _FakePlugin(link={"material_prim": "/RootNode/Looks/mat_A", "normal_format": "directx"})
        panel = self._panel(plugin)
        self.assertEqual(panel._normals_label.text(), "Normals: DirectX")
        plugin.link = {"material_prim": "/RootNode/Looks/mat_A"}  # project not created by Pull
        panel.refresh()
        self.assertEqual(panel._normals_label.text(), "Normals: OpenGL (from Settings)")

    def test_loading_a_preset_without_an_active_one_asks_first(self):
        plugin = _FakePlugin(presets=["DX"])
        panel = self._panel(plugin)
        idx = panel._preset_combo.findData("DX")
        with patch.object(QtWidgets.QMessageBox, "question", return_value=QtWidgets.QMessageBox.No) as ask:
            panel._on_preset_chosen(idx)
        ask.assert_called_once()
        self.assertEqual(plugin.applied, [])  # hand-tuned settings were not replaced
        self.assertEqual(panel._preset_combo.currentData(), "")

    def test_switching_between_clean_presets_needs_no_question(self):
        plugin = _FakePlugin(presets=["DX", "GL"], active="GL")
        panel = self._panel(plugin)
        with patch.object(QtWidgets.QMessageBox, "question") as ask:
            panel._on_preset_chosen(panel._preset_combo.findData("DX"))
        ask.assert_not_called()
        self.assertEqual(plugin.applied, ["DX"])

    def test_modified_preset_is_marked(self):
        plugin = _FakePlugin(presets=["GL"], active="GL", modified=True)
        panel = self._panel(plugin)
        self.assertEqual(panel._preset_combo.currentText(), "GL (modified)")

    def test_actions_disabled_while_busy(self):
        plugin = _FakePlugin(link={"material_prim": "/RootNode/Looks/mat_A"})
        plugin.current_operation = "Push to Remix"
        panel = self._panel(plugin)
        self.assertFalse(panel._push_btn.isEnabled())
        self.assertFalse(panel._preset_combo.isEnabled())
        self.assertIn("Running: Push to Remix", panel._op_label.text())


if __name__ == "__main__":
    unittest.main()

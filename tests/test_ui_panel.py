"""Tests for ui_panel.py with real PySide6 widgets (offscreen) and a fake plugin."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")

from PySide6 import QtCore, QtWidgets  # noqa: E402

from ._isolated import import_plugin_module  # noqa: E402

ui_panel = import_plugin_module("ui_panel")

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _FakePlugin(QtCore.QObject):
    state_changed = QtCore.Signal()

    def __init__(self, link=None):
        super().__init__()
        self.link = link
        self.current_operation = None
        self.last_message = ""
        self.painter_controller = MagicMock()
        self.painter_controller.is_project_open.return_value = True

    def connection_state(self):
        return {"ok": True, "message": "Connected - Mod"}

    def refresh_connection(self):
        pass

    def read_link(self):
        return self.link

    def project_normal_format(self, link=None):
        return (link or {}).get("normal_format") or "opengl"

    def show_error(self, *args):
        pass


def _handlers():
    return SimpleNamespace(**{name: MagicMock() for name in (
        "handle_select_in_remix", "handle_pull_from_remix", "handle_import_textures", "handle_push_to_remix",
        "handle_link_to_selection", "handle_add_anisotropy_channels", "handle_add_subsurface_channels",
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

    def test_panel_has_no_preset_switcher(self):
        panel = self._panel(_FakePlugin())
        self.assertFalse(hasattr(panel, "_preset_combo"))

    def test_channels_button_offers_the_two_groups(self):
        handlers = _handlers()
        panel = ui_panel.RemixPanel(_FakePlugin(), handlers)
        self.addCleanup(panel.stop)
        self.addCleanup(panel.deleteLater)
        actions = panel._channels_btn.menu().actions()
        self.assertEqual([a.text() for a in actions], ["Anisotropy", "Subsurface"])
        actions[1].trigger()
        handlers.handle_add_subsurface_channels.assert_called_once()
        self.assertFalse(hasattr(panel, "_force_push_btn"))

    def test_actions_disabled_while_busy(self):
        plugin = _FakePlugin(link={"material_prim": "/RootNode/Looks/mat_A"})
        plugin.current_operation = "Push to Remix"
        panel = self._panel(plugin)
        self.assertFalse(panel._push_btn.isEnabled())
        self.assertIn("Running: Push to Remix", panel._op_label.text())


if __name__ == "__main__":
    unittest.main()

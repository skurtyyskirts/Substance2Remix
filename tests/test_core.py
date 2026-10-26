"""Tests for core.py: pull mesh selection, export presets, aspect handling and
the push/import worker steps (Painter and Remix are mocked).

core.py uses package-relative imports, so it is imported as <plugin folder>.core.
It also needs a real Qt binding (PySide6, as shipped with Painter).
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")

# requests + substance_painter stubs are installed by tests/conftest.py.
_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT_DIR = os.path.dirname(_PLUGIN_DIR)
_PKG_NAME = os.path.basename(_PLUGIN_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

core = __import__(f"{_PKG_NAME}.core", fromlist=["core"])

_BOUND = (
    "_author_material_group_wrapper", "_pull_pick_mesh", "_tiling_mesh_path", "_pull_fetch",
    "_push_ingest", "_restore_aspect_ratio", "_rename_for_force_push", "_require_remix_project",
    "_import_fetch", "_texconv_path", "_normal_map_format",
)


def _make_plugin(settings=None):
    """A RemixConnectorPlugin stand-in with the real methods under test bound
    to it (constructing the real QObject would spin up a thread pool)."""
    plugin = MagicMock(spec=core.RemixConnectorPlugin)
    plugin.settings = dict(settings or {})
    plugin.remix_api = MagicMock()
    plugin.remix_api.get_project_info.return_value = (
        {"project_file": "C:/Mods/MyMod/mod.usda", "project_dir": "C:/Mods/MyMod", "project_name": "MyMod"}, None)
    plugin.texture_processor = MagicMock()
    plugin._invoker = MagicMock()
    plugin._connection = {}
    for name in _BOUND:
        setattr(plugin, name, getattr(core.RemixConnectorPlugin, name).__get__(plugin))
    return plugin


class TestAuthorMaterialGroupWrapper(unittest.TestCase):
    def test_writes_parseable_usda_with_all_references(self):
        plugin = _make_plugin()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "PLUGIN_DIR", tmp):
                paths = [
                    os.path.join(tmp, "captures", "meshes", "mesh_AAAA1111AAAA1111.usd"),
                    os.path.join(tmp, "captures", "meshes", "mesh_BBBB2222BBBB2222.usd"),
                ]
                wrapper = plugin._author_material_group_wrapper(paths, "/RootNode/Looks/mat_DEADBEEFDEADBEEF")
            text = open(wrapper, encoding="utf-8").read()
            self.assertIn("#usda 1.0", text)
            self.assertIn('defaultPrim = "Substance2RemixGroup"', text)
            for p in paths:
                self.assertIn(p.replace("\\", "/"), text)
            self.assertTrue(wrapper.endswith("DEADBEEFDEADBEEF.usda"))

    def test_child_prim_names_are_unique_and_sanitized(self):
        plugin = _make_plugin()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "PLUGIN_DIR", tmp):
                paths = [
                    os.path.join(tmp, "a", "mesh_X.usd"),
                    os.path.join(tmp, "b", "mesh_X.usd"),
                    os.path.join(tmp, "c", "mesh-with-dashes.usd"),
                ]
                wrapper = plugin._author_material_group_wrapper(paths, "/Looks/mat_FOO")
            text = open(wrapper, encoding="utf-8").read()
            self.assertIn('def "mesh_0_mesh_X"', text)
            self.assertIn('def "mesh_1_mesh_X"', text)
            self.assertIn('def "mesh_2_mesh_with_dashes"', text)

    def test_empty_paths_returns_none(self):
        self.assertIsNone(_make_plugin()._author_material_group_wrapper([], "/Looks/mat_FOO"))

    def test_material_without_hash_uses_its_prim_name(self):
        plugin = _make_plugin()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(core, "PLUGIN_DIR", tmp):
                wrapper = plugin._author_material_group_wrapper([os.path.join(tmp, "mesh.usd")], "/Looks/Custom Mat")
            self.assertTrue(wrapper.endswith("Custom_Mat.usda"))


class TestPullFetch(unittest.TestCase):
    def _selection(self, plugin, materials, meshes):
        plugin.remix_api.get_selection.return_value = ({"materials": materials, "meshes": meshes, "prims": []}, None)

    def test_resolves_each_mesh_once(self):
        plugin = _make_plugin()
        self._selection(plugin, ["/RootNode/Looks/mat_A"], ["/RootNode/meshes/mesh_1", "/RootNode/meshes/mesh_2"])
        plugin.remix_api.resolve_mesh_file.side_effect = [("C:/m/one.usd", None), ("C:/M/ONE.usd", None)]
        result = plugin._pull_fetch()
        self.assertEqual(result["mesh_files"], ["C:/m/one.usd"])  # case-insensitive de-dup
        self.assertEqual(result["materials"], ["/RootNode/Looks/mat_A"])

    def test_tiling_pull_skips_mesh_resolution(self):
        plugin = _make_plugin({"use_simple_tiling_mesh_on_pull": True})
        self._selection(plugin, ["/RootNode/Looks/mat_A"], ["/RootNode/meshes/mesh_1"])
        result = plugin._pull_fetch()
        plugin.remix_api.resolve_mesh_file.assert_not_called()
        self.assertEqual(result["mesh_files"], [])

    def test_empty_selection_raises_friendly_error(self):
        plugin = _make_plugin()
        self._selection(plugin, [], [])
        with self.assertRaises(core.RemixError) as ctx:
            plugin._pull_fetch()
        self.assertIn("Nothing is selected", str(ctx.exception))

    def test_unreachable_remix_raises(self):
        plugin = _make_plugin()
        plugin.remix_api.get_project_info.return_value = (None, "Can't reach RTX Remix")
        with self.assertRaises(core.RemixError):
            plugin._pull_fetch()
        plugin.remix_api.get_selection.assert_not_called()


class TestPullPickMesh(unittest.TestCase):
    def test_single_mesh_is_used_directly(self):
        plugin = _make_plugin()
        path, note = plugin._pull_pick_mesh({"mesh_files": ["C:/m/a.usd"]}, "/Looks/mat_A")
        self.assertEqual(path, "C:/m/a.usd")
        self.assertIsNone(note)

    def test_multiple_meshes_are_bundled(self):
        plugin = _make_plugin()
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, "PLUGIN_DIR", tmp):
            path, note = plugin._pull_pick_mesh({"mesh_files": ["C:/m/a.usd", "C:/m/b.usd"]}, "/Looks/mat_DEADBEEFDEADBEEF")
            self.assertTrue(path.endswith("DEADBEEFDEADBEEF.usda"))
        self.assertIn("Bundled 2", note)

    def test_no_mesh_falls_back_to_tiling_plane(self):
        plugin = _make_plugin()
        path, note = plugin._pull_pick_mesh({"mesh_files": []}, "/Looks/mat_A")
        self.assertTrue(path.endswith("plane_tiling.usd"))
        self.assertTrue(os.path.isfile(path))
        self.assertIn("tiling plane", note)


class TestBuildExportMaps(unittest.TestCase):
    def _channels(self, maps, stem):
        return next(m["channels"] for m in maps if m["fileName"] == stem)

    def test_only_present_channels_are_exported(self):
        maps, stems = core.build_export_maps("H", {"albedo", "normal", "roughness"})
        self.assertEqual([m["fileName"] for m in maps], ["H_Albedo", "H_Normal", "H_Roughness"])
        self.assertEqual(stems, {"h_albedo": "albedo", "h_normal": "normal", "h_roughness": "roughness"})

    def test_normal_uses_virtual_map_matching_format(self):
        maps, _ = core.build_export_maps("H", {"normal"}, "opengl")
        self.assertEqual(self._channels(maps, "H_Normal")[0]["srcMapName"], "Normal_OpenGL")
        self.assertEqual(self._channels(maps, "H_Normal")[0]["srcMapType"], "virtualMap")
        maps, _ = core.build_export_maps("H", {"height"}, "directx")
        self.assertEqual(self._channels(maps, "H_Normal")[0]["srcMapName"], "Normal_DirectX")

    def test_opacity_goes_into_albedo_alpha(self):
        maps, _ = core.build_export_maps("H", {"albedo", "opacity"})
        alpha = [c for c in self._channels(maps, "H_Albedo") if c["destChannel"] == "A"]
        self.assertEqual(alpha[0]["srcMapName"], "opacity")
        self.assertNotIn("H_Opacity", [m["fileName"] for m in maps])


class TestAspectRestoreSize(unittest.TestCase):
    def test_matching_aspect_needs_no_resize(self):
        self.assertIsNone(core.aspect_restore_size(512, 2048, 256, 1024))

    def test_restores_ratio_keeping_long_side(self):
        self.assertEqual(core.aspect_restore_size(2048, 2048, 300, 400), (1536, 2048))
        self.assertEqual(core.aspect_restore_size(1024, 1024, 1000, 500), (1024, 512))

    def test_missing_sizes(self):
        self.assertIsNone(core.aspect_restore_size(0, 0, 100, 100))
        self.assertIsNone(core.aspect_restore_size(100, 100, None, None))


class TestPushIngest(unittest.TestCase):
    def setUp(self):
        self.preflight = {"output_dir": "C:/Remix/out", "edit_target": "C:/Remix/mod.usda",
                          "shader_path": "/RootNode/Looks/mat_H/Shader", "textures": []}
        self.link = {"material_prim": "/RootNode/Looks/mat_H", "material_hash": "H"}

    def test_ingests_updates_and_saves(self):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": False})
        plugin.remix_api.ingest_texture.side_effect = lambda pbr, path, out: (f"C:/ing/{pbr}.dds", None)
        plugin.remix_api.update_textures_batch.return_value = (True, None)
        plugin.remix_api.save_layer.return_value = (True, None)
        summary = plugin._push_ingest({"normal": "n.png", "albedo": "a.png"}, self.preflight, self.link, False, (None, None))
        self.assertEqual(summary["pushed"], ["albedo", "normal"])
        self.assertTrue(summary["saved"])
        updates = dict(plugin.remix_api.update_textures_batch.call_args[0][0])
        self.assertEqual(updates["/RootNode/Looks/mat_H/Shader.inputs:diffuse_texture"], "C:/ing/albedo.dds")
        self.assertEqual(updates["/RootNode/Looks/mat_H/Shader.inputs:normalmap_texture"], "C:/ing/normal.dds")

    def test_partial_failure_is_reported_not_fatal(self):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": False})
        plugin.remix_api.ingest_texture.side_effect = lambda pbr, path, out: (None, "boom") if pbr == "height" else (f"C:/ing/{pbr}.dds", None)
        plugin.remix_api.update_textures_batch.return_value = (True, None)
        plugin.remix_api.save_layer.return_value = (False, "locked")
        summary = plugin._push_ingest({"albedo": "a.png", "height": "h.png"}, self.preflight, self.link, False, (None, None))
        self.assertEqual(summary["failed"], {"height": "boom"})
        self.assertFalse(summary["saved"])

    def test_all_ingests_failing_raises(self):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": False})
        plugin.remix_api.ingest_texture.return_value = (None, "nope")
        with self.assertRaises(core.RemixError):
            plugin._push_ingest({"albedo": "a.png"}, self.preflight, self.link, False, (None, None))
        plugin.remix_api.update_textures_batch.assert_not_called()

    def test_aspect_restore_resizes_mismatched_exports(self):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": True})
        with patch.object(core, "read_image_size", return_value=(2048, 2048)), \
                patch.object(plugin, "_texconv_path", return_value="texconv.exe"):
            plugin._restore_aspect_ratio({"albedo": "a.png"}, ("256", "1024"), self.preflight)
        plugin.texture_processor.resize_png.assert_called_once_with("texconv.exe", "a.png", 512, 2048)


class TestImportFetch(unittest.TestCase):
    def test_copies_textures_and_converts_normals(self):
        plugin = _make_plugin({"normal_map_format": "opengl"})
        with tempfile.TemporaryDirectory() as tmp:
            albedo = os.path.join(tmp, "H_albedo.png")
            normal = os.path.join(tmp, "H_OTH_Normal.png")
            for p in (albedo, normal):
                open(p, "wb").close()
            plugin.remix_api.get_material_textures.return_value = ([
                ("/RootNode/Looks/mat_H/Shader.inputs:diffuse_texture", albedo),
                ("/RootNode/Looks/mat_H/Shader.inputs:normalmap_texture", normal),
                ("/RootNode/Looks/mat_H/Shader.inputs:unknown_texture", albedo),
            ], None)
            plugin.texture_processor.extract_alpha.return_value = None
            with patch.object(core, "PULLED_TEXTURES_DIR", os.path.join(tmp, "pulled")):
                result = plugin._import_fetch("/RootNode/Looks/mat_DEADBEEFDEADBEEF")
            pbrs = sorted(p for p, _ in result["textures"])
            self.assertEqual(pbrs, ["albedo", "normal"])
            kwargs = plugin.texture_processor.convert_remix_normal.call_args[1]
            self.assertTrue(kwargs["octahedral"])
            self.assertTrue(kwargs["target_opengl"])
            # One folder per Remix project and material.
            for _, path in result["textures"]:
                self.assertIn(os.path.join("pulled", "MyMod", "DEADBEEFDEADBEEF"), path)

    def test_missing_files_are_reported(self):
        plugin = _make_plugin()
        plugin.remix_api.get_material_textures.return_value = ([
            ("/M/Shader.inputs:diffuse_texture", "C:/nope/missing.dds"),
        ], None)
        result = plugin._import_fetch("/RootNode/Looks/mat_H")
        self.assertEqual(result["textures"], [])
        self.assertIn("file not found", result["notes"][0])


class TestLinkMetadata(unittest.TestCase):
    def test_material_file_key(self):
        self.assertEqual(core._material_file_key("/RootNode/Looks/mat_DEADBEEFDEADBEEF"), "DEADBEEFDEADBEEF")
        self.assertEqual(core._material_file_key("/RootNode/meshes/mesh_X/ref_1/Looks/My Mat-2"), "My_Mat_2")

    def test_relink_clears_previous_material_facts(self):
        plugin = _make_plugin()
        plugin._write_link = core.RemixConnectorPlugin._write_link.__get__(plugin)
        meta = MagicMock()
        sp = sys.modules["substance_painter"]
        with patch.object(sp.project, "Metadata", return_value=meta):
            plugin._write_link("/RootNode/Looks/mat_0123456789ABCDEF", relink=True)
        written = {c[0][0]: c[0][1] for c in meta.set.call_args_list}
        self.assertEqual(written["remix_material_hash"], "0123456789ABCDEF")
        for key in ("remix_original_width", "remix_original_height", "remix_project_file"):
            self.assertEqual(written[key], "")


class TestSafeCall(unittest.TestCase):
    def _instance(self, operation):
        inst = MagicMock(spec=core.RemixConnectorPlugin)
        inst.current_operation = operation
        return inst

    def test_error_never_releases_another_operations_lock(self):
        inst = self._instance("Push to Remix")
        inst.handle_settings.side_effect = RuntimeError("dialog exploded")
        with patch.object(core, "plugin_instance", inst):
            core.handle_settings()
        inst._fail_operation.assert_not_called()
        inst.show_error.assert_called_once()

    def test_error_ends_the_operation_the_handler_started(self):
        inst = self._instance(None)

        def start_then_fail():
            inst.current_operation = "Push to Remix"
            raise core.RemixError("no link")

        inst.handle_push_to_remix.side_effect = start_then_fail
        with patch.object(core, "plugin_instance", inst):
            core.handle_push_to_remix()
        inst._fail_operation.assert_called_once_with("no link")


if __name__ == "__main__":
    unittest.main()

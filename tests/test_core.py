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
    "_import_fetch", "_texconv_path", "_normal_map_format", "_push_options", "project_normal_format",
    "_push_done", "handle_add_channels",
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

    def test_switched_off_maps_are_not_exported(self):
        present = {"albedo", "opacity", "normal", "height", "roughness"}
        maps, stems = core.build_export_maps("H", present, enabled={"albedo", "height", "roughness"})
        self.assertEqual(sorted(stems.values()), ["albedo", "height", "roughness"])
        # Height alone no longer produces a normal map once Normal is off, and opacity stays out of the alpha.
        self.assertEqual([c["destChannel"] for c in self._channels(maps, "H_Albedo")], ["R", "G", "B"])

    def test_extended_maps_use_resolved_document_maps(self):
        present = {"anisotropy", "transmittance", "thickness", "single_scattering"}
        doc_maps = {"anisotropy": "specularroughnessanisotropy", "transmittance": "transmissioncolor",
                    "thickness": "user0", "single_scattering": "subsurfacecolor"}
        maps, stems = core.build_export_maps("H", present, doc_maps=doc_maps)
        self.assertEqual([m["fileName"] for m in maps],
                         ["H_Anisotropy", "H_Transmittance", "H_Thickness", "H_SingleScattering"])
        self.assertEqual(self._channels(maps, "H_Anisotropy"),
                         [{"srcMapType": "documentMap", "srcMapName": "specularroughnessanisotropy", "srcChannel": "L", "destChannel": "L"}])
        self.assertEqual(self._channels(maps, "H_Thickness")[0]["srcMapName"], "user0")
        self.assertEqual([c["destChannel"] for c in self._channels(maps, "H_Transmittance")], ["R", "G", "B"])
        # A map whose channel name couldn't be resolved is skipped, not exported blank.
        maps, _ = core.build_export_maps("H", {"anisotropy"}, doc_maps={})
        self.assertEqual(maps, [])


class TestAspectRestoreSize(unittest.TestCase):
    def test_matching_aspect_needs_no_resize(self):
        self.assertIsNone(core.aspect_restore_size(512, 2048, 256, 1024))

    def test_restores_ratio_keeping_long_side(self):
        self.assertEqual(core.aspect_restore_size(2048, 2048, 300, 400), (1536, 2048))
        self.assertEqual(core.aspect_restore_size(1024, 1024, 1000, 500), (1024, 512))

    def test_missing_sizes(self):
        self.assertIsNone(core.aspect_restore_size(0, 0, 100, 100))
        self.assertIsNone(core.aspect_restore_size(100, 100, None, None))


def _ingested(pbr, path, out, **_):
    return f"C:/ing/{pbr}.dds", None


class TestPushIngest(unittest.TestCase):
    def setUp(self):
        self.preflight = {"output_dir": "C:/Remix/out", "edit_target": "C:/Remix/mod.usda",
                          "shader_path": "/RootNode/Looks/mat_H/Shader", "textures": []}
        self.link = {"material_prim": "/RootNode/Looks/mat_H", "material_hash": "H"}

    def _plugin(self, **settings):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": False, **settings})
        plugin.remix_api.ingest_texture.side_effect = _ingested
        plugin.remix_api.update_textures_batch.return_value = (True, None)
        plugin.remix_api.save_layer.return_value = (True, None)
        return plugin

    def test_ingests_updates_and_saves(self):
        plugin = self._plugin()
        summary = plugin._push_ingest({"normal": "n.png", "albedo": "a.png"}, self.preflight, self.link, False, (None, None))
        self.assertEqual(summary["pushed"], ["albedo", "normal"])
        self.assertTrue(summary["saved"])
        updates = dict(plugin.remix_api.update_textures_batch.call_args[0][0])
        self.assertEqual(updates["/RootNode/Looks/mat_H/Shader.inputs:diffuse_texture"], "C:/ing/albedo.dds")
        self.assertEqual(updates["/RootNode/Looks/mat_H/Shader.inputs:normalmap_texture"], "C:/ing/normal.dds")

    def test_normal_format_of_the_push_reaches_every_ingest(self):
        # The setting says OpenGL, but this project was created as DirectX: Remix must be told DirectX.
        plugin = self._plugin(normal_map_format="opengl", remix_output_subfolder="Textures/Mine")
        options = plugin._push_options("directx")
        summary = plugin._push_ingest({"normal": "n.png", "albedo": "a.png"}, self.preflight, self.link, False,
                                      (None, None), options)
        for call in plugin.remix_api.ingest_texture.call_args_list:
            self.assertEqual(call.kwargs["normal_map_format"], "directx")
            self.assertEqual(call.kwargs["output_subfolder"], "Textures/Mine")
        self.assertEqual(summary["normal_format"], "directx")

    def test_push_message_names_the_normal_convention(self):
        plugin = _make_plugin()
        plugin._push_done({"material_prim": "/RootNode/Looks/mat_H", "pushed": ["albedo", "normal"], "failed": {},
                           "saved": True, "save_error": None, "normal_format": "directx"}, [])
        self.assertIn("normal (DirectX)", plugin._finish_operation.call_args[0][0])

    def test_extended_maps_are_assigned_in_their_own_batch(self):
        plugin = self._plugin()
        summary = plugin._push_ingest({"albedo": "a.png", "anisotropy": "an.png", "thickness": "t.png"},
                                      self.preflight, self.link, False, (None, None))
        batches = [dict(c[0][0]) for c in plugin.remix_api.update_textures_batch.call_args_list]
        self.assertEqual(list(batches[0]), ["/RootNode/Looks/mat_H/Shader.inputs:diffuse_texture"])
        self.assertEqual(sorted(batches[1]), ["/RootNode/Looks/mat_H/Shader.inputs:anisotropy_texture",
                                              "/RootNode/Looks/mat_H/Shader.inputs:subsurface_thickness_texture"])
        self.assertEqual(summary["pushed"], ["albedo", "anisotropy", "thickness"])
        # Painter's level is remapped to Remix's signed range before the ingest.
        plugin.texture_processor.anisotropy_to_remix.assert_called_once_with("an.png")

    def test_rejected_extended_maps_do_not_fail_the_push(self):
        plugin = self._plugin()
        plugin.remix_api.update_textures_batch.side_effect = [(True, None), (False, "no such input")]
        summary = plugin._push_ingest({"albedo": "a.png", "transmittance": "tr.png"}, self.preflight, self.link,
                                      False, (None, None))
        self.assertEqual(summary["pushed"], ["albedo"])
        self.assertIn("no such input", summary["failed"]["transmittance"])
        self.assertTrue(summary["saved"])

    def test_only_extended_maps_rejected_raises(self):
        plugin = self._plugin()
        plugin.remix_api.update_textures_batch.return_value = (False, "no such input")
        with self.assertRaises(core.RemixError):
            plugin._push_ingest({"anisotropy": "an.png"}, self.preflight, self.link, False, (None, None))

    def test_partial_failure_is_reported_not_fatal(self):
        plugin = self._plugin()
        plugin.remix_api.ingest_texture.side_effect = lambda pbr, path, out, **_: (None, "boom") if pbr == "height" else (f"C:/ing/{pbr}.dds", None)
        plugin.remix_api.save_layer.return_value = (False, "locked")
        summary = plugin._push_ingest({"albedo": "a.png", "height": "h.png"}, self.preflight, self.link, False, (None, None))
        self.assertEqual(summary["failed"], {"height": "boom"})
        self.assertFalse(summary["saved"])

    def test_all_ingests_failing_raises(self):
        plugin = self._plugin()
        plugin.remix_api.ingest_texture.side_effect = None
        plugin.remix_api.ingest_texture.return_value = (None, "nope")
        with self.assertRaises(core.RemixError):
            plugin._push_ingest({"albedo": "a.png"}, self.preflight, self.link, False, (None, None))
        plugin.remix_api.update_textures_batch.assert_not_called()

    def test_force_push_reports_maps_it_could_not_rename(self):
        plugin = self._plugin(remix_output_subfolder="Textures/Settings")
        plugin.texture_processor.choose_non_overwriting_root.return_value = "H_1"
        plugin.texture_processor.copy_texture_with_forced_root.side_effect = (
            lambda path, root, pbr, tmp: (None, "disk full") if pbr == "normal" else (f"C:/tmp/{root}.png", None))
        options = plugin._push_options()
        options["output_subfolder"] = "Textures/Push"
        summary = plugin._push_ingest({"albedo": "C:/exp/a.png", "normal": "C:/exp/n.png"}, self.preflight,
                                      self.link, True, (None, None), options)
        # Never pushed under its old name (that could overwrite an earlier ingest), but reported.
        self.assertEqual(summary["pushed"], ["albedo"])
        self.assertEqual(summary["failed"], {"normal": "disk full"})
        ingested_paths = [c[0][1] for c in plugin.remix_api.ingest_texture.call_args_list]
        self.assertEqual(ingested_paths, ["C:/tmp/H_1_Albedo.png"])
        # The collision check looks in the folder this push ingests into.
        ingest_dir = plugin.texture_processor.choose_non_overwriting_root.call_args[0][1]
        self.assertTrue(ingest_dir.replace("\\", "/").endswith("Textures/Push"))

    def test_aspect_fallback_resolves_relative_albedo_paths(self):
        plugin = _make_plugin()
        preflight = {**self.preflight, "project": {"project_dir": "C:/Mods/MyMod"},
                     "textures": [("/M/Shader.inputs:diffuse_texture", "rtx-remix/a.dds")]}
        with patch.object(core, "read_image_size", return_value=(0, 0)) as size:
            plugin._restore_aspect_ratio({"albedo": "a.png"}, (None, None), preflight)
        self.assertEqual(os.path.normcase(size.call_args_list[0][0][0]),
                         os.path.normcase(os.path.normpath("C:/Mods/MyMod/rtx-remix/a.dds")))

    def test_aspect_restore_resizes_mismatched_exports(self):
        plugin = _make_plugin({"restore_original_aspect_ratio_on_export": True})
        with patch.object(core, "read_image_size", return_value=(2048, 2048)), \
                patch.object(plugin, "_texconv_path", return_value="texconv.exe"):
            plugin._restore_aspect_ratio({"albedo": "a.tga"}, ("256", "1024"), self.preflight)
        plugin.texture_processor.resize_image.assert_called_once_with("texconv.exe", "a.tga", 512, 2048)


class TestExportTextures(unittest.TestCase):
    """Painter's export call, with the stack and Painter's export module faked."""

    def setUp(self):
        self.plugin = _make_plugin()
        self.plugin._export_textures = core.RemixConnectorPlugin._export_textures.__get__(self.plugin)
        pc = self.plugin.painter_controller = MagicMock()
        pc.stack_texture_set.return_value.name.return_value = "TS"
        pc.active_stack.return_value.name.return_value = ""
        pc.present_pbr_types.return_value = {"albedo", "roughness", "anisotropy"}
        pc.document_map_names.return_value = {"anisotropy": "specularroughnessanisotropy"}
        # The code reaches these through the parent module (`substance_painter.export`).
        sp = sys.modules["substance_painter"]
        self.export = sp.export
        self.export.ExportStatus = MagicMock(Success="ok", Warning="warn", Cancelled="cancel", Error="err")
        sp.textureset.all_texture_sets.return_value = [MagicMock()]
        self.options = self.plugin._push_options("opengl")

    def tearDown(self):
        self.export.export_project_textures.reset_mock(side_effect=True, return_value=True)

    def _result(self, status, files=(), message=""):
        return MagicMock(status=status, message=message, textures={"TS": list(files)})

    def test_extended_map_failure_does_not_block_the_standard_maps(self):
        calls = []

        def export(config):
            names = [m["fileName"] for m in config["exportPresets"][0]["maps"]]
            calls.append(names)
            if "H_Anisotropy" in names:
                return self._result("err", message="unknown map specularroughnessanisotropy")
            return self._result("ok", [f"C:/exp/{n}.png" for n in names])

        self.export.export_project_textures.side_effect = export
        exported, notes = self.plugin._export_textures("C:/exp", "H", self.options)
        self.assertEqual(calls, [["H_Albedo", "H_Roughness", "H_Anisotropy"], ["H_Albedo", "H_Roughness"]])
        self.assertEqual(sorted(exported), ["albedo", "roughness"])
        self.assertIn("couldn't export anisotropy", notes[0])

    def test_standard_map_failure_still_fails(self):
        self.plugin.painter_controller.present_pbr_types.return_value = {"albedo"}
        self.export.export_project_textures.side_effect = None
        self.export.export_project_textures.return_value = self._result("err", message="disk full")
        with self.assertRaises(core.RemixError) as ctx:
            self.plugin._export_textures("C:/exp", "H", self.options)
        self.assertIn("disk full", str(ctx.exception))
        self.assertEqual(self.export.export_project_textures.call_count, 1)


class TestNormalFormat(unittest.TestCase):
    def test_project_format_from_pull_wins_over_setting(self):
        plugin = _make_plugin({"normal_map_format": "opengl"})
        self.assertEqual(plugin.project_normal_format({"normal_format": "directx"}), "directx")

    def test_falls_back_to_setting(self):
        plugin = _make_plugin({"normal_map_format": "directx"})
        self.assertEqual(plugin.project_normal_format({}), "directx")
        self.assertEqual(plugin.project_normal_format({"normal_format": "bogus"}), "directx")


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

    def test_options_choose_maps_and_normal_convention(self):
        plugin = _make_plugin({"normal_map_format": "opengl"})
        with tempfile.TemporaryDirectory() as tmp:
            paths = {name: os.path.join(tmp, name) for name in ("H_OTH_Normal.png", "H_rough.png", "H_aniso.png")}
            for p in paths.values():
                open(p, "wb").close()
            plugin.remix_api.get_material_textures.return_value = ([
                ("/M/Shader.inputs:normalmap_texture", paths["H_OTH_Normal.png"]),
                ("/M/Shader.inputs:reflectionroughness_texture", paths["H_rough.png"]),
                ("/M/Shader.inputs:anisotropy_texture", paths["H_aniso.png"]),
            ], None)
            options = {"normal_format": "directx", "maps": {"normal", "anisotropy"}}
            with patch.object(core, "PULLED_TEXTURES_DIR", os.path.join(tmp, "pulled")):
                result = plugin._import_fetch("/RootNode/Looks/mat_H", options)
        self.assertEqual(sorted(p for p, _ in result["textures"]), ["anisotropy", "normal"])
        self.assertFalse(plugin.texture_processor.convert_remix_normal.call_args[1]["target_opengl"])
        plugin.texture_processor.anisotropy_from_remix.assert_called_once()


class TestAddChannels(unittest.TestCase):
    def test_adds_only_missing_enabled_channels(self):
        plugin = _make_plugin({"texture_maps": {"anisotropy": False}})
        plugin._operation = None
        plugin.painter_controller = MagicMock()
        plugin.painter_controller.present_pbr_types.return_value = {"albedo", "normal", "roughness", "metallic", "height"}
        plugin.painter_controller.ensure_channel.return_value = True
        plugin.handle_add_channels()
        added = [c[0][1] for c in plugin.painter_controller.ensure_channel.call_args_list]
        self.assertEqual(added, ["emissive", "transmittance", "thickness", "single_scattering", "opacity"])
        self.assertIn("Added channels", plugin.display_message.call_args[0][0])

    def test_refuses_while_an_operation_runs(self):
        plugin = _make_plugin()
        plugin._operation = "Push to Remix"
        plugin.painter_controller = MagicMock()
        plugin.handle_add_channels()
        plugin.painter_controller.ensure_channel.assert_not_called()


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

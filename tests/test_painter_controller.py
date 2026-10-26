import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from ._isolated import import_plugin_module

# painter_controller handles missing substance_painter on import; tests
# replace painter_controller.substance_painter in setUp.
painter_controller = import_plugin_module("painter_controller")
PainterController = painter_controller.PainterController
aspect_matched_resolution = painter_controller.aspect_matched_resolution


class TestAspectMatchedResolution(unittest.TestCase):
    def test_square_source(self):
        self.assertEqual(aspect_matched_resolution(1024, 1024, 2048), (2048, 2048))

    def test_tall_power_of_two_ratio_is_exact(self):
        self.assertEqual(aspect_matched_resolution(256, 1024, 2048), (512, 2048))

    def test_wide_source(self):
        self.assertEqual(aspect_matched_resolution(2048, 1024, 4096), (4096, 2048))

    def test_non_power_of_two_ratio_rounds(self):
        # 3:4 is closer to 1:1 than 1:2 in log space.
        self.assertEqual(aspect_matched_resolution(300, 400, 2048), (2048, 2048))

    def test_clamped_to_painter_limits(self):
        self.assertEqual(aspect_matched_resolution(16, 4096, 8192), (128, 4096))
        self.assertEqual(aspect_matched_resolution(64, 64, 3000), (2048, 2048))

    def test_unknown_source_is_square(self):
        self.assertEqual(aspect_matched_resolution(0, 0, 1024), (1024, 1024))

    def test_pow2_ceil_never_goes_below_the_source(self):
        self.assertEqual(painter_controller.pow2_ceil(3000), 4096)
        self.assertEqual(painter_controller.pow2_ceil(2048), 2048)
        self.assertEqual(painter_controller.pow2_ceil(2049), 4096)
        self.assertEqual(painter_controller.pow2_ceil(9000), 4096)  # Painter's limit
        self.assertEqual(aspect_matched_resolution(3000, 3000, painter_controller.pow2_ceil(3000)), (4096, 4096))


class TestPainterController(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.controller = PainterController(self.logger)
        self.sp = MagicMock()
        painter_controller.substance_painter = self.sp

    def test_channel_type_and_format_lookup(self):
        self.assertIs(self.controller.channel_type("albedo"), self.sp.textureset.ChannelType.BaseColor)
        self.assertIs(self.controller.channel_format("height"), self.sp.textureset.ChannelFormat.L16F)
        self.assertIsNone(self.controller.channel_type("unknown"))

    def test_ensure_channel_adds_missing_channel_with_format(self):
        stack = MagicMock()
        stack.has_channel.return_value = False
        self.assertTrue(self.controller.ensure_channel(stack, "emissive"))
        stack.add_channel.assert_called_once_with(
            self.sp.textureset.ChannelType.Emissive, self.sp.textureset.ChannelFormat.sRGB8)

    def test_ensure_channel_keeps_existing(self):
        stack = MagicMock()
        stack.has_channel.return_value = True
        self.assertTrue(self.controller.ensure_channel(stack, "roughness"))
        stack.add_channel.assert_not_called()

    def test_ensure_channel_failure_is_reported(self):
        stack = MagicMock()
        stack.has_channel.return_value = False
        stack.add_channel.side_effect = ValueError("material layering")
        self.assertFalse(self.controller.ensure_channel(stack, "emissive"))
        self.logger.warning.assert_called()

    def test_present_pbr_types(self):
        stack = MagicMock()
        present = {self.sp.textureset.ChannelType.BaseColor, self.sp.textureset.ChannelType.Normal}
        stack.has_channel.side_effect = lambda ct: ct in present
        self.assertEqual(self.controller.present_pbr_types(stack), {"albedo", "normal"})

    def test_create_fill_layer_sets_only_sourced_channels(self):
        stack = MagicMock()
        stack.has_channel.return_value = True
        fill = MagicMock()
        self.sp.layerstack.insert_fill.return_value = fill
        self.sp.resource.import_project_resource.side_effect = lambda path, usage: MagicMock(identifier=MagicMock(return_value=f"rid:{path}"))

        assigned, errors = self.controller.create_fill_layer(stack, {"albedo": "a.png", "normal": "n.png"}, "Remix mat_X")

        self.assertEqual(sorted(assigned), ["albedo", "normal"])
        self.assertEqual(errors, [])
        self.sp.layerstack.ScopedModification.assert_called_once_with("Remix mat_X")
        fill.set_name.assert_called_once_with("Remix mat_X")
        self.assertEqual(fill.active_channels, {self.sp.textureset.ChannelType.BaseColor, self.sp.textureset.ChannelType.Normal})
        fill.set_source.assert_any_call(self.sp.textureset.ChannelType.BaseColor, "rid:a.png")
        fill.set_source.assert_any_call(self.sp.textureset.ChannelType.Normal, "rid:n.png")

    def test_create_fill_layer_deactivates_channels_whose_source_failed(self):
        stack = MagicMock()
        stack.has_channel.return_value = True
        fill = MagicMock()
        self.sp.layerstack.insert_fill.return_value = fill
        self.sp.resource.import_project_resource.side_effect = lambda path, usage: MagicMock(identifier=MagicMock(return_value=path))

        def set_source(ct, rid):
            if rid == "n.png":
                raise ValueError("bad")

        fill.set_source.side_effect = set_source

        assigned, errors = self.controller.create_fill_layer(stack, {"albedo": "a.png", "normal": "n.png"}, "Remix")

        self.assertEqual(assigned, ["albedo"])
        self.assertIn("normal", errors[0])
        # The failed Normal channel must not stay active with its default value.
        self.assertEqual(fill.active_channels, {self.sp.textureset.ChannelType.BaseColor})
        self.sp.layerstack.delete_node.assert_not_called()

    def test_create_fill_layer_removes_an_empty_layer(self):
        stack = MagicMock()
        stack.has_channel.return_value = True
        fill = MagicMock()
        fill.set_source.side_effect = ValueError("bad")
        self.sp.layerstack.insert_fill.return_value = fill
        assigned, _ = self.controller.create_fill_layer(stack, {"albedo": "a.png"}, "Remix")
        self.assertEqual(assigned, [])
        self.sp.layerstack.delete_node.assert_called_once_with(fill)

    def test_create_fill_layer_skips_failed_imports(self):
        stack = MagicMock()
        stack.has_channel.return_value = True
        self.sp.resource.import_project_resource.side_effect = RuntimeError("bad file")
        assigned, errors = self.controller.create_fill_layer(stack, {"albedo": "a.png"}, "Remix")
        self.assertEqual(assigned, [])
        self.assertIn("import failed", errors[0])
        self.sp.layerstack.insert_fill.assert_not_called()

    def test_set_resolution_only_when_different(self):
        ts = MagicMock()
        ts.get_resolution.return_value = MagicMock(width=2048, height=2048)
        self.assertTrue(self.controller.set_resolution(ts, 2048, 2048))
        ts.set_resolution.assert_not_called()
        self.assertTrue(self.controller.set_resolution(ts, 512, 2048))
        ts.set_resolution.assert_called_once()

    def test_channel_type_falls_back_to_legacy_name(self):
        # Painter 12 calls it SpecularRoughnessAnisotropy; older versions only know Anisotropylevel.
        self.sp.textureset.ChannelType = SimpleNamespace(Anisotropylevel="legacy-aniso")
        self.assertEqual(self.controller.channel_type("anisotropy"), "legacy-aniso")
        self.sp.textureset.ChannelType = SimpleNamespace(SpecularRoughnessAnisotropy="aniso", Anisotropylevel="aniso")
        self.assertEqual(self.controller.channel_type("anisotropy"), "aniso")

    def _user_stack(self, labels):
        """A stack whose User channels carry ``labels`` ({index: label})."""
        self.sp.textureset.ChannelType = SimpleNamespace(**{f"User{i}": f"User{i}" for i in range(32)})
        stack = MagicMock()
        stack.has_channel.side_effect = lambda ct: ct in {f"User{i}" for i in labels}
        stack.get_channel.side_effect = lambda ct: MagicMock(label=MagicMock(return_value=labels[int(ct[4:])]))
        return stack

    def test_thickness_lives_in_a_labelled_user_channel(self):
        stack = self._user_stack({0: "Wetness", 1: "remix thickness"})
        self.assertEqual(self.controller.channel_type("thickness", stack), "User1")
        self.assertIsNone(self.controller.channel_type("thickness"))  # needs the stack

    def test_ensure_thickness_adds_the_first_free_user_channel(self):
        stack = self._user_stack({0: "Wetness"})
        self.assertTrue(self.controller.ensure_channel(stack, "thickness"))
        stack.add_channel.assert_called_once_with("User1", self.sp.textureset.ChannelFormat.L8, "Remix Thickness")

    def test_document_map_names_come_from_the_channel(self):
        stack = MagicMock()
        stack.get_channel.return_value.type.return_value.name = "SpecularRoughnessAnisotropy"
        names = self.controller.document_map_names(stack, {"anisotropy", "albedo", "normal"})
        # Maps with a fixed name (albedo) or a virtual map (normal) aren't resolved.
        self.assertEqual(names, {"anisotropy": "specularroughnessanisotropy"})

    def _js(self, instances):
        calls = []

        def evaluate(code):
            calls.append(code)
            return instances if code == "alg.shaders.instances()" else None

        self.sp.js.evaluate.side_effect = evaluate
        return calls

    def test_register_shelf_adds_it_once(self):
        self.sp.resource.Shelves.exists.return_value = False
        self.controller.register_shelf()
        self.sp.resource.Shelves.add.assert_called_once_with("substance2remix", painter_controller.SHELF_PATH)
        self.assertTrue(os.path.isfile(painter_controller.REMIX_SHADER_PATH))
        self.assertEqual(os.path.dirname(os.path.dirname(painter_controller.REMIX_SHADER_PATH)),
                         painter_controller.SHELF_PATH)
        self.sp.resource.Shelves.reset_mock()
        self.sp.resource.Shelves.exists.return_value = True
        self.controller.register_shelf()
        self.sp.resource.Shelves.add.assert_not_called()

    def test_use_remix_shader_takes_the_shelf_copy(self):
        calls = self._js([{"id": 0, "shader": "pbr-metal-rough-with-alpha-blending"}])
        hit = MagicMock()
        hit.identifier.return_value.url.return_value = "resource://substance2remix/rtx-remix-preview"
        self.sp.resource.search.return_value = [hit]
        self.controller.use_remix_shader(self._user_stack({}))
        self.assertEqual(self.sp.resource.search.call_args[0][0], "s:substance2remix u:shader n:rtx-remix-preview")
        self.sp.resource.import_project_resource.assert_not_called()
        self.assertIn('alg.shaders.updateShaderInstance(0, "resource://substance2remix/rtx-remix-preview")', calls)

    def test_use_remix_shader_switches_and_points_at_the_thickness_slot(self):
        calls = self._js([{"id": 0, "shader": "pbr-metal-rough-with-alpha-blending"}])
        self.sp.resource.search.return_value = []  # shelf not crawled yet: import a project copy
        self.sp.resource.import_project_resource.return_value.identifier.return_value.url.return_value = "resource://p/rtx"
        stack = self._user_stack({0: "Wetness", 2: "Remix Thickness"})
        self.assertEqual(self.controller.use_remix_shader(stack), 1)
        path, usage = self.sp.resource.import_project_resource.call_args[0]
        self.assertTrue(path.endswith("rtx-remix-preview.glsl"))
        self.assertIs(usage, self.sp.resource.Usage.SHADER)
        self.assertIn('alg.shaders.updateShaderInstance(0, "resource://p/rtx")', calls)
        self.assertIn('alg.shaders.setParameters(0, {"remixThicknessChannel": 2})', calls)

    def test_use_remix_shader_is_idempotent(self):
        calls = self._js([{"id": 3, "shader": "rtx-remix-preview"}])
        stack = self._user_stack({})
        self.assertEqual(self.controller.use_remix_shader(stack), 0)
        self.sp.resource.search.assert_not_called()
        self.sp.resource.import_project_resource.assert_not_called()  # no duplicate resource
        self.assertIn('alg.shaders.setParameters(3, {"remixThicknessChannel": -1})', calls)

    def test_sync_thickness_slot_only_touches_the_preview_shader(self):
        calls = self._js([{"id": 0, "shader": "rtx-remix-preview"}, {"id": 1, "shader": "pbr-metal-rough"}])
        self.controller.sync_thickness_slot(self._user_stack({0: "Wetness", 1: "Remix Thickness"}))
        self.assertIn('alg.shaders.setParameters(0, {"remixThicknessChannel": 1})', calls)
        self.assertFalse(any(c.startswith("alg.shaders.setParameters(1,") for c in calls))
        self.assertFalse(any("updateShaderInstance" in c for c in calls))

    def test_thickness_beyond_the_shader_slots_is_not_previewed(self):
        calls = self._js([{"id": 0, "shader": "rtx-remix-preview"}])
        stack = self._user_stack({5: "Remix Thickness"})
        self.controller.use_remix_shader(stack)
        self.assertIn('alg.shaders.setParameters(0, {"remixThicknessChannel": -1})', calls)
        self.logger.warning.assert_called()

    def test_preview_shader_reads_every_remix_channel(self):
        with open(painter_controller.REMIX_SHADER_PATH, encoding="utf-8") as f:
            source = f.read()
        for needle in ("channel_basecolor", "channel_opacity", "channel_roughness", "channel_metallic",
                       "channel_anisotropylevel", "channel_absorptioncolor", "channel_scatteringcolor",
                       "channel_user0", "channel_user3", "uniform int remixThicknessChannel",
                       "//: state blend over", "alphaOutput(", "emissiveColorOutput("):
            self.assertIn(needle, source)

    def test_active_stack_falls_back_to_first_texture_set(self):
        self.sp.textureset.get_active_stack.side_effect = RuntimeError("no active stack")
        ts = MagicMock()
        self.sp.textureset.all_texture_sets.return_value = [ts]
        self.assertIs(self.controller.active_stack(), ts.get_stack.return_value)


if __name__ == "__main__":
    unittest.main()

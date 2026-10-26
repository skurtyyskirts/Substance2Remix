import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# painter_controller handles missing substance_painter on import; tests
# replace painter_controller.substance_painter in setUp.
import painter_controller
from painter_controller import PainterController, aspect_matched_resolution


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

    def test_active_stack_falls_back_to_first_texture_set(self):
        self.sp.textureset.get_active_stack.side_effect = RuntimeError("no active stack")
        ts = MagicMock()
        self.sp.textureset.all_texture_sets.return_value = [ts]
        self.assertIs(self.controller.active_stack(), ts.get_stack.return_value)


if __name__ == "__main__":
    unittest.main()

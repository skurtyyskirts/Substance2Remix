import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to path to import blender_auto_unwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock bpy before importing blender_auto_unwrap
bpy_mock = MagicMock()
sys.modules['bpy'] = bpy_mock

import blender_auto_unwrap  # noqa: E402


def _rna(*names):
    """Fake operator whose RNA type exposes the given property identifiers."""
    op = MagicMock()
    op.get_rna_type.return_value.properties = [MagicMock(identifier=n) for n in names]
    op.idname_py.return_value = "wm.fake_op"
    return op


class TestSupportedKwargs(unittest.TestCase):
    def test_unknown_keywords_are_dropped(self):
        # Blender 5.x rejects unknown keywords (e.g. the old "primvars_interpolation").
        op = _rna("filepath", "selected_objects_only")
        with patch.object(blender_auto_unwrap, "log_message") as log:
            kept = blender_auto_unwrap._supported_kwargs(op, {"filepath": "x", "primvars_interpolation": "Varying"})
        self.assertEqual(kept, {"filepath": "x"})
        self.assertIn("primvars_interpolation", log.call_args[0][1])

    def test_falls_back_to_all_keywords_without_rna(self):
        op = MagicMock()
        op.get_rna_type.side_effect = AttributeError
        self.assertEqual(blender_auto_unwrap._supported_kwargs(op, {"a": 1}), {"a": 1})


@patch.object(blender_auto_unwrap, "_supported_kwargs", side_effect=lambda op, kw: kw)
class TestBlenderAutoUnwrap(unittest.TestCase):
    def setUp(self):
        bpy_mock.reset_mock()
        self.original_argv = sys.argv.copy()
        self.mesh = MagicMock(type='MESH')
        bpy_mock.context.scene.objects = [self.mesh]

    def tearDown(self):
        sys.argv = self.original_argv

    def _run(self, *args):
        sys.argv = ['blender', '--background', '--python', 'script.py', '--', *args]
        with patch('blender_auto_unwrap.os.path.exists', return_value=True), \
                patch('blender_auto_unwrap.os.makedirs'), \
                patch('blender_auto_unwrap.log_message') as log:
            blender_auto_unwrap.main()
        return log

    def test_missing_arguments(self, _kw):
        sys.argv = ['blender', '--python', 'script.py', '--']
        with patch('blender_auto_unwrap.log_message') as log, self.assertRaises(SystemExit) as ctx:
            blender_auto_unwrap.main()
        self.assertEqual(ctx.exception.code, 2)
        log.assert_called_with("error", "Argument parsing failed. Argparse exit code: 2. Arguments received: []")

    def test_input_file_not_found(self, _kw):
        sys.argv = ['blender', '--python', 'script.py', '--', 'input.fbx', 'output.fbx']
        with patch('blender_auto_unwrap.os.path.exists', return_value=False), \
                patch('blender_auto_unwrap.log_message') as log, self.assertRaises(SystemExit) as ctx:
            blender_auto_unwrap.main()
        self.assertEqual(ctx.exception.code, 1)
        log.assert_any_call("error", "Input mesh file not found: input.fbx")

    def test_usd_round_trip_unwraps_all_meshes_once(self, _kw):
        second = MagicMock(type='MESH')
        bpy_mock.context.scene.objects = [self.mesh, second, MagicMock(type='CAMERA')]
        self._run('in.usda', 'out.usd', '--angle_limit', '45', '--stretch_to_bounds', 'True')

        bpy_mock.ops.wm.read_factory_settings.assert_called_once_with(use_empty=True)
        bpy_mock.ops.wm.usd_import.assert_called_once_with(filepath='in.usda', import_materials=False)
        self.mesh.select_set.assert_called_with(True)
        second.select_set.assert_called_with(True)
        bpy_mock.ops.uv.smart_project.assert_called_once()
        kwargs = bpy_mock.ops.uv.smart_project.call_args[1]
        self.assertAlmostEqual(kwargs["angle_limit"], 0.785398, places=5)
        self.assertTrue(kwargs["scale_to_bounds"])
        export_kwargs = bpy_mock.ops.wm.usd_export.call_args[1]
        self.assertEqual(export_kwargs["filepath"], 'out.usd')
        self.assertTrue(export_kwargs["export_uvmaps"])
        self.assertNotIn("primvars_interpolation", export_kwargs)

    def test_fbx_flow(self, _kw):
        self._run('in.fbx', 'out.fbx')
        bpy_mock.ops.import_scene.fbx.assert_called_once_with(filepath='in.fbx')
        bpy_mock.ops.export_scene.fbx.assert_called_once_with(filepath='out.fbx', use_selection=True)

    def test_gltf_export_format_follows_the_extension(self, _kw):
        # Blender's glTF exporter writes GLB unless told otherwise, whatever the file name.
        self._run('in.gltf', 'out.gltf')
        self.assertEqual(bpy_mock.ops.export_scene.gltf.call_args[1]["export_format"], "GLTF_SEPARATE")
        bpy_mock.reset_mock()
        bpy_mock.context.scene.objects = [self.mesh]
        self._run('in.glb', 'out.glb')
        self.assertEqual(bpy_mock.ops.export_scene.gltf.call_args[1]["export_format"], "GLB")

    def test_obj_flow_uses_modern_operators(self, _kw):
        self._run('in.obj', 'out.obj')
        bpy_mock.ops.wm.obj_import.assert_called_once_with(filepath='in.obj')
        bpy_mock.ops.wm.obj_export.assert_called_once()

    def test_no_mesh_objects_after_import(self, _kw):
        bpy_mock.context.scene.objects = [MagicMock(type='CAMERA')]
        with self.assertRaises(SystemExit) as ctx:
            log = self._run('in.usd', 'out.usd')
        self.assertEqual(ctx.exception.code, 1)

    def test_unsupported_formats_exit_with_error(self, _kw):
        for args in (('in.abc', 'out.usd'), ('in.usd', 'out.abc')):
            sys.argv = ['blender', '--', *args]
            with patch('blender_auto_unwrap.os.path.exists', return_value=True), \
                    patch('blender_auto_unwrap.os.makedirs'), \
                    patch('blender_auto_unwrap.log_message') as log, self.assertRaises(SystemExit) as ctx:
                blender_auto_unwrap.main()
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("Unsupported", str(log.call_args_list))

    def test_missing_output_after_export_is_an_error(self, _kw):
        sys.argv = ['blender', '--', 'in.usd', 'out.usd']
        exists = MagicMock(side_effect=lambda p: p == 'in.usd')
        with patch('blender_auto_unwrap.os.path.exists', exists), \
                patch('blender_auto_unwrap.os.makedirs'), \
                patch('blender_auto_unwrap.log_message') as log, self.assertRaises(SystemExit):
            blender_auto_unwrap.main()
        log.assert_any_call("error", "Export reported success but the output file is missing.")


if __name__ == '__main__':
    unittest.main()

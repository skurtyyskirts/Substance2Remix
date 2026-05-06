import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add parent dir to path to import blender_auto_unwrap
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock bpy before importing blender_auto_unwrap
bpy_mock = MagicMock()
sys.modules['bpy'] = bpy_mock

import blender_auto_unwrap

class TestBlenderAutoUnwrap(unittest.TestCase):
    def setUp(self):
        # Reset the bpy mock and its children for each test
        bpy_mock.reset_mock()

        # Reset sys.argv
        self.original_argv = sys.argv.copy()

    def tearDown(self):
        # Restore sys.argv
        sys.argv = self.original_argv

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_missing_arguments(self, mock_log, mock_exit, mock_exists):
        # Test without required arguments
        sys.argv = ['blender', '--python', 'script.py', '--']

        # We need to make mock_exit raise an exception to stop execution
        # like the real sys.exit would
        mock_exit.side_effect = SystemExit(2)

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        # Argparse will call sys.exit(2) on error
        mock_exit.assert_called_with(2)
        mock_log.assert_called_with("error", "Argument parsing failed. Argparse exit code: 2. Arguments received: []")

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_input_file_not_found(self, mock_log, mock_exit, mock_exists):
        # Test when input file does not exist
        sys.argv = ['blender', '--python', 'script.py', '--', 'input.fbx', 'output.fbx']
        mock_exists.return_value = False
        mock_exit.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        mock_exists.assert_called_with('input.fbx')
        mock_exit.assert_called_with(1)
        mock_log.assert_any_call("error", "Input mesh file not found: input.fbx")

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_argument_parsing_with_separator(self, mock_log, mock_exit, mock_exists):
        # Test successful parsing with "--" separator
        sys.argv = ['blender', '-b', '--python', 'script.py', '--', 'in.obj', 'out.obj', '--angle_limit', '45.0']
        mock_exists.return_value = True

        # We need to mock the rest of the flow to prevent errors
        bpy_mock.context.selected_objects = [MagicMock(type='MESH')]

        # Mock sys.exit to stop flow early after args parsing (simulate success)
        mock_exit.side_effect = SystemExit(0)

        # We don't want to actually execute the blender stuff in this test
        with patch('blender_auto_unwrap.bpy', bpy_mock):
            try:
                blender_auto_unwrap.main()
            except SystemExit:
                pass

        # Check that it proceeded past argument validation
        mock_exists.assert_called_with('in.obj')




    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_main_flow_usd(self, mock_log, mock_exit, mock_exists):
        # Test full flow for USD file
        sys.argv = ['blender', '--', 'in.usd', 'out.usd']
        mock_exists.return_value = True

        # Setup bpy mocks
        bpy_mock.ops.object.select_all.poll.return_value = True
        bpy_mock.ops.object.delete.poll.return_value = True
        bpy_mock.ops.outliner.orphans_purge.poll.return_value = True

        # Mock USD import available
        bpy_mock.ops.wm.usd_import = MagicMock()

        # Setup selected objects
        mesh_mock = MagicMock()
        mesh_mock.type = 'MESH'
        mesh_mock.name = 'Cube'
        bpy_mock.context.selected_objects = [mesh_mock]
        bpy_mock.context.scene.objects = [mesh_mock]

        # Mock USD export available
        bpy_mock.ops.wm.usd_export = MagicMock()

        blender_auto_unwrap.main()

        # Verify import/export calls
        bpy_mock.ops.wm.usd_import.assert_called_once_with(filepath='in.usd')
        bpy_mock.ops.wm.usd_export.assert_called_once_with(
            filepath='out.usd',
            selected_objects_only=True,
            primvars_interpolation='Varying'
        )

        # Verify unwrap calls
        bpy_mock.ops.uv.smart_project.assert_called_once()

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_main_flow_fbx(self, mock_log, mock_exit, mock_exists):
        # Test full flow for FBX file
        sys.argv = ['blender', '--', 'in.fbx', 'out.fbx']
        mock_exists.return_value = True

        # Mock FBX import/export available
        bpy_mock.ops.import_scene.fbx = MagicMock()
        bpy_mock.ops.export_scene.fbx = MagicMock()

        # Setup selected objects
        mesh_mock = MagicMock()
        mesh_mock.type = 'MESH'
        bpy_mock.context.selected_objects = [mesh_mock]
        bpy_mock.context.scene.objects = [mesh_mock]

        blender_auto_unwrap.main()

        # Verify import/export calls
        bpy_mock.ops.import_scene.fbx.assert_called_once_with(filepath='in.fbx')
        bpy_mock.ops.export_scene.fbx.assert_called_once_with(filepath='out.fbx', use_selection=True)

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_main_flow_obj(self, mock_log, mock_exit, mock_exists):
        # Test full flow for OBJ file
        sys.argv = ['blender', '--', 'in.obj', 'out.obj']
        mock_exists.return_value = True

        # Mock OBJ import/export available
        bpy_mock.ops.import_scene.obj = MagicMock()
        bpy_mock.ops.export_scene.obj = MagicMock()

        # Mock that wm module does NOT have obj_import to test the preferred import_scene path
        # Using a fresh MagicMock for wm
        bpy_mock.ops.wm = MagicMock(spec=[])

        # Setup selected objects
        mesh_mock = MagicMock()
        mesh_mock.type = 'MESH'
        bpy_mock.context.selected_objects = [mesh_mock]
        bpy_mock.context.scene.objects = [mesh_mock]

        blender_auto_unwrap.main()

        # Verify import/export calls
        bpy_mock.ops.import_scene.obj.assert_called_once_with(filepath='in.obj')
        bpy_mock.ops.export_scene.obj.assert_called_once_with(filepath='out.obj', use_selection=True)

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_main_flow_obj_fallback(self, mock_log, mock_exit, mock_exists):
        # Test full flow for OBJ file with fallback import/export methods
        sys.argv = ['blender', '--', 'in.obj', 'out.obj']
        mock_exists.return_value = True

        # Using a mock that explicitly raises AttributeError when import_scene.obj is accessed
        class EmptyClass: pass
        bpy_mock.ops.import_scene = MagicMock(spec=EmptyClass)
        bpy_mock.ops.export_scene = MagicMock(spec=EmptyClass)

        # Add fallback methods
        bpy_mock.ops.wm.obj_import = MagicMock()
        bpy_mock.ops.wm.obj_export = MagicMock()

        # Setup selected objects
        mesh_mock = MagicMock()
        mesh_mock.type = 'MESH'
        bpy_mock.context.selected_objects = [mesh_mock]
        bpy_mock.context.scene.objects = [mesh_mock]

        blender_auto_unwrap.main()

        # Verify fallback import/export calls
        bpy_mock.ops.wm.obj_import.assert_called_once_with(filepath='in.obj')
        bpy_mock.ops.wm.obj_export.assert_called_once_with(filepath='out.obj', use_selection=True)


    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_unsupported_input_format(self, mock_log, mock_exit, mock_exists):
        # Test input file with unsupported extension
        sys.argv = ['blender', '--', 'in.abc', 'out.fbx']
        mock_exists.return_value = True
        mock_exit.side_effect = SystemExit(1)

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        mock_log.assert_any_call("error", "Unsupported input format: .abc")

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_unsupported_output_format(self, mock_log, mock_exit, mock_exists):
        # Test output file with unsupported extension
        sys.argv = ['blender', '--', 'in.fbx', 'out.abc']
        mock_exists.return_value = True
        mock_exit.side_effect = SystemExit(1)

        # Mock FBX import available
        bpy_mock.ops.import_scene.fbx = MagicMock()

        # Setup selected objects
        mesh_mock = MagicMock()
        mesh_mock.type = 'MESH'
        bpy_mock.context.selected_objects = [mesh_mock]
        bpy_mock.context.scene.objects = [mesh_mock]

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        mock_log.assert_any_call("error", "Unsupported output format: .abc")

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_missing_import_module(self, mock_log, mock_exit, mock_exists):
        # Test when the required import module is missing from bpy
        sys.argv = ['blender', '--', 'in.fbx', 'out.fbx']
        mock_exists.return_value = True
        mock_exit.side_effect = SystemExit(1)

        # Explicitly remove import_scene.fbx to simulate missing module
        class EmptyClass: pass
        bpy_mock.ops.import_scene = MagicMock(spec=EmptyClass)

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        mock_log.assert_any_call("error", "FBX import not available.")

    @patch('blender_auto_unwrap.os.path.exists')
    @patch('blender_auto_unwrap.sys.exit')
    @patch('blender_auto_unwrap.log_message')
    def test_no_mesh_objects_after_import(self, mock_log, mock_exit, mock_exists):
        # Test when import succeeds but no mesh objects are found
        sys.argv = ['blender', '--', 'in.fbx', 'out.fbx']
        mock_exists.return_value = True
        mock_exit.side_effect = SystemExit(1)

        # Mock FBX import available
        bpy_mock.ops.import_scene.fbx = MagicMock()

        # Setup selected objects with NO mesh (e.g. only cameras/lights)
        non_mesh_mock = MagicMock()
        non_mesh_mock.type = 'CAMERA'
        bpy_mock.context.selected_objects = []
        bpy_mock.context.scene.objects = [non_mesh_mock]

        with self.assertRaises(SystemExit):
            blender_auto_unwrap.main()

        mock_log.assert_any_call("error", "No mesh objects found in scene after import.")

if __name__ == '__main__':
    unittest.main()

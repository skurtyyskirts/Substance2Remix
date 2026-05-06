import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Mock bpy before importing blender_auto_unwrap
sys.modules['bpy'] = MagicMock()

import blender_auto_unwrap

class TestBlenderAutoUnwrap(unittest.TestCase):
    def setUp(self):
        # Reset the mock before each test to ensure clean state
        self.mock_bpy = sys.modules['bpy']
        self.mock_bpy.reset_mock()

    @patch('builtins.print')
    def test_log_message(self, mock_print):
        blender_auto_unwrap.log_message('info', 'Test message')
        mock_print.assert_called_once_with('BlenderScript: INFO: Test message')

    @patch('sys.argv', ['blender_auto_unwrap.py', '--'])
    @patch('sys.exit')
    @patch('builtins.print')
    def test_main_missing_args(self, mock_print, mock_exit):
        # argparse will call sys.exit(2) when required arguments are missing
        # However, our script catches SystemExit and potentially re-raises it.
        # It's better to expect SystemExit directly if it isn't mocked deeply.

        # In blender_auto_unwrap.py, args are parsed, and if it fails, it calls sys.exit(1 or code)
        mock_exit.side_effect = SystemExit
        with self.assertRaises(SystemExit) as context:
            blender_auto_unwrap.main()

        mock_exit.assert_called_with(2) if '2' in str(mock_exit.call_args) else mock_exit.assert_called_with(1)
        # Verify error log
        self.assertTrue(any("Argument parsing failed" in str(call) for call in mock_print.mock_calls))

    @patch('sys.argv', ['blender_auto_unwrap.py', '--', 'input.obj', 'output.obj'])
    @patch('os.path.exists')
    @patch('sys.exit')
    @patch('builtins.print')
    def test_main_missing_input_file(self, mock_print, mock_exit, mock_exists):
        mock_exists.return_value = False
        mock_exit.side_effect = SystemExit

        with self.assertRaises(SystemExit) as context:
            blender_auto_unwrap.main()

        mock_exit.assert_called_once_with(1)
        mock_exists.assert_any_call('input.obj')
        self.assertTrue(any("Input mesh file not found" in str(call) for call in mock_print.mock_calls))

    @patch('sys.argv', ['blender_auto_unwrap.py', '--', 'input.obj', 'output.obj'])
    @patch('os.path.exists')
    @patch('builtins.print')
    def test_main_success_flow(self, mock_print, mock_exists):
        mock_exists.return_value = True

        # Setup mock scene and objects
        mock_mesh_obj = MagicMock()
        mock_mesh_obj.type = 'MESH'
        mock_mesh_obj.name = 'TestMesh'

        self.mock_bpy.context.selected_objects = [mock_mesh_obj]
        self.mock_bpy.context.scene.objects = [mock_mesh_obj]

        # Execute the main function
        blender_auto_unwrap.main()

        # Verify import calls
        # Since it's .obj, it uses either import_scene.obj or wm.obj_import
        # Because we're using MagicMock for bpy, both hasattr checks will pass
        # The code prefers import_scene.obj
        self.mock_bpy.ops.import_scene.obj.assert_called_once_with(filepath='input.obj')

        # Verify processing calls
        self.mock_bpy.ops.uv.smart_project.assert_called_once()
        self.mock_bpy.ops.object.mode_set.assert_any_call(mode='EDIT')
        self.mock_bpy.ops.object.mode_set.assert_any_call(mode='OBJECT')

        # Verify export calls
        self.mock_bpy.ops.export_scene.obj.assert_called_once_with(
            filepath='output.obj',
            use_selection=True
        )

        self.assertTrue(any("Mesh exported successfully." in str(call) for call in mock_print.mock_calls))

if __name__ == '__main__':
    unittest.main()

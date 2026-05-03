import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from painter_controller import PainterController

class TestPainterControllerAssignTexture(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()

        self.patcher = patch('painter_controller.substance_painter')
        self.mock_sp = self.patcher.start()

        # Simplify _coerce_to_resource_id behavior for tests by making ResourceID a pass-through
        self.mock_sp.resource.ResourceID.side_effect = lambda x: x

        # Clear out any pre-existing attributes on the mocked textureset
        self.mock_sp.textureset = MagicMock(spec=[])

        # Initialize controller AFTER patching so it uses the mocked substance_painter
        # (Though __init__ only does map init, it's safer)
        self.controller = PainterController(self.logger)

    def tearDown(self):
        self.patcher.stop()

    def test_assign_texture_global_set_channel_texture_resource(self):
        # Scenario 1: global set_channel_texture_resource available
        self.mock_sp.textureset.set_channel_texture_resource = MagicMock()
        channel_obj = MagicMock()

        result = self.controller.assign_texture_to_channel(channel_obj, "my_resource_id")

        self.assertTrue(result)
        self.mock_sp.textureset.set_channel_texture_resource.assert_called_once_with(channel_obj, "my_resource_id")

    def test_assign_texture_instance_method(self):
        # Scenario 2: global throws, instance method available
        self.mock_sp.textureset.set_channel_texture_resource = MagicMock(side_effect=Exception("API missing"))

        channel_obj = MagicMock(spec=['set_texture_resource'])
        channel_obj.set_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel_obj, "my_resource_id")

        self.assertTrue(result)
        channel_obj.set_texture_resource.assert_called_once_with("my_resource_id")

    def test_assign_texture_stack_method(self):
        # Scenario 3: global and instance fail, stack method available
        self.mock_sp.textureset.set_channel_texture_resource = MagicMock(side_effect=Exception("API missing"))

        channel_obj = MagicMock(spec=['stack'])
        stack_mock = MagicMock(spec=['set_channel_texture_resource'])
        stack_mock.set_channel_texture_resource = MagicMock()
        channel_obj.stack.return_value = stack_mock

        result = self.controller.assign_texture_to_channel(channel_obj, "my_resource_id")

        self.assertTrue(result)
        stack_mock.set_channel_texture_resource.assert_called_once_with(channel_obj, "my_resource_id")

    def test_assign_texture_module_fallback(self):
        # Scenario 4: all others fail, module fallback available
        # Ensure global set_channel_texture_resource is missing
        if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
            del self.mock_sp.textureset.set_channel_texture_resource

        # No instance methods, no stack method
        channel_obj = MagicMock(spec=[])

        self.mock_sp.textureset.set_channel_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel_obj, "my_resource_id")

        self.assertTrue(result)
        self.mock_sp.textureset.set_channel_resource.assert_called_once_with(channel_obj, "my_resource_id")

    def test_assign_texture_all_fail(self):
        # Scenario 5: nothing works
        if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
            del self.mock_sp.textureset.set_channel_texture_resource
        channel_obj = MagicMock(spec=[])

        result = self.controller.assign_texture_to_channel(channel_obj, "my_resource_id")

        self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()

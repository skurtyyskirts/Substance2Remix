import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# We need to mock substance_painter before importing painter_controller
import painter_controller
from painter_controller import PainterController

class TestPainterControllerAssignTexture(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.controller = PainterController(self.logger)

        # Reset the mock for each test
        painter_controller.substance_painter = MagicMock()
        painter_controller.substance_painter.textureset = MagicMock()
        painter_controller.substance_painter.resource = MagicMock()

        # Consistent resource ID mock
        painter_controller.substance_painter.resource.ResourceID = MagicMock(return_value="mocked_id")

    def test_assign_via_global_textureset_method(self):
        # 1. Try global set_channel_texture_resource if available
        channel = MagicMock()

        # Set up the first fallback
        painter_controller.substance_painter.textureset.set_channel_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        painter_controller.substance_painter.textureset.set_channel_texture_resource.assert_called_once_with(channel, "mocked_id")

    def test_assign_via_channel_instance_method(self):
        # 2. Instance methods on Channel
        channel = MagicMock()

        # Disable the first fallback
        del painter_controller.substance_painter.textureset.set_channel_texture_resource

        # Set up the second fallback
        channel.set_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        channel.set_texture_resource.assert_called_once_with("mocked_id")

    def test_assign_via_channel_instance_method_alternate(self):
        # 2. Instance methods on Channel (alternate method name)
        channel = MagicMock()

        # Disable the first fallback
        del painter_controller.substance_painter.textureset.set_channel_texture_resource

        # Set up one of the other allowed method names and delete the first one
        # Because we're using MagicMock, we need to explicitly delete the attributes we don't want to be found
        # before the one we're testing.
        del channel.set_texture_resource
        del channel.setTextureResource
        del channel.set_resource
        del channel.setResource
        channel.assign_texture = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        channel.assign_texture.assert_called_once_with("mocked_id")

    def test_assign_via_stack_method(self):
        # 3. Stack methods
        channel = MagicMock()
        stack = MagicMock()
        channel.stack = MagicMock(return_value=stack)

        # Disable previous fallbacks
        del painter_controller.substance_painter.textureset.set_channel_texture_resource
        for method_name in ['set_texture_resource', 'setTextureResource', 'set_resource', 'setResource', 'assign_texture', 'assignTexture']:
            delattr(channel, method_name)

        # Set up the third fallback
        stack.set_channel_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        stack.set_channel_texture_resource.assert_called_once_with(channel, "mocked_id")

    def test_assign_via_module_level_fallback(self):
        # 4. Module level fallbacks
        channel = MagicMock()

        # Disable previous fallbacks
        del painter_controller.substance_painter.textureset.set_channel_texture_resource
        for method_name in ['set_texture_resource', 'setTextureResource', 'set_resource', 'setResource', 'assign_texture', 'assignTexture']:
            delattr(channel, method_name)
        del channel.stack

        # Set up the fourth fallback
        painter_controller.substance_painter.textureset.set_channel_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        painter_controller.substance_painter.textureset.set_channel_resource.assert_called_once_with(channel, "mocked_id")

    def test_assign_fails_when_all_fallbacks_fail(self):
        channel = MagicMock()

        # Disable all fallbacks
        del painter_controller.substance_painter.textureset.set_channel_texture_resource
        for method_name in ['set_texture_resource', 'setTextureResource', 'set_resource', 'setResource', 'assign_texture', 'assignTexture']:
            delattr(channel, method_name)
        del channel.stack
        for method_name in ['set_channel_resource', 'set_channel_texture', 'set_channel_map']:
            delattr(painter_controller.substance_painter.textureset, method_name)

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertFalse(result)

    def test_exception_in_fallback_continues_to_next(self):
        channel = MagicMock()

        # Make the first fallback raise an exception
        painter_controller.substance_painter.textureset.set_channel_texture_resource = MagicMock(side_effect=Exception("Failed"))

        # Make the second fallback work
        channel.set_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        channel.set_texture_resource.assert_called_once_with("mocked_id")

    def test_coerce_to_resource_id_fallback(self):
        # Test what happens if substance_painter.resource.ResourceID is not available or raises
        del painter_controller.substance_painter.resource.ResourceID

        channel = MagicMock()
        painter_controller.substance_painter.textureset.set_channel_texture_resource = MagicMock()

        result = self.controller.assign_texture_to_channel(channel, "my_resource")

        self.assertTrue(result)
        # Should be called with the original string since coercion failed
        painter_controller.substance_painter.textureset.set_channel_texture_resource.assert_called_once_with(channel, "my_resource")

if __name__ == "__main__":
    unittest.main()

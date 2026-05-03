import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from painter_controller import PainterController

class TestAssignTextureToChannel(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.controller = PainterController(self.logger)

    def test_global_set_channel_texture_resource(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            mock_channel = MagicMock()
            mock_rid = "resource_id"

            # Setup global method to succeed
            mock_sp.textureset.set_channel_texture_resource = MagicMock()

            result = self.controller.assign_texture_to_channel(mock_channel, mock_rid)

            self.assertTrue(result)
            mock_sp.textureset.set_channel_texture_resource.assert_called_once()

    def test_instance_methods_fallback(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            mock_channel = MagicMock()
            mock_rid = "resource_id"

            # Remove global method to trigger fallback
            del mock_sp.textureset.set_channel_texture_resource

            # Setup channel instance method
            mock_channel.set_texture_resource = MagicMock()

            result = self.controller.assign_texture_to_channel(mock_channel, mock_rid)

            self.assertTrue(result)
            mock_channel.set_texture_resource.assert_called_once()

    def test_stack_methods_fallback(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            mock_channel = MagicMock()
            mock_rid = "resource_id"

            # Remove global and instance methods to trigger fallback
            del mock_sp.textureset.set_channel_texture_resource
            mock_channel.set_texture_resource = None
            mock_channel.setTextureResource = None
            mock_channel.set_resource = None
            mock_channel.setResource = None
            mock_channel.assign_texture = None
            mock_channel.assignTexture = None

            # Setup stack methods
            mock_stack = MagicMock()
            mock_stack.set_channel_texture_resource = MagicMock()
            mock_channel.stack.return_value = mock_stack

            result = self.controller.assign_texture_to_channel(mock_channel, mock_rid)

            self.assertTrue(result)
            mock_stack.set_channel_texture_resource.assert_called_once_with(mock_channel, self.controller._coerce_to_resource_id(mock_rid))

    def test_module_level_fallbacks(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            mock_channel = MagicMock()
            mock_rid = "resource_id"

            # Remove global, instance, and stack methods to trigger fallback
            del mock_sp.textureset.set_channel_texture_resource
            mock_channel.set_texture_resource = None
            mock_channel.setTextureResource = None
            mock_channel.set_resource = None
            mock_channel.setResource = None
            mock_channel.assign_texture = None
            mock_channel.assignTexture = None

            mock_channel.stack.side_effect = AttributeError("No stack")

            # Setup module level fallback
            mock_sp.textureset.set_channel_resource = MagicMock()

            result = self.controller.assign_texture_to_channel(mock_channel, mock_rid)

            self.assertTrue(result)
            mock_sp.textureset.set_channel_resource.assert_called_once()

    def test_all_fallbacks_fail(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            mock_channel = MagicMock()
            mock_rid = "resource_id"

            # Remove all fallback methods
            del mock_sp.textureset.set_channel_texture_resource
            mock_channel.set_texture_resource = None
            mock_channel.setTextureResource = None
            mock_channel.set_resource = None
            mock_channel.setResource = None
            mock_channel.assign_texture = None
            mock_channel.assignTexture = None

            mock_channel.stack.side_effect = AttributeError("No stack")

            mock_sp.textureset.set_channel_resource = None
            mock_sp.textureset.set_channel_texture = None
            mock_sp.textureset.set_channel_map = None

            result = self.controller.assign_texture_to_channel(mock_channel, mock_rid)

            self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from painter_controller import PainterController

class MockChannel:
    pass

class TestAssignTextureToChannel(unittest.TestCase):
    def setUp(self):
        self.controller = PainterController(logger=MagicMock())
        # Use a plain object to avoid auto-creating mock methods on hasattr
        self.channel_obj = MockChannel()

    def test_global_set_channel_texture_resource(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            result = self.controller.assign_texture_to_channel(self.channel_obj, "my_resource")
            self.assertTrue(result)
            mock_sp.textureset.set_channel_texture_resource.assert_called_once()

    def test_instance_method_fallback(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            # Force global hasattr check to fail
            del mock_sp.textureset.set_channel_texture_resource

            # Provide the instance method
            self.channel_obj.set_texture_resource = MagicMock()

            result = self.controller.assign_texture_to_channel(self.channel_obj, "my_resource")

            self.assertTrue(result)
            self.channel_obj.set_texture_resource.assert_called_once()

    def test_stack_method_fallback(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            del mock_sp.textureset.set_channel_texture_resource

            mock_stack = MagicMock()
            self.channel_obj.stack = MagicMock(return_value=mock_stack)

            result = self.controller.assign_texture_to_channel(self.channel_obj, "my_resource")

            self.assertTrue(result)
            mock_stack.set_channel_texture_resource.assert_called_once()

    def test_module_level_fallback(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            del mock_sp.textureset.set_channel_texture_resource
            # We don't have instance methods, no stack on channel_obj

            # Let's verify module level fallback works
            del mock_sp.textureset.set_channel_resource
            mock_sp.textureset.set_channel_texture = MagicMock()

            result = self.controller.assign_texture_to_channel(self.channel_obj, "my_resource")

            self.assertTrue(result)
            mock_sp.textureset.set_channel_texture.assert_called_once()

    def test_complete_failure(self):
        with patch('painter_controller.substance_painter') as mock_sp:
            del mock_sp.textureset.set_channel_texture_resource
            del mock_sp.textureset.set_channel_resource
            del mock_sp.textureset.set_channel_texture
            del mock_sp.textureset.set_channel_map

            result = self.controller.assign_texture_to_channel(self.channel_obj, "my_resource")

            self.assertFalse(result)

if __name__ == "__main__":
    unittest.main()

"""Tests for painter_controller.py — testing assign_texture_to_channel fallback logic."""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from painter_controller import PainterController

class TestAssignTextureToChannel(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self.controller = PainterController(logger=self.logger)

        # We need to ensure we can cleanly mock the module-level fallbacks.
        # So we'll patch substance_painter within the context of each test.
        self.patcher = patch('painter_controller.substance_painter')
        self.mock_sp = self.patcher.start()

        # Override _coerce_to_resource_id so we don't have to deal with ResourceID logic
        # and can just assert on the raw string.
        self.controller._coerce_to_resource_id = MagicMock(side_effect=lambda x: x)

    def tearDown(self):
        self.patcher.stop()

    def test_fallback_1_global_set_channel_texture_resource(self):
        """Test that fallback 1 is used when available."""
        # Setup mock for fallback 1
        self.mock_sp.textureset.set_channel_texture_resource = MagicMock()

        channel_object = MagicMock()
        resource_id = "test_resource"

        result = self.controller.assign_texture_to_channel(channel_object, resource_id)

        self.assertTrue(result)
        self.mock_sp.textureset.set_channel_texture_resource.assert_called_once_with(channel_object, resource_id)

    def test_fallback_2_instance_methods(self):
        """Test that fallback 2 is used when fallback 1 is unavailable."""
        resource_id = "test_resource"

        # Test each possible method name
        for method_name in ['set_texture_resource', 'setTextureResource', 'set_resource', 'setResource', 'assign_texture', 'assignTexture']:
            with self.subTest(method=method_name):
                # Ensure fallback 1 is removed for each subtest
                if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
                    delattr(self.mock_sp.textureset, 'set_channel_texture_resource')

                channel_object = MagicMock(spec=[method_name])
                mock_method = MagicMock()
                setattr(channel_object, method_name, mock_method)

                result = self.controller.assign_texture_to_channel(channel_object, resource_id)

                self.assertTrue(result)
                mock_method.assert_called_once_with(resource_id)

    def test_fallback_3_stack_methods(self):
        """Test that fallback 3 is used when fallbacks 1 and 2 are unavailable."""
        resource_id = "test_resource"

        # Test each possible stack method name
        for method_name in ['set_channel_texture_resource', 'setChannelTextureResource', 'assign_texture_to_channel']:
            with self.subTest(method=method_name):
                # Ensure fallback 1 is removed for each subtest
                if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
                    delattr(self.mock_sp.textureset, 'set_channel_texture_resource')

                channel_object = MagicMock(spec=['stack'])

                mock_stack = MagicMock(spec=[method_name])
                mock_method = MagicMock()
                setattr(mock_stack, method_name, mock_method)
                channel_object.stack.return_value = mock_stack

                result = self.controller.assign_texture_to_channel(channel_object, resource_id)

                self.assertTrue(result)
                mock_method.assert_called_once_with(channel_object, resource_id)

    def test_fallback_4_module_level_fallbacks(self):
        """Test that fallback 4 is used when fallbacks 1-3 are unavailable."""
        resource_id = "test_resource"

        for func_name in ['set_channel_resource', 'set_channel_texture', 'set_channel_map']:
            with self.subTest(func=func_name):
                # Clean slate for each subtest
                self.mock_sp.reset_mock()
                # Remove fallback 1
                if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
                    delattr(self.mock_sp.textureset, 'set_channel_texture_resource')

                # Use a plain object or carefully scoped mock so fallback 2 & 3 are fully absent
                class DummyChannel:
                    pass
                channel_object = DummyChannel()

                # Setup fallback 4
                mock_func = MagicMock()
                # Important: Mock the functions we don't want to hit to raise exceptions or not exist
                for other_func in ['set_channel_resource', 'set_channel_texture', 'set_channel_map']:
                    if hasattr(self.mock_sp.textureset, other_func):
                        delattr(self.mock_sp.textureset, other_func)
                setattr(self.mock_sp.textureset, func_name, mock_func)

                result = self.controller.assign_texture_to_channel(channel_object, resource_id)

                self.assertTrue(result)
                mock_func.assert_called_once_with(channel_object, resource_id)

    def test_exhaustion(self):
        """Test that exhaustion returns False."""
        if hasattr(self.mock_sp.textureset, 'set_channel_texture_resource'):
            delattr(self.mock_sp.textureset, 'set_channel_texture_resource')

        for other_func in ['set_channel_resource', 'set_channel_texture', 'set_channel_map']:
            if hasattr(self.mock_sp.textureset, other_func):
                delattr(self.mock_sp.textureset, other_func)

        class DummyChannel:
            pass
        channel_object = DummyChannel()

        result = self.controller.assign_texture_to_channel(channel_object, "test_resource")

        self.assertFalse(result)

if __name__ == '__main__':
    unittest.main()

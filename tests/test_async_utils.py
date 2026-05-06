import unittest
import sys
import os
import traceback
import builtins
from unittest.mock import MagicMock, patch

# Insert the parent directory of the app into sys.path to allow `import async_utils`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MockQObject:
    pass

class MockQRunnable:
    pass

class SignalDescriptor:
    def __init__(self, *args):
        self.args = args
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if not hasattr(obj, '_mock_signals'):
            obj._mock_signals = {}
        name = id(self)
        if name not in obj._mock_signals:
            obj._mock_signals[name] = MagicMock()
        return obj._mock_signals[name]

def MockSlot(*args):
    def decorator(func): return func
    return decorator

mock_qt = MagicMock()
mock_qt.QObject = MockQObject
mock_qt.QRunnable = MockQRunnable
mock_qt.Signal = SignalDescriptor
mock_qt.Slot = MockSlot

class TestAsyncUtils(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # We need to temporarily modify __import__ ONLY for this test suite
        # because the module uses a relative import `from .qt_utils` at the module level.
        # Following the memory instruction:
        # "temporarily override builtins.__import__ in the test setup to intercept the
        # specific relative import (e.g., checking name and level == 1) to return the mocked module,
        # then restore builtins.__import__."

        cls.original_import = builtins.__import__

        def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 1 and name == 'qt_utils':
                return mock_qt
            return cls.original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = custom_import

        # Clear out any existing cached version
        if 'async_utils' in sys.modules:
            del sys.modules['async_utils']

        import async_utils
        cls.async_utils = async_utils

    @classmethod
    def tearDownClass(cls):
        builtins.__import__ = cls.original_import

        # Clean up so we don't pollute subsequent tests
        if 'async_utils' in sys.modules:
            del sys.modules['async_utils']

    def test_worker_success(self):
        """Test happy path where worker completes successfully."""
        def success_fn():
            return "success_result"

        worker = self.async_utils.Worker(success_fn)
        worker.run()

        worker.signals.result.emit.assert_called_once_with("success_result")
        worker.signals.finished.emit.assert_called_once()
        worker.signals.error.emit.assert_not_called()

    def test_worker_error(self):
        """Test error path where worker crashes."""
        def crashing_fn():
            raise ValueError("Test error")

        worker = self.async_utils.Worker(crashing_fn)

        # Suppress traceback print
        with patch('traceback.print_exc') as mock_print_exc:
            worker.run()

        mock_print_exc.assert_called_once()
        worker.signals.error.emit.assert_called_once()

        # Check arguments emitted
        args = worker.signals.error.emit.call_args[0][0]
        self.assertEqual(args[0], ValueError)
        self.assertIsInstance(args[1], ValueError)
        self.assertEqual(str(args[1]), "Test error")
        self.assertIn("Test error", args[2])

        worker.signals.result.emit.assert_not_called()
        worker.signals.finished.emit.assert_called_once()

    def test_worker_callbacks(self):
        """Test that progress and status callbacks are injected when wanted."""
        def callback_fn(progress_callback=None, status_callback=None):
            if progress_callback:
                progress_callback.emit(50)
            if status_callback:
                status_callback.emit("Running")
            return True

        worker = self.async_utils.Worker(callback_fn)
        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

        worker.run()

        # Worker automatically passes its signals to the callbacks
        # Our callback_fn emits directly to them
        worker.signals.progress.emit.assert_called_once_with(50)
        worker.signals.status.emit.assert_called_once_with("Running")

        worker.signals.result.emit.assert_called_once_with(True)
        worker.signals.finished.emit.assert_called_once()

    def test_worker_kwargs(self):
        """Test that progress and status callbacks work with **kwargs."""
        def kwargs_fn(**kwargs):
            return "kwargs_result"

        worker = self.async_utils.Worker(kwargs_fn)
        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

        worker.run()
        self.assertIn('progress_callback', worker.kwargs)
        self.assertIn('status_callback', worker.kwargs)
        worker.signals.result.emit.assert_called_once_with("kwargs_result")

    def test_worker_init_signature_error(self):
        """Test init handles built-ins that don't support inspect.signature."""
        # By using standard len(), inspect.signature raises ValueError
        worker = self.async_utils.Worker(len, "test")
        self.assertFalse(worker._wants_progress)
        self.assertFalse(worker._wants_status)

        worker.run()
        worker.signals.result.emit.assert_called_once_with(4)
        worker.signals.finished.emit.assert_called_once()

    def test_worker_init_type_error(self):
        """Test init handles objects that raise TypeError on inspect.signature."""
        class NotCallable:
            pass

        worker = self.async_utils.Worker(NotCallable())
        self.assertFalse(worker._wants_progress)
        self.assertFalse(worker._wants_status)

    def test_worker_signal_emission_error(self):
        """Test worker handles exceptions when emitting signals."""
        def success_fn():
            return "success"

        worker = self.async_utils.Worker(success_fn)

        # Make result and finished emission crash
        worker.signals.result.emit.side_effect = Exception("Signal error")
        worker.signals.finished.emit.side_effect = Exception("Signal error")

        # Should not crash the runner
        worker.run()

    def test_worker_error_signal_emission_error(self):
        """Test worker handles exceptions when emitting error signals."""
        def crashing_fn():
            raise ValueError("Test error")

        worker = self.async_utils.Worker(crashing_fn)

        # Make error and finished emission crash
        worker.signals.error.emit.side_effect = Exception("Signal error")
        worker.signals.finished.emit.side_effect = Exception("Signal error")

        with patch('traceback.print_exc'):
            # Should not crash the runner
            worker.run()

if __name__ == '__main__':
    unittest.main()

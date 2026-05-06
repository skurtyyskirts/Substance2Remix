import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Need to intercept the relative import of qt_utils from async_utils
# as a MagicMock inside sys.modules doesn't always work properly for relative imports
orig_import = __import__

class MockSignal:
    def __init__(self, *args):
        self.emit = MagicMock()

def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "qt_utils" and level == 1:
        mock_qt_utils = MagicMock()
        mock_qt_utils.QObject = type("QObject", (), {})
        mock_qt_utils.QRunnable = type("QRunnable", (), {
            "__init__": lambda self: None
        })
        # Mock signal to return an object with an 'emit' method
        mock_qt_utils.Signal = lambda *args: MockSignal(*args)
        mock_qt_utils.Slot = lambda *args: lambda f: f
        return mock_qt_utils
    return orig_import(name, globals, locals, fromlist, level)

import builtins
builtins.__import__ = _mock_import

import async_utils
builtins.__import__ = orig_import


class TestWorkerSignals(unittest.TestCase):
    def test_signals_initialization(self):
        signals = async_utils.WorkerSignals()
        self.assertTrue(hasattr(signals, "finished"))
        self.assertTrue(hasattr(signals, "error"))
        self.assertTrue(hasattr(signals, "result"))
        self.assertTrue(hasattr(signals, "progress"))
        self.assertTrue(hasattr(signals, "status"))


class TestWorker(unittest.TestCase):
    def test_worker_init_no_callbacks(self):
        def my_func():
            pass

        worker = async_utils.Worker(my_func)
        self.assertFalse(worker._wants_progress)
        self.assertFalse(worker._wants_status)

    def test_worker_init_with_callbacks(self):
        def my_func(progress_callback, status_callback):
            pass

        worker = async_utils.Worker(my_func)
        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

    def test_worker_init_with_kwargs(self):
        def my_func(**kwargs):
            pass

        worker = async_utils.Worker(my_func)
        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

    def test_worker_init_exception_inspect(self):
        # Passing a built-in like print might fail inspect.signature in some python versions
        # or we can mock inspect.signature to raise TypeError
        with patch('inspect.signature', side_effect=TypeError):
            worker = async_utils.Worker(lambda: None)
            self.assertFalse(worker._wants_progress)
            self.assertFalse(worker._wants_status)

    def test_run_success(self):
        def my_func(a, b):
            return a + b

        worker = async_utils.Worker(my_func, 2, 3)
        worker.signals.result = MagicMock()
        worker.signals.finished = MagicMock()

        worker.run()

        worker.signals.result.emit.assert_called_once_with(5)
        worker.signals.finished.emit.assert_called_once()

    def test_run_success_with_callbacks(self):
        def my_func(progress_callback=None, status_callback=None):
            progress_callback.emit(50)
            status_callback.emit("halfway")
            return "done"

        worker = async_utils.Worker(my_func)
        worker.signals.result = MagicMock()
        worker.signals.finished = MagicMock()
        worker.signals.progress = MagicMock()
        worker.signals.status = MagicMock()

        worker.run()

        # Test that callbacks were successfully injected and used
        worker.signals.progress.emit.assert_called_once_with(50)
        worker.signals.status.emit.assert_called_once_with("halfway")
        worker.signals.result.emit.assert_called_once_with("done")
        worker.signals.finished.emit.assert_called_once()

    @patch('traceback.print_exc')
    def test_run_exception(self, mock_print_exc):
        def my_func():
            raise ValueError("Test error")

        worker = async_utils.Worker(my_func)
        worker.signals.error = MagicMock()
        worker.signals.finished = MagicMock()
        worker.signals.result = MagicMock()

        worker.run()

        mock_print_exc.assert_called_once()

        # Should emit error and finished, but not result
        worker.signals.error.emit.assert_called_once()
        args = worker.signals.error.emit.call_args[0][0]
        self.assertEqual(args[0], ValueError)
        self.assertIsInstance(args[1], ValueError)
        self.assertEqual(str(args[1]), "Test error")
        self.assertIn("Test error", args[2]) # trace string

        worker.signals.finished.emit.assert_called_once()
        worker.signals.result.emit.assert_not_called()

    @patch('traceback.print_exc')
    def test_run_exception_emit_error_fails(self, mock_print_exc):
        # Simulate signals.error.emit throwing an exception to hit line 76
        def my_func():
            raise ValueError("Test error")

        worker = async_utils.Worker(my_func)
        worker.signals.error = MagicMock()
        worker.signals.error.emit.side_effect = Exception("Emit error failed")
        worker.signals.finished = MagicMock()
        worker.signals.result = MagicMock()

        # Should catch the Exception and hit pass block on line 76
        worker.run()

    def test_run_success_emit_result_fails(self):
        # Simulate signals.result.emit throwing an exception to hit line 81
        def my_func():
            return "success"

        worker = async_utils.Worker(my_func)
        worker.signals.result = MagicMock()
        worker.signals.result.emit.side_effect = Exception("Emit result failed")
        worker.signals.finished = MagicMock()

        # Should catch the Exception and hit pass block on line 81
        worker.run()

    def test_run_emit_finished_fails(self):
        # Simulate signals.finished.emit throwing an exception to hit line 86
        def my_func():
            return "success"

        worker = async_utils.Worker(my_func)
        worker.signals.result = MagicMock()
        worker.signals.finished = MagicMock()
        worker.signals.finished.emit.side_effect = Exception("Emit finished failed")

        # Should catch the Exception and hit pass block on line 86
        worker.run()

if __name__ == "__main__":
    unittest.main()

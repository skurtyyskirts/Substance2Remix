import os
import sys
import unittest
from unittest.mock import patch, MagicMock
import types
import importlib.util

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Fully mock out Qt classes so we don't need a QApplication, avoiding segfaults.
mock_qt_utils = types.ModuleType("qt_utils")
mock_qt_utils.QObject = type("QObject", (object,), {})
mock_qt_utils.QRunnable = type("QRunnable", (object,), {})

class MockSignal:
    def __init__(self, *args):
        pass
    def connect(self, slot):
        pass
    def emit(self, *args, **kwargs):
        pass

mock_qt_utils.Signal = MockSignal
mock_qt_utils.Slot = lambda *args, **kwargs: lambda f: f

# Setup a fake package context so relative imports resolve without __import__ hacks
pkg = types.ModuleType("mock_pkg")
pkg.__path__ = []
sys.modules["mock_pkg"] = pkg
sys.modules["mock_pkg.qt_utils"] = mock_qt_utils

# Import async_utils as mock_pkg.async_utils
spec = importlib.util.spec_from_file_location(
    "mock_pkg.async_utils",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "async_utils.py")
)
async_utils = importlib.util.module_from_spec(spec)
sys.modules["mock_pkg.async_utils"] = async_utils
spec.loader.exec_module(async_utils)

# Also expose Worker into the test module's namespace for convenience
Worker = async_utils.Worker


class TestWorker(unittest.TestCase):
    def test_worker_success(self):
        def my_func(a, b):
            return a + b

        worker = Worker(my_func, 1, 2)

        results = []
        finished = []

        worker.signals.result.emit = lambda r: results.append(r)
        worker.signals.finished.emit = lambda: finished.append(True)

        worker.run()

        self.assertEqual(results, [3])
        self.assertEqual(finished, [True])

    def test_worker_with_callbacks(self):
        def my_func(progress_callback, status_callback, **kwargs):
            progress_callback.emit(50)
            status_callback.emit("Halfway")
            return "done"

        worker = Worker(my_func)
        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

        progress = []
        status = []
        worker.signals.progress.emit = lambda p: progress.append(p)
        worker.signals.status.emit = lambda s: status.append(s)

        worker.run()

        self.assertEqual(progress, [50])
        self.assertEqual(status, ["Halfway"])

    def test_worker_error(self):
        def my_func():
            raise ValueError("Test error")

        worker = Worker(my_func)

        errors = []
        worker.signals.error.emit = lambda e: errors.append(e)

        worker.run()

        self.assertEqual(len(errors), 1)
        exctype, value, tb = errors[0]
        self.assertEqual(exctype, ValueError)
        self.assertEqual(str(value), "Test error")
        self.assertIn("Traceback", tb)
        self.assertIn("Test error", tb)

    def test_worker_init_signature_error(self):
        def my_func():
            pass

        with patch('mock_pkg.async_utils.inspect.signature') as mock_sig:
            mock_sig.side_effect = ValueError("Mocked error")
            worker = Worker(my_func)

            self.assertFalse(worker._wants_progress)
            self.assertFalse(worker._wants_status)

    def test_worker_emit_exceptions(self):
        def my_func():
            return "ok"

        worker = Worker(my_func)

        def bad_result(*args, **kwargs):
            raise Exception("Result Emit Error")
        def bad_finished(*args, **kwargs):
            raise Exception("Finished Emit Error")

        worker.signals.result.emit = MagicMock(side_effect=bad_result)
        worker.signals.finished.emit = MagicMock(side_effect=bad_finished)

        worker.run()

        worker.signals.result.emit.assert_called_once_with("ok")
        worker.signals.finished.emit.assert_called_once()

    def test_worker_error_emit_exception(self):
        def my_func():
            raise ValueError("Failure")

        worker = Worker(my_func)

        def bad_error(*args, **kwargs):
            raise Exception("Error Emit Error")

        worker.signals.error.emit = MagicMock(side_effect=bad_error)

        worker.run()

        worker.signals.error.emit.assert_called_once()

if __name__ == "__main__":
    unittest.main()

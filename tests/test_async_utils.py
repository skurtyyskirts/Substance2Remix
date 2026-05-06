import unittest
import sys
from unittest.mock import MagicMock, patch
import builtins

class TestAsyncUtilsWorker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # We need to set up the environment for relative imports
        cls._original_import = builtins.__import__
        def _mock_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level == 1 and name == "qt_utils":
                return cls._original_import("qt_utils", globals, locals, fromlist, 0)
            return cls._original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = _mock_import
        try:
            # We must import Worker globally so the tests can use it
            global Worker
            from async_utils import Worker
        finally:
            builtins.__import__ = cls._original_import

    @patch('async_utils.traceback.print_exc')
    def test_worker_error_path(self, mock_print_exc):
        def crashing_fn():
            raise ValueError("Simulated crash")

        worker = Worker(crashing_fn)

        error_emitted = []
        result_emitted = []
        finished_emitted = []

        worker.signals.error.connect(lambda e: error_emitted.append(e))
        worker.signals.result.connect(lambda r: result_emitted.append(r))
        worker.signals.finished.connect(lambda: finished_emitted.append(True))

        worker.run()

        mock_print_exc.assert_called_once()

        self.assertEqual(len(error_emitted), 1)
        error_tuple = error_emitted[0]
        self.assertEqual(error_tuple[0], ValueError)
        self.assertIsInstance(error_tuple[1], ValueError)
        self.assertEqual(str(error_tuple[1]), "Simulated crash")
        self.assertIn("Simulated crash", error_tuple[2])

        self.assertEqual(len(result_emitted), 0)
        self.assertEqual(len(finished_emitted), 1)

    def test_worker_success_path(self):
        def success_fn():
            return "success_result"

        worker = Worker(success_fn)

        error_emitted = []
        result_emitted = []
        finished_emitted = []

        worker.signals.error.connect(lambda e: error_emitted.append(e))
        worker.signals.result.connect(lambda r: result_emitted.append(r))
        worker.signals.finished.connect(lambda: finished_emitted.append(True))

        worker.run()

        self.assertEqual(len(error_emitted), 0)
        self.assertEqual(len(result_emitted), 1)
        self.assertEqual(result_emitted[0], "success_result")
        self.assertEqual(len(finished_emitted), 1)

    def test_worker_progress_status_args(self):
        def progress_fn(progress_callback=None, status_callback=None):
            if progress_callback:
                progress_callback.emit(50)
            if status_callback:
                status_callback.emit("Running")
            return "done"

        worker = Worker(progress_fn)

        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

        progress_emitted = []
        status_emitted = []

        worker.signals.progress.connect(lambda p: progress_emitted.append(p))
        worker.signals.status.connect(lambda s: status_emitted.append(s))

        worker.run()

        self.assertEqual(len(progress_emitted), 1)
        self.assertEqual(progress_emitted[0], 50)

        self.assertEqual(len(status_emitted), 1)
        self.assertEqual(status_emitted[0], "Running")

    def test_worker_kwargs(self):
        def kwarg_fn(**kwargs):
            if 'progress_callback' in kwargs:
                kwargs['progress_callback'].emit(100)
            if 'status_callback' in kwargs:
                kwargs['status_callback'].emit("Complete")
            return "kwarg_done"

        worker = Worker(kwarg_fn)

        self.assertTrue(worker._wants_progress)
        self.assertTrue(worker._wants_status)

        progress_emitted = []
        status_emitted = []

        worker.signals.progress.connect(lambda p: progress_emitted.append(p))
        worker.signals.status.connect(lambda s: status_emitted.append(s))

        worker.run()

        self.assertEqual(len(progress_emitted), 1)
        self.assertEqual(progress_emitted[0], 100)

        self.assertEqual(len(status_emitted), 1)
        self.assertEqual(status_emitted[0], "Complete")

    def test_worker_init_exception(self):
        def dummy_fn():
            pass

        with patch('async_utils.inspect.signature', side_effect=TypeError("Simulated error")):
            worker = Worker(dummy_fn)
            self.assertFalse(worker._wants_progress)
            self.assertFalse(worker._wants_status)

    def test_worker_emit_exceptions(self):
        # We need to test the except Exception: pass blocks around emits
        # Because SignalInstance.emit is read-only in PySide6, we can mock
        # the entire signals object

        # 1. Test error.emit exception
        def crashing_fn():
            raise ValueError("Simulated crash")

        worker = Worker(crashing_fn)

        mock_signals = MagicMock()
        mock_signals.error.emit.side_effect = RuntimeError("Emit failed")
        worker.signals = mock_signals

        with patch('async_utils.traceback.print_exc'):
            worker.run()
            # Should silently pass the exception in emit
            mock_signals.error.emit.assert_called_once()

        # 2. Test result.emit exception
        def success_fn():
            return "success"

        worker = Worker(success_fn)

        mock_signals = MagicMock()
        mock_signals.result.emit.side_effect = RuntimeError("Emit failed")
        worker.signals = mock_signals

        worker.run()
        # Should silently pass the exception in emit
        mock_signals.result.emit.assert_called_once()

        # 3. Test finished.emit exception
        worker = Worker(success_fn)

        mock_signals = MagicMock()
        mock_signals.finished.emit.side_effect = RuntimeError("Emit failed")
        worker.signals = mock_signals

        worker.run()
        # Should silently pass the exception in emit
        mock_signals.finished.emit.assert_called_once()

if __name__ == '__main__':
    unittest.main()

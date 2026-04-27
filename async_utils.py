import traceback
import sys
import inspect
from .qt_utils import QObject, Signal, Slot, QRunnable


class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.
    finished: No data
    error:    tuple (exctype, value, traceback.format_exc())
    result:   object data returned from processing
    progress: int indicating % progress
    status:   str indicating status message
    """
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    status = Signal(str)


class Worker(QRunnable):
    """
    Worker thread runnable. Inherits from QRunnable to handle worker
    thread setup, signals and wrap-up.

    Important lifetime notes:
      * The signals QObject is created on whichever thread instantiates
        the Worker (expected to be the main/UI thread). When the worker
        emits from QThreadPool, signals are delivered via QueuedConnection
        to QObject receivers in the main thread, which is what we want.
      * Auto-delete is left at the QRunnable default (True) so the runtime
        deletes the runnable after run() returns; we still keep an
        external strong reference in the plugin to bridge the gap until
        the `finished` signal has been processed.
    """

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

        try:
            params = inspect.signature(fn).parameters
            self._wants_progress = (
                'progress_callback' in params
                or any(p.kind == p.VAR_KEYWORD for p in params.values())
            )
            self._wants_status = (
                'status_callback' in params
                or any(p.kind == p.VAR_KEYWORD for p in params.values())
            )
        except (TypeError, ValueError):
            self._wants_progress = False
            self._wants_status = False

    @Slot()
    def run(self):
        if self._wants_progress:
            self.kwargs['progress_callback'] = self.signals.progress
        if self._wants_status:
            self.kwargs['status_callback'] = self.signals.status

        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            try:
                self.signals.error.emit((exctype, value, traceback.format_exc()))
            except Exception:
                pass
        else:
            try:
                self.signals.result.emit(result)
            except Exception:
                pass
        finally:
            try:
                self.signals.finished.emit()
            except Exception:
                pass

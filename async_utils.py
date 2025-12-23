import traceback
import sys
import inspect
from .qt_utils import QObject, Signal, Slot, QRunnable

class WorkerSignals(QObject):
    """
    Defines the signals available from a running worker thread.
    Supported signals are:
    finished: No data
    error: tuple (exctype, value, traceback.format_exc())
    result: object data returned from processing
    progress: int indicating % progress
    status: str indicating status message
    """
    finished = Signal()
    error = Signal(tuple)
    result = Signal(object)
    progress = Signal(int)
    status = Signal(str)

class Worker(QRunnable):
    """
    Worker thread runnable.
    Inherits from QRunnable to handle worker thread setup, signals and wrap-up.
    """
    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """
        Initialise the runner function with passed args, kwargs.
        """
        # Inject callbacks if the function accepts them or **kwargs
        sig = inspect.signature(self.fn)
        params = sig.parameters
        
        if 'progress_callback' in params or any(p.kind == p.VAR_KEYWORD for p in params.values()):
            self.kwargs['progress_callback'] = self.signals.progress
        
        if 'status_callback' in params or any(p.kind == p.VAR_KEYWORD for p in params.values()):
            self.kwargs['status_callback'] = self.signals.status

        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()

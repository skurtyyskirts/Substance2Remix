import sys

# Initialize variables to None
QtWidgets = None
QtCore = None
QtGui = None
Signal = None
Slot = None
QThread = None
QObject = None
QRunnable = None
QThreadPool = None
QAction = None

QT_AVAILABLE = False
QT_BINDING = None

def _log_qt_info(message):
    print(f"[RemixConnector QtUtils] {message}")

try:
    from PySide6 import QtWidgets as QtW, QtCore as QtC, QtGui as QtG
    QtWidgets = QtW
    QtCore = QtC
    QtGui = QtG
    Signal = QtC.Signal
    Slot = QtC.Slot
    QThread = QtC.QThread
    QObject = QtC.QObject
    QRunnable = QtC.QRunnable
    QThreadPool = QtC.QThreadPool
    QAction = QtG.QAction
    QT_AVAILABLE = True
    QT_BINDING = "PySide6"
    _log_qt_info("Successfully initialized PySide6.")
except ImportError:
    try:
        from PySide2 import QtWidgets as QtW, QtCore as QtC, QtGui as QtG
        QtWidgets = QtW
        QtCore = QtC
        QtGui = QtG
        Signal = QtC.Signal
        Slot = QtC.Slot
        QThread = QtC.QThread
        QObject = QtC.QObject
        QRunnable = QtC.QRunnable
        QThreadPool = QtC.QThreadPool
        # PySide2 has QAction in QtWidgets usually
        QAction = QtW.QAction
        QT_AVAILABLE = True
        QT_BINDING = "PySide2"
        _log_qt_info("Successfully initialized PySide2.")
    except ImportError:
        try:
            from PyQt5 import QtWidgets as QtW, QtCore as QtC, QtGui as QtG
            QtWidgets = QtW
            QtCore = QtC
            QtGui = QtG
            Signal = QtC.pyqtSignal
            Slot = QtC.pyqtSlot
            QThread = QtC.QThread
            QObject = QtC.QObject
            QRunnable = QtC.QRunnable
            QThreadPool = QtC.QThreadPool
            QAction = QtW.QAction
            QT_AVAILABLE = True
            QT_BINDING = "PyQt5"
            _log_qt_info("Successfully initialized PyQt5.")
        except ImportError:
            _log_qt_info("CRITICAL: No compatible Qt binding found (PySide6, PySide2, PyQt5). UI will not work.")

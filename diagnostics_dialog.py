import os

from .plugin_info import PLUGIN_NAME
from .qt_utils import QtWidgets, QtCore, QtGui, QT_AVAILABLE


class DiagnosticsDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    def __init__(self, diagnostics_text: str, parent=None, log_file_path: str = None):
        if not QT_AVAILABLE:
            self._text = diagnostics_text
            return

        super().__init__(parent)
        self.setWindowTitle(f"{PLUGIN_NAME} - Diagnostics")
        self.setMinimumWidth(760)
        self.setMinimumHeight(520)
        self._log_file_path = log_file_path or ""

        layout = QtWidgets.QVBoxLayout(self)

        self.text_edit = QtWidgets.QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.text_edit.setPlainText(diagnostics_text or "")
        layout.addWidget(self.text_edit)

        btn_row = QtWidgets.QHBoxLayout()

        self.log_btn = QtWidgets.QPushButton("Open Log Folder")
        self.log_btn.setEnabled(bool(self._log_file_path))
        btn_row.addWidget(self.log_btn)
        btn_row.addStretch(1)

        self.copy_btn = QtWidgets.QPushButton("Copy to Clipboard")
        self.close_btn = QtWidgets.QPushButton("Close")

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        self.log_btn.clicked.connect(self._open_log_folder)
        self.copy_btn.clicked.connect(self._copy)
        self.close_btn.clicked.connect(self.accept)

    def _copy(self):
        try:
            cb = QtWidgets.QApplication.clipboard()
            if cb is not None:
                cb.setText(self.text_edit.toPlainText())
        except Exception:
            pass

    def _open_log_folder(self):
        try:
            folder = os.path.dirname(self._log_file_path)
            if folder:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
        except Exception:
            pass

    # PySide6 compatibility: callers use exec_() in some places.
    def exec_(self):  # noqa: N802
        try:
            return super().exec()
        except AttributeError:
            return super().exec_()

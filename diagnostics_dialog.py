from .qt_utils import QtWidgets, QtCore, QT_AVAILABLE


class DiagnosticsDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    def __init__(self, diagnostics_text: str, parent=None):
        if not QT_AVAILABLE:
            self._text = diagnostics_text
            return

        super().__init__(parent)
        self.setWindowTitle("RTX Remix Connector - Diagnostics")
        self.setMinimumWidth(760)
        self.setMinimumHeight(520)

        layout = QtWidgets.QVBoxLayout(self)

        self.text_edit = QtWidgets.QPlainTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.text_edit.setPlainText(diagnostics_text or "")
        layout.addWidget(self.text_edit)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)

        self.copy_btn = QtWidgets.QPushButton("Copy to Clipboard")
        self.close_btn = QtWidgets.QPushButton("Close")

        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.close_btn)
        layout.addLayout(btn_row)

        self.copy_btn.clicked.connect(self._copy)
        self.close_btn.clicked.connect(self.accept)

    def _copy(self):
        try:
            cb = QtWidgets.QApplication.clipboard()
            cb.setText(self.text_edit.toPlainText())
        except Exception:
            pass

    # PySide6 compatibility: core calls exec_() in some places.
    def exec_(self):  # noqa: N802
        try:
            return super().exec()
        except Exception:
            return super().exec_()



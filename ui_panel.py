"""Substance2Remix dock panel and icon."""
import os

from .plugin_info import PLUGIN_NAME
from .qt_utils import QtWidgets, QtCore, QtGui
from .remix_api import NORMAL_FORMAT_NAMES

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons", "substance2remix.svg")
PANEL_OBJECT_NAME = "Substance2RemixPanel"
POLL_INTERVAL_MS = 5000

_STATUS_COLORS = {True: "#5cb85c", False: "#d9534f", None: "#8a8a8a"}
_NO_PRESET = "(no preset)"


def plugin_icon():
    """The plugin icon; falls back to a drawn badge if the SVG can't load."""
    icon = QtGui.QIcon(ICON_PATH) if os.path.isfile(ICON_PATH) else QtGui.QIcon()
    # SVG icons report no fixed sizes; rendering one proves the svg plugin loaded.
    if not icon.isNull() and not icon.pixmap(32, 32).isNull():
        return icon
    pix = QtGui.QPixmap(32, 32)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor("#c8c8c8"), 2))
    p.drawRoundedRect(3, 3, 26, 26, 5, 5)
    p.drawText(pix.rect(), QtCore.Qt.AlignCenter, "S2R")
    p.end()
    return QtGui.QIcon(pix)


class RemixPanel(QtWidgets.QWidget):
    """Dock panel: connection + link status and the plugin's actions.

    ``handlers`` is the core module; its module-level ``handle_*`` functions
    wrap every action with error reporting.
    """

    def __init__(self, plugin, handlers, parent=None):
        super().__init__(parent)
        self._plugin = plugin
        self._handlers = handlers
        self.setObjectName(PANEL_OBJECT_NAME)
        self.setWindowTitle(PLUGIN_NAME)
        self.setWindowIcon(plugin_icon())

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Connection row
        conn_row = QtWidgets.QHBoxLayout()
        self._dot = QtWidgets.QLabel()
        self._dot.setFixedSize(10, 10)
        self._conn_label = QtWidgets.QLabel()
        self._conn_label.setWordWrap(True)
        refresh = QtWidgets.QToolButton()
        refresh.setText("↻")
        refresh.setToolTip("Check the connection to RTX Remix now")
        refresh.setAutoRaise(True)
        refresh.clicked.connect(self._plugin.refresh_connection)
        conn_row.addWidget(self._dot, 0, QtCore.Qt.AlignVCenter)
        conn_row.addWidget(self._conn_label, 1)
        conn_row.addWidget(refresh)
        root.addLayout(conn_row)

        # Link row
        link_box = QtWidgets.QGroupBox("Linked Remix material")
        link_layout = QtWidgets.QGridLayout(link_box)
        self._link_label = QtWidgets.QLabel()
        self._link_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._show_btn = QtWidgets.QToolButton()
        self._show_btn.setText("Show")
        self._show_btn.setToolTip("Select the linked material in RTX Remix")
        self._show_btn.clicked.connect(handlers.handle_select_in_remix)
        self._normals_label = QtWidgets.QLabel()
        self._normals_label.setStyleSheet("color:#888")
        link_layout.addWidget(self._link_label, 0, 0)
        link_layout.addWidget(self._show_btn, 0, 1)
        link_layout.addWidget(self._normals_label, 1, 0, 1, 2)
        link_layout.setColumnStretch(0, 1)
        root.addWidget(link_box)

        # Preset row: switching applies (and saves) the preset immediately.
        preset_row = QtWidgets.QHBoxLayout()
        preset_row.addWidget(QtWidgets.QLabel("Preset"))
        self._preset_combo = QtWidgets.QComboBox()
        self._preset_combo.setToolTip("Settings preset. Create and edit presets in Settings.")
        self._preset_combo.activated.connect(self._on_preset_chosen)
        preset_row.addWidget(self._preset_combo, 1)
        root.addLayout(preset_row)

        # Actions
        self._pull_btn = self._action_button(
            "Pull from Remix", handlers.handle_pull_from_remix,
            "Create a Painter project from the mesh and material selected in RTX Remix.")
        self._import_btn = self._action_button(
            "Import Textures", handlers.handle_import_textures,
            "Add the linked material's Remix textures as a new fill layer.")
        self._push_btn = self._action_button(
            "Push to Remix", handlers.handle_push_to_remix,
            "Export, ingest and assign this project's textures to the linked Remix material.")
        self._push_btn.setDefault(True)
        self._force_btn = self._action_button(
            "Force Push to Selected Material", handlers.handle_relink_and_push_to_remix,
            "Relink to the material selected in Remix and push under new file names (never overwrites earlier ingests).")
        self._link_btn = self._action_button(
            "Link to Selected Material", handlers.handle_link_to_selection,
            "Link this project to the material selected in Remix without pushing.")
        self._channels_btn = self._action_button(
            "Add Remix Channels", handlers.handle_add_channels,
            "Add the Painter channels for every map switched on in Settings > Texture Maps "
            "(anisotropy, subsurface, ...) to the active texture set.")
        for btn in (self._pull_btn, self._import_btn, self._push_btn, self._force_btn, self._link_btn,
                    self._channels_btn):
            root.addWidget(btn)

        self._op_label = QtWidgets.QLabel()
        self._op_label.setWordWrap(True)
        self._op_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(self._op_label)
        root.addStretch(1)

        footer = QtWidgets.QHBoxLayout()
        settings_btn = QtWidgets.QPushButton("Settings...")
        settings_btn.clicked.connect(handlers.handle_settings)
        diag_btn = QtWidgets.QPushButton("Diagnostics...")
        diag_btn.clicked.connect(handlers.handle_diagnostics)
        footer.addWidget(settings_btn)
        footer.addWidget(diag_btn)
        root.addLayout(footer)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        plugin.state_changed.connect(self.refresh)
        self.refresh()

    def _action_button(self, text, handler, tooltip):
        btn = QtWidgets.QPushButton(text)
        btn.setToolTip(tooltip)
        btn.clicked.connect(handler)
        return btn

    def _poll(self):
        # Only poll while someone can see the result, and never during an operation.
        if self.isVisible() and not self._plugin.current_operation:
            self._plugin.refresh_connection()

    def _on_preset_chosen(self, index):
        name = self._preset_combo.itemData(index) or ""
        if name == self._plugin.active_preset():
            return
        if not name:
            self._plugin.update_settings({"active_preset": ""})
            return
        active = self._plugin.active_preset()
        if self._plugin.preset_modified():
            question = f"Your settings have changes that aren't saved in '{active}'. Load '{name}' anyway?"
        elif not active:
            question = f"Load preset '{name}'? It replaces your current workflow settings."
        else:
            question = None
        Box = QtWidgets.QMessageBox
        if question and Box.question(self, PLUGIN_NAME, question, Box.Yes | Box.No, Box.No) != Box.Yes:
            self.refresh()
            return
        try:
            self._plugin.apply_preset(name)
        except Exception as e:
            self._plugin.show_error("Preset", str(e))

    def _refresh_presets(self):
        active = self._plugin.active_preset()
        modified = self._plugin.preset_modified()
        self._preset_combo.blockSignals(True)
        self._preset_combo.clear()
        self._preset_combo.addItem(_NO_PRESET, "")
        for name in self._plugin.preset_names():
            self._preset_combo.addItem(f"{name} (modified)" if name == active and modified else name, name)
        idx = self._preset_combo.findData(active)
        self._preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._preset_combo.blockSignals(False)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._poll()

    def stop(self):
        self._timer.stop()
        try:
            self._plugin.state_changed.disconnect(self.refresh)
        except Exception:
            pass

    def refresh(self):
        state = self._plugin.connection_state()
        ok = state.get("ok")
        self._dot.setStyleSheet(f"background-color: {_STATUS_COLORS.get(ok)}; border-radius: 5px;")
        self._conn_label.setText(state.get("message") or "")
        self._conn_label.setToolTip(state.get("message") or "")

        project_open = self._plugin.painter_controller.is_project_open()
        link = self._plugin.read_link() if project_open else None
        if link:
            self._link_label.setText(link["material_prim"].rsplit("/", 1)[-1])
            self._link_label.setToolTip(link["material_prim"])
        else:
            self._link_label.setText("No project open" if not project_open else "Not linked")
            self._link_label.setToolTip("")
        if project_open:
            fmt = NORMAL_FORMAT_NAMES[self._plugin.project_normal_format(link or {})]
            recorded = (link or {}).get("normal_format") in NORMAL_FORMAT_NAMES
            tooltip = (f"Pushes export the normal map as {fmt} and tell Remix it is {fmt}; "
                       f"imports convert Remix normals to {fmt}.")
            if not recorded:
                # Painter's API can't report a project's normal format; only Pull records it.
                tooltip += ("\n\nThis project wasn't created by Pull, so the convention comes from "
                            "Settings > Project > Normal Map Format. Pushes are correct either way; for "
                            "imports, set it to match the project's normal map format.")
            self._normals_label.setText(f"Normals: {fmt}" + ("" if recorded else " (from Settings)"))
            self._normals_label.setToolTip(tooltip)
        else:
            self._normals_label.setText("")
        self._refresh_presets()

        busy = self._plugin.current_operation
        # Painter has no notification API: the last result lives here.
        self._op_label.setText(f"Running: {busy}..." if busy else self._plugin.last_message)
        self._pull_btn.setEnabled(not busy)
        self._preset_combo.setEnabled(not busy)
        for btn in (self._import_btn, self._push_btn, self._show_btn):
            btn.setEnabled(not busy and bool(link))
        for btn in (self._force_btn, self._link_btn, self._channels_btn):
            btn.setEnabled(not busy and project_open)

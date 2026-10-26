from typing import Dict

from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION
from .qt_utils import QtWidgets, QtCore, QT_AVAILABLE
from .settings_schema import TEXTURE_RESOLUTIONS, NORMAL_MAP_FORMATS, POLL_TIMEOUT_RANGE

_NORMAL_FORMAT_LABELS = {"opengl": "OpenGL (Painter default)", "directx": "DirectX"}
# Coalesces bursts of edits (spin box arrows, typing) into one save.
_SAVE_DELAY_MS = 300


class SettingsDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    """Settings that save themselves: every change is written as it's made.

    Only what Painter and RTX Remix don't already control lives here: the
    Remix address, what Pull uses in place of Painter's New Project dialog,
    how pushes land in the Remix project, and the optional Blender re-unwrap.

    ``controller`` owns the settings (RemixConnectorPlugin in Painter). It
    needs ``settings``, ``update_settings(values)`` and ``reset_settings()``;
    both methods return the new settings dict.
    """

    def __init__(self, controller, parent=None):
        self._controller = controller
        if not QT_AVAILABLE:
            return

        super().__init__(parent)
        self.setWindowTitle(f"{PLUGIN_NAME} - Settings")
        self.setMinimumWidth(640)

        self._settings = dict(controller.settings)
        self._loading = False

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._commit)

        root = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(f"<b>{PLUGIN_NAME}</b> <span style='color:#888'>v{PLUGIN_VERSION}</span>")
        root.addWidget(header)

        self.tabs = QtWidgets.QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self._build_tab_general()
        self._build_tab_push()
        self._build_tab_blender()
        self._build_tab_advanced()

        footer = QtWidgets.QHBoxLayout()
        self.reset_btn = QtWidgets.QPushButton("Restore Defaults")
        self.reset_btn.setToolTip("Reset every setting to its default.")
        self.saved_label = QtWidgets.QLabel("Changes are saved automatically.")
        self.saved_label.setStyleSheet("color:#888")
        self.close_btn = QtWidgets.QPushButton("Close")
        self.close_btn.setDefault(True)
        footer.addWidget(self.reset_btn)
        footer.addStretch(1)
        footer.addWidget(self.saved_label)
        footer.addSpacing(12)
        footer.addWidget(self.close_btn)
        root.addLayout(footer)
        self.reset_btn.clicked.connect(self._reset_defaults)
        self.close_btn.clicked.connect(self.accept)

        self._load_fields(self._settings)

    # --- helpers ---
    def _confirm(self, title, text):
        Box = QtWidgets.QMessageBox
        return Box.question(self, f"{PLUGIN_NAME} - {title}", text, Box.Yes | Box.No, Box.No) == Box.Yes

    # --- tab builders ---
    def _build_tab_general(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.api_base_url = QtWidgets.QLineEdit()
        self.api_base_url.setPlaceholderText("http://localhost:8011")
        self.api_base_url.setToolTip("RTX Remix Toolkit REST API address (port 8011 by default). "
                                     "The panel's status dot shows whether Painter can reach it.")
        layout.addRow("RTX Remix Address", self.api_base_url)

        pull = QtWidgets.QLabel("<b>Pull</b> <span style='color:#888'>(what Painter's New Project dialog would ask)</span>")
        layout.addRow(pull)

        self.import_template = QtWidgets.QLineEdit()
        self.import_template.setPlaceholderText("Default: PBR - Metallic Roughness Alpha-blend (with the RTX Remix preview shader)")
        self.import_template.setToolTip(
            "Project template (.spt) for pulled projects. With the default template the project uses the RTX Remix "
            "preview shader; a template of your own keeps its shader.")
        layout.addRow("Template", self._with_browse(self.import_template, "Select project template",
                                                    "Painter template (*.spt);;All Files (*)"))

        self.normal_format = QtWidgets.QComboBox()
        for fmt in NORMAL_MAP_FORMATS:
            self.normal_format.addItem(_NORMAL_FORMAT_LABELS[fmt], fmt)
        self.normal_format.setToolTip(
            "Normal map format of pulled projects. A project keeps the format it was created with: pushes "
            "export its normal map in that format and tell Remix which one it is.")
        layout.addRow("Normal Map Format", self.normal_format)

        self.resolution = QtWidgets.QComboBox()
        for res in TEXTURE_RESOLUTIONS:
            self.resolution.addItem(str(res), res)
        self.resolution.setToolTip("Starting texture set resolution. Pull raises it to the source texture's size and "
                                   "matches its aspect ratio; change it later in Texture Set Settings as usual.")
        layout.addRow("Starting Resolution", self.resolution)

        self.auto_import = QtWidgets.QCheckBox("Import the material's Remix textures")
        self.auto_import.setToolTip("Adds the Remix textures as a fill layer right after the project is created.")
        layout.addRow(self.auto_import)

        self.use_simple_mesh = QtWidgets.QCheckBox("Use a tiling plane instead of the selected mesh")
        self.use_simple_mesh.setToolTip("For authoring tiling materials: the project uses a flat plane mesh.")
        layout.addRow(self.use_simple_mesh)

        self.simple_mesh_path = QtWidgets.QLineEdit()
        self.simple_mesh_path.setToolTip("Mesh used for tiling pulls (relative to the plugin folder, or absolute).")
        layout.addRow("Tiling Mesh", self._with_browse(self.simple_mesh_path, "Select mesh file",
                                                       "Mesh (*.usd *.usda *.usdc *.fbx *.obj *.gltf *.glb);;All Files (*)"))

        self._watch(self.api_base_url, self.import_template, self.normal_format, self.resolution,
                    self.auto_import, self.use_simple_mesh, self.simple_mesh_path)
        self.tabs.addTab(w, "General")

    def _build_tab_push(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        intro = QtWidgets.QLabel(
            "Push sends every Remix map whose channel exists in the texture set. Whether Remix uses a map "
            "(emission, opacity, displacement strength) is set on the Remix material.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#888")
        layout.addRow(intro)

        self.restore_aspect = QtWidgets.QCheckBox("Restore the source texture's aspect ratio")
        self.restore_aspect.setToolTip("Painter texture sets are powers of two. When the material's original Remix "
                                       "texture isn't (e.g. 768x1024), pushed textures are resized back to its ratio.")
        layout.addRow(self.restore_aspect)

        self.remix_output_subfolder = QtWidgets.QLineEdit()
        self.remix_output_subfolder.setToolTip("Folder, inside the Remix project's ingest folder, that receives pushed textures.")
        layout.addRow("Remix Output Subfolder", self.remix_output_subfolder)

        self._watch(self.restore_aspect, self.remix_output_subfolder)
        self.tabs.addTab(w, "Push")

    def _build_tab_blender(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.auto_unwrap = QtWidgets.QCheckBox("Re-unwrap pulled meshes with Blender (Smart UV Project)")
        self.auto_unwrap.setToolTip("For captures with unusable UVs. The new UVs won't match the mesh in Remix, so pushed "
                                    "textures only line up after you replace that mesh in Remix.")
        layout.addRow(self.auto_unwrap)

        self.blender_exe = QtWidgets.QLineEdit()
        self.blender_exe.setToolTip("blender.exe. Found automatically when Blender is installed in the usual place.")
        layout.addRow("Blender", self._with_browse(self.blender_exe, "Select blender.exe",
                                                   "blender.exe (*.exe);;All Files (*)"))

        self.uv_angle = QtWidgets.QDoubleSpinBox()
        self.uv_angle.setRange(0.0, 89.0)
        self.uv_angle.setDecimals(1)
        self.uv_angle.setSuffix("°")
        layout.addRow("Angle Limit", self.uv_angle)

        self.uv_margin = QtWidgets.QDoubleSpinBox()
        self.uv_margin.setRange(0.0, 1.0)
        self.uv_margin.setDecimals(4)
        self.uv_margin.setSingleStep(0.0005)
        layout.addRow("Island Margin", self.uv_margin)

        self.uv_area = QtWidgets.QDoubleSpinBox()
        self.uv_area.setRange(0.0, 10.0)
        self.uv_area.setDecimals(3)
        layout.addRow("Area Weight", self.uv_area)

        self.uv_stretch = QtWidgets.QCheckBox("Stretch to Bounds")
        layout.addRow(self.uv_stretch)

        self._watch(self.auto_unwrap, self.blender_exe, self.uv_angle, self.uv_margin, self.uv_area, self.uv_stretch)
        self.tabs.addTab(w, "Blender")

    def _build_tab_advanced(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.poll_timeout = QtWidgets.QDoubleSpinBox()
        self.poll_timeout.setRange(*POLL_TIMEOUT_RANGE)
        self.poll_timeout.setDecimals(1)
        self.poll_timeout.setSingleStep(0.5)
        self.poll_timeout.setSuffix(" s")
        self.poll_timeout.setToolTip("Timeout for Remix API calls (texture ingestion has its own, longer timeout).")
        layout.addRow("Request Timeout", self.poll_timeout)

        self.log_level = QtWidgets.QComboBox()
        self.log_level.addItems(["debug", "info", "warning", "error"])
        self.log_level.setToolTip("Detail of the plugin log (Substance2Remix > Open Log Folder).")
        layout.addRow("Log Level", self.log_level)

        self._watch(self.poll_timeout, self.log_level)
        self.tabs.addTab(w, "Advanced")

    # --- widgets ---
    def _watch(self, *widgets):
        """Save when any of ``widgets`` changes. Text fields save when editing
        finishes, so a half-typed path or URL is never written."""
        for widget in widgets:
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.editingFinished.connect(self._changed)
            elif isinstance(widget, QtWidgets.QAbstractButton):
                widget.toggled.connect(self._changed)
            elif isinstance(widget, QtWidgets.QComboBox):
                widget.currentIndexChanged.connect(self._changed)
            elif isinstance(widget, QtWidgets.QAbstractSpinBox):
                widget.valueChanged.connect(self._changed)

    def _with_browse(self, line_edit: QtWidgets.QLineEdit, title: str, filter: str = ""):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        btn = QtWidgets.QPushButton("Browse...")
        row.addWidget(line_edit, 1)
        row.addWidget(btn)

        def _browse():
            try:
                path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, line_edit.text() or "", filter)
                if path:
                    line_edit.setText(path)
                    self._changed()
            except Exception:
                pass

        btn.clicked.connect(_browse)
        host = QtWidgets.QWidget(self)
        host.setLayout(row)
        return host

    @staticmethod
    def _select_data(combo, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _select_text(combo, value):
        idx = combo.findText(str(value).lower())
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _load_fields(self, s: Dict):
        self._loading = True
        try:
            self.api_base_url.setText(s.get("api_base_url", ""))
            self.import_template.setText(s.get("painter_import_template_path", ""))
            self._select_data(self.normal_format, s.get("normal_map_format", "opengl"))
            self._select_data(self.resolution, int(s.get("project_texture_resolution", 2048)))
            self.auto_import.setChecked(bool(s.get("auto_import_textures_on_pull", True)))
            self.use_simple_mesh.setChecked(bool(s.get("use_simple_tiling_mesh_on_pull", False)))
            self.simple_mesh_path.setText(s.get("simple_tiling_mesh_path", ""))

            self.restore_aspect.setChecked(bool(s.get("restore_original_aspect_ratio_on_export", True)))
            self.remix_output_subfolder.setText(s.get("remix_output_subfolder", ""))

            self.auto_unwrap.setChecked(bool(s.get("auto_unwrap_with_blender_on_pull", False)))
            self.blender_exe.setText(s.get("blender_executable_path", ""))
            self.uv_angle.setValue(float(s.get("blender_smart_uv_angle_limit", 66.0)))
            self.uv_margin.setValue(float(s.get("blender_smart_uv_island_margin", 0.003)))
            self.uv_area.setValue(float(s.get("blender_smart_uv_area_weight", 0.0)))
            self.uv_stretch.setChecked(bool(s.get("blender_smart_uv_stretch_to_bounds", False)))

            self.poll_timeout.setValue(float(s.get("poll_timeout", 60.0)))
            self._select_text(self.log_level, s.get("log_level", "info"))
        finally:
            self._loading = False

    def _gather(self) -> Dict:
        """The values this dialog edits (merged into the settings on save)."""
        return {
            "api_base_url": self.api_base_url.text().strip(),
            "painter_import_template_path": self.import_template.text().strip(),
            "normal_map_format": self.normal_format.currentData(),
            "project_texture_resolution": int(self.resolution.currentData()),
            "auto_import_textures_on_pull": bool(self.auto_import.isChecked()),
            "use_simple_tiling_mesh_on_pull": bool(self.use_simple_mesh.isChecked()),
            "simple_tiling_mesh_path": self.simple_mesh_path.text().strip(),

            "restore_original_aspect_ratio_on_export": bool(self.restore_aspect.isChecked()),
            "remix_output_subfolder": self.remix_output_subfolder.text().strip(),

            "auto_unwrap_with_blender_on_pull": bool(self.auto_unwrap.isChecked()),
            "blender_executable_path": self.blender_exe.text().strip(),
            "blender_smart_uv_angle_limit": float(self.uv_angle.value()),
            "blender_smart_uv_island_margin": float(self.uv_margin.value()),
            "blender_smart_uv_area_weight": float(self.uv_area.value()),
            "blender_smart_uv_stretch_to_bounds": bool(self.uv_stretch.isChecked()),

            "poll_timeout": float(self.poll_timeout.value()),
            "log_level": self.log_level.currentText().strip().lower(),
        }

    # --- autosave ---
    def _changed(self, *_):
        if not self._loading:
            self._save_timer.start()

    def _commit(self):
        self._save_timer.stop()
        self._settings = self._controller.update_settings(self._gather())
        self._show_saved("Saved.")

    def _show_saved(self, text):
        self.saved_label.setText(text)
        # The label is the timer's context, so Qt drops the timer if the dialog is deleted first.
        label = self.saved_label
        QtCore.QTimer.singleShot(2500, label, lambda: label.setText("Changes are saved automatically."))

    def _reset_defaults(self):
        if not self._confirm("Restore Defaults", "Reset every setting to its default?"):
            return
        self._save_timer.stop()
        self._settings = self._controller.reset_settings()
        self._load_fields(self._settings)
        self._show_saved("Defaults restored.")

    def done(self, result):  # noqa: D401 - Qt override
        # Closing with the window button skips editingFinished; save what's there.
        if not self._loading:
            gathered = self._gather()
            if self._save_timer.isActive() or any(self._settings.get(k) != v for k, v in gathered.items()):
                self._commit()
        super().done(result)

    def get_settings(self) -> Dict:
        return dict(self._settings)

    # PySide6 compatibility
    def exec_(self):  # noqa: N802
        try:
            return super().exec()
        except AttributeError:
            return super().exec_()


def create_settings_dialog_instance(controller, parent=None):
    return SettingsDialog(controller, parent=parent)

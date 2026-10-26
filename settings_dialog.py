import os
from typing import Callable, Dict, Optional, Tuple

from .pbr_maps import MAPS_BY_KEY, PBR_MAPS, OPACITY
from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION
from .qt_utils import QtWidgets, QtCore, QtGui, QT_AVAILABLE
from .settings_schema import TEXTURE_RESOLUTIONS, NORMAL_MAP_FORMATS, EXPORT_FORMATS, POLL_TIMEOUT_RANGE

TestConnectionFn = Callable[[Dict], Tuple[bool, str]]

_NORMAL_FORMAT_LABELS = {"opengl": "OpenGL (Painter default)", "directx": "DirectX"}
# Coalesces bursts of edits (spin box arrows, typing) into one save.
_SAVE_DELAY_MS = 300


class SettingsDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    """Settings that save themselves: every change is written as it's made.

    ``controller`` owns the settings (RemixConnectorPlugin in Painter). It
    needs ``settings``, ``update_settings(values)`` and ``reset_settings()``;
    both methods return the new settings dict.
    """

    def __init__(
        self,
        controller,
        parent=None,
        test_connection_fn: Optional[TestConnectionFn] = None,
        log_file_path: Optional[str] = None,
        add_channels_fn: Optional[Callable[[], None]] = None,
    ):
        self._controller = controller
        if not QT_AVAILABLE:
            return

        super().__init__(parent)
        self.setWindowTitle(f"{PLUGIN_NAME} - Settings")
        self.setMinimumWidth(720)

        self._test_connection_fn = test_connection_fn
        self._add_channels_fn = add_channels_fn
        self._log_file_path = log_file_path or ""
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

        self._build_tab_connection()
        self._build_tab_project()
        self._build_tab_maps()
        self._build_tab_export()
        self._build_tab_paths()
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
    def _build_tab_connection(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.api_base_url = QtWidgets.QLineEdit()
        self.api_base_url.setPlaceholderText("http://localhost:8011")
        self.api_base_url.setToolTip("RTX Remix Toolkit REST API address. The Toolkit serves it on port 8011 by default.")

        self.poll_timeout = QtWidgets.QDoubleSpinBox()
        self.poll_timeout.setRange(*POLL_TIMEOUT_RANGE)
        self.poll_timeout.setDecimals(1)
        self.poll_timeout.setSingleStep(0.5)
        self.poll_timeout.setSuffix(" s")
        self.poll_timeout.setToolTip("Timeout for Remix API calls (texture ingestion has its own, longer timeout).")

        layout.addRow("API Address", self.api_base_url)
        layout.addRow("Request Timeout", self.poll_timeout)

        test_row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Test Connection")
        self.test_result = QtWidgets.QLabel("")
        self.test_result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        layout.addRow("", test_row)
        self.test_btn.clicked.connect(self._test_connection)

        self._watch(self.api_base_url, self.poll_timeout)
        self.tabs.addTab(w, "Connection")

    def _build_tab_project(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.auto_import = QtWidgets.QCheckBox("Import the material's Remix textures after Pull")
        self.auto_import.setToolTip("Adds the Remix textures as a fill layer right after the project is created.")
        layout.addRow(self.auto_import)

        self.resolution = QtWidgets.QComboBox()
        for res in TEXTURE_RESOLUTIONS:
            self.resolution.addItem(str(res), res)
        self.resolution.setToolTip("Texture set resolution for new projects. Imported textures never get a lower "
                                   "resolution than their source, and non-square sources keep their aspect ratio.")
        layout.addRow("Texture Resolution", self.resolution)

        self.normal_format = QtWidgets.QComboBox()
        for fmt in NORMAL_MAP_FORMATS:
            self.normal_format.addItem(_NORMAL_FORMAT_LABELS[fmt], fmt)
        self.normal_format.setToolTip(
            "Normal map convention for projects created by Pull. A project keeps the convention it was "
            "created with: pushes export its normal map in that convention and tell Remix which one it is, "
            "and imports convert Remix normals to it.")
        layout.addRow("Normal Map Format", self.normal_format)

        self.import_template = QtWidgets.QLineEdit()
        self.import_template.setPlaceholderText("Default: PBR - Metallic Roughness Alpha-blend")
        self.import_template.setToolTip("Optional Painter project template (.spt) for new projects.")
        layout.addRow("Project Template", self._with_browse(self.import_template, mode="file", title="Select project template", filter="Painter template (*.spt);;All Files (*)"))

        self.use_simple_mesh = QtWidgets.QCheckBox("Pull onto a tiling plane instead of the selected mesh")
        self.use_simple_mesh.setToolTip("For authoring tiling materials: the project uses a flat plane mesh.")
        layout.addRow(self.use_simple_mesh)

        self.simple_mesh_path = QtWidgets.QLineEdit()
        self.simple_mesh_path.setToolTip("Mesh used for tiling pulls (relative to the plugin folder, or absolute).")
        layout.addRow("Tiling Mesh", self._with_browse(self.simple_mesh_path, mode="file", title="Select mesh file", filter="Mesh (*.usd *.usda *.usdc *.fbx *.obj *.gltf *.glb);;All Files (*)"))

        self.auto_unwrap = QtWidgets.QCheckBox("Re-unwrap pulled meshes with Blender (Smart UV Project)")
        self.auto_unwrap.setToolTip("For captures with unusable UVs. The new UVs won't match the mesh in Remix, so pushed "
                                    "textures only line up after you replace that mesh in Remix.")
        layout.addRow(self.auto_unwrap)

        self._watch(self.auto_import, self.resolution, self.normal_format, self.import_template,
                    self.use_simple_mesh, self.simple_mesh_path, self.auto_unwrap)
        self.tabs.addTab(w, "Project")

    def _build_tab_maps(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(w)
        intro = QtWidgets.QLabel(
            "The RTX Remix texture maps that Push and Import include. A map is pushed only when its "
            "Painter channel exists in the texture set; Import adds missing channels.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.map_checks = {}

        def add_group(title, keys):
            box = QtWidgets.QGroupBox(title)
            grid = QtWidgets.QGridLayout(box)
            grid.setColumnStretch(1, 1)
            for row, key in enumerate(keys):
                if key == OPACITY:
                    label, channel, indent = "Opacity (in the albedo alpha)", "Opacity", 20
                else:
                    m = MAPS_BY_KEY[key]
                    label, channel, indent = m.label, m.painter_label, 0
                check = QtWidgets.QCheckBox(label)
                check.setStyleSheet(f"margin-left:{indent}px" if indent else "")
                source = QtWidgets.QLabel(channel)
                source.setStyleSheet("color:#888")
                grid.addWidget(check, row, 0)
                grid.addWidget(source, row, 1)
                self.map_checks[key] = check
            layout.addWidget(box)

        standard = [m.key for m in PBR_MAPS if not m.dds]
        standard.insert(standard.index("albedo") + 1, OPACITY)
        add_group("Standard maps", standard)
        add_group("AperturePBR extras (anisotropy and subsurface)", [m.key for m in PBR_MAPS if m.dds])

        note = QtWidgets.QLabel(
            "Anisotropy: Painter's level maps onto Remix's positive range (0 = isotropic). "
            "Subsurface thickness values pass through unchanged, in Remix's units.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#888")
        layout.addWidget(note)

        self.preview_shader = QtWidgets.QCheckBox("Show every Remix map in Painter's viewport (RTX Remix preview shader)")
        self.preview_shader.setToolTip(
            "Pull, Import and Add Remix Channels switch the project to the RTX Remix preview shader. It renders "
            "like Painter's standard alpha-blended PBR shader and also shows anisotropy and an approximation of "
            "Remix's subsurface maps. It only changes Painter's viewport, never what is pushed.")
        layout.addWidget(self.preview_shader)

        if self._add_channels_fn is not None:
            row = QtWidgets.QHBoxLayout()
            self.add_channels_btn = QtWidgets.QPushButton("Add Checked Channels to the Active Texture Set")
            self.add_channels_btn.setToolTip("Adds the Painter channel of every checked map the texture set doesn't have yet.")
            self.add_channels_btn.clicked.connect(self._add_channels)
            row.addWidget(self.add_channels_btn)
            row.addStretch(1)
            layout.addLayout(row)
        layout.addStretch(1)

        self.map_checks["albedo"].toggled.connect(lambda on: self.map_checks[OPACITY].setEnabled(on))
        self._watch(*self.map_checks.values(), self.preview_shader)
        self.tabs.addTab(w, "Texture Maps")

    def _build_tab_export(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.export_format = QtWidgets.QComboBox()
        self.export_format.addItems(list(EXPORT_FORMATS))
        self.export_format.setToolTip("File format of the textures handed to Remix ingestion (PNG recommended).")
        layout.addRow("Export Format", self.export_format)

        self.restore_aspect = QtWidgets.QCheckBox("Restore the source texture's aspect ratio on push")
        self.restore_aspect.setToolTip("Resizes exports to the aspect ratio of the material's original Remix texture "
                                       "(only when Painter's power-of-two resolution can't match it exactly).")
        layout.addRow(self.restore_aspect)

        self.remix_output_subfolder = QtWidgets.QLineEdit()
        self.remix_output_subfolder.setToolTip("Subfolder of the Remix project's ingest folder that receives pushed textures.")
        layout.addRow("Remix Output Subfolder", self.remix_output_subfolder)

        self.export_path = QtWidgets.QLineEdit()
        self.export_path.setToolTip("Where Painter exports textures before Remix ingests them.")
        layout.addRow("Export Folder", self._with_browse(self.export_path, mode="dir", title="Select export folder"))

        self._watch(self.export_format, self.restore_aspect, self.remix_output_subfolder, self.export_path)
        self.tabs.addTab(w, "Export")

    def _build_tab_paths(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.texconv_path = QtWidgets.QLineEdit()
        self.texconv_path.setToolTip("texconv.exe converts Remix DDS textures. Leave blank to use the bundled copy.")
        layout.addRow("texconv.exe", self._with_browse(self.texconv_path, mode="file", title="Select texconv.exe", filter="texconv.exe (*.exe);;All Files (*)"))

        self.blender_exe = QtWidgets.QLineEdit()
        self.blender_exe.setToolTip("blender.exe for the optional re-unwrap. Leave blank to use the newest installed Blender.")
        layout.addRow("Blender", self._with_browse(self.blender_exe, mode="file", title="Select blender.exe", filter="blender.exe (*.exe);;All Files (*)"))

        self.blender_script = QtWidgets.QLineEdit()
        self.blender_script.setToolTip("Optional custom Blender unwrap script. Leave blank to use the built-in script.")
        layout.addRow("Blender Unwrap Script", self._with_browse(self.blender_script, mode="file", title="Select unwrap script", filter="Python (*.py);;All Files (*)"))

        log_row = QtWidgets.QHBoxLayout()
        self.log_path_label = QtWidgets.QLineEdit(self._log_file_path)
        self.log_path_label.setReadOnly(True)
        self.log_open_btn = QtWidgets.QPushButton("Open Folder")
        log_row.addWidget(self.log_path_label, 1)
        log_row.addWidget(self.log_open_btn)
        layout.addRow("Plugin Log", log_row)
        self.log_open_btn.clicked.connect(self._open_log_folder)

        self._watch(self.texconv_path, self.blender_exe, self.blender_script)
        self.tabs.addTab(w, "Paths")

    def _build_tab_advanced(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.log_level = QtWidgets.QComboBox()
        self.log_level.addItems(["debug", "info", "warning", "error"])
        layout.addRow("Log Level", self.log_level)

        uv_box = QtWidgets.QGroupBox("Blender Smart UV Project")
        uv_layout = QtWidgets.QFormLayout(uv_box)

        self.uv_angle = QtWidgets.QDoubleSpinBox()
        self.uv_angle.setRange(0.0, 89.0)
        self.uv_angle.setDecimals(1)
        self.uv_angle.setSuffix("°")
        uv_layout.addRow("Angle Limit", self.uv_angle)

        self.uv_margin = QtWidgets.QDoubleSpinBox()
        self.uv_margin.setRange(0.0, 1.0)
        self.uv_margin.setDecimals(4)
        self.uv_margin.setSingleStep(0.0005)
        uv_layout.addRow("Island Margin", self.uv_margin)

        self.uv_area = QtWidgets.QDoubleSpinBox()
        self.uv_area.setRange(0.0, 10.0)
        self.uv_area.setDecimals(3)
        uv_layout.addRow("Area Weight", self.uv_area)

        self.uv_stretch = QtWidgets.QCheckBox("Stretch to Bounds")
        uv_layout.addRow(self.uv_stretch)
        layout.addRow(uv_box)

        self._watch(self.log_level, self.uv_angle, self.uv_margin, self.uv_area, self.uv_stretch)
        self.tabs.addTab(w, "Advanced")

    # --- helpers ---
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

    def _with_browse(self, line_edit: QtWidgets.QLineEdit, mode: str, title: str, filter: str = ""):
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        btn = QtWidgets.QPushButton("Browse...")
        row.addWidget(line_edit, 1)
        row.addWidget(btn)

        def _browse():
            try:
                if mode == "dir":
                    path = QtWidgets.QFileDialog.getExistingDirectory(self, title, line_edit.text() or "")
                else:
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

    def _open_log_folder(self):
        try:
            folder = os.path.dirname(self._log_file_path) if self._log_file_path else ""
            if folder:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
        except Exception:
            pass

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
            self.poll_timeout.setValue(float(s.get("poll_timeout", 60.0)))

            self.auto_import.setChecked(bool(s.get("auto_import_textures_on_pull", True)))
            self._select_data(self.resolution, int(s.get("project_texture_resolution", 2048)))
            self._select_data(self.normal_format, s.get("normal_map_format", "opengl"))
            self.import_template.setText(s.get("painter_import_template_path", ""))
            self.use_simple_mesh.setChecked(bool(s.get("use_simple_tiling_mesh_on_pull", False)))
            self.simple_mesh_path.setText(s.get("simple_tiling_mesh_path", ""))
            self.auto_unwrap.setChecked(bool(s.get("auto_unwrap_with_blender_on_pull", False)))

            maps = s.get("texture_maps") or {}
            for key, check in self.map_checks.items():
                check.setChecked(bool(maps.get(key, True)))
            self.map_checks[OPACITY].setEnabled(self.map_checks["albedo"].isChecked())
            self.preview_shader.setChecked(bool(s.get("use_remix_preview_shader", True)))

            self._select_text(self.export_format, s.get("export_file_format", "png"))
            self.restore_aspect.setChecked(bool(s.get("restore_original_aspect_ratio_on_export", True)))
            self.remix_output_subfolder.setText(s.get("remix_output_subfolder", ""))
            self.export_path.setText(s.get("painter_export_path", ""))

            self.texconv_path.setText(s.get("texconv_path", ""))
            self.blender_exe.setText(s.get("blender_executable_path", ""))
            self.blender_script.setText(s.get("blender_unwrap_script_path", ""))

            self._select_text(self.log_level, s.get("log_level", "info"))
            self.uv_angle.setValue(float(s.get("blender_smart_uv_angle_limit", 66.0)))
            self.uv_margin.setValue(float(s.get("blender_smart_uv_island_margin", 0.003)))
            self.uv_area.setValue(float(s.get("blender_smart_uv_area_weight", 0.0)))
            self.uv_stretch.setChecked(bool(s.get("blender_smart_uv_stretch_to_bounds", False)))
        finally:
            self._loading = False

    def _gather(self) -> Dict:
        """The values this dialog edits (merged into the settings on save)."""
        return {
            "api_base_url": self.api_base_url.text().strip(),
            "poll_timeout": float(self.poll_timeout.value()),

            "auto_import_textures_on_pull": bool(self.auto_import.isChecked()),
            "project_texture_resolution": int(self.resolution.currentData()),
            "normal_map_format": self.normal_format.currentData(),
            "painter_import_template_path": self.import_template.text().strip(),
            "use_simple_tiling_mesh_on_pull": bool(self.use_simple_mesh.isChecked()),
            "simple_tiling_mesh_path": self.simple_mesh_path.text().strip(),
            "auto_unwrap_with_blender_on_pull": bool(self.auto_unwrap.isChecked()),

            "texture_maps": {key: bool(check.isChecked()) for key, check in self.map_checks.items()},
            "use_remix_preview_shader": bool(self.preview_shader.isChecked()),

            "export_file_format": self.export_format.currentText().strip().lower(),
            "restore_original_aspect_ratio_on_export": bool(self.restore_aspect.isChecked()),
            "remix_output_subfolder": self.remix_output_subfolder.text().strip(),
            "painter_export_path": self.export_path.text().strip(),

            "texconv_path": self.texconv_path.text().strip(),
            "blender_executable_path": self.blender_exe.text().strip(),
            "blender_unwrap_script_path": self.blender_script.text().strip(),

            "log_level": self.log_level.currentText().strip().lower(),
            "blender_smart_uv_angle_limit": float(self.uv_angle.value()),
            "blender_smart_uv_island_margin": float(self.uv_margin.value()),
            "blender_smart_uv_area_weight": float(self.uv_area.value()),
            "blender_smart_uv_stretch_to_bounds": bool(self.uv_stretch.isChecked()),
        }

    # --- autosave ---
    def _changed(self, *_):
        if not self._loading:
            self._save_timer.start()

    def _commit(self):
        self._save_timer.stop()
        self._settings = self._controller.update_settings(self._gather())
        self._show_saved("Saved.")

    def _flush(self):
        """Save a pending (debounced) change now."""
        if self._save_timer.isActive():
            self._commit()

    def _show_saved(self, text):
        self.saved_label.setText(text)
        # The label is the timer's context, so Qt drops the timer if the dialog is deleted first.
        label = self.saved_label
        QtCore.QTimer.singleShot(2500, label, lambda: label.setText("Changes are saved automatically."))

    def _test_connection(self):
        if not self._test_connection_fn:
            self.test_result.setText("No test function available.")
            return
        self.test_result.setText("Testing...")
        QtWidgets.QApplication.processEvents()
        try:
            ok, msg = self._test_connection_fn({**self._settings, **self._gather()})
            self.test_result.setText(("OK: " if ok else "FAIL: ") + str(msg))
        except Exception as e:
            self.test_result.setText(f"FAIL: {e}")

    def _add_channels(self):
        self._flush()
        if self._add_channels_fn is not None:
            self._add_channels_fn()

    def _reset_defaults(self):
        if not self._confirm("Restore Defaults", "Reset every setting to its default?"):
            return
        self._save_timer.stop()
        self._settings = self._controller.reset_settings()
        self._load_fields(self._settings)
        self.test_result.setText("")
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


def create_settings_dialog_instance(
    controller,
    parent=None,
    test_connection_fn: Optional[TestConnectionFn] = None,
    log_file_path: Optional[str] = None,
    add_channels_fn: Optional[Callable[[], None]] = None,
):
    return SettingsDialog(controller, parent=parent, test_connection_fn=test_connection_fn,
                          log_file_path=log_file_path, add_channels_fn=add_channels_fn)

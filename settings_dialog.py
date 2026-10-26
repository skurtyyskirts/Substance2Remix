import os
from typing import Callable, Dict, Optional, Tuple

from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION
from .qt_utils import QtWidgets, QtCore, QtGui, QT_AVAILABLE
from .settings_schema import sanitize_settings, TEXTURE_RESOLUTIONS, NORMAL_MAP_FORMATS, EXPORT_FORMATS

TestConnectionFn = Callable[[Dict], Tuple[bool, str]]

_NORMAL_FORMAT_LABELS = {"opengl": "OpenGL (Painter default)", "directx": "DirectX"}


class SettingsDialog(QtWidgets.QDialog if QT_AVAILABLE else object):
    def __init__(
        self,
        current_settings: Dict,
        parent=None,
        test_connection_fn: Optional[TestConnectionFn] = None,
        log_file_path: Optional[str] = None,
    ):
        if not QT_AVAILABLE:
            self._settings = dict(current_settings or {})
            return

        super().__init__(parent)
        self.setWindowTitle(f"{PLUGIN_NAME} - Settings")
        self.setMinimumWidth(720)

        self._test_connection_fn = test_connection_fn
        self._log_file_path = log_file_path or ""

        # Fill defaults + normalize types for UI.
        self._plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._settings = sanitize_settings(current_settings or {}, self._plugin_dir)

        root = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(f"<b>{PLUGIN_NAME}</b> <span style='color:#888'>v{PLUGIN_VERSION}</span>")
        root.addWidget(header)

        self.tabs = QtWidgets.QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self._build_tab_connection()
        self._build_tab_project()
        self._build_tab_export()
        self._build_tab_paths()
        self._build_tab_advanced()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.RestoreDefaults | QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok
        )
        root.addWidget(buttons)
        self.reset_btn = buttons.button(QtWidgets.QDialogButtonBox.RestoreDefaults)
        self.ok_btn = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self.cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        self.reset_btn.clicked.connect(self._reset_defaults)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        self._load_fields(self._settings)

    # --- tab builders ---
    def _build_tab_connection(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.api_base_url = QtWidgets.QLineEdit()
        self.api_base_url.setPlaceholderText("http://localhost:8011")
        self.api_base_url.setToolTip("RTX Remix Toolkit REST API address. The Toolkit serves it on port 8011 by default.")

        self.poll_timeout = QtWidgets.QDoubleSpinBox()
        self.poll_timeout.setRange(0.2, 300.0)
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
        self.normal_format.setToolTip("Normal map convention used for new projects, imports and pushes. "
                                      "Remix converts either one to its octahedral format on ingest.")
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

        self.tabs.addTab(w, "Project")

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

        self.tabs.addTab(w, "Advanced")

    # --- helpers ---
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
                    if path:
                        line_edit.setText(path)
                else:
                    path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, line_edit.text() or "", filter)
                    if path:
                        line_edit.setText(path)
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
        self.api_base_url.setText(s.get("api_base_url", ""))
        self.poll_timeout.setValue(float(s.get("poll_timeout", 60.0)))

        self.auto_import.setChecked(bool(s.get("auto_import_textures_on_pull", True)))
        self._select_data(self.resolution, int(s.get("project_texture_resolution", 2048)))
        self._select_data(self.normal_format, s.get("normal_map_format", "opengl"))
        self.import_template.setText(s.get("painter_import_template_path", ""))
        self.use_simple_mesh.setChecked(bool(s.get("use_simple_tiling_mesh_on_pull", False)))
        self.simple_mesh_path.setText(s.get("simple_tiling_mesh_path", ""))
        self.auto_unwrap.setChecked(bool(s.get("auto_unwrap_with_blender_on_pull", False)))

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

    def _gather(self) -> Dict:
        s = dict(self._settings)
        s["api_base_url"] = self.api_base_url.text().strip()
        s["poll_timeout"] = float(self.poll_timeout.value())

        s["auto_import_textures_on_pull"] = bool(self.auto_import.isChecked())
        s["project_texture_resolution"] = int(self.resolution.currentData())
        s["normal_map_format"] = self.normal_format.currentData()
        s["painter_import_template_path"] = self.import_template.text().strip()
        s["use_simple_tiling_mesh_on_pull"] = bool(self.use_simple_mesh.isChecked())
        s["simple_tiling_mesh_path"] = self.simple_mesh_path.text().strip()
        s["auto_unwrap_with_blender_on_pull"] = bool(self.auto_unwrap.isChecked())

        s["export_file_format"] = self.export_format.currentText().strip().lower()
        s["restore_original_aspect_ratio_on_export"] = bool(self.restore_aspect.isChecked())
        s["remix_output_subfolder"] = self.remix_output_subfolder.text().strip()
        s["painter_export_path"] = self.export_path.text().strip()

        s["texconv_path"] = self.texconv_path.text().strip()
        s["blender_executable_path"] = self.blender_exe.text().strip()
        s["blender_unwrap_script_path"] = self.blender_script.text().strip()

        s["log_level"] = self.log_level.currentText().strip().lower()
        s["blender_smart_uv_angle_limit"] = float(self.uv_angle.value())
        s["blender_smart_uv_island_margin"] = float(self.uv_margin.value())
        s["blender_smart_uv_area_weight"] = float(self.uv_area.value())
        s["blender_smart_uv_stretch_to_bounds"] = bool(self.uv_stretch.isChecked())
        return s

    def _test_connection(self):
        if not self._test_connection_fn:
            self.test_result.setText("No test function available.")
            return
        self.test_result.setText("Testing...")
        QtWidgets.QApplication.processEvents()
        try:
            ok, msg = self._test_connection_fn(self._gather())
            self.test_result.setText(("OK: " if ok else "FAIL: ") + str(msg))
        except Exception as e:
            self.test_result.setText(f"FAIL: {e}")

    def _reset_defaults(self):
        defaults = sanitize_settings({}, self._plugin_dir)
        # Keep keys this dialog doesn't edit (data other tools stored alongside).
        extras = {k: v for k, v in self._settings.items() if k not in defaults}
        self._settings = {**extras, **defaults}
        self._load_fields(self._settings)
        self.test_result.setText("")

    def _accept(self):
        self._settings = self._gather()
        self.accept()

    def get_settings(self) -> Dict:
        return dict(self._settings)

    # PySide6 compatibility
    def exec_(self):  # noqa: N802
        try:
            return super().exec()
        except AttributeError:
            return super().exec_()


def create_settings_dialog_instance(
    current_settings: Dict,
    parent=None,
    test_connection_fn: Optional[TestConnectionFn] = None,
    log_file_path: Optional[str] = None,
):
    return SettingsDialog(current_settings, parent=parent, test_connection_fn=test_connection_fn, log_file_path=log_file_path)

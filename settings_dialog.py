import os
import sys
from typing import Callable, Dict, Optional, Tuple

from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION
from .qt_utils import QtWidgets, QtCore, QT_AVAILABLE
from .settings_schema import sanitize_settings

TestConnectionFn = Callable[[Dict], Tuple[bool, str]]


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
        self.setMinimumWidth(760)
        self.setMinimumHeight(540)

        self._test_connection_fn = test_connection_fn
        self._log_file_path = log_file_path or ""

        # Fill defaults + normalize types for UI.
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._settings = sanitize_settings(current_settings or {}, plugin_dir)

        root = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel(f"<b>{PLUGIN_NAME}</b> <span style='color:#888'>v{PLUGIN_VERSION}</span>")
        root.addWidget(header)

        self.tabs = QtWidgets.QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self._build_tab_connection()
        self._build_tab_paths()
        self._build_tab_pull()
        self._build_tab_export()
        self._build_tab_advanced()

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)

        self.reset_btn = QtWidgets.QPushButton("Reset to Defaults")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.ok_btn = QtWidgets.QPushButton("OK")
        self.ok_btn.setDefault(True)

        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.ok_btn)
        root.addLayout(btn_row)

        self.reset_btn.clicked.connect(self._reset_defaults)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._accept)

    # --- tab builders ---
    def _build_tab_connection(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.api_base_url = QtWidgets.QLineEdit(self._settings.get("api_base_url", ""))
        self.api_base_url.setPlaceholderText("http://localhost:8011")
        self.api_base_url.setToolTip("RTX Remix REST API base URL (must match the Remix service).")

        self.poll_timeout = QtWidgets.QDoubleSpinBox()
        self.poll_timeout.setRange(0.2, 300.0)
        self.poll_timeout.setDecimals(1)
        self.poll_timeout.setSingleStep(0.5)
        self.poll_timeout.setValue(float(self._settings.get("poll_timeout", 60.0)))
        self.poll_timeout.setToolTip("Network timeout in seconds for Remix API calls.")

        layout.addRow("API Base URL", self.api_base_url)
        layout.addRow("Request Timeout (sec)", self.poll_timeout)

        # Test connection row
        test_row = QtWidgets.QHBoxLayout()
        self.test_btn = QtWidgets.QPushButton("Test Connection")
        self.test_result = QtWidgets.QLabel("")
        self.test_result.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        layout.addRow(" ", test_row)

        self.test_btn.clicked.connect(self._test_connection)

        self.tabs.addTab(w, "Connection")

    def _build_tab_paths(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.texconv_path = QtWidgets.QLineEdit(self._settings.get("texconv_path", ""))
        self.texconv_path.setToolTip("Path to texconv.exe (used to convert DDS pulled from Remix into PNG).")
        layout.addRow("texconv.exe", self._with_browse(self.texconv_path, mode="file", title="Select texconv.exe", filter="texconv.exe (*.exe);;All Files (*)"))

        self.blender_exe = QtWidgets.QLineEdit(self._settings.get("blender_executable_path", ""))
        self.blender_exe.setToolTip("Path to blender.exe (optional; used for auto-unwrap on pull).")
        layout.addRow("Blender Executable", self._with_browse(self.blender_exe, mode="file", title="Select blender.exe", filter="blender.exe (*.exe);;All Files (*)"))

        self.blender_script = QtWidgets.QLineEdit(self._settings.get("blender_unwrap_script_path", ""))
        self.blender_script.setToolTip("Optional custom Blender unwrap script. Leave blank to use the built-in script shipped with this plugin.")
        layout.addRow("Blender Unwrap Script", self._with_browse(self.blender_script, mode="file", title="Select unwrap script", filter="Python (*.py);;All Files (*)"))

        self.export_path = QtWidgets.QLineEdit(self._settings.get("painter_export_path", ""))
        self.export_path.setToolTip("Where Painter exports temporary textures before ingestion.")
        layout.addRow("Export Folder", self._with_browse(self.export_path, mode="dir", title="Select export folder"))

        self.remix_output_subfolder = QtWidgets.QLineEdit(self._settings.get("remix_output_subfolder", ""))
        self.remix_output_subfolder.setToolTip("Subfolder inside the Remix project output directory for ingested textures.")
        layout.addRow("Remix Output Subfolder", self.remix_output_subfolder)

        # Log file (read-only)
        log_row = QtWidgets.QHBoxLayout()
        self.log_path_label = QtWidgets.QLineEdit(self._log_file_path)
        self.log_path_label.setReadOnly(True)
        self.log_open_btn = QtWidgets.QPushButton("Open Folder")
        log_row.addWidget(self.log_path_label, 1)
        log_row.addWidget(self.log_open_btn)
        layout.addRow("Plugin Log", log_row)
        self.log_open_btn.clicked.connect(self._open_log_folder)

        self.tabs.addTab(w, "Paths")

    def _build_tab_pull(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.use_simple_mesh = QtWidgets.QCheckBox("Use simple tiling mesh instead of the selected Remix mesh")
        self.use_simple_mesh.setChecked(bool(self._settings.get("use_simple_tiling_mesh_on_pull", False)))
        self.use_simple_mesh.setToolTip("Useful for authoring tiling materials (pulls a simple plane mesh instead of the selected asset).")
        layout.addRow(self.use_simple_mesh)

        self.simple_mesh_path = QtWidgets.QLineEdit(self._settings.get("simple_tiling_mesh_path", ""))
        self.simple_mesh_path.setToolTip("Mesh path (relative to plugin folder or absolute) used when 'Use simple tiling mesh' is enabled.")
        layout.addRow("Simple Tiling Mesh", self._with_browse(self.simple_mesh_path, mode="file", title="Select mesh file", filter="Mesh (*.usd *.usda *.usdc *.fbx *.obj *.gltf *.glb);;All Files (*)"))

        self.auto_unwrap = QtWidgets.QCheckBox("Auto-unwrap pulled meshes with Blender (Smart UV Project)")
        self.auto_unwrap.setChecked(bool(self._settings.get("auto_unwrap_with_blender_on_pull", False)))
        self.auto_unwrap.setToolTip("Runs Blender in the background to generate UVs before creating the Painter project.")
        layout.addRow(self.auto_unwrap)

        self.import_template = QtWidgets.QLineEdit(self._settings.get("painter_import_template_path", ""))
        self.import_template.setToolTip("Optional Painter template/workflow identifier URL. Leave blank to auto-detect a PBR Metallic/Roughness template.")
        layout.addRow("Painter Import Template (optional)", self.import_template)

        self.tabs.addTab(w, "Pull")

    def _build_tab_export(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.export_format = QtWidgets.QComboBox()
        self.export_format.addItems(["png", "tga", "jpg"])
        current = str(self._settings.get("export_file_format", "png")).lower()
        idx = self.export_format.findText(current)
        if idx >= 0:
            self.export_format.setCurrentIndex(idx)
        self.export_format.setToolTip("Texture export file format (PNG recommended).")
        layout.addRow("Export Format", self.export_format)

        self.include_opacity = QtWidgets.QCheckBox("Export & push separate Opacity texture (in addition to BaseColor alpha)")
        self.include_opacity.setChecked(bool(self._settings.get("include_opacity_map", False)))
        self.include_opacity.setToolTip("Some Remix materials prefer a dedicated opacity texture input. Off preserves current behavior.")
        layout.addRow(self.include_opacity)

        self.tabs.addTab(w, "Export")

    def _build_tab_advanced(self):
        w = QtWidgets.QWidget(self)
        layout = QtWidgets.QFormLayout(w)

        self.log_level = QtWidgets.QComboBox()
        self.log_level.addItems(["debug", "info", "warning", "error"])
        cur = str(self._settings.get("log_level", "info")).lower()
        idx = self.log_level.findText(cur)
        if idx >= 0:
            self.log_level.setCurrentIndex(idx)
        layout.addRow("Log Level", self.log_level)

        # Blender Smart UV parameters
        self.uv_angle = QtWidgets.QDoubleSpinBox()
        self.uv_angle.setRange(0.0, 89.0)
        self.uv_angle.setDecimals(1)
        self.uv_angle.setValue(float(self._settings.get("blender_smart_uv_angle_limit", 66.0)))
        layout.addRow("Smart UV Angle Limit", self.uv_angle)

        self.uv_margin = QtWidgets.QDoubleSpinBox()
        self.uv_margin.setRange(0.0, 1.0)
        self.uv_margin.setDecimals(4)
        self.uv_margin.setSingleStep(0.0005)
        self.uv_margin.setValue(float(self._settings.get("blender_smart_uv_island_margin", 0.003)))
        layout.addRow("Smart UV Island Margin", self.uv_margin)

        self.uv_area = QtWidgets.QDoubleSpinBox()
        self.uv_area.setRange(0.0, 10.0)
        self.uv_area.setDecimals(3)
        self.uv_area.setValue(float(self._settings.get("blender_smart_uv_area_weight", 0.0)))
        layout.addRow("Smart UV Area Weight", self.uv_area)

        self.uv_stretch = QtWidgets.QCheckBox("Stretch to Bounds")
        self.uv_stretch.setChecked(bool(self._settings.get("blender_smart_uv_stretch_to_bounds", False)))
        layout.addRow(self.uv_stretch)

        self.tabs.addTab(w, "Advanced")

    # --- helpers ---
    def _with_browse(self, line_edit: QtWidgets.QLineEdit, mode: str, title: str, filter: str = ""):
        row = QtWidgets.QHBoxLayout()
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
            if not folder:
                return
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _gather(self) -> Dict:
        s = dict(self._settings)
        s["api_base_url"] = self.api_base_url.text().strip()
        s["poll_timeout"] = float(self.poll_timeout.value())

        s["texconv_path"] = self.texconv_path.text().strip()
        s["blender_executable_path"] = self.blender_exe.text().strip()
        s["blender_unwrap_script_path"] = self.blender_script.text().strip()
        s["painter_export_path"] = self.export_path.text().strip()
        s["remix_output_subfolder"] = self.remix_output_subfolder.text().strip()

        s["use_simple_tiling_mesh_on_pull"] = bool(self.use_simple_mesh.isChecked())
        s["simple_tiling_mesh_path"] = self.simple_mesh_path.text().strip()
        s["auto_unwrap_with_blender_on_pull"] = bool(self.auto_unwrap.isChecked())
        s["painter_import_template_path"] = self.import_template.text().strip()

        s["export_file_format"] = self.export_format.currentText().strip().lower()
        s["include_opacity_map"] = bool(self.include_opacity.isChecked())

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
        try:
            ok, msg = self._test_connection_fn(self._gather())
            self.test_result.setText(("OK: " if ok else "FAIL: ") + str(msg))
        except Exception as e:
            self.test_result.setText(f"FAIL: {e}")

    def _reset_defaults(self):
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._settings = sanitize_settings({}, plugin_dir)

        # Re-sync UI fields
        self.api_base_url.setText(self._settings.get("api_base_url", ""))
        self.poll_timeout.setValue(float(self._settings.get("poll_timeout", 60.0)))

        self.texconv_path.setText(self._settings.get("texconv_path", ""))
        self.blender_exe.setText(self._settings.get("blender_executable_path", ""))
        self.blender_script.setText(self._settings.get("blender_unwrap_script_path", ""))
        self.export_path.setText(self._settings.get("painter_export_path", ""))
        self.remix_output_subfolder.setText(self._settings.get("remix_output_subfolder", ""))

        self.use_simple_mesh.setChecked(bool(self._settings.get("use_simple_tiling_mesh_on_pull", False)))
        self.simple_mesh_path.setText(self._settings.get("simple_tiling_mesh_path", ""))
        self.auto_unwrap.setChecked(bool(self._settings.get("auto_unwrap_with_blender_on_pull", False)))
        self.import_template.setText(self._settings.get("painter_import_template_path", ""))

        fmt = str(self._settings.get("export_file_format", "png")).lower()
        idx = self.export_format.findText(fmt)
        if idx >= 0:
            self.export_format.setCurrentIndex(idx)
        self.include_opacity.setChecked(bool(self._settings.get("include_opacity_map", False)))

        lvl = str(self._settings.get("log_level", "info")).lower()
        idx = self.log_level.findText(lvl)
        if idx >= 0:
            self.log_level.setCurrentIndex(idx)

        self.uv_angle.setValue(float(self._settings.get("blender_smart_uv_angle_limit", 66.0)))
        self.uv_margin.setValue(float(self._settings.get("blender_smart_uv_island_margin", 0.003)))
        self.uv_area.setValue(float(self._settings.get("blender_smart_uv_area_weight", 0.0)))
        self.uv_stretch.setChecked(bool(self._settings.get("blender_smart_uv_stretch_to_bounds", False)))

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
        except Exception:
            return super().exec_()


def create_settings_dialog_instance(
    current_settings: Dict,
    parent=None,
    test_connection_fn: Optional[TestConnectionFn] = None,
    log_file_path: Optional[str] = None,
):
    return SettingsDialog(current_settings, parent=parent, test_connection_fn=test_connection_fn, log_file_path=log_file_path)

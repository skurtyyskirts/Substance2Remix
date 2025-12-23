import os
import sys
import json
import tempfile
import traceback
import time
import shutil
import re

# Local imports
from . import dependency_manager
from .qt_utils import QObject, Signal, Slot, QThread, QRunnable, QThreadPool, QtWidgets, QtCore, QT_BINDING
from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION, PLUGIN_REPO_URL, PLUGIN_DESCRIPTION
from .remix_api import RemixAPIClient, REMIX_ATTR_SUFFIX_TO_PBR_MAP, PBR_TO_REMIX_INGEST_VALIDATION_TYPE_MAP
from .texture_processor import TextureProcessor
from .painter_controller import PainterController
from .async_utils import Worker
from .settings_dialog import create_settings_dialog_instance
from .settings_schema import sanitize_settings, atomic_write_json
from .diagnostics_dialog import DiagnosticsDialog

# --- Logging Setup ---
try:
    import substance_painter.logging as sp_logging
except ImportError:
    class MockLogger:
        def info(self, m): print(f"[INFO] {m}")
        def warning(self, m): print(f"[WARN] {m}")
        def error(self, m, exc_info=False): print(f"[ERROR] {m}")
        def debug(self, m): print(f"[DEBUG] {m}")
    sp_logging = MockLogger()

DEFAULT_REMIX_API_BASE_URL = "http://localhost:8011"
SETTINGS_FILE_NAME = "settings.json"
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE_PATH = os.path.join(PLUGIN_DIR, SETTINGS_FILE_NAME)
LOG_DIR = os.path.join(PLUGIN_DIR, "logs")
LOG_FILE_PATH = os.path.join(LOG_DIR, "remix_connector.log")

PBR_TO_MDL_INPUT_MAP = {
    "albedo": "diffuse_texture",
    "normal": "normalmap_texture",
    "height": "height_texture",
    "roughness": "reflectionroughness_texture",
    "metallic": "metallic_texture",
    "emissive": "emissive_mask_texture",
    "opacity": "opacity_texture",
}

class RemixConnectorPlugin(QObject):
    def __init__(self):
        super().__init__()
        self._active_workers = set()
        self._active_progress_dialogs = {}
        self._log_file_path = LOG_FILE_PATH
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except Exception:
            pass

        self.settings = {}
        self.load_settings()
        
        self.logger_adapter = {
            'info': self.log_info,
            'debug': self.log_debug,
            'warning': self.log_warning,
            'error': self.log_error
        }
        
        self.remix_api = RemixAPIClient(self.get_settings, self.logger_adapter)
        self.texture_processor = TextureProcessor(self.get_settings, self.logger_adapter, self.display_message)
        self.painter_controller = PainterController(self.logger_adapter)
        
        self.threadpool = QThreadPool()

    # --- Worker lifecycle (prevents GC / improves reliability when app is unfocused) ---
    def _get_ui_parent(self):
        try:
            import substance_painter.ui
            return substance_painter.ui.get_main_window()
        except Exception:
            return None

    def _start_worker(self, worker, on_result=None, title=None, show_progress=True):
        """
        Starts a Worker and keeps a strong reference until it finishes.
        This prevents intermittent dropouts due to Python GC/Qt ownership nuances.
        """
        try:
            self._active_workers.add(worker)
        except Exception:
            pass

        # Optional progress dialog (uses Worker's status/progress signals)
        progress_dialog = None
        if show_progress and QtWidgets and QtCore:
            try:
                progress_dialog = QtWidgets.QProgressDialog("Working...", "Hide", 0, 0, self._get_ui_parent())
                progress_dialog.setWindowTitle(title or PLUGIN_NAME)
                progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
                progress_dialog.setMinimumDuration(0)
                progress_dialog.setAutoClose(True)
                progress_dialog.setAutoReset(True)
                progress_dialog.setValue(0)
                try:
                    progress_dialog.canceled.connect(progress_dialog.hide)
                except Exception:
                    pass
                progress_dialog.show()
                self._active_progress_dialogs[worker] = progress_dialog

                def _on_status(text, dlg=progress_dialog):
                    try:
                        dlg.setLabelText(str(text))
                    except Exception:
                        pass

                def _on_progress(pct, dlg=progress_dialog):
                    try:
                        # Switch from indeterminate to 0-100 when we receive a progress update.
                        if dlg.maximum() == 0:
                            dlg.setRange(0, 100)
                        dlg.setValue(int(pct))
                    except Exception:
                        pass

                worker.signals.status.connect(_on_status)
                worker.signals.progress.connect(_on_progress)
            except Exception:
                progress_dialog = None

        def _cleanup():
            try:
                self._active_workers.discard(worker)
            except Exception:
                pass
            try:
                dlg = self._active_progress_dialogs.pop(worker, None)
                if dlg:
                    dlg.close()
            except Exception:
                pass

        try:
            worker.signals.finished.connect(_cleanup)
        except Exception:
            pass

        if on_result:
            try:
                worker.signals.result.connect(on_result)
            except Exception:
                pass

        worker.signals.error.connect(self._on_worker_error)
        self.threadpool.start(worker)

    # --- Painter stack/channel helpers (API differences + missing-channel robustness) ---
    def _get_texture_set_stack(self, texture_set):
        for name in ("get_stack", "getStack", "stack", "getStackObject"):
            try:
                fn = getattr(texture_set, name, None)
                if callable(fn):
                    return fn()
            except Exception:
                continue
        return None

    def _safe_stack_get_channel(self, stack, channel_type):
        for name in ("get_channel", "getChannel"):
            try:
                fn = getattr(stack, name, None)
                if callable(fn):
                    return fn(channel_type)
            except Exception:
                return None
        return None

    def _safe_stack_add_channel(self, stack, channel_type):
        for name in ("add_channel", "addChannel"):
            try:
                fn = getattr(stack, name, None)
                if callable(fn):
                    fn(channel_type)
                    return True
            except Exception:
                return False
        return False

    def _ensure_stack_channel(self, stack, channel_type, label):
        ch = self._safe_stack_get_channel(stack, channel_type)
        if ch:
            return ch
        if not self._safe_stack_add_channel(stack, channel_type):
            self.log_warning(f"Could not add missing channel '{label}' to texture set stack.")
            return None
        return self._safe_stack_get_channel(stack, channel_type)

    def _ensure_required_channels_for_export(self):
        """
        Ensures channels exist so MapExporter can generate maps like Emissive/Opacity even if the template lacks them.
        """
        try:
            import substance_painter.textureset
        except Exception:
            return

        required = ["baseColor", "normal", "roughness", "metallic", "height", "emissive", "opacity"]
        all_ts = substance_painter.textureset.all_texture_sets() or []
        for ts in all_ts:
            stack = self._get_texture_set_stack(ts)
            if not stack:
                continue
            for name in required:
                ctype = self.painter_controller.PAINTER_STRING_TO_CHANNELTYPE_MAP.get(name)
                if not ctype:
                    continue
                self._ensure_stack_channel(stack, ctype, name)
        
    def get_settings(self):
        return self.settings

    def _write_log_line(self, level, msg):
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(self._log_file_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{level.upper()}] {msg}\n")
        except Exception:
            # Never let logging crash the plugin.
            pass

    def log_info(self, msg):
        if self.settings.get("log_level", "info") in ["debug", "info"]:
            self._write_log_line("info", msg)
            sp_logging.info(f"[RemixConnector] {msg}")

    def log_debug(self, msg):
        if self.settings.get("log_level", "info") == "debug":
            self._write_log_line("debug", msg)
            if hasattr(sp_logging, 'debug'):
                sp_logging.debug(f"[RemixConnector DEBUG] {msg}")
            elif hasattr(sp_logging, 'info'):
                sp_logging.info(f"[RemixConnector DEBUG] {msg}")
            else:
                print(f"[RemixConnector DEBUG] {msg}")

    def log_warning(self, msg):
        if self.settings.get("log_level", "info") in ["debug", "info", "warning"]:
            self._write_log_line("warning", msg)
            sp_logging.warning(f"[RemixConnector WARN] {msg}")

    def log_error(self, msg, exc_info=False):
        self._write_log_line("error", msg)
        sp_logging.error(f"[RemixConnector ERROR] {msg}")
        if exc_info:
            tb = traceback.format_exc()
            self._write_log_line("error", tb)
            sp_logging.error(tb)

    def display_message(self, msg):
        try:
            import substance_painter.ui
            substance_painter.ui.display_message(str(msg))
        except:
            self.log_info(f"UI Message: {msg}")

    def load_settings(self):
        raw = {}
        try:
            if os.path.exists(SETTINGS_FILE_PATH):
                with open(SETTINGS_FILE_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
        except Exception as e:
            # Continue with defaults if settings are corrupted/unreadable.
            self.log_error(f"Failed to load settings (using defaults): {e}", exc_info=True)
            raw = {}

        self.settings = sanitize_settings(raw, PLUGIN_DIR)

    def save_settings(self):
        try:
            self.settings = sanitize_settings(self.settings or {}, PLUGIN_DIR)
            ok, err = atomic_write_json(SETTINGS_FILE_PATH, self.settings)
            if not ok:
                raise RuntimeError(err or "Unknown error")
        except Exception as e:
            self.log_error(f"Failed to save settings: {e}", exc_info=True)

    def _on_worker_error(self, err_tuple):
        exctype, value, tb = err_tuple
        self.log_error(f"Worker Error: {value}\n{tb}")
        self.display_message(f"Operation failed: {value}")

    # --- Actions ---

    def handle_pull_from_remix(self):
        self.log_info("Starting Pull from Remix (Async)...")
        worker = Worker(self._pull_step1_fetch)
        self._start_worker(worker, on_result=self._pull_step2_painter_setup, title="Pull from Remix")

    def _pull_step1_fetch(self, progress_callback=None, status_callback=None):
        if status_callback: status_callback.emit("Querying Remix for selection...")
        mesh_file, material_prim, context_file, err = self.remix_api.get_selected_asset_details()
        if err: raise Exception(err)
        return (mesh_file, material_prim, context_file)

    def _pull_step2_painter_setup(self, result):
        mesh_file, material_prim, context_file = result
        self.log_info(f"Pull selection: mesh='{mesh_file}', material='{material_prim}'")

        # Resolve mesh path (Remix may return a relative mesh path + absolute context file)
        mesh_path = mesh_file
        try:
            if mesh_path and not os.path.isabs(mesh_path) and context_file and os.path.isabs(context_file):
                candidate = os.path.normpath(os.path.join(os.path.dirname(context_file), mesh_path))
                if os.path.isfile(candidate):
                    mesh_path = candidate
        except Exception:
            pass

        # Optional: override with simple tiling mesh
        used_simple_mesh = False
        if self.settings.get("use_simple_tiling_mesh_on_pull", False):
            simple_mesh = self.settings.get("simple_tiling_mesh_path")
            if simple_mesh:
                simple_abs = os.path.join(PLUGIN_DIR, simple_mesh)
                if os.path.isfile(simple_abs):
                    mesh_path = simple_abs
                    used_simple_mesh = True

        # Optional: unwrap before project creation (runs in background)
        if self.settings.get("auto_unwrap_with_blender_on_pull", False) and not used_simple_mesh:
            self.log_info("Auto-unwrap enabled; starting Blender unwrap...")
            worker = Worker(self._pull_step2b_unwrap_mesh, mesh_path)
            self._start_worker(
                worker,
                on_result=lambda unwrapped: self._pull_step2c_create_project(unwrapped or mesh_path, material_prim),
                title="Auto-Unwrap Mesh (Blender)",
            )
            return

        self._pull_step2c_create_project(mesh_path, material_prim)

    def _pull_step2b_unwrap_mesh(self, mesh_path, progress_callback=None, status_callback=None):
        if status_callback:
            status_callback.emit("Unwrapping mesh with Blender...")
        return self.texture_processor.unwrap_mesh_with_blender(mesh_path) or ""

    def _pull_step2c_create_project(self, mesh_path, material_prim):
        try:
            import substance_painter.project

            # Close any existing project (do this late, after unwrap, to avoid leaving user without a project).
            if self.painter_controller.is_project_open():
                self.painter_controller.close_project()

            settings = substance_painter.project.Settings(import_cameras=False)

            template_path = self.settings.get("painter_import_template_path")
            if template_path:
                self.log_debug(f"Using configured import template: {template_path}")
            else:
                try:
                    import substance_painter.resource
                    templates = substance_painter.resource.search("PBR - Metallic Roughness Alpha-blend")
                    for t in templates:
                        url = t.identifier().url()
                        if "starter_assets" in url:
                            template_path = url
                            break
                    if not template_path and templates:
                        template_path = templates[0].identifier().url()
                except Exception as e:
                    self.log_debug(f"Template search failed: {e}")

            if template_path:
                try:
                    settings.import_project_workflow = template_path
                except Exception:
                    # Some Painter versions may not support this property
                    pass

            self.log_info(f"Creating Painter project from mesh: {mesh_path}")
            substance_painter.project.create(mesh_file_path=mesh_path, settings=settings)

            meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
            meta.set("remix_material_prim", material_prim)
            m = re.search(r"([A-Z0-9]{16})$", str(material_prim))
            if m:
                meta.set("remix_material_hash", m.group(1))

            self.display_message(
                "Project created and linked to Remix.\n"
                "Use 'Import Textures from Remix' to pull textures when you want them."
            )

        except Exception as e:
            self.log_error(f"Error creating project: {e}", exc_info=True)
            self.display_message(f"Error creating project: {e}")

    def _pull_step3_fetch_process_textures(self, material_prim, progress_callback=None, status_callback=None):
        if status_callback: status_callback.emit("Fetching textures from Remix...")
        textures, err = self.remix_api.get_material_textures(material_prim)
        if err: raise Exception(err)
        
        remix_proj_dir, _ = self.remix_api.get_project_default_output_dir()
        project_name = self.remix_api.derive_project_name_from_dir(remix_proj_dir)
        dest_dir = os.path.join(PLUGIN_DIR, "Pulled Textures", project_name)
        os.makedirs(dest_dir, exist_ok=True)
        
        processed_textures = [] 
        
        for usd_attr, tex_path_raw in textures:
            input_name = (usd_attr.split(':')[-1] if ':' in usd_attr else os.path.basename(usd_attr)).lower()
            pbr_type = REMIX_ATTR_SUFFIX_TO_PBR_MAP.get(input_name)
            if not pbr_type: continue
            
            abs_path = os.path.normpath(tex_path_raw) if os.path.isabs(tex_path_raw) else (os.path.join(remix_proj_dir, tex_path_raw) if remix_proj_dir else None)
            if not abs_path or not os.path.isfile(abs_path): continue
            
            final_path = abs_path
            if abs_path.lower().endswith((".dds", ".rtex.dds")):
                if status_callback:
                    status_callback.emit(f"Converting {os.path.basename(abs_path)}...")

                texconv = self.settings.get("texconv_path")
                if not texconv or not os.path.isfile(texconv):
                    local = os.path.join(PLUGIN_DIR, "texconv.exe")
                    if os.path.isfile(local):
                        texconv = local

                if not texconv:
                    self.log_warning("texconv.exe not configured; cannot convert DDS to PNG. Skipping.")
                    continue

                try:
                    final_path = self.texture_processor.convert_dds_to_png(texconv, abs_path, "", dest_dir)
                except Exception as e:
                    self.log_warning(f"Conversion failed: {e}")
                    # Fallback: copy the DDS as-is and try importing it directly into Painter.
                    try:
                        dds_target = os.path.join(dest_dir, os.path.basename(abs_path))
                        if os.path.normcase(os.path.abspath(abs_path)) != os.path.normcase(os.path.abspath(dds_target)):
                            shutil.copy2(abs_path, dds_target)
                        final_path = dds_target
                        self.log_warning(f"Using DDS directly (texconv failed): {os.path.basename(final_path)}")
                    except Exception as e2:
                        self.log_warning(f"Fallback DDS copy failed: {e2}")
                        continue
            else:
                try:
                    target = os.path.join(dest_dir, os.path.basename(abs_path))
                    shutil.copy2(abs_path, target)
                    final_path = target
                except Exception as e:
                    self.log_warning(f"Failed to copy {abs_path}: {e}")
                    continue

            if final_path and os.path.isfile(final_path):
                processed_textures.append((pbr_type, final_path))
            
        return processed_textures

    def _pull_step4_assign(self, processed_textures):
        self.log_info(f"Pull Step 3 Complete. Assigning {len(processed_textures)} textures...")
        import substance_painter.resource
        import substance_painter.textureset
        
        ts_list = substance_painter.textureset.all_texture_sets()
        if not ts_list: return
        target_ts = ts_list[0]
        stack = self._get_texture_set_stack(target_ts)
        if not stack:
            self.log_warning("Could not retrieve texture set stack; cannot assign textures.")
            return

        # Ensure channels exist before assignment (some Painter APIs raise on get_channel when missing)
        needed = []
        for pbr_type, _ in processed_textures:
            painter_channel = self.painter_controller.REMIX_PBR_TO_PAINTER_CHANNEL_MAP.get(pbr_type)
            ctype = self.painter_controller.PAINTER_STRING_TO_CHANNELTYPE_MAP.get(painter_channel) if painter_channel else None
            if painter_channel and ctype:
                needed.append((painter_channel, ctype))
        for label, ctype in {k: v for (k, v) in needed}.items():
            self._ensure_stack_channel(stack, ctype, label)
        
        for pbr_type, path in processed_textures:
            try:
                res = substance_painter.resource.import_project_resource(path, substance_painter.resource.Usage.TEXTURE)
                rid = res.identifier()

                painter_channel = self.painter_controller.REMIX_PBR_TO_PAINTER_CHANNEL_MAP.get(pbr_type)
                if not painter_channel:
                    continue

                ctype = self.painter_controller.PAINTER_STRING_TO_CHANNELTYPE_MAP.get(painter_channel)
                if not ctype:
                    continue

                channel = self._ensure_stack_channel(stack, ctype, painter_channel)
                if not channel:
                    continue
                self.painter_controller.assign_texture_to_channel(channel, rid)
            except Exception as e:
                self.log_warning(f"Failed to assign {path}: {e}")
        
        self.display_message("Operation completed successfully.")

    # --- Import Textures ---
    def handle_import_textures(self):
        try:
            import substance_painter.project

            if not substance_painter.project.is_open():
                self.display_message("No project open.")
                return

            meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
            linked_material_prim = meta.get("remix_material_prim")
            if not linked_material_prim:
                self.display_message("Project not linked to Remix.")
                return

            self.log_info("Starting Import Textures (Async)...")
            worker = Worker(self._pull_step3_fetch_process_textures, linked_material_prim)
            self._start_worker(worker, on_result=self._pull_step4_assign, title="Import Textures from Remix")
        except Exception as e:
            self.log_error(f"Import Textures failed: {e}", exc_info=True)
            self.display_message(f"Import Textures failed: {e}")

    # --- Push ---
    def handle_push_to_remix(self):
        self._start_push(force_new_root=False)

    def handle_relink_and_push_to_remix(self):
        self.log_info("Relinking...")
        worker = Worker(self._relink_step1)
        self._start_worker(worker, on_result=self._relink_step2_push, title="Relink Material (Remix)")

    def _relink_step1(self, progress_callback=None, status_callback=None):
        _, material_prim, _, err = self.remix_api.get_selected_asset_details()
        if err: raise Exception(err)
        import re
        m = re.search(r'([A-Z0-9]{16})$', material_prim)
        if not m: raise Exception("Invalid material hash")
        return material_prim, m.group(1)

    def _relink_step2_push(self, result):
        material_prim, material_hash = result
        import substance_painter.project
        if not substance_painter.project.is_open(): return
        
        meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
        meta.set("remix_material_prim", material_prim)
        meta.set("remix_material_hash", material_hash)
        
        self.display_message(f"Relinked to {material_prim}. Starting Force Push...")
        self._start_push(force_new_root=True)

    def _start_push(self, force_new_root=False):
        try:
            import substance_painter.project

            if not substance_painter.project.is_open():
                self.display_message("No project open.")
                return

            meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
            linked_material_prim = meta.get("remix_material_prim")
            if not linked_material_prim:
                self.display_message("Project not linked to Remix.")
                return

            self.display_message("Exporting textures...")
            export_path = self.settings.get("painter_export_path") or os.path.join(tempfile.gettempdir(), "RemixConnector_Export")
            os.makedirs(export_path, exist_ok=True)

            # Ensure required channels exist so export can generate emissive/opacity-based maps.
            self._ensure_required_channels_for_export()
            exported_files = self._export_textures_main_thread(export_path)

            worker = Worker(self._push_step2_ingest_update, exported_files, force_new_root, linked_material_prim)
            worker.signals.result.connect(lambda res: self.display_message(res))
            self._start_worker(worker, title="Push to Remix")

        except Exception as e:
            self.log_error(f"Push Init Failed: {e}", exc_info=True)
            self.display_message(f"Push failed: {e}")

    def _export_textures_main_thread(self, export_path):
        import substance_painter.export
        import substance_painter.project
        import substance_painter.textureset
        
        meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
        material_hash = meta.get("remix_material_hash")
        if not material_hash: raise Exception("Missing material hash")

        all_ts = substance_painter.textureset.all_texture_sets()
        if not all_ts: raise Exception("No texture sets")
        
        export_format = self.settings.get("export_file_format", "png")
        preset_name = f"Remix_Dynamic_{material_hash}"
        
        maps_to_create = [
            {"p_channel": "baseColor", "pbr_type": "albedo"},
            {"p_channel": "normal", "pbr_type": "normal"},
            {"p_channel": "roughness", "pbr_type": "roughness"},
            {"p_channel": "metallic", "pbr_type": "metallic"},
            {"p_channel": "height", "pbr_type": "height"},
            {"p_channel": "emissive", "pbr_type": "emissive"}
        ]
        if self.settings.get("include_opacity_map", False):
            maps_to_create.append({"p_channel": "opacity", "pbr_type": "opacity"})

        dynamic_preset_maps = []
        filename_map = {}
        
        base_params = {"fileFormat": export_format, "bitDepth": "8", "paddingAlgorithm": "infinite", "dithering": False, "sizeMultiplier": 1, "keepAlpha": True}

        for map_info in maps_to_create:
            p_chan = map_info["p_channel"]
            pbr = map_info["pbr_type"]
            fname = f"{material_hash}_{pbr}"
            
            full_path = os.path.join(export_path, f"{fname}.{export_format}").replace('\\', '/')
            filename_map[full_path] = pbr
            
            ch_conf = []
            if p_chan == 'baseColor': ch_conf = [{"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "R", "destChannel": "R"}, {"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "G", "destChannel": "G"}, {"srcMapType": "documentMap", "srcMapName": "baseColor", "srcChannel": "B", "destChannel": "B"}, {"srcMapType": "documentMap", "srcMapName": "opacity", "srcChannel": "L", "destChannel": "A"}]
            elif p_chan == 'normal': ch_conf = [{"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "R", "destChannel": "R"}, {"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "G", "destChannel": "G"}, {"srcMapType": "documentMap", "srcMapName": "normal", "srcChannel": "B", "destChannel": "B"}]
            elif p_chan == 'emissive': ch_conf = [{"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "R", "destChannel": "R"}, {"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "G", "destChannel": "G"}, {"srcMapType": "documentMap", "srcMapName": "emissive", "srcChannel": "B", "destChannel": "B"}]
            else: ch_conf = [{"srcMapType": "documentMap", "srcMapName": p_chan, "srcChannel": "L", "destChannel": "L"}]
            
            dynamic_preset_maps.append({"fileName": fname, "parameters": base_params, "channels": ch_conf})

        export_config = {
            "exportShaderParams": False, "exportPath": export_path,
            "exportPresets": [{ "name": preset_name, "maps": dynamic_preset_maps }],
            "exportList": [{"rootPath": ts.name(), "exportPreset": preset_name} for ts in all_ts]
        }
        
        res = substance_painter.export.export_project_textures(export_config)
        if res.status != substance_painter.export.ExportStatus.Success:
            raise Exception(f"Export failed: {res.message}")
            
        exported = {}
        for ts, files in res.textures.items():
            for f in files:
                norm = f.replace('\\', '/')
                if norm in filename_map:
                    exported[filename_map[norm]] = f
                    
        return exported

    def _push_step2_ingest_update(self, exported_files, force_new_root, linked_material_prim, progress_callback=None, status_callback=None):
        if not exported_files: return "No files exported."
        
        if status_callback: status_callback.emit("Ingesting textures...")
        remix_proj_dir, _ = self.remix_api.get_project_default_output_dir()
        
        # Force Push: avoid overwriting existing ingested textures by renaming exported files to a non-conflicting root.
        if force_new_root and remix_proj_dir:
            try:
                output_subfolder = self.settings.get("remix_output_subfolder", "Textures/PainterConnector_Ingested").strip("/\\")
                ingest_dir_abs = os.path.normpath(os.path.join(remix_proj_dir, output_subfolder))
                os.makedirs(ingest_dir_abs, exist_ok=True)

                # Derive desired root from linked material hash (fallback: first exported filename stem)
                desired_root = None
                m = re.search(r"([A-Z0-9]{16})$", str(linked_material_prim))
                if m:
                    desired_root = m.group(1)
                if not desired_root and exported_files:
                    first_path = next(iter(exported_files.values()))
                    stem = os.path.splitext(os.path.basename(first_path))[0]
                    desired_root = stem.split("_", 1)[0] if stem else "ForcePush"

                forced_root = self.texture_processor.choose_non_overwriting_root(desired_root or "ForcePush", ingest_dir_abs)
                if forced_root and desired_root and forced_root != desired_root:
                    self.log_debug(f"ForcePush root chosen: desired={desired_root} forced={forced_root} ingestDir={ingest_dir_abs}")

                    renamed = {}
                    temp_root = os.path.dirname(next(iter(exported_files.values()))) if exported_files else tempfile.gettempdir()
                    for pbr, path in exported_files.items():
                        forced_stem = f"{forced_root}_{pbr}"
                        new_path, err = self.texture_processor.copy_texture_with_forced_root(path, forced_stem, pbr, temp_root)
                        if new_path:
                            renamed[pbr] = new_path
                        else:
                            self.log_warning(err or f"ForcePush rename failed for {pbr}")
                    if renamed:
                        exported_files = renamed
            except Exception as e:
                self.log_warning(f"Force Push rename step failed (continuing without rename): {e}")

        ingested_paths = {}
        for pbr, path in exported_files.items():
            res, err = self.remix_api.ingest_texture(pbr, path, remix_proj_dir)
            if res:
                ingested_paths[pbr] = res
            else:
                self.log_warning(f"Ingest failed for {pbr}: {err}")
            
        if not ingested_paths: raise Exception("Ingestion failed")
        
        if status_callback: status_callback.emit("Updating Remix...")
        textures_to_update = []
        for pbr, path in ingested_paths.items():
            mdl = PBR_TO_MDL_INPUT_MAP.get(pbr)
            if pbr == "metallic" and mdl == "metalness_texture": mdl = "metallic_texture"
            if mdl: textures_to_update.append((f"{linked_material_prim}/Shader.inputs:{mdl}", path))
            
        success, err = self.remix_api.update_textures_batch(textures_to_update)
        if not success: raise Exception(f"Update failed: {err}")
        
        self.remix_api.save_layer(linked_material_prim)
        return "Push Complete"

    def handle_settings(self):
        parent = None
        try:
            import substance_painter.ui
            parent = substance_painter.ui.get_main_window()
        except: pass

        def _test_connection(candidate_settings):
            try:
                candidate = sanitize_settings(candidate_settings or {}, PLUGIN_DIR)
                tmp_client = RemixAPIClient(lambda: candidate, self.logger_adapter)
                return tmp_client.ping(timeout=2.0)
            except Exception as e:
                return False, str(e)

        dialog = create_settings_dialog_instance(
            self.settings,
            parent,
            test_connection_fn=_test_connection,
            log_file_path=self._log_file_path,
        )

        try:
            ok = dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()
        except Exception:
            ok = dialog.exec_()

        if ok:
            self.settings = sanitize_settings(dialog.get_settings(), PLUGIN_DIR)
            self.save_settings()
            self.display_message("Settings saved.")

    def _build_diagnostics_text(self):
        lines = []
        lines.append(f"{PLUGIN_NAME} v{PLUGIN_VERSION}")
        lines.append("")
        lines.append(f"Plugin dir: {PLUGIN_DIR}")
        lines.append(f"Settings file: {SETTINGS_FILE_PATH}")
        lines.append(f"Log file: {self._log_file_path}")
        lines.append(f"Python: {sys.version.replace(os.linesep, ' ')}")
        lines.append(f"Qt binding: {QT_BINDING}")
        lines.append("")

        # Connection check
        try:
            ok, msg = self.remix_api.ping(timeout=2.0)
        except Exception as e:
            ok, msg = False, str(e)
        lines.append(f"Remix API ping: {'OK' if ok else 'FAIL'} - {msg}")
        lines.append("")

        # Key settings
        s = self.settings or {}
        def _path_status(p):
            try:
                return "OK" if p and os.path.exists(p) else "MISSING"
            except Exception:
                return "?"

        lines.append("Key settings:")
        lines.append(f"  api_base_url: {s.get('api_base_url')}")
        lines.append(f"  texconv_path: {s.get('texconv_path')} ({_path_status(s.get('texconv_path'))})")
        lines.append(f"  blender_executable_path: {s.get('blender_executable_path')} ({_path_status(s.get('blender_executable_path'))})")
        lines.append(f"  painter_export_path: {s.get('painter_export_path')}")
        lines.append(f"  remix_output_subfolder: {s.get('remix_output_subfolder')}")
        lines.append(f"  include_opacity_map: {s.get('include_opacity_map')}")
        lines.append(f"  auto_unwrap_with_blender_on_pull: {s.get('auto_unwrap_with_blender_on_pull')}")
        lines.append("")

        # Project link info (if available)
        try:
            import substance_painter.project
            if substance_painter.project.is_open():
                meta = substance_painter.project.Metadata("RTXRemixConnectorLink")
                lines.append("Active project link:")
                lines.append(f"  remix_material_prim: {meta.get('remix_material_prim')}")
                lines.append(f"  remix_material_hash: {meta.get('remix_material_hash')}")
        except Exception:
            pass

        lines.append("")
        lines.append(f"Repo: {PLUGIN_REPO_URL}")
        return "\n".join(lines)

    def handle_diagnostics(self):
        try:
            dlg = DiagnosticsDialog(self._build_diagnostics_text(), self._get_ui_parent())
            dlg.exec_()
        except Exception as e:
            self.log_error(f"Diagnostics failed: {e}", exc_info=True)
            self.display_message(f"Diagnostics failed: {e}")

    def handle_about(self):
        try:
            if QtWidgets:
                QtWidgets.QMessageBox.information(
                    self._get_ui_parent(),
                    f"About {PLUGIN_NAME}",
                    f"{PLUGIN_NAME} v{PLUGIN_VERSION}\n\n{PLUGIN_DESCRIPTION}\n\n{PLUGIN_REPO_URL}",
                )
            else:
                self.display_message(f"{PLUGIN_NAME} v{PLUGIN_VERSION}")
        except Exception:
            self.display_message(f"{PLUGIN_NAME} v{PLUGIN_VERSION}")

plugin_instance = None
PLUGIN_SETTINGS = {}

def setup_logging():
    global plugin_instance, PLUGIN_SETTINGS
    plugin_instance = RemixConnectorPlugin()
    PLUGIN_SETTINGS = plugin_instance.settings

def handle_pull_from_remix(): plugin_instance.handle_pull_from_remix()
def handle_import_textures(): plugin_instance.handle_import_textures()
def handle_push_to_remix(): plugin_instance.handle_push_to_remix()
def handle_relink_and_push_to_remix(): plugin_instance.handle_relink_and_push_to_remix()
def handle_settings(): plugin_instance.handle_settings()
def handle_diagnostics(): plugin_instance.handle_diagnostics()
def handle_about(): plugin_instance.handle_about()
def load_plugin_settings(): pass # handled by class
def save_plugin_settings(): plugin_instance.save_settings()

if __name__ == "__main__":
    setup_logging()

import os
import sys
import json
import tempfile
import traceback
import time
import shutil
import re
import threading
from concurrent.futures import ThreadPoolExecutor

# Cap concurrent texconv subprocesses. Remix ingests are capped lower: each one
# spawns a Kit process that converts on the GPU, and the Toolkit's own default
# is 2 concurrent conversions to avoid running out of VRAM.
_PIPELINE_MAX_WORKERS = min(4, (os.cpu_count() or 4))
_INGEST_MAX_WORKERS = 2

# Local imports
from .qt_utils import QObject, Signal, Slot, QThreadPool, QtWidgets, QtCore, QtGui, QT_BINDING
from .plugin_info import PLUGIN_NAME, PLUGIN_VERSION, PLUGIN_REPO_URL, PLUGIN_DESCRIPTION
from .remix_api import RemixAPIClient, REMIX_ATTR_SUFFIX_TO_PBR_MAP, PBR_TO_MDL_INPUT_MAP, material_hash_from_prim
from .texture_processor import TextureProcessor, read_image_size, is_octahedral_normal_name
from .painter_controller import PainterController, aspect_matched_resolution
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
PULLED_TEXTURES_DIR = os.path.join(PLUGIN_DIR, "Pulled Textures")
WORK_DIR = os.path.join(PLUGIN_DIR, "_temp")
DEFAULT_TILING_MESH = os.path.join("assets", "meshes", "plane_tiling.usd")
DEFAULT_TEMPLATE_NAME = "PBR - Metallic Roughness Alpha-blend.spt"

# Project metadata context. Kept from earlier releases so existing .spp files stay linked.
METADATA_CONTEXT = "RTXRemixConnectorLink"

# Exported file suffix per PBR type. "_Normal" lets Remix's octahedral
# conversion produce the conventional "<hash>_OTH_Normal" name.
EXPORT_FILE_SUFFIX = {
    "albedo": "Albedo",
    "normal": "Normal",
    "roughness": "Roughness",
    "metallic": "Metallic",
    "height": "Height",
    "emissive": "Emissive",
}
_PUSH_ORDER = ("albedo", "normal", "roughness", "metallic", "height", "emissive")


# Link keys describing where the material came from; cleared on relink.
_LINK_SOURCE_KEYS = ("remix_original_width", "remix_original_height", "remix_project_file",
                     "remix_mesh_prims", "remix_source_mesh")


class RemixError(Exception):
    """An expected failure with a message meant for the user (no traceback)."""


def _material_file_key(material_prim):
    """File-name root for a material: its capture hash, or its sanitized prim
    name for materials that have none (e.g. ones authored in a replacement)."""
    key = material_hash_from_prim(material_prim)
    if key:
        return key
    name = str(material_prim or "").rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9_]", "_", name) or "Material"


def build_export_maps(material_hash, present_pbr, normal_map_format="opengl", export_format="png"):
    """Painter export-preset maps for the channels that exist in the stack.

    The normal map uses Painter's ``Normal_OpenGL``/``Normal_DirectX`` virtual
    map, which bakes the height channel and any baked normal map into the
    normal channel (the plain ``normal`` document map omits both). Opacity
    rides in the albedo alpha, which is where AperturePBR reads it.

    Returns (maps, {file stem: pbr type}).
    """
    params = {"fileFormat": export_format, "bitDepth": "8", "paddingAlgorithm": "infinite",
              "dithering": False, "keepAlpha": True}

    def rgb(map_type, name):
        return [{"srcMapType": map_type, "srcMapName": name, "srcChannel": c, "destChannel": c} for c in "RGB"]

    def mono(name):
        return [{"srcMapType": "documentMap", "srcMapName": name, "srcChannel": "L", "destChannel": "L"}]

    channels = {}
    if "albedo" in present_pbr:
        channels["albedo"] = rgb("documentMap", "baseColor")
        if "opacity" in present_pbr:
            channels["albedo"].append({"srcMapType": "documentMap", "srcMapName": "opacity", "srcChannel": "L", "destChannel": "A"})
    if "normal" in present_pbr or "height" in present_pbr:
        virtual = "Normal_DirectX" if normal_map_format == "directx" else "Normal_OpenGL"
        channels["normal"] = rgb("virtualMap", virtual)
    for pbr in ("roughness", "metallic", "height"):
        if pbr in present_pbr:
            channels[pbr] = mono(pbr)
    if "emissive" in present_pbr:
        channels["emissive"] = rgb("documentMap", "emissive")

    maps, stems = [], {}
    for pbr in _PUSH_ORDER:
        if pbr not in channels:
            continue
        stem = f"{material_hash}_{EXPORT_FILE_SUFFIX[pbr]}"
        stems[stem.lower()] = pbr
        maps.append({"fileName": stem, "parameters": dict(params), "channels": channels[pbr]})
    return maps, stems


def aspect_restore_size(cur_w, cur_h, orig_w, orig_h, tolerance=0.01):
    """Size that restores the original aspect ratio while keeping the long side,
    or None when the export already matches."""
    if not (cur_w and cur_h and orig_w and orig_h):
        return None
    orig_aspect = float(orig_w) / float(orig_h)
    if abs((float(cur_w) / float(cur_h)) - orig_aspect) <= tolerance * orig_aspect:
        return None
    max_dim = max(cur_w, cur_h)
    if orig_aspect >= 1.0:
        target = (max_dim, int(round(max_dim / orig_aspect)))
    else:
        target = (int(round(max_dim * orig_aspect)), max_dim)
    target = (max(1, target[0]), max(1, target[1]))
    return None if target == (cur_w, cur_h) else target


class _MainThreadInvoker(QObject):
    """Runs callables on the thread that owns it (the GUI thread).

    Emitting a signal is thread-safe and the slot connection is queued, so
    worker threads can hand results back without touching Qt or Painter.
    """
    _call = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._call.connect(self._run, QtCore.Qt.QueuedConnection)

    @Slot(object)
    def _run(self, fn):
        try:
            fn()
        except Exception:
            traceback.print_exc()

    def post(self, fn):
        self._call.emit(fn)


class _ProgressBridge(QObject):
    """
    Tiny QObject that lives on the GUI thread and forwards progress
    integers to a QProgressDialog. Existing only as a QObject is what
    causes Qt to use a queued connection from worker threads.
    """
    def __init__(self, dialog, parent=None):
        super().__init__(parent)
        self._dialog = dialog

    @Slot(int)
    def on_progress(self, pct):
        dlg = self._dialog
        if dlg is None:
            return
        try:
            if dlg.maximum() == 0:
                dlg.setRange(0, 100)
            dlg.setValue(int(pct))
        except Exception:
            pass


class RemixConnectorPlugin(QObject):
    # Emitted on the GUI thread whenever connection, link or busy state changes.
    state_changed = Signal()

    def __init__(self):
        super().__init__()
        self._active_workers = set()
        self._active_progress_dialogs = {}
        self._workers_lock = threading.Lock()
        self._log_lock = threading.Lock()
        self._shutting_down = False
        self._log_file_path = LOG_FILE_PATH
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
        except OSError:
            pass

        self.settings = {}
        self.load_settings()

        self.logger_adapter = {
            'info': self.log_info,
            'debug': self.log_debug,
            'warning': self.log_warning,
            'error': self.log_error
        }

        self._invoker = _MainThreadInvoker(self)
        self.remix_api = RemixAPIClient(self.get_settings, self.logger_adapter)
        # TextureProcessor reports from worker threads, so its messages are posted to the GUI thread.
        self.texture_processor = TextureProcessor(self.get_settings, self.logger_adapter, self.post_message)
        self.painter_controller = PainterController(self.logger_adapter)

        # Use a dedicated thread pool so we can wait for our own workers
        # at shutdown without blocking on unrelated Painter tasks.
        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(max(2, QThreadPool.globalInstance().maxThreadCount()))

        self._operation = None
        self._awaiting_project = False
        self._last_message = ""
        self._panel = None
        self._connection = {"ok": None, "message": "Not checked yet"}
        self._ping_in_flight = False
        self._event_handlers = []
        self._connect_painter_events()

    # --- Worker lifecycle ---
    def _get_ui_parent(self):
        try:
            import substance_painter.ui
            return substance_painter.ui.get_main_window()
        except Exception:
            return None

    def _start_worker(self, fn, *args, on_result=None, on_error=None, title=None, show_progress=True, operational=True):
        """
        Runs ``fn(*args)`` on the plugin thread pool and keeps a strong reference
        until it finishes. ``on_result``/``on_error`` are always invoked on the
        GUI thread; worker threads never touch Qt widgets or Painter.

        ``operational`` marks work that belongs to the running user operation:
        its failures end that operation. Background work (connection pings,
        diagnostics) passes False so it can never release another operation's lock.
        """
        if self._shutting_down:
            self.log_warning("Plugin is shutting down; refusing to start new worker.")
            return None

        worker = Worker(fn, *args)
        with self._workers_lock:
            self._active_workers.add(worker)

        progress_dialog = None
        if show_progress and QtWidgets and QtCore:
            try:
                progress_dialog = QtWidgets.QProgressDialog("Working...", "Hide", 0, 0, self._get_ui_parent())
                progress_dialog.setWindowTitle(title or PLUGIN_NAME)
                progress_dialog.setWindowModality(QtCore.Qt.NonModal)
                progress_dialog.setMinimumDuration(400)
                progress_dialog.setAutoClose(False)
                progress_dialog.setAutoReset(False)
                progress_dialog.setMinimumWidth(380)
                progress_dialog.setValue(0)
                # Hide-only: the operation keeps running in the background.
                try:
                    progress_dialog.canceled.connect(progress_dialog.hide)
                except (AttributeError, TypeError):
                    pass
                with self._workers_lock:
                    self._active_progress_dialogs[worker] = progress_dialog
                try:
                    worker.signals.status.connect(progress_dialog.setLabelText, QtCore.Qt.QueuedConnection)
                except (AttributeError, TypeError):
                    pass
                # Parented to the dialog so it is destroyed with it.
                helper = _ProgressBridge(progress_dialog, parent=progress_dialog)
                try:
                    worker.signals.progress.connect(helper.on_progress, QtCore.Qt.QueuedConnection)
                except (AttributeError, TypeError):
                    pass
            except Exception as e:
                self.log_debug(f"Progress dialog setup failed (non-fatal): {e}")
                progress_dialog = None

        # These closures run on the worker thread (DirectConnection) and only
        # post to the invoker, which runs the real handler on the GUI thread.
        direct = QtCore.Qt.DirectConnection
        worker.signals.result.connect(
            lambda res: self._invoker.post(lambda: self._dispatch(on_result, res, operational)) if on_result else None, direct)
        worker.signals.error.connect(
            lambda err: self._invoker.post(lambda: self._on_worker_error(err, on_error, operational)), direct)
        worker.signals.finished.connect(
            lambda w=worker: self._invoker.post(lambda: self._on_worker_finished(w)), direct)

        self.threadpool.start(worker)
        return worker

    def _dispatch(self, callback, value, operational=True):
        if self._shutting_down:
            return
        try:
            callback(value)
        except Exception as e:
            if not isinstance(e, RemixError):
                self.log_error(f"Unexpected error: {e}", exc_info=True)
            if operational:
                self._fail_operation(str(e))
            else:
                self.show_error("Error", str(e))

    def _on_worker_finished(self, worker):
        """Runs on the GUI thread. Safe to touch Qt."""
        with self._workers_lock:
            self._active_workers.discard(worker)
            dlg = self._active_progress_dialogs.pop(worker, None)
        if dlg is not None:
            try:
                dlg.close()
            except Exception:
                pass
            try:
                dlg.deleteLater()
            except Exception:
                pass
        try:
            worker.signals.deleteLater()
        except Exception:
            pass

    def _on_worker_error(self, err_tuple, on_error=None, operational=True):
        exctype, value, tb = err_tuple
        if isinstance(value, RemixError):
            self.log_warning(str(value))
        else:
            self.log_error(f"Worker Error: {value}\n{tb}")
        if self._shutting_down:
            return
        if on_error:
            self._dispatch(on_error, value, operational)
        elif operational:
            self._fail_operation(str(value))
        else:
            self.show_error("Error", str(value))

    def shutdown(self, wait_ms=5000):
        """
        Cleanly tear the plugin down: stop accepting new work, close
        progress dialogs, then wait briefly for in-flight workers.

        Returns True if the threadpool drained inside ``wait_ms``; the
        caller should only release ``self`` (e.g. ``deleteLater``) when
        this returns True.
        """
        self._shutting_down = True
        self._disconnect_painter_events()

        with self._workers_lock:
            dialogs = list(self._active_progress_dialogs.values())
            self._active_progress_dialogs.clear()

        for dlg in dialogs:
            try:
                dlg.close()
            except Exception:
                pass
            try:
                dlg.deleteLater()
            except Exception:
                pass

        try:
            self.threadpool.clear()  # remove queued runnables that haven't started
        except Exception:
            pass

        drained = False
        try:
            drained = bool(self.threadpool.waitForDone(int(wait_ms)))
        except Exception:
            drained = False

        with self._workers_lock:
            self._active_workers.clear()

        # Release HTTP connection pool.
        try:
            if hasattr(self, "remix_api") and hasattr(self.remix_api, "close"):
                self.remix_api.close()
        except Exception:
            pass

        return drained

    # --- Operations (one at a time) ---
    @property
    def current_operation(self):
        return self._operation

    def _begin_operation(self, label):
        if self._shutting_down:
            return False
        if self._operation:
            self.display_message(f"{self._operation} is still running. Try again when it finishes.", level="notice")
            return False
        self._operation = label
        self._last_message = ""
        self._emit_state()
        return True

    def _finish_operation(self, message=None, level="info"):
        label = self._operation
        self._operation = None
        self._awaiting_project = False
        if message:
            self.display_message(f"{label}: {message}" if label and level != "status" else message, level=level)
        self._emit_state()

    def _fail_operation(self, message):
        label = self._operation or "Operation"
        self._operation = None
        self._awaiting_project = False
        self._last_message = f"{label} failed: {message}"
        self._emit_state()
        if self._shutting_down:
            self.log_info(f"[shutdown] {label} failed: {message}")
            return
        self.show_error(f"{label} failed", str(message))

    def _emit_state(self):
        if self._shutting_down:
            return
        try:
            self.state_changed.emit()
        except Exception:
            pass

    # --- Painter events ---
    def _connect_painter_events(self):
        try:
            import substance_painter.event as sp_event
        except Exception:
            return
        for name in ("ProjectOpened", "ProjectCreated", "ProjectClosed"):
            evt = getattr(sp_event, name, None)
            if evt is None:
                continue
            try:
                sp_event.DISPATCHER.connect(evt, self._on_project_event)
                self._event_handlers.append(evt)
            except Exception as e:
                self.log_debug(f"Could not subscribe to {name}: {e}")

    def _disconnect_painter_events(self):
        try:
            import substance_painter.event as sp_event
        except Exception:
            return
        for evt in self._event_handlers:
            try:
                sp_event.DISPATCHER.disconnect(evt, self._on_project_event)
            except Exception:
                pass
        self._event_handlers = []

    def _on_project_event(self, event):
        # A pull waiting for the new project to settle can't continue if it closed.
        if type(event).__name__ == "ProjectClosed" and self._awaiting_project:
            self._fail_operation("The project was closed before the Remix textures could be imported.")
        self._emit_state()

    # --- Settings / logging ---
    def get_settings(self):
        return self.settings

    def _write_log_line(self, level, msg):
        # Serialize file writes so concurrent workers cannot interleave bytes.
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{ts}] [{level.upper()}] {msg}\n"
            with self._log_lock:
                with open(self._log_file_path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception:
            # Never let logging crash the plugin.
            pass

    def _painter_log(self, level, text):
        """Painter's Log window. Its API is GUI-thread only, so worker lines are posted."""
        def _emit():
            fn = getattr(sp_logging, level, None) or sp_logging.info
            try:
                fn(text)
            except Exception:
                pass
        if threading.current_thread() is threading.main_thread():
            _emit()
        elif not self._shutting_down:
            self._invoker.post(_emit)

    def log_info(self, msg):
        if self.settings.get("log_level", "info") in ["debug", "info"]:
            self._write_log_line("info", msg)
            self._painter_log("info", f"[{PLUGIN_NAME}] {msg}")

    def log_debug(self, msg):
        if self.settings.get("log_level", "info") == "debug":
            self._write_log_line("debug", msg)
            self._painter_log("info", f"[{PLUGIN_NAME} DEBUG] {msg}")

    def log_warning(self, msg):
        if self.settings.get("log_level", "info") in ["debug", "info", "warning"]:
            self._write_log_line("warning", msg)
            self._painter_log("warning", f"[{PLUGIN_NAME}] {msg}")

    def log_error(self, msg, exc_info=False):
        self._write_log_line("error", msg)
        self._painter_log("error", f"[{PLUGIN_NAME}] {msg}")
        if exc_info:
            tb = traceback.format_exc()
            self._write_log_line("error", tb)
            self._painter_log("error", tb)

    def attach_panel(self, panel):
        self._panel = panel

    def _panel_visible(self):
        try:
            return self._panel is not None and self._panel.isVisible()
        except Exception:
            return False

    @property
    def last_message(self):
        return self._last_message

    def display_message(self, msg, level="info"):
        """Tell the user something. GUI thread only (see post_message).

        Painter's Python API has no notification call, so messages go to the
        panel's status line and Painter's Log window. ``level`` decides when a
        dialog is also shown:
          * "status"  - never (progress chatter)
          * "info"    - only when the panel is closed (operation results)
          * "notice"  - always, information icon (the user's action did nothing)
          * "warning" - always, warning icon
        """
        msg = str(msg)
        # Workers can fire results after shutdown begins (Painter closing,
        # plugin reload). We must not touch Painter's UI in that window.
        if self._shutting_down:
            self._write_log_line("info", f"[shutdown] {msg}")
            return
        (self.log_warning if level == "warning" else self.log_info)(msg)
        self._last_message = msg
        self._emit_state()
        if level == "status" or (level == "info" and self._panel_visible()):
            return
        if QtWidgets is None:
            return
        try:
            box = QtWidgets.QMessageBox.warning if level == "warning" else QtWidgets.QMessageBox.information
            box(self._get_ui_parent(), PLUGIN_NAME, msg)
        except Exception:
            pass

    def post_message(self, msg, level="warning"):
        """Thread-safe display_message (used by TextureProcessor for tool failures)."""
        self._invoker.post(lambda m=str(msg): self.display_message(m, level=level))

    def show_error(self, title, message):
        self.log_warning(f"{title}: {message}")
        self._last_message = f"{title}: {message}"
        self._emit_state()
        if QtWidgets is None:
            return
        try:
            QtWidgets.QMessageBox.warning(self._get_ui_parent(), f"{PLUGIN_NAME} - {title}", str(message))
        except Exception:
            pass

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

    def _texconv_path(self):
        texconv = self.settings.get("texconv_path")
        if texconv and os.path.isfile(texconv):
            return texconv
        local = os.path.join(PLUGIN_DIR, "texconv.exe")
        return local if os.path.isfile(local) else None

    def _normal_map_format(self):
        return "directx" if self.settings.get("normal_map_format") == "directx" else "opengl"

    # --- Project link (metadata) ---
    def read_link(self):
        """The Remix link stored in the open project, or None. GUI thread only."""
        try:
            import substance_painter.project
            if not substance_painter.project.is_open():
                return None
            meta = substance_painter.project.Metadata(METADATA_CONTEXT)

            def _get(key):
                try:
                    return meta.get(key)
                except Exception:
                    return None

            prim = _get("remix_material_prim")
            if not isinstance(prim, str) or not prim:
                return None
            return {
                "material_prim": prim,
                "material_hash": _get("remix_material_hash") or _material_file_key(prim),
                "original_width": _get("remix_original_width"),
                "original_height": _get("remix_original_height"),
                "remix_project": _get("remix_project_file"),
            }
        except Exception as e:
            self.log_debug(f"Could not read project link: {e}")
            return None

    def _write_link(self, material_prim, extra=None, relink=False):
        """Store the link. ``relink`` clears facts about the previous material
        (its texture size, mesh, Remix project) so they can't leak into pushes."""
        import substance_painter.project
        meta = substance_painter.project.Metadata(METADATA_CONTEXT)
        values = {}
        if relink:
            values.update({key: "" for key in _LINK_SOURCE_KEYS})
        values.update({"remix_material_prim": material_prim, "remix_material_hash": _material_file_key(material_prim)})
        values.update({k: v for k, v in (extra or {}).items() if v is not None})
        for key, value in values.items():
            meta.set(key, value)
        self._emit_state()

    def link_summary(self):
        link = self.read_link()
        if not link:
            return None
        return link["material_prim"].rsplit("/", 1)[-1]

    def connection_state(self):
        return dict(self._connection)

    # --- Connection monitoring ---
    def refresh_connection(self):
        """Background ping used by the panel; never logs at warning level."""
        if self._ping_in_flight or self._shutting_down:
            return
        self._ping_in_flight = True

        def _done(result):
            self._ping_in_flight = False
            ok, msg = result
            if ok != self._connection.get("ok") or msg != self._connection.get("message"):
                self._connection = {"ok": ok, "message": msg}
                self._emit_state()

        def _failed(error):
            _done((False, str(error)))

        self._start_worker(self._ping_worker, on_result=_done, on_error=_failed, show_progress=False, operational=False)

    def _ping_worker(self, progress_callback=None, status_callback=None):
        return self.remix_api.ping(timeout=1.5, log_failures=False)

    def _require_remix_project(self, status_callback=None):
        """Worker-side guard: fail fast with a clear message when Remix is unusable."""
        if status_callback: status_callback.emit("Connecting to RTX Remix...")
        project, err = self.remix_api.get_project_info(timeout=5.0)
        ok = bool(project)
        self._connection = {"ok": ok, "message": f"Connected - {project['project_name']}" if ok else err}
        self._invoker.post(self._emit_state)
        if not ok:
            raise RemixError(err)
        return project

    def _choose_material(self, materials, title):
        """Pick one material prim; asks when the selection spans several."""
        if len(materials) == 1:
            return materials[0]
        labels = [f"{m.rsplit('/', 1)[-1]}    ({m})" for m in materials]
        item, ok = QtWidgets.QInputDialog.getItem(
            self._get_ui_parent(), f"{PLUGIN_NAME} - {title}",
            "The Remix selection uses several materials.\nWhich one should this project use?",
            labels, 0, False,
        )
        if not ok:
            return None
        return materials[labels.index(item)]

    def _confirm_close_current_project(self):
        """Ask before discarding unsaved work. Returns False to abort."""
        if not self.painter_controller.is_project_open() or not self.painter_controller.needs_saving():
            return True
        Box = QtWidgets.QMessageBox
        box = Box(Box.Warning, PLUGIN_NAME, "The current project has unsaved changes.",
                  Box.Save | Box.Discard | Box.Cancel, self._get_ui_parent())
        box.setInformativeText("Pulling from Remix closes it. Save it first?")
        box.setDefaultButton(Box.Save)
        choice = box.exec()
        if choice == Box.Cancel:
            return False
        if choice == Box.Discard:
            return True
        import substance_painter.project
        try:
            if self.painter_controller.project_file_path():
                substance_painter.project.save()
            else:
                path, _ = QtWidgets.QFileDialog.getSaveFileName(
                    self._get_ui_parent(), "Save Project", "", "Substance 3D Painter project (*.spp)")
                if not path:
                    return False
                substance_painter.project.save_as(path)
            return True
        except Exception as e:
            self.show_error("Save failed", str(e))
            return False

    # --- Pull ---
    def handle_pull_from_remix(self):
        if not self._begin_operation("Pull from Remix"):
            return
        self.log_info("Pull from Remix: reading the Remix selection...")
        self._start_worker(self._pull_fetch, on_result=self._pull_on_fetched, title="Pull from Remix")

    def _pull_fetch(self, progress_callback=None, status_callback=None):
        project = self._require_remix_project(status_callback)

        if status_callback: status_callback.emit("Reading the Remix selection...")
        selection, err = self.remix_api.get_selection()
        if err:
            raise RemixError(err)
        if not selection["materials"] and not selection["meshes"]:
            raise RemixError("Nothing is selected in RTX Remix. Select a mesh (or its material) in the viewport, then pull again.")
        if not selection["materials"]:
            raise RemixError("The Remix selection has no material. Select the mesh in the viewport (its material comes with it), then pull again.")

        mesh_files, mesh_errors, seen = [], [], set()
        if not self.settings.get("use_simple_tiling_mesh_on_pull", False):
            meshes = selection["meshes"]
            for i, mesh_prim in enumerate(meshes, 1):
                if status_callback: status_callback.emit(f"Locating mesh {i}/{len(meshes)}...")
                if progress_callback: progress_callback.emit(int(100 * i / len(meshes)))
                path, err = self.remix_api.resolve_mesh_file(mesh_prim)
                if path:
                    if path.lower() not in seen:
                        seen.add(path.lower())
                        mesh_files.append(path)
                else:
                    mesh_errors.append(f"{mesh_prim}: {err}")
        return {
            "project": project,
            "materials": selection["materials"],
            "meshes": selection["meshes"],
            "mesh_files": mesh_files,
            "mesh_errors": mesh_errors,
        }

    def _pull_on_fetched(self, result):
        material_prim = self._choose_material(result["materials"], "Pull from Remix")
        if not material_prim:
            return self._finish_operation("Pull cancelled.", level="status")

        for err in result["mesh_errors"]:
            self.log_warning(f"Mesh not resolved: {err}")
        mesh_path, note = self._pull_pick_mesh(result, material_prim)

        if not self._confirm_close_current_project():
            return self._finish_operation("Pull cancelled.", level="status")

        link_extra = {
            "remix_project_file": result["project"]["project_file"],
            "remix_mesh_prims": json.dumps(result["meshes"]),
            "remix_source_mesh": mesh_path,
            "plugin_version": PLUGIN_VERSION,
        }
        uses_plane = os.path.normcase(mesh_path) == os.path.normcase(self._tiling_mesh_path())
        if self.settings.get("auto_unwrap_with_blender_on_pull", False) and not uses_plane:
            self.log_info("Auto-unwrap enabled; starting Blender unwrap...")
            unwrap_dir = os.path.join(WORK_DIR, "unwrapped")
            self._start_worker(
                self._pull_unwrap_mesh, mesh_path, unwrap_dir,
                on_result=lambda unwrapped: self._pull_create_project(unwrapped or mesh_path, material_prim, link_extra, note, unwrapped=bool(unwrapped)),
                title="Auto-Unwrap Mesh (Blender)",
            )
            return
        self._pull_create_project(mesh_path, material_prim, link_extra, note)

    def _pull_pick_mesh(self, result, material_prim):
        """The mesh to build the project from, plus a note for the user."""
        if self.settings.get("use_simple_tiling_mesh_on_pull", False):
            return self._tiling_mesh_path(), "Using the tiling plane (Settings > Pull)."
        files = result["mesh_files"]
        if not files:
            return self._tiling_mesh_path(), "No mesh file was found for the selection, so the tiling plane was used."
        if len(files) == 1:
            return files[0], None
        wrapper = self._author_material_group_wrapper(files, material_prim)
        if wrapper:
            return wrapper, f"Bundled {len(files)} selected meshes into one project."
        return files[0], "Could not bundle the selected meshes; using the first one."

    def _tiling_mesh_path(self):
        configured = self.settings.get("simple_tiling_mesh_path") or DEFAULT_TILING_MESH
        path = configured if os.path.isabs(configured) else os.path.join(PLUGIN_DIR, configured)
        if not os.path.isfile(path):
            self.log_warning(f"Tiling mesh not found at '{path}'; using the bundled plane.")
            path = os.path.join(PLUGIN_DIR, DEFAULT_TILING_MESH)
        return os.path.normpath(path)

    def _author_material_group_wrapper(self, mesh_file_paths, material_prim):
        """Write a transient .usda that references every mesh file. Returns the
        wrapper's absolute path, or None on failure.

        The wrapper is keyed by material hash so re-pulls overwrite cleanly.
        Absolute @...@ references with forward-slash paths avoid drive-letter
        and Windows-separator quirks in USD's path resolver.
        """
        if not mesh_file_paths:
            return None
        try:
            material_hash = _material_file_key(material_prim) or "group"

            wrapper_dir = os.path.join(PLUGIN_DIR, "_temp", "material_groups")
            os.makedirs(wrapper_dir, exist_ok=True)
            wrapper_path = os.path.join(wrapper_dir, f"{material_hash}.usda")

            lines = [
                "#usda 1.0",
                "(",
                '    defaultPrim = "Substance2RemixGroup"',
                '    upAxis = "Y"',
                "    metersPerUnit = 0.01",
                ")",
                "",
                'def Xform "Substance2RemixGroup"',
                "{",
            ]
            for idx, abs_path in enumerate(mesh_file_paths):
                ref = abs_path.replace('\\', '/')
                # USD ASCII child names must be valid identifiers; index keeps them unique.
                stem = os.path.splitext(os.path.basename(abs_path))[0]
                safe_stem = re.sub(r'[^A-Za-z0-9_]', '_', stem) or "mesh"
                lines.append(f'    def "mesh_{idx}_{safe_stem}" ( prepend references = @{ref}@ )')
                lines.append("    {")
                lines.append("    }")
            lines.append("}")
            lines.append("")

            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            self.log_info(f"Wrote material-group wrapper with {len(mesh_file_paths)} mesh references: {wrapper_path}")
            return wrapper_path
        except Exception as e:
            self.log_error(f"Failed to author material-group wrapper: {e}", exc_info=True)
            return None

    def _pull_unwrap_mesh(self, mesh_path, output_dir, progress_callback=None, status_callback=None):
        if status_callback:
            status_callback.emit("Unwrapping mesh with Blender...")
        return self.texture_processor.unwrap_mesh_with_blender(mesh_path, output_dir=output_dir) or ""

    def _resolve_project_template(self):
        """A .spt template path for project creation, or None for Painter's default."""
        configured = (self.settings.get("painter_import_template_path") or "").strip()
        if configured:
            if os.path.isfile(configured) and configured.lower().endswith(".spt"):
                return configured
            self.log_warning(f"Configured project template not found: '{configured}'. Using the default template.")
        try:
            import substance_painter.resource
            shelf = substance_painter.resource.Shelves.application_shelf()
            candidate = os.path.join(shelf.path(), "templates", DEFAULT_TEMPLATE_NAME)
            if os.path.isfile(candidate):
                return candidate
        except Exception as e:
            self.log_debug(f"Starter template lookup failed: {e}")
        return None

    def _pull_create_project(self, mesh_path, material_prim, link_extra, note=None, unwrapped=False):
        import substance_painter.project

        if self.painter_controller.is_project_open():
            self.painter_controller.close_project()

        settings = substance_painter.project.Settings(
            import_cameras=False,
            normal_map_format=(substance_painter.project.NormalMapFormat.DirectX
                               if self._normal_map_format() == "directx"
                               else substance_painter.project.NormalMapFormat.OpenGL),
            default_texture_resolution=int(self.settings.get("project_texture_resolution", 2048)),
        )
        template = self._resolve_project_template()
        self.log_info(f"Creating Painter project from mesh: {mesh_path}" + (f" (template: {os.path.basename(template)})" if template else ""))
        substance_painter.project.create(mesh_file_path=mesh_path, template_file_path=template, settings=settings)
        self._write_link(material_prim, link_extra)

        notes = [n for n in (note,) if n]
        if unwrapped:
            notes.append("The mesh was re-unwrapped in Blender: its UVs no longer match the mesh in Remix, "
                         "so pushed textures only line up after you replace that mesh in Remix.")
        material_name = material_prim.rsplit("/", 1)[-1]

        if not self.settings.get("auto_import_textures_on_pull", True):
            notes.insert(0, f"Project created and linked to {material_name}.")
            return self._finish_operation(" ".join(notes))

        # Painter computes for a moment after creating a project; layer edits must wait.
        self._awaiting_project = True

        def _continue():
            if not self._awaiting_project or self._operation is None:
                return
            self._awaiting_project = False
            try:
                self._import_start(material_prim, adjust_resolution=True, notes=notes)
            except Exception as e:
                self.log_error(f"Import after pull failed: {e}", exc_info=True)
                self._fail_operation(str(e))

        substance_painter.project.execute_when_not_busy(_continue)

    # --- Import textures ---
    def handle_import_textures(self):
        link = self.read_link()
        if not link:
            return self.display_message("Open a project linked to Remix first (Pull from Remix, or Link to Selected Remix Material).", level="notice")
        if not self._begin_operation("Import Textures from Remix"):
            return
        self._import_start(link["material_prim"], adjust_resolution=False)

    def _import_start(self, material_prim, adjust_resolution=False, notes=None):
        self.log_info(f"Importing textures of {material_prim}...")
        self._start_worker(
            self._import_fetch, material_prim,
            on_result=lambda result: self._import_assign(result, adjust_resolution, notes or []),
            title="Import Textures from Remix",
        )

    def _import_fetch(self, material_prim, progress_callback=None, status_callback=None):
        project = self._require_remix_project(status_callback)
        if status_callback: status_callback.emit("Fetching material textures...")
        textures, err = self.remix_api.get_material_textures(material_prim)
        if err:
            raise RemixError(err)

        notes = []
        work_items, seen = [], set()
        for usd_attr, tex_path_raw in textures or []:
            input_name = str(usd_attr).split(':')[-1].lower()
            pbr_type = REMIX_ATTR_SUFFIX_TO_PBR_MAP.get(input_name)
            if not pbr_type or pbr_type in seen or not tex_path_raw:
                continue
            abs_path = os.path.normpath(str(tex_path_raw))
            if not os.path.isabs(abs_path):
                abs_path = os.path.normpath(os.path.join(project["project_dir"], abs_path))
            if not os.path.isfile(abs_path):
                notes.append(f"{pbr_type}: file not found ({os.path.basename(abs_path)})")
                continue
            seen.add(pbr_type)
            work_items.append((pbr_type, abs_path))

        if not work_items:
            return {"material_prim": material_prim, "textures": [], "source_size": (0, 0), "notes": notes}

        material_hash = _material_file_key(material_prim)
        dest_dir = os.path.join(PULLED_TEXTURES_DIR, project["project_name"], material_hash)
        os.makedirs(dest_dir, exist_ok=True)
        texconv = self._texconv_path()
        target_opengl = self._normal_map_format() == "opengl"

        total = len(work_items)
        done_counter = [0]
        progress_lock = threading.Lock()

        def _bump_progress():
            with progress_lock:
                done_counter[0] += 1
                pct = int(100 * done_counter[0] / total)
            if progress_callback:
                try: progress_callback.emit(pct)
                except Exception: pass

        def _process_one(pbr_type, abs_path):
            size = read_image_size(abs_path)
            if abs_path.lower().endswith(".dds"):
                if not texconv:
                    raise RemixError("texconv.exe is missing, so DDS textures can't be converted.")
                try:
                    final_path = self.texture_processor.convert_dds_to_png(texconv, abs_path, "", dest_dir, force_rgba=(pbr_type == "normal"))
                except Exception as e:
                    if pbr_type == "normal":
                        raise
                    # Painter reads most DDS formats directly; fall back to the raw file.
                    self.log_warning(f"Conversion failed for {os.path.basename(abs_path)} ({e}); importing the DDS directly.")
                    final_path = os.path.join(dest_dir, os.path.basename(abs_path))
                    if os.path.normcase(os.path.abspath(abs_path)) != os.path.normcase(os.path.abspath(final_path)):
                        shutil.copy2(abs_path, final_path)
            else:
                final_path = os.path.join(dest_dir, os.path.basename(abs_path))
                shutil.copy2(abs_path, final_path)

            if pbr_type == "normal":
                self.texture_processor.convert_remix_normal(
                    final_path,
                    octahedral=is_octahedral_normal_name(abs_path),
                    # Non-octahedral .rtex normals came from older releases of this plugin, which ingested DirectX.
                    source_directx=abs_path.lower().endswith(".rtex.dds"),
                    target_opengl=target_opengl,
                )
            return pbr_type, final_path, size

        if status_callback:
            status_callback.emit(f"Converting {total} texture{'s' if total != 1 else ''}...")

        processed = []
        sizes = {}
        with ThreadPoolExecutor(max_workers=min(_PIPELINE_MAX_WORKERS, total)) as pool:
            futures = {pool.submit(_process_one, pbr, path): pbr for pbr, path in work_items}
            for fut, pbr in futures.items():
                try:
                    pbr_type, final_path, size = fut.result()
                    processed.append((pbr_type, final_path))
                    sizes[pbr_type] = size
                except Exception as e:
                    self.log_warning(f"Texture '{pbr}' skipped: {e}")
                    notes.append(f"{pbr}: {e}")
                finally:
                    _bump_progress()

        albedo = dict(processed).get("albedo")
        if albedo:
            try:
                stem = os.path.splitext(os.path.basename(albedo))[0]
                opacity = self.texture_processor.extract_alpha(albedo, os.path.join(dest_dir, f"{stem}_opacity.png"))
                if opacity:
                    processed.append(("opacity", opacity))
            except Exception as e:
                self.log_warning(f"Could not extract opacity from the albedo alpha: {e}")

        source_size = sizes.get("albedo") or next((s for s in sizes.values() if s[0] and s[1]), (0, 0))
        return {"material_prim": material_prim, "textures": processed, "source_size": source_size, "notes": notes}

    def _import_assign(self, result, adjust_resolution, notes):
        notes = list(notes) + list(result.get("notes") or [])
        material_name = result["material_prim"].rsplit("/", 1)[-1]
        if not self.painter_controller.is_project_open():
            raise RemixError("The project was closed before the textures could be imported.")
        if not result["textures"]:
            notes.insert(0, f"{material_name} has no textures to import.")
            return self._finish_operation(" ".join(notes))

        stack = self.painter_controller.active_stack()
        if stack is None:
            raise RemixError("The project has no texture set to import into.")

        src_w, src_h = result.get("source_size") or (0, 0)
        if adjust_resolution and src_w and src_h:
            # Never paint at less than the source's resolution (capped by Painter's limit).
            long_side = max(int(self.settings.get("project_texture_resolution", 2048)), max(src_w, src_h))
            w, h = aspect_matched_resolution(src_w, src_h, long_side)
            texture_set = self.painter_controller.stack_texture_set(stack)
            if texture_set is not None:
                self.painter_controller.set_resolution(texture_set, w, h)

        sources = dict(result["textures"])
        assigned, errors = self.painter_controller.create_fill_layer(stack, sources, f"Remix {material_name}")
        if src_w and src_h:
            try:
                self._write_link(result["material_prim"], {"remix_original_width": str(src_w), "remix_original_height": str(src_h)})
            except Exception as e:
                self.log_debug(f"Failed to save original texture size metadata: {e}")

        for err in errors:
            self.log_warning(f"Import: {err}")
        if not assigned:
            raise RemixError("No textures could be applied: " + "; ".join(errors or notes or ["unknown error"]))
        summary = f"Imported {len(assigned)} texture{'s' if len(assigned) != 1 else ''} from {material_name} into a new fill layer."
        problems = notes + errors
        if problems:
            summary += " Skipped: " + "; ".join(problems)
        self._finish_operation(summary)

    # --- Link / relink ---
    def handle_link_to_selection(self):
        if not self.painter_controller.is_project_open():
            return self.display_message("Open a Painter project first.", level="notice")
        if not self._begin_operation("Link to Remix Material"):
            return
        self._start_worker(self._read_selected_materials, on_result=lambda mats: self._apply_relink(mats, push=False),
                           title="Link to Remix Material")

    def handle_relink_and_push_to_remix(self):
        if not self.painter_controller.is_project_open():
            return self.display_message("Open a Painter project first.", level="notice")
        if not self._begin_operation("Force Push to Remix"):
            return
        self._start_worker(self._read_selected_materials, on_result=lambda mats: self._apply_relink(mats, push=True),
                           title="Force Push to Remix")

    def _read_selected_materials(self, progress_callback=None, status_callback=None):
        self._require_remix_project(status_callback)
        if status_callback: status_callback.emit("Reading the Remix selection...")
        selection, err = self.remix_api.get_selection()
        if err:
            raise RemixError(err)
        if not selection["materials"]:
            raise RemixError("Select a mesh or material in the RTX Remix viewport first.")
        return selection["materials"]

    def _apply_relink(self, materials, push):
        material_prim = self._choose_material(materials, "Link to Remix Material")
        if not material_prim:
            return self._finish_operation("Cancelled.", level="status")
        self._write_link(material_prim, relink=True)
        material_name = material_prim.rsplit("/", 1)[-1]
        if not push:
            return self._finish_operation(f"Project linked to {material_name}.")
        self.log_info(f"Relinked to {material_prim}; force pushing with new file names.")
        self._push_start(self.read_link(), force_new_root=True)

    # --- Push ---
    def handle_push_to_remix(self):
        link = self.read_link()
        if not link:
            return self.display_message("Open a project linked to Remix first (Pull from Remix, or Link to Selected Remix Material).", level="notice")
        if not self._begin_operation("Push to Remix"):
            return
        self._push_start(link, force_new_root=False)

    def _push_start(self, link, force_new_root):
        if not link or not link.get("material_hash"):
            raise RemixError("The project link has no material hash. Use Link to Selected Remix Material.")
        self._start_worker(
            self._push_preflight, link["material_prim"],
            on_result=lambda preflight: self._push_export(preflight, link, force_new_root),
            title="Push to Remix",
        )

    def _push_preflight(self, material_prim, progress_callback=None, status_callback=None):
        """Worker: make sure Remix can take the push before Painter exports anything."""
        project = self._require_remix_project(status_callback)
        if status_callback: status_callback.emit("Preparing the Remix project...")
        output_dir, err = self.remix_api.get_project_default_output_dir()
        if err or not output_dir:
            raise RemixError(f"Couldn't get the Remix ingest folder: {err}")
        edit_target, _ = self.remix_api.get_current_edit_target()
        # Use the material's real shader path when Remix reports one.
        shader_path = f"{material_prim}/Shader"
        textures, _ = self.remix_api.get_material_textures(material_prim)
        for usd_attr, _path in textures or []:
            if ".inputs:" in str(usd_attr):
                shader_path = str(usd_attr).split(".inputs:")[0]
                break
        return {"project": project, "output_dir": output_dir, "edit_target": edit_target,
                "shader_path": shader_path, "textures": textures or []}

    def _push_export(self, preflight, link, force_new_root):
        """GUI thread: Painter's export API must run here."""
        export_path = self.settings.get("painter_export_path") or os.path.join(tempfile.gettempdir(), "RemixConnector_Export")
        os.makedirs(export_path, exist_ok=True)
        self.display_message("Exporting textures...", level="status")
        exported, notes = self._export_textures(export_path, link["material_hash"])
        original_size = (link.get("original_width"), link.get("original_height"))
        self._start_worker(
            self._push_ingest, exported, preflight, link, force_new_root, original_size,
            on_result=lambda summary: self._push_done(summary, notes),
            title="Push to Remix",
        )

    def _export_textures(self, export_path, material_hash):
        import substance_painter.export
        import substance_painter.textureset

        stack = self.painter_controller.active_stack()
        if stack is None:
            raise RemixError("The project has no texture set to export.")
        texture_set = self.painter_controller.stack_texture_set(stack)
        ts_name = texture_set.name() if texture_set is not None else ""
        stack_name = ""
        try:
            stack_name = stack.name() or ""
        except Exception:
            pass
        root_path = f"{ts_name}/{stack_name}" if stack_name else ts_name

        notes = []
        all_sets = substance_painter.textureset.all_texture_sets() or []
        if len(all_sets) > 1:
            notes.append(f"Only the active texture set '{ts_name}' was pushed.")

        present = self.painter_controller.present_pbr_types(stack)
        maps, stems = build_export_maps(
            material_hash, present, self._normal_map_format(), self.settings.get("export_file_format", "png"))
        if not maps:
            raise RemixError(f"Texture set '{ts_name}' has no channels Remix can use.")

        preset_name = f"Remix_Dynamic_{material_hash}"
        export_config = {
            "exportShaderParams": False,
            "exportPath": export_path,
            "exportPresets": [{"name": preset_name, "maps": maps}],
            "exportList": [{"rootPath": root_path, "exportPreset": preset_name}],
        }
        res = substance_painter.export.export_project_textures(export_config)
        status = substance_painter.export.ExportStatus
        if res.status == status.Cancelled:
            raise RemixError("Texture export was cancelled.")
        if res.status not in (status.Success, getattr(status, "Warning", status.Success)):
            raise RemixError(f"Texture export failed: {res.message}")
        if res.status != status.Success and res.message:
            self.log_warning(f"Export warning: {res.message}")

        exported = {}
        for files in (res.textures or {}).values():
            for f in files:
                stem = os.path.splitext(os.path.basename(f))[0].lower()
                if stem in stems:
                    exported[stems[stem]] = f
        if not exported:
            raise RemixError("Painter exported no textures.")
        return exported, notes

    def _push_ingest(self, exported, preflight, link, force_new_root, original_size, progress_callback=None, status_callback=None):
        """Worker: resize, ingest, update the material and save the Remix layer."""
        exported = dict(exported)
        remix_out_dir = preflight["output_dir"]

        if self.settings.get("restore_original_aspect_ratio_on_export", True):
            self._restore_aspect_ratio(exported, original_size, preflight, status_callback)

        if force_new_root:
            exported = self._rename_for_force_push(exported, link, remix_out_dir)

        items = [(pbr, exported[pbr]) for pbr in _PUSH_ORDER if pbr in exported]
        total = len(items)
        if status_callback: status_callback.emit(f"Ingesting {total} texture{'s' if total != 1 else ''} in Remix...")
        if progress_callback: progress_callback.emit(5)

        ingested, failed = {}, {}
        done = [0]
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=min(_INGEST_MAX_WORKERS, total)) as pool:
            futures = {pool.submit(self.remix_api.ingest_texture, pbr, path, remix_out_dir): pbr for pbr, path in items}
            for fut, pbr in futures.items():
                try:
                    res, err = fut.result()
                    if res:
                        ingested[pbr] = res
                    else:
                        failed[pbr] = err or "unknown error"
                except Exception as e:
                    failed[pbr] = str(e)
                finally:
                    with lock:
                        done[0] += 1
                        pct = 5 + int(85 * done[0] / total)
                    if progress_callback:
                        try: progress_callback.emit(pct)
                        except Exception: pass

        for pbr, err in failed.items():
            self.log_warning(f"Ingest failed for {pbr}: {err}")
        if not ingested:
            raise RemixError("Remix could not ingest any texture: " + "; ".join(f"{k}: {v}" for k, v in failed.items()))

        if status_callback: status_callback.emit("Updating the Remix material...")
        shader_path = preflight["shader_path"]
        textures_to_update = [(f"{shader_path}.inputs:{PBR_TO_MDL_INPUT_MAP[pbr]}", path)
                              for pbr, path in ingested.items() if pbr in PBR_TO_MDL_INPUT_MAP]
        success, err = self.remix_api.update_textures_batch(textures_to_update)
        if not success:
            raise RemixError(f"Remix rejected the texture update: {err}")

        saved, save_err = self.remix_api.save_layer(preflight.get("edit_target") or link["material_prim"])
        if not saved:
            self.log_warning(f"Layer save failed: {save_err}")
        if progress_callback: progress_callback.emit(100)
        return {"material_prim": link["material_prim"], "pushed": sorted(ingested, key=_PUSH_ORDER.index),
                "failed": failed, "saved": saved, "save_error": save_err}

    def _restore_aspect_ratio(self, exported, original_size, preflight, status_callback=None):
        orig_w, orig_h = original_size or (None, None)
        try:
            orig_w, orig_h = int(float(orig_w or 0)), int(float(orig_h or 0))
        except (TypeError, ValueError):
            orig_w, orig_h = 0, 0
        if not (orig_w and orig_h):
            # Older links have no stored size: read it from the material's current albedo.
            for usd_attr, path in preflight.get("textures") or []:
                if REMIX_ATTR_SUFFIX_TO_PBR_MAP.get(str(usd_attr).split(":")[-1].lower()) == "albedo" and path:
                    orig_w, orig_h = read_image_size(str(path))
                    break
        if not (orig_w and orig_h):
            return
        texconv = self._texconv_path()
        for pbr, path in exported.items():
            cur_w, cur_h = read_image_size(path)
            target = aspect_restore_size(cur_w, cur_h, orig_w, orig_h)
            if not target:
                continue
            if not texconv:
                self.log_warning("Cannot restore the aspect ratio: texconv.exe not found.")
                return
            if status_callback: status_callback.emit(f"Resizing {pbr} to {target[0]}x{target[1]}...")
            try:
                self.texture_processor.resize_png(texconv, path, target[0], target[1])
                self.log_info(f"Resized {pbr} to {target[0]}x{target[1]} to match the original {orig_w}x{orig_h}.")
            except Exception as e:
                self.log_warning(f"Failed to resize {os.path.basename(path)}: {e}")

    def _rename_for_force_push(self, exported, link, remix_out_dir):
        """Copy exports to a file root that doesn't collide with earlier ingests."""
        try:
            output_subfolder = self.settings.get("remix_output_subfolder", "Textures/PainterConnector_Ingested").strip("/\\")
            ingest_dir_abs = os.path.normpath(os.path.join(remix_out_dir, output_subfolder))
            desired_root = link.get("material_hash") or "ForcePush"
            forced_root = self.texture_processor.choose_non_overwriting_root(desired_root, ingest_dir_abs)
            if not forced_root or forced_root == desired_root:
                return exported
            self.log_debug(f"ForcePush root chosen: desired={desired_root} forced={forced_root} ingestDir={ingest_dir_abs}")
            temp_root = os.path.dirname(next(iter(exported.values())))
            renamed = {}
            for pbr, path in exported.items():
                new_path, err = self.texture_processor.copy_texture_with_forced_root(
                    path, f"{forced_root}_{EXPORT_FILE_SUFFIX.get(pbr, pbr)}", pbr, temp_root)
                if new_path:
                    renamed[pbr] = new_path
                else:
                    self.log_warning(err or f"ForcePush rename failed for {pbr}")
            return renamed or exported
        except Exception as e:
            self.log_warning(f"Force Push rename step failed (continuing without rename): {e}")
            return exported

    def _push_done(self, summary, notes):
        material_name = summary["material_prim"].rsplit("/", 1)[-1]
        parts = [f"Pushed {', '.join(summary['pushed'])} to {material_name}."]
        if summary["failed"]:
            parts.append("Failed: " + "; ".join(f"{k} ({v})" for k, v in summary["failed"].items()) + ".")
        if not summary["saved"]:
            parts.append(f"Remix layer NOT saved ({summary['save_error']}); save it in Remix.")
        parts.extend(notes)
        self._finish_operation(" ".join(parts), level="warning" if (summary["failed"] or not summary["saved"]) else "info")

    # --- Show in Remix ---
    def handle_select_in_remix(self):
        link = self.read_link()
        if not link:
            return self.display_message("This project isn't linked to a Remix material.", level="notice")
        if not self._begin_operation("Show in Remix"):
            return

        def _select(progress_callback=None, status_callback=None):
            self._require_remix_project(status_callback)
            ok, err = self.remix_api.select_prims([link["material_prim"]])
            if not ok:
                raise RemixError(err)
            return link["material_prim"]

        self._start_worker(_select, on_result=lambda prim: self._finish_operation(f"Selected {prim.rsplit('/', 1)[-1]} in RTX Remix."),
                           title="Show in Remix", show_progress=False)

    # --- Settings / diagnostics / about ---
    def handle_settings(self):
        def _test_connection(candidate_settings):
            tmp_client = None
            try:
                candidate = sanitize_settings(candidate_settings or {}, PLUGIN_DIR)
                tmp_client = RemixAPIClient(lambda: candidate, self.logger_adapter)
                return tmp_client.ping(timeout=2.0)
            except Exception as e:
                return False, str(e)
            finally:
                # Each ping creates a requests.Session under the hood; close it.
                if tmp_client is not None:
                    try:
                        tmp_client.close()
                    except Exception:
                        pass

        dialog = create_settings_dialog_instance(
            self.settings,
            self._get_ui_parent(),
            test_connection_fn=_test_connection,
            log_file_path=self._log_file_path,
        )

        if dialog.exec():
            self.settings = sanitize_settings(dialog.get_settings(), PLUGIN_DIR)
            self.save_settings()
            self.display_message("Settings saved.", level="status")
            self._connection = {"ok": None, "message": "Checking..."}
            self._emit_state()
            self.refresh_connection()

    def _diagnostics_remix(self, progress_callback=None, status_callback=None):
        if status_callback:
            status_callback.emit("Querying RTX Remix...")
        info = {}
        try:
            info["project"], info["project_error"] = self.remix_api.get_project_info(timeout=3.0)
            if info["project"]:
                info["output_dir"], info["output_error"] = self.remix_api.get_project_default_output_dir()
                info["edit_target"], info["edit_target_error"] = self.remix_api.get_current_edit_target()
                info["selection"], info["selection_error"] = self.remix_api.get_selection()
        except Exception as e:
            info["project_error"] = str(e)
        return info

    def _build_diagnostics_text(self, remix_info):
        s = self.settings or {}

        def _path_status(p):
            try:
                return "OK" if p and os.path.exists(p) else "MISSING"
            except Exception:
                return "?"

        lines = [f"{PLUGIN_NAME} v{PLUGIN_VERSION}", ""]
        try:
            import substance_painter.application
            lines.append(f"Substance 3D Painter: {substance_painter.application.version()}")
        except Exception:
            pass
        lines.append(f"Python: {sys.version.split()[0]}  |  Qt binding: {QT_BINDING}")
        try:
            import PIL
            from PIL import Image  # noqa: F401  (fails when the binary doesn't match this Python)
            lines.append(f"Pillow: {PIL.__version__} (OK)")
        except Exception as e:
            lines.append(f"Pillow: UNAVAILABLE ({e}) - normal maps can't be imported")
        lines += [
            f"Plugin dir: {PLUGIN_DIR}",
            f"Settings file: {SETTINGS_FILE_PATH}",
            f"Log file: {self._log_file_path}",
            "",
            "RTX Remix:",
            f"  API: {self.remix_api.api_base_url()}",
        ]
        project = remix_info.get("project")
        if project:
            lines.append(f"  Project: {project['project_file']}")
            lines.append(f"  Ingest folder: {remix_info.get('output_dir') or remix_info.get('output_error')}")
            lines.append(f"  Edit target layer: {remix_info.get('edit_target') or remix_info.get('edit_target_error')}")
            sel = remix_info.get("selection")
            if sel:
                lines.append(f"  Selection: {len(sel['materials'])} material(s), {len(sel['meshes'])} mesh(es)")
                for m in sel["materials"]:
                    lines.append(f"    material: {m}")
            else:
                lines.append(f"  Selection: {remix_info.get('selection_error')}")
        else:
            lines.append(f"  NOT CONNECTED: {remix_info.get('project_error')}")
        lines += [
            "",
            "Tools:",
            f"  texconv: {self._texconv_path() or 'MISSING'}",
            f"  Blender: {s.get('blender_executable_path') or '(not set)'} ({_path_status(s.get('blender_executable_path'))})",
            "",
            "Key settings:",
            f"  normal_map_format: {s.get('normal_map_format')}",
            f"  project_texture_resolution: {s.get('project_texture_resolution')}",
            f"  auto_import_textures_on_pull: {s.get('auto_import_textures_on_pull')}",
            f"  use_simple_tiling_mesh_on_pull: {s.get('use_simple_tiling_mesh_on_pull')}",
            f"  auto_unwrap_with_blender_on_pull: {s.get('auto_unwrap_with_blender_on_pull')}",
            f"  restore_original_aspect_ratio_on_export: {s.get('restore_original_aspect_ratio_on_export')}",
            f"  painter_export_path: {s.get('painter_export_path')}",
            f"  remix_output_subfolder: {s.get('remix_output_subfolder')}",
            "",
        ]

        try:
            import substance_painter.project
            if substance_painter.project.is_open():
                link = self.read_link()
                lines.append("Painter project:")
                lines.append(f"  File: {substance_painter.project.file_path() or '(unsaved)'}")
                if link:
                    lines.append(f"  Linked material: {link['material_prim']}")
                    lines.append(f"  Material hash: {link['material_hash']}")
                    if link.get("original_width"):
                        lines.append(f"  Source texture size: {link['original_width']}x{link['original_height']}")
                else:
                    lines.append("  Not linked to Remix.")
                stack = self.painter_controller.active_stack()
                if stack is not None:
                    present = sorted(self.painter_controller.present_pbr_types(stack))
                    lines.append(f"  Active stack channels: {', '.join(present) or '(none)'}")
            else:
                lines.append("Painter project: none open")
        except Exception as e:
            lines.append(f"Painter project: ? ({e})")

        lines += ["", f"Repo: {PLUGIN_REPO_URL}"]
        return "\n".join(lines)

    def handle_diagnostics(self):
        def _show(remix_info):
            text = self._build_diagnostics_text(remix_info)
            dlg = DiagnosticsDialog(text, self._get_ui_parent(), log_file_path=self._log_file_path)
            dlg.exec_()

        self._start_worker(self._diagnostics_remix, on_result=_show, title="Diagnostics", show_progress=False, operational=False)

    def handle_open_log_folder(self):
        try:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(LOG_DIR))
        except Exception as e:
            self.display_message(f"Could not open {LOG_DIR}: {e}", level="warning")

    def handle_about(self):
        text = (f"<b>{PLUGIN_NAME}</b> v{PLUGIN_VERSION}<br><br>{PLUGIN_DESCRIPTION}<br><br>"
                f"<a href='{PLUGIN_REPO_URL}'>{PLUGIN_REPO_URL}</a>")
        try:
            QtWidgets.QMessageBox.about(self._get_ui_parent(), f"About {PLUGIN_NAME}", text)
        except Exception:
            self.display_message(f"{PLUGIN_NAME} v{PLUGIN_VERSION}")


plugin_instance = None
PLUGIN_SETTINGS = {}


def setup_logging():
    """Create the plugin instance (the name predates the class; kept for __init__)."""
    global plugin_instance, PLUGIN_SETTINGS
    if plugin_instance is not None:
        teardown()
        try:
            if QtCore is not None:
                QtCore.QCoreApplication.processEvents()
        except Exception:
            pass
    plugin_instance = RemixConnectorPlugin()
    PLUGIN_SETTINGS = plugin_instance.settings


def teardown():
    """
    Called by the host on plugin shutdown.

    If the threadpool drained within the wait window, schedule the
    QObject for deletion. If it did not (e.g. a 600s ingest or 900s
    Blender unwrap is still running), keep the QObject alive so the
    running worker's ``run()`` can complete; ``_shutting_down`` makes
    every late callback a no-op.
    """
    global plugin_instance
    if plugin_instance is None:
        return

    drained = False
    try:
        drained = bool(plugin_instance.shutdown(wait_ms=5000))
    except Exception:
        drained = False

    if drained:
        try:
            plugin_instance.deleteLater()
        except Exception:
            pass

    plugin_instance = None


def _safe_call(handler_name):
    inst = plugin_instance
    if inst is None:
        print(f"[{PLUGIN_NAME}] Plugin not initialized; ignoring '{handler_name}'.")
        return
    handler = getattr(inst, handler_name, None)
    if not callable(handler):
        print(f"[{PLUGIN_NAME}] Missing handler '{handler_name}'.")
        return
    running_before = inst.current_operation
    try:
        handler()
    except Exception as e:
        if not isinstance(e, RemixError):
            inst.log_error(f"{handler_name} failed: {e}", exc_info=True)
        # Only end an operation this handler started; never another one's lock.
        if running_before is None and inst.current_operation is not None:
            inst._fail_operation(str(e))
        else:
            inst.show_error("Error", str(e))


def handle_pull_from_remix(): _safe_call('handle_pull_from_remix')
def handle_import_textures(): _safe_call('handle_import_textures')
def handle_push_to_remix(): _safe_call('handle_push_to_remix')
def handle_relink_and_push_to_remix(): _safe_call('handle_relink_and_push_to_remix')
def handle_link_to_selection(): _safe_call('handle_link_to_selection')
def handle_select_in_remix(): _safe_call('handle_select_in_remix')
def handle_settings(): _safe_call('handle_settings')
def handle_diagnostics(): _safe_call('handle_diagnostics')
def handle_open_log_folder(): _safe_call('handle_open_log_folder')
def handle_about(): _safe_call('handle_about')
def save_plugin_settings(): _safe_call('save_settings')
